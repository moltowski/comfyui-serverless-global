#!/usr/bin/env python3
"""Copie au réveil du worker : <GV_ROOT>/models -> /models (disque local du conteneur).

Variables :
  PRELOAD_MODELS  presets de model_presets.txt et/ou chemins relatifs à models/, séparés par des
                  espaces ou des virgules ("krea", "h3-r2v vae/autre.safetensors"). Défaut : none.
  PRELOAD_LORAS   1 (défaut) : copie aussi tout loras/ ; 0 : non.
  PRELOAD_CHUNKS  nombre de lectures parallèles par fichier (défaut 1 = une lecture séquentielle,
                  la seule méthode éprouvée : 4 copies parallèles ont cassé un hôte le 04/10).
  PRELOAD_RETRIES essais par fichier (défaut 3).
  GV_BENCH_WRITE  1 (défaut) : écrit aussi la mesure sur le volume, <GV_ROOT>/bench/<worker>-<t>.json

Écrit toujours /tmp/gv_preload.json (lu par gv_handler.py). Un fichier qui n'a pas pu être copié
n'arrête rien : ComfyUI le lira alors en direct sur le volume (lent).
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.environ.get("GV_ROOT", "/runpod-volume")
SRC = os.path.join(ROOT, "models")
DST = "/models"
PRESETS = "/opt/gv/model_presets.txt"
OUT = "/tmp/gv_preload.json"
BLOCK = 64 * 1024 * 1024
ENV_KEYS = ("RUNPOD_POD_ID", "RUNPOD_DC_ID", "RUNPOD_ENDPOINT_ID", "RUNPOD_GPU_COUNT",
            "RUNPOD_CPU_COUNT", "RUNPOD_MEM_GB", "RUNPOD_POD_HOSTNAME",
            "PRELOAD_MODELS", "PRELOAD_LORAS", "PRELOAD_CHUNKS", "GV_MODE", "COMFY_ARGS")


def wanted():
    presets = {}
    try:
        with open(PRESETS, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    name, rel = line.split(None, 1)
                    presets.setdefault(name, []).append(rel.strip())
    except OSError:
        pass
    items = [] if os.environ.get("PRELOAD_LORAS", "1") == "0" else ["loras/"]
    for w in os.environ.get("PRELOAD_MODELS", "none").replace(",", " ").split():
        if w != "none":
            items += presets.get(w, [w])
    seen = set()
    return [x for x in items if not (x in seen or seen.add(x))]


def _copy_range(src, part, start, end, errs):
    try:
        with open(src, "rb", buffering=0) as s, open(part, "r+b", buffering=0) as d:
            s.seek(start)
            d.seek(start)
            pos = start
            while pos < end:
                b = s.read(min(BLOCK, end - pos))
                if not b:
                    raise IOError("lecture courte à l'octet %d" % pos)
                mv = memoryview(b)
                while mv:
                    k = d.write(mv)
                    mv = mv[k:]
                pos += len(b)
    except Exception as e:
        errs.append(repr(e))


def copy_file(src, dst, chunks):
    size = os.path.getsize(src)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst) and os.path.getsize(dst) == size:
        return size, "deja"
    part = dst + ".part"
    with open(part, "wb") as f:
        f.truncate(size)
    n = max(1, min(chunks, size // BLOCK or 1))
    step = -(-size // n)
    errs = []
    threads = [threading.Thread(target=_copy_range,
                                args=(src, part, i * step, min(size, (i + 1) * step), errs))
               for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errs:
        os.remove(part)
        raise IOError("; ".join(errs[:3]))
    os.replace(part, dst)
    return size, "ok"


def files_of(rel):
    """Liste (chemin source, chemin destination, relatif) pour un fichier ou un dossier (rel/)."""
    src = os.path.join(SRC, rel)
    if rel.endswith("/"):
        out = []
        for d, _, names in os.walk(src):
            for n in sorted(names):
                p = os.path.join(d, n)
                r = os.path.relpath(p, SRC)
                out.append((p, os.path.join(DST, r), r))
        return out
    return [(src, os.path.join(DST, rel), rel)]


def gpu_name():
    try:
        return subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                              capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception as e:
        return "?" + repr(e)


def container_age_s():
    try:
        return round(time.time() - os.stat("/proc/1").st_mtime, 1)
    except OSError:
        return None


def write_bench(rec):
    """Copie de la mesure sur le volume, en tâche de fond bornée : une écriture GeeseFS qui traîne
    ne doit pas retarder le démarrage."""
    def _w():
        try:
            d = os.path.join(ROOT, "bench")
            os.makedirs(d, exist_ok=True)
            who = rec["env"].get("RUNPOD_POD_ID") or os.uname().nodename
            with open(os.path.join(d, "%s-%d.json" % (who, int(rec["t_start"]))), "w") as f:
                json.dump(rec, f)
        except Exception as e:
            print("gv: mesure non écrite sur le volume :", repr(e))
    t = threading.Thread(target=_w, daemon=True)
    t.start()
    t.join(20)


def main():
    record_only = "--record-only" in sys.argv
    chunks = int(os.environ.get("PRELOAD_CHUNKS", "1"))
    retries = int(os.environ.get("PRELOAD_RETRIES", "3"))
    rec = {
        "t_start": time.time(),
        "container_age_at_start_s": container_age_s(),
        "gpu": gpu_name(),
        "env": {k: os.environ[k] for k in ENV_KEYS if k in os.environ},
        "volume_mounted": os.path.isdir(SRC),
        "mode": "record-only" if record_only else "copy",
        "files": [],
    }
    print("gv: volume %s, modèles %s, GPU %s" % (ROOT, "présents" if rec["volume_mounted"] else "ABSENTS", rec["gpu"]))

    if not record_only and rec["volume_mounted"]:
        plan = []
        for rel in wanted():
            if rel.endswith("/") or os.path.isfile(os.path.join(SRC, rel)):
                plan += files_of(rel)
            else:
                rec["files"].append({"rel": rel, "status": "absent"})
                print("gv: ABSENT", rel)
        need = sum(os.path.getsize(s) for s, _, _ in plan if os.path.exists(s))
        free = shutil.disk_usage(DST).free
        rec["need_gb"], rec["free_gb"] = round(need / 1e9, 1), round(free / 1e9, 1)
        if need > free:
            print("gv: disque trop petit (%.1f Go demandés, %.1f Go libres) : copie partielle" % (need / 1e9, free / 1e9))
        for src, dst, rel in plan:
            e = {"rel": rel}
            t0 = time.time()
            for attempt in range(1, retries + 1):
                try:
                    if shutil.disk_usage(DST).free < os.path.getsize(src) + (1 << 30):
                        raise IOError("plus de place sur le disque local")
                    size, status = copy_file(src, dst, chunks)
                    e.update(status=status, tries=attempt, mb=round(size / 1e6))
                    break
                except Exception as ex:
                    e.update(status="echec", tries=attempt, error=repr(ex)[:300])
                    if "plus de place" in repr(ex):
                        break
                    time.sleep(5)
            e["s"] = round(time.time() - t0, 1)
            if e["status"] == "ok" and e["s"] > 0:
                e["mbps"] = round(e["mb"] / e["s"], 1)
            rec["files"].append(e)
            if e.get("mb", 0) >= 100 or e["status"] != "ok":
                print("gv: %s %s %s Mo %ss %s Mo/s" % (e["status"].upper(), rel, e.get("mb", "?"), e["s"], e.get("mbps", "-")))

    rec["t_end"] = time.time()
    rec["total_s"] = round(rec["t_end"] - rec["t_start"], 1)
    copied = [f for f in rec["files"] if f.get("status") == "ok"]
    rec["copied_gb"] = round(sum(f["mb"] for f in copied) / 1e3, 2)
    copy_s = sum(f["s"] for f in copied)
    rec["copy_mbps"] = round(rec["copied_gb"] * 1e3 / copy_s, 1) if copy_s else None
    rec["failed"] = [f["rel"] for f in rec["files"] if f.get("status") in ("echec", "absent")]
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    print("gv: copie terminée en %ss, %s Go, %s Mo/s, échecs : %s" % (rec["total_s"], rec["copied_gb"], rec["copy_mbps"], rec["failed"] or "aucun"))
    if os.environ.get("GV_BENCH_WRITE", "1") == "1" and rec["volume_mounted"]:
        write_bench(rec)


if __name__ == "__main__":
    main()

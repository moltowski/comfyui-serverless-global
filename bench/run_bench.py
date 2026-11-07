#!/usr/bin/env python3
"""Banc serverless : envoie des jobs à un endpoint et note les temps, un JSON par ligne.

    set RUNPOD_API_KEY=...     (clé du compte qui porte l'endpoint)
    python bench/run_bench.py --endpoint <id> --info                  # contenu du volume (gv_info)
    python bench/run_bench.py --endpoint <id> --n 8 --cold            # 8 démarrages à froid
    python bench/run_bench.py --endpoint <id> --n 3                   # 3 jobs à la suite (chauds)
    python bench/run_bench.py --endpoint 0ccxrcn554agid --n 3 --cold \
        --clip qwen3vl_4b_fp8_scaled.safetensors                       # témoin network volume

--cold : avant chaque job, attend que l'endpoint n'ait plus aucun worker (/health), pour que le job
réveille un worker neuf. Seed tirée au hasard à chaque job (sinon ComfyUI renvoie son cache).
Résultats : <out>/results.jsonl (delayTime, executionTime, mesures "gv" du worker, taille de la
sortie). Les images ne sont PAS ouvertes : seul leur nombre et leur taille sont relevés.
Stdlib uniquement.
"""
import argparse
import base64
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def call(url, key, payload=None, timeout=60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read()[:500].decode("utf8", "replace")}


def workers_alive(h):
    w = h.get("workers", {})
    return sum(w.get(k, 0) for k in ("idle", "initializing", "ready", "running"))


def wait_no_worker(ep, key, max_wait):
    t0 = time.time()
    while time.time() - t0 < max_wait:
        h = call(ep + "/health", key)
        if workers_alive(h) == 0 and h.get("jobs", {}).get("inQueue", 0) == 0:
            return round(time.time() - t0)
        time.sleep(15)
    return None


def run_job(ep, key, payload, max_wait):
    t_sub = time.time()
    r = call(ep + "/run", key, payload)
    jid = r.get("id")
    if not jid:
        return {"error": r}
    st = {}
    while time.time() - t_sub < max_wait:
        time.sleep(5)
        st = call(ep + "/status/" + jid, key, timeout=120)
        if st.get("status") in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            break
    st["_id"] = jid
    st["_wall_s"] = round(time.time() - t_sub, 1)
    return st


def summarize(st, out_dir, tag):
    out = st.get("output") or {}
    rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "tag": tag, "id": st.get("_id"),
           "status": st.get("status"), "wall_s": st.get("_wall_s"),
           "delay_s": round(st.get("delayTime", 0) / 1000, 1) if st.get("delayTime") else None,
           "exec_s": round(st.get("executionTime", 0) / 1000, 1) if st.get("executionTime") else None,
           "workerId": st.get("workerId")}
    if isinstance(out, dict):
        imgs = out.get("images") or []
        rec["n_outputs"] = len(imgs)
        rec["output_bytes"] = [len(base64.b64decode(i.get("data", ""))) for i in imgs if i.get("type") == "base64"]
        for i, img in enumerate(imgs):
            if img.get("type") == "base64":
                with open(os.path.join(out_dir, "%s_%s_%d_%s" % (tag, rec["id"], i, img.get("filename", "out"))), "wb") as f:
                    f.write(base64.b64decode(img["data"]))
        gv = out.get("gv")
        if gv:
            rec["gv"] = {k: gv.get(k) for k in ("job_index", "gpu", "env", "total_s", "copied_gb",
                                                 "copy_mbps", "failed", "free_gb", "need_gb",
                                                 "container_age_at_start_s", "handler_s", "mode", "error")}
            rec["gv"]["files"] = [{k: f.get(k) for k in ("rel", "status", "mb", "s", "mbps", "tries", "error")}
                                  for f in gv.get("files", []) if f.get("mb", 0) >= 100 or f.get("status") != "ok"]
        for k in ("error", "errors", "details"):
            if k in out:
                rec[k] = out[k]
    elif out:
        rec["output"] = str(out)[:500]
    if st.get("error"):
        rec["error"] = st["error"]
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--workflow", default=os.path.join(HERE, "krea_bench.json"))
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--cold", action="store_true")
    ap.add_argument("--info", action="store_true", help="un job gv_info (inventaire du volume)")
    ap.add_argument("--clip", help="remplace le fichier du CLIPLoader (ex. témoin sur c-edge)")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--max-wait", type=int, default=3600, help="attente max par job, en s")
    ap.add_argument("--out", default=os.path.join(HERE, "runs"))
    a = ap.parse_args()

    key = os.environ.get("RUNPOD_API_KEY") or sys.exit("RUNPOD_API_KEY absente")
    ep = "https://api.runpod.ai/v2/" + a.endpoint
    os.makedirs(a.out, exist_ok=True)
    log = os.path.join(a.out, "results.jsonl")

    if a.info:
        st = run_job(ep, key, {"input": {"gv_info": True}}, a.max_wait)
        path = os.path.join(a.out, "gv_info_%s.json" % time.strftime("%Y%m%d-%H%M%S"))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=1)
        out = st.get("output") or {}
        inv = out.get("inventory", {}) if isinstance(out, dict) else {}
        print(st.get("status"), "| volume :", inv.get("files"), "fichiers,", inv.get("gb"), "Go ->", path)
        return

    wf = json.load(open(a.workflow, encoding="utf-8"))
    for i in range(a.n):
        for n in wf.values():
            if "seed" in n.get("inputs", {}):
                n["inputs"]["seed"] = random.randint(1, 2 ** 48)
            if a.clip and n.get("class_type") == "CLIPLoader":
                n["inputs"]["clip_name"] = a.clip
        if a.cold:
            waited = wait_no_worker(ep, key, 1800)
            print("attente sans worker : %ss" % waited)
        st = run_job(ep, key, {"input": {"workflow": wf}}, a.max_wait)
        rec = summarize(st, a.out, "%s%02d" % (a.tag, i + 1))
        rec["cold_requested"] = a.cold
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        gv = rec.get("gv") or {}
        print("%s %s attente %ss exécution %ss | copie %ss %s Go %s Mo/s | %s | job n°%s sur ce worker | sorties %s" % (
            rec["tag"], rec["status"], rec["delay_s"], rec["exec_s"], gv.get("total_s"), gv.get("copied_gb"),
            gv.get("copy_mbps"), gv.get("gpu"), gv.get("job_index"), rec.get("n_outputs")))


if __name__ == "__main__":
    main()

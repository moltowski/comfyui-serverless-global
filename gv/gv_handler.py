"""Enveloppe du handler officiel worker-comfyui.

- Chaque sortie de job reçoit une clé "gv" : mesures de la copie au réveil du worker
  (/tmp/gv_preload.json), rang du job sur ce worker (1 = premier job = démarrage à froid),
  durée du handler.
- Un job {"input": {"gv_info": true}} ne touche pas ComfyUI : il renvoie les mesures de copie,
  le contenu de <GV_ROOT>/models (nom, taille) et celui de /models.
"""
import json
import os
import sys
import time

sys.path.insert(0, "/")
import runpod  # noqa: E402
import handler as base  # noqa: E402  (le handler officiel, /handler.py)

PRELOAD_JSON = "/tmp/gv_preload.json"
JOBS = 0


def _preload():
    if not os.path.exists(PRELOAD_JSON):
        return {"error": "copie en cours ou pas encore faite"}
    try:
        with open(PRELOAD_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # pas de copie faite, ou fichier illisible
        return {"error": "no preload record: %s" % e}


def _inventory(root):
    files, total = [], 0
    for d, _, names in os.walk(root):
        for n in names:
            p = os.path.join(d, n)
            try:
                s = os.path.getsize(p)
            except OSError:
                s = -1
            files.append([os.path.relpath(p, root), s])
            total += max(s, 0)
    files.sort()
    return {"root": root, "files": len(files), "gb": round(total / 1e9, 1), "list": files}


def handler(job):
    global JOBS
    JOBS += 1
    inp = job.get("input") or {}
    gv = _preload()
    gv["job_index"] = JOBS
    if inp.get("gv_info"):
        root = os.path.join(os.environ.get("GV_ROOT", "/runpod-volume"), "models")
        return {"gv": gv, "inventory": _inventory(root), "local": _inventory("/models")}
    t0 = time.time()
    out = base.handler(job)
    gv["handler_s"] = round(time.time() - t0, 1)
    if isinstance(out, dict):
        out["gv"] = gv
    return out


if __name__ == "__main__":
    print("gv: handler enveloppé (worker-comfyui + mesures global volume)")
    runpod.serverless.start({"handler": handler})

#!/usr/bin/env python3
"""Reconfigure un endpoint serverless (API REST v2) et garantit des workers neufs.

    python bench/set_endpoint.py <id> --preload h3-i2v --disk 90 --pools ADA_32_PRO --timeout-s 3600
    python bench/set_endpoint.py <id> --max 2           (seulement le nombre de workers)
    python bench/set_endpoint.py <id> --restore fichier.json   (pools, disque, env, timeout, workers)

--fresh : passe d'abord à 0 worker et attend qu'aucun ne tourne, pour que le job suivant tombe sur un
worker neuf avec la nouvelle config (sinon RunPod garde l'ancien worker quelques minutes).
Clé : RUNPOD_API_KEY (compte de l'endpoint). Stdlib.
"""
import argparse, json, os, sys, time, urllib.request, urllib.error

KEY = os.environ.get("RUNPOD_API_KEY") or sys.exit("RUNPOD_API_KEY absente")
H = {"Authorization": "Bearer " + KEY, "User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


def call(m, u, b=None):
    r = urllib.request.Request(u, data=json.dumps(b).encode() if b is not None else None, method=m, headers=H)
    try:
        return json.loads(urllib.request.urlopen(r, timeout=60).read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit("HTTP %s : %s" % (e.code, e.read()[:400].decode("utf8", "replace")))


def health(eid):
    return call("GET", "https://api.runpod.ai/v2/%s/health" % eid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--preload")
    ap.add_argument("--image", help="image Docker (tag épinglé)")
    ap.add_argument("--disk", type=int)
    ap.add_argument("--pools")
    ap.add_argument("--timeout-s", type=int)
    ap.add_argument("--max", type=int)
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--restore")
    a = ap.parse_args()
    u = "https://api.runpod.io/v2/serverless/" + a.id
    cur = call("GET", u)
    patch = {}
    if a.restore:
        old = json.load(open(a.restore, encoding="utf-8"))
        patch = {"gpu": {k: old["gpu"][k] for k in ("pools", "excludedTypes", "allowedCudaVersions", "count") if k in old["gpu"]},
                 "disk": old["disk"], "timeout": old["timeout"], "workers": old["workers"]}
        if isinstance(old.get("env"), dict):
            patch["env"] = old["env"]
    if a.preload:
        env = dict(cur.get("env") or {}); env["PRELOAD_MODELS"] = a.preload; patch["env"] = env
    if a.disk:
        patch["disk"] = a.disk
    if a.image:
        patch["image"] = a.image
    if a.pools:
        gpu = {k: cur["gpu"][k] for k in ("excludedTypes", "allowedCudaVersions", "count") if k in cur["gpu"]}
        gpu["pools"] = a.pools.split(",")
        # RunPod refuse un type exclu qui n'appartient à aucun pool choisi (Max-Q = pool BLACKWELL_96)
        if "BLACKWELL_96" in gpu["pools"]:
            gpu["excludedTypes"] = ["NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition"]
        else:
            gpu["excludedTypes"] = []
        patch["gpu"] = gpu
    if a.timeout_s:
        patch["timeout"] = a.timeout_s * 1000
    target_max = a.max if a.max is not None else cur["workers"]["max"]
    if a.fresh:
        w = dict(cur["workers"]); w["max"] = 0
        call("PATCH", u, {"workers": w})
        t0 = time.time()
        while time.time() - t0 < 600:
            ws = health(a.id).get("workers", {})
            if sum(ws.get(k, 0) for k in ("running", "initializing", "idle", "ready")) == 0:
                break
            time.sleep(10)
        print("0 worker après %ds" % (time.time() - t0))
    if patch:
        call("PATCH", u, patch)
    w = dict((patch.get("workers") or cur["workers"])); w["max"] = target_max if not a.restore else w["max"]
    call("PATCH", u, {"workers": w})
    # Après un passage à 0, l'API des jobs peut rester « en pause » malgré max > 0 (vu le 07/11) :
    # réécrire la valeur par l'API v1 débloque l'état.
    call("PATCH", "https://rest.runpod.io/v1/endpoints/" + a.id, {"workersMax": w["max"]})
    g = call("GET", u)
    print(json.dumps({"image": g.get("image", "")[-12:], "preload": (g.get("env") or {}).get("PRELOAD_MODELS"), "disk": g["disk"], "pools": g["gpu"]["pools"],
                      "timeout_s": g["timeout"] / 1000, "workers": g["workers"], "mounts": g["mounts"]}))


if __name__ == "__main__":
    main()

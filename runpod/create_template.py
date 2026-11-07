#!/usr/bin/env python3
"""Crée (ou affiche) le template serverless RunPod du worker global volume.

    python runpod/create_template.py --image ghcr.io/<owner>/comfyui-serverless-global:<sha>
    python runpod/create_template.py --image ... --key-file D:/safetychan/Voice/runpod-api-key-PERSO.txt --apply

Sans --apply : affiche seulement le corps de la requête. La clé n'est jamais affichée.
--key-file : fichier qui contient la clé (défaut : variable RUNPOD_API_KEY).
--public : demande un template public (à vérifier : RunPod l'accepte-t-il pour un template
serverless ? c'est ce qui permettrait à un autre compte de l'utiliser).
Le global volume ne se règle pas dans le template : il s'attache à l'endpoint
(console : Manage > Edit endpoint > Advanced > Global volume).
Stdlib uniquement.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

README = """ComfyUI serverless worker for RunPod global volumes.

The image holds ComfyUI 0.37 and its custom nodes, no models. On wake-up the worker copies the
models named in PRELOAD_MODELS from the global volume (/runpod-volume/models) to the container
disk, then starts ComfyUI on those local copies. Reading weights straight from the global volume
stalls ComfyUI; copying first is what works (measured 2026-09-29 and 2026-10-08).

Attach the global volume to the endpoint (Edit endpoint > Advanced > Global volume).
Container disk: copied models + ~15 GB (krea ~31 GB, krea-turbo ~19, qwen21 ~32, h3-r2v ~53).

Env: PRELOAD_MODELS (presets: krea, krea-turbo, qwen21, h3-r2v, h3-i2v, h3), PRELOAD_LORAS (1/0),
PRELOAD_CHUNKS (1), GV_MODE (copy|direct), COMFY_ARGS.
Input: {"input": {"workflow": <API-format workflow>}} as worker-comfyui; every output carries a
"gv" key with the copy timings. {"input": {"gv_info": true}} lists the volume's models.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--name", default="comfyui-serverless-global")
    ap.add_argument("--disk", type=int, default=60, help="disque conteneur en Go")
    ap.add_argument("--preload", default="krea")
    ap.add_argument("--key-file")
    ap.add_argument("--public", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    body = {
        "name": a.name,
        "imageName": a.image,
        "isServerless": True,
        "isPublic": a.public,
        "containerDiskInGb": a.disk,
        "volumeInGb": 0,
        "env": {
            "PRELOAD_MODELS": a.preload,
            "PRELOAD_LORAS": "1",
            "PRELOAD_CHUNKS": "1",
            "GV_MODE": "copy",
            "COMFY_LOG_LEVEL": "INFO",
        },
        "readme": README,
    }
    print(json.dumps({k: v for k, v in body.items() if k != "readme"}, indent=1))
    if not a.apply:
        print("(dry-run : rien créé ; ajouter --apply)")
        return

    if a.key_file:
        raw = open(a.key_file, encoding="utf-8").read()
        m = re.search(r"rpa_[A-Za-z0-9]+", raw)
        key = m.group(0) if m else raw.strip()
    else:
        key = os.environ.get("RUNPOD_API_KEY") or sys.exit("pas de clé (RUNPOD_API_KEY ou --key-file)")
    req = urllib.request.Request("https://rest.runpod.io/v1/templates", data=json.dumps(body).encode(),
                                 method="POST", headers={"Authorization": "Bearer " + key,
                                                         "Content-Type": "application/json",
                                                         "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("HTTP %s : %s" % (e.code, e.read()[:800].decode("utf8", "replace")))
    print("template créé :", res.get("id"), "| public :", res.get("isPublic"), "| serverless :", res.get("isServerless"))


if __name__ == "__main__":
    main()

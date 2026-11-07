#!/usr/bin/env python3
"""Relève le coût horaire réel ($/h) et la machine de chaque worker d'un endpoint (API REST v1).
Le $/h facturé dépend de la carte : il sert aussi à savoir quelle carte un worker a eue.

    python bench/worker_costs.py <endpoint> [<endpoint> ...] >> runs/workers.jsonl
"""
import json, os, sys, time, urllib.request
H = {"Authorization": "Bearer " + os.environ["RUNPOD_API_KEY"], "User-Agent": "Mozilla/5.0"}
for eid in sys.argv[1:]:
    e = json.load(urllib.request.urlopen(urllib.request.Request(
        "https://rest.runpod.io/v1/endpoints/%s?includeWorkers=true" % eid, headers=H), timeout=60))
    for w in e.get("workers") or []:
        print(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "endpoint": eid, "workerId": w["id"],
                          "status": w.get("desiredStatus"), "costPerHr": w.get("costPerHr"),
                          "machineId": w.get("machineId"), "lastStartedAt": w.get("lastStartedAt"),
                          "vcpu": w.get("vcpuCount"), "memGb": w.get("memoryInGb")}))

# comfyui-serverless-global

Worker serverless RunPod (ComfyUI) pour le **global volume** : les GPU de n'importe quel data center, les modèles sur un seul volume.

Au réveil, le worker copie depuis le volume (`/runpod-volume/models`) les modèles demandés vers son disque local, puis lance ComfyUI sur ces copies. Lire les poids en direct sur le global volume bloque ComfyUI ou prend 12 min (mesuré le 29/09) ; la copie d'abord est ce qui marche (retest du 08/10 : 52 à 157 Mo/s selon l'hôte).

## Contenu

| Fichier | Rôle |
|---|---|
| `Dockerfile` | base `runpod/worker-comfyui:5.8.6-base` (handler officiel), ComfyUI v0.37.0 et nodes aux mêmes commits que `comfyui-pod-global` |
| `nodes.txt`, `custom_nodes/` | nodes publics épinglés ; PT_InputHub v2 et PT_LoadAudioOptional |
| `model_presets.txt` | presets de `PRELOAD_MODELS` : `krea`, `krea-turbo`, `qwen21`, `h3-r2v`, `h3-i2v`, `h3` |
| `gv/gv_start.sh` | point d'entrée : copie, puis `/start.sh` de la base |
| `gv/preload.py` | copie une à une, 3 essais, mesure par fichier dans `/tmp/gv_preload.json` et `<volume>/bench/` |
| `gv/gv_handler.py` | handler officiel enveloppé : clé `gv` (mesures) dans chaque sortie ; job `gv_info` = inventaire du volume |
| `extra_model_paths.yaml` | `/models` local d'abord, le volume en secours |
| `runpod/create_template.py` | crée le template serverless (dry-run par défaut) |
| `bench/run_bench.py`, `bench/krea_bench.json` | banc : froids, chauds, inventaire ; workflow tasse FinePorn v4 du retest |

## Variables

| Variable | Défaut | Effet |
|---|---|---|
| `PRELOAD_MODELS` | `none` | presets et/ou chemins sous `models/`, séparés par espace ou virgule |
| `PRELOAD_LORAS` | `1` | copie aussi `loras/` |
| `PRELOAD_CHUNKS` | `1` | lectures parallèles par fichier (1 = la seule méthode éprouvée) |
| `PRELOAD_RETRIES` | `3` | essais par fichier |
| `GV_MODE` | `copy` | `direct` = pas de copie (avec `COMFY_ARGS=--disable-mmap`) |
| `COMFY_ARGS` | vide | arguments ajoutés au lancement de ComfyUI |
| `GV_BENCH_WRITE` | `1` | écrit la mesure aussi sur le volume |

## Endpoint

- global volume attaché à l'endpoint (console : Manage > Edit endpoint > Advanced > Global volume ; jamais avec un network volume) ;
- disque conteneur : modèles copiés + ~15 Go (`krea` 60 Go, `h3-r2v` 80 Go) ;
- la copie a lieu avant le handler : elle compte dans `delayTime` ; `executionTime` = chargement local + rendu ;
- épingler l'image au tag `:<sha>`, pas `:latest`.

Plan de test et résultats : `D:\safetychan\research\global-volume-serverless-2026-11-07\`.

#!/bin/bash
# Point d'entrée du worker : copie des modèles du global volume vers /models, puis démarrage
# normal de worker-comfyui (/start.sh : ComfyUI + handler).
#   GV_MODE=copy   (défaut) copie PRELOAD_MODELS en local avant de lancer ComfyUI
#   GV_MODE=direct pas de copie : ComfyUI lit le volume (à combiner avec COMFY_ARGS="--disable-mmap")
# La copie a lieu AVANT le handler : elle tombe dans le delayTime du job, executionTime = chargement
# depuis le disque local + rendu.
set -u
export GV_ROOT="${GV_ROOT:-/runpod-volume}"
mkdir -p /models

if [ "${GV_MODE:-copy}" = "copy" ]; then
  python -u /opt/gv/preload.py || echo "gv: la copie a échoué, ComfyUI lira le volume en direct"
else
  echo "gv: GV_MODE=${GV_MODE}, pas de copie (COMFY_ARGS=${COMFY_ARGS:-})"
  python -u /opt/gv/preload.py --record-only || true
fi

exec /start.sh

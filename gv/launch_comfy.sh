#!/bin/bash
# Lancé par /start.sh à la place de `python -u /comfyui/main.py` (patch du Dockerfile), en arrière-plan :
# son PID est celui que start.sh écrit dans /tmp/comfyui.pid. On copie d'abord les modèles, puis
# `exec` remplace ce script par ComfyUI sous le même PID.
#
# Pourquoi ici et pas avant /start.sh : le 07/11, avec la copie avant le handler, les workers H3
# (55 Go à copier) redémarraient en boucle (~9 min) sans jamais prendre de job ; Krea (32 Go)
# passait. Ici le handler démarre tout de suite, et il attend ComfyUI sans limite tant que ce
# processus est vivant (check_server de worker-comfyui). La copie tombe alors dans l'executionTime
# du premier job.
#   GV_MODE=copy   (défaut) copie PRELOAD_MODELS en local avant de lancer ComfyUI
#   GV_MODE=direct pas de copie : ComfyUI lit le volume (à combiner avec COMFY_ARGS="--disable-mmap")
export GV_ROOT="${GV_ROOT:-/runpod-volume}"
mkdir -p /models
if [ "${GV_MODE:-copy}" = "copy" ]; then
  python -u /opt/gv/preload.py || echo "gv: la copie a échoué, ComfyUI lira le volume en direct"
else
  echo "gv: GV_MODE=${GV_MODE}, pas de copie"
  python -u /opt/gv/preload.py --record-only || true
fi
exec python -u /comfyui/main.py "$@"

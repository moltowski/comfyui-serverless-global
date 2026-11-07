#!/bin/bash
# Point d'entrée du worker : le /start.sh de worker-comfyui, patché au build pour lancer
# /opt/gv/launch_comfy.sh (copie des modèles puis ComfyUI) et /gv_handler.py.
# La copie ne bloque plus le démarrage du handler (cf. launch_comfy.sh).
export GV_ROOT="${GV_ROOT:-/runpod-volume}"
exec /start.sh

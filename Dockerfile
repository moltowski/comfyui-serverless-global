# comfyui-serverless-global : worker serverless ComfyUI pour le GLOBAL VOLUME RunPod.
#
# Pourquoi une image à part (mesures du 29/09 et du 08/10, cf. research/global-volume-*) :
#   - le global volume est du stockage objet (GeeseFS) : ComfyUI qui y lit les poids en direct
#     bloque, ou met 12 min avec --disable-mmap -> au réveil du worker, on COPIE d'abord les modèles
#     utiles sur le disque local (/models), puis ComfyUI les charge depuis ce disque ;
#   - rien de ce qui s'exécute ne peut vivre sur le volume (pas de .so, pas de chmod +x)
#     -> ComfyUI + nodes sont dans l'image, le volume ne porte que les modèles (sous models/).
#
# Base = handler officiel runpod/worker-comfyui (schéma {"input": {"workflow": <format API>}}),
# comme comfyui-serverless-krea et -h3. ComfyUI + custom nodes = mêmes commits que l'image de pod
# comfyui-pod-global (testée sur test_volume le 08/10), pour qu'un workflow passe de l'une à l'autre.
#
# Démarrage : /gv_start.sh (copie, cf. gv/preload.py) puis /start.sh de la base, patché pour
# accepter COMFY_ARGS et lancer /gv_handler.py (ajoute les mesures de copie à chaque sortie de job).
# Aucun modèle, aucun secret dans l'image.

ARG BASE=runpod/worker-comfyui:5.8.6-base
FROM ${BASE}

ENV PYTHONUNBUFFERED=1

# ffmpeg : VideoHelperSuite / SaveVideo (H3) ; libgl1 + libglib : opencv (WAS, KJNodes).
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# 1. ComfyUI au commit de comfyui-pod-global (v0.37.0 : nodes natifs Qwen 2.1 et MiniMax H3).
#    On met à jour le clone existant (/comfyui) : rejouer `comfy install` échoue sur un workspace
#    existant. `uv pip` et pas `pip` : la base a 2 venvs, le runtime est /opt/venv (piège vécu sur H3).
#    Toujours `--python /opt/venv/bin/python` : sinon uv prend le venv le plus proche du dossier
#    courant, et après un `cd /comfyui/...` c'est /comfyui/.venv (1er build du 07/11 cassé ainsi).
ARG COMFYUI_SHA=a7169322485d0049380fb207fa17e9fb3ec40486
RUN git -C /comfyui fetch --depth 1 origin "${COMFYUI_SHA}" && \
    git -C /comfyui checkout -q FETCH_HEAD && \
    uv pip install --python /opt/venv/bin/python --no-cache-dir -r /comfyui/requirements.txt && \
    python -c "import sys; sys.path.insert(0,'/comfyui'); from comfyui_version import __version__ as v; print('ComfyUI', v); assert v.startswith('0.37'), v"

# 2. torchaudio (importé par le node natif MiniMax H3), à la version exacte du torch de la base.
#    Puis on fige torch / torchvision / torchaudio : aucun requirements.txt de node ne les remplace.
RUN TV=$(python -c "import torch; print(torch.__version__.split('+')[0])") && echo "torch=$TV" && \
    ( python -c "import torchaudio" 2>/dev/null || \
      uv pip install --python /opt/venv/bin/python --no-cache-dir "torchaudio==${TV}" --index-url https://download.pytorch.org/whl/cu128 ) && \
    uv pip freeze --python /opt/venv/bin/python | grep -iE '^(torch|torchvision|torchaudio)==' > /opt/torch-constraints.txt && \
    cat /opt/torch-constraints.txt

# 3. Custom nodes publics épinglés au SHA (nodes.txt, même liste que comfyui-pod-global).
COPY nodes.txt /opt/nodes.txt
RUN cd /comfyui/custom_nodes && \
    grep -vE '^\s*(#|$)' /opt/nodes.txt | while read url sha; do \
      d=$(basename "$url" .git); \
      git clone -q "$url" "$d" && git -C "$d" checkout -q "$sha" || exit 1; \
      if [ -f "$d/requirements.txt" ]; then \
        uv pip install --python /opt/venv/bin/python --no-cache-dir -c /opt/torch-constraints.txt -r "$d/requirements.txt" || exit 1; \
      fi; \
      echo "node $d @ $sha"; \
    done

# 4. Nos nodes (PT_InputHub v2, PT_LoadAudioOptional) : les workflows prod en dépendent.
COPY custom_nodes/ /comfyui/custom_nodes/

# 5. Modèles : /models (copies locales) d'abord, le global volume en secours.
COPY extra_model_paths.yaml /comfyui/extra_model_paths.yaml

# 6. Démarrage : copie, puis le /start.sh de la base, patché (COMFY_ARGS + handler enveloppé).
COPY model_presets.txt /opt/gv/model_presets.txt
COPY gv/preload.py /opt/gv/preload.py
COPY gv/gv_start.sh /gv_start.sh
COPY gv/gv_handler.py /gv_handler.py
RUN chmod +x /gv_start.sh && \
    sed -i 's#python -u /comfyui/main.py #python -u /comfyui/main.py ${COMFY_ARGS:-} #g; s#python -u /handler.py#python -u /gv_handler.py#g' /start.sh && \
    test "$(grep -c 'COMFY_ARGS' /start.sh)" = 2 && \
    test "$(grep -c 'gv_handler.py' /start.sh)" = 2 && \
    python -c "import ast; ast.parse(open('/gv_handler.py').read()); ast.parse(open('/opt/gv/preload.py').read())"

# 7. Vérification au build : torch n'a pas bougé, ComfyUI + tous les nodes s'importent.
RUN python -c "import torch, torchaudio; print('torch', torch.__version__, 'torchaudio', torchaudio.__version__)" && \
    cd /comfyui && \
    timeout 600 python main.py --cpu --quick-test-for-ci > /tmp/import-test.log 2>&1; \
    grep -B3 -A15 -E "Traceback|IMPORT FAILED" /tmp/import-test.log | head -150; \
    ! grep -q "IMPORT FAILED" /tmp/import-test.log

CMD ["/gv_start.sh"]

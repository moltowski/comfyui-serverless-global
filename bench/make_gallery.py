#!/usr/bin/env python3
"""Page de comparaison du banc : toutes les images et vidéos de runs/, avec temps et coût estimé.

    python bench/make_gallery.py research/global-volume-serverless-2026-11-07/runs

Écrit <runs>/compare.html (fichiers référencés en relatif, même dossier). Clic = plein écran.
Coût estimé = secondes facturées × prix RunPod flex (page pricing du 04/11/2026) :
  froid  = copie (gv.total_s) + ~20 s de démarrage + exécution + 5 s d'inactivité
  chaud  = exécution + 5 s d'inactivité
Pour l'endpoint témoin (pas de mesure gv), le froid = exécution (chargement compris) + 5 s.
"""
import html
import json
import os
import sys

PRICE_H = {"5090": 1.79, "PRO 6000": 3.49, "6000 Ada": 1.75, "A40": 1.22, "A6000": 1.22}


def price_per_s(gpu):
    for k, v in PRICE_H.items():
        if k in (gpu or ""):
            return v / 3600
    return None


def main():
    runs = sys.argv[1]
    recs = [json.loads(l) for l in open(os.path.join(runs, "results.jsonl"), encoding="utf-8")]
    # $/h réellement facturé par worker (bench/worker_costs.py) : prioritaire sur la grille publique
    rate = {}
    wpath = os.path.join(runs, "workers.jsonl")
    if os.path.exists(wpath):
        for l in open(wpath, encoding="utf-8"):
            w = json.loads(l)
            if w.get("costPerHr"):
                rate[w["workerId"]] = w["costPerHr"]
    GPU_BY_RATE = {1.19: "RTX 5090", 2.49: "RTX PRO 6000"}
    files = sorted(os.listdir(runs))
    cards = []
    for r in recs:
        if r.get("status") != "COMPLETED":
            continue
        media = [f for f in files if f.startswith("%s_%s_" % (r["tag"], r["id"]))]
        gv = r.get("gv") or {}
        gpu = r.get("gpu") or gv.get("gpu") or GPU_BY_RATE.get(rate.get(r.get("workerId")), "")
        dc = (gv.get("env") or {}).get("RUNPOD_DC_ID") or r.get("dc") or "?"
        cold = gv.get("job_index") == 1 if gv else r.get("cold")
        exec_s = r.get("exec_s") or 0
        pps = rate[r["workerId"]] / 3600 if r.get("workerId") in rate else price_per_s(gpu)
        if gv and cold:
            billed = (gv.get("total_s") or 0) + 20 + exec_s + 5
        else:
            billed = exec_s + 5
        cost = "%.3f $" % (billed * pps) if pps else "?"
        total = (r.get("delay_s") or 0) + exec_s
        ep = "témoin c-edge" if r["tag"].startswith("ref_") else "global volume"
        label = "%s · %s · %s · %s" % (r["tag"], ep, gpu.split(",")[0].replace("NVIDIA ", ""), dc)
        stats = "%s · attente %ss · exécution %ss · total %ss · ~%s" % (
            "FROID" if cold else "chaud", r.get("delay_s"), exec_s, round(total, 1), cost)
        for m in media:
            q = html.escape(m)
            if m.lower().endswith((".mp4", ".webm", ".mov")):
                el = '<video src="%s" controls loop muted playsinline preload="metadata"></video>' % q
            else:
                el = '<img src="%s" loading="lazy" alt="">' % q
            cards.append('<figure>%s<figcaption><b>%s</b><br>%s</figcaption></figure>' % (el, html.escape(label), html.escape(stats)))
    page = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Banc global volume</title><style>
:root{--bg:#111;--fg:#eee;--mut:#aaa;--card:#1c1c1c}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}
h1{font-size:18px;margin:0 0 4px} p{color:var(--mut);margin:0 0 16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
figure{margin:0;background:var(--card);border-radius:8px;overflow:hidden}
img,video{width:100%;display:block;background:#000;cursor:zoom-in;max-height:520px;object-fit:contain}
figcaption{padding:8px;font-size:12px;color:var(--mut)} figcaption b{color:var(--fg)}
#z{position:fixed;inset:0;background:#000e;display:none;align-items:center;justify-content:center;z-index:9}
#z img,#z video{max-width:96vw;max-height:96vh;width:auto;cursor:zoom-out}
</style></head><body><h1>Banc global volume serverless</h1>
<p>__N__ rendus. Coût = secondes facturées × $/h réel du worker sur le compte (5090 1,19 $/h, RTX PRO 6000 2,49 $/h ; grille publique sinon). Froid global volume = copie + 20 s + exécution + 5 s d'inactivité ; chaud et témoin = exécution + 5 s. Clic = plein écran, Échap pour fermer.</p>
<div class="grid">__CARDS__</div><div id="z"></div><script>
const z=document.getElementById('z');
document.querySelectorAll('.grid img,.grid video').forEach(e=>e.addEventListener('click',ev=>{
  if(e.tagName==='VIDEO'&&ev.offsetY>e.clientHeight-40)return;
  z.innerHTML='';const c=e.cloneNode();if(c.tagName==='VIDEO'){c.controls=true;c.autoplay=true;c.muted=false}
  z.appendChild(c);z.style.display='flex'}));
z.addEventListener('click',()=>{z.style.display='none';z.innerHTML=''});
addEventListener('keydown',e=>{if(e.key==='Escape'){z.style.display='none';z.innerHTML=''}});
</script></body></html>""".replace("__N__", str(len(cards))).replace("__CARDS__", "\n".join(cards))
    out = os.path.join(runs, "compare.html")
    open(out, "w", encoding="utf-8").write(page)
    print(out, len(cards), "rendus")


if __name__ == "__main__":
    main()

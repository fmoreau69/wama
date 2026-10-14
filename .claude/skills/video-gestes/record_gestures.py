"""Rejoue des gestes nocturnes choisis en filmant chaque contexte Playwright (vidéo .webm).

Aucune modification du dépôt : `Browser.new_context` est enveloppé à l'exécution pour ajouter
`record_video_dir` et un curseur visible (le mode headless n'en dessine pas).
Usage (WSL, cwd = dépôt) : python record_gestures.py <out_dir> <id1,id2,...>
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django  # noqa: E402
django.setup()

from playwright.sync_api._generated import Browser  # noqa: E402

from wama.common.services import nightly_tests as nt  # noqa: E402

OUT = Path(sys.argv[1])
IDS = [i for i in sys.argv[2].split(',') if i]
CURRENT = {'dir': OUT / '_unassigned'}

CURSOR_JS = r"""
(() => {
  if (window.__recCursor) return; window.__recCursor = true;
  const mk = () => {
    if (document.getElementById('__rec_cursor')) return;
    const c = document.createElement('div'); c.id = '__rec_cursor';
    c.style.cssText = 'position:fixed;left:-50px;top:-50px;width:22px;height:22px;margin:-11px 0 0 -11px;'
      + 'border-radius:50%;background:rgba(255,80,40,.55);border:2px solid #fff;box-shadow:0 0 6px rgba(0,0,0,.6);'
      + 'z-index:2147483647;pointer-events:none;transition:left .08s,top .08s';
    document.documentElement.appendChild(c);
  };
  const move = (e) => { mk(); const c = document.getElementById('__rec_cursor');
    c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; };
  document.addEventListener('mousemove', move, true);
  document.addEventListener('pointermove', move, true);
  document.addEventListener('mousedown', (e) => {
    move(e);
    const r = document.createElement('div');
    r.style.cssText = 'position:fixed;left:' + e.clientX + 'px;top:' + e.clientY + 'px;width:16px;height:16px;'
      + 'margin:-8px 0 0 -8px;border-radius:50%;border:3px solid rgba(255,80,40,.9);z-index:2147483647;'
      + 'pointer-events:none;transition:all .45s ease-out;opacity:1';
    document.documentElement.appendChild(r);
    requestAnimationFrame(() => { r.style.width = r.style.height = '60px'; r.style.margin = '-30px 0 0 -30px'; r.style.opacity = '0'; });
    setTimeout(() => r.remove(), 600);
  }, true);
})();
"""

_orig_new_context = Browser.new_context
_orig_new_page = Browser.new_page


def _video_kw(kw):
    vp = kw.get('viewport') or {'width': 1280, 'height': 720}
    CURRENT['dir'].mkdir(parents=True, exist_ok=True)
    kw.setdefault('record_video_dir', str(CURRENT['dir']))
    kw.setdefault('record_video_size', {'width': vp['width'], 'height': vp['height']})
    return kw


def new_context(self, *a, **kw):
    ctx = _orig_new_context(self, *a, **_video_kw(kw))
    ctx.add_init_script(CURSOR_JS)
    return ctx


def new_page(self, *a, **kw):
    page = _orig_new_page(self, *a, **_video_kw(kw))
    page.add_init_script(CURSOR_JS)
    return page


_orig_close = Browser.close


def close(self, *a, **kw):
    # `browser.close()` coupe l'encodeur (fichier tronqué à 1 Mio) ; fermer les contextes
    # d'abord attend l'écriture complète de chaque vidéo.
    for c in list(self.contexts):
        try:
            c.close()
        except Exception:
            pass
    return _orig_close(self, *a, **kw)


Browser.new_context = new_context
Browser.new_page = new_page
Browser.close = close

by_id = {s.id: s for s in nt.REGISTRY}
missing = [i for i in IDS if i not in by_id]
if missing:
    print('UNKNOWN', missing)
ctx = {'user': nt.get_test_user()}
manifest = []
for sid in IDS:
    sc = by_id.get(sid)
    if not sc:
        continue
    CURRENT['dir'] = OUT / sid
    t0 = time.time()
    res = nt.run_one(sc, ctx)
    vids = sorted(str(p) for p in CURRENT['dir'].glob('*.webm')) if CURRENT['dir'].exists() else []
    row = {'id': sid, 'app': sc.app, 'description': sc.description, 'ok': res.ok,
           'skipped': res.skipped, 'duration_s': round(time.time() - t0, 1),
           'error': res.error, 'detail': (res.detail or '')[:300], 'videos': vids}
    manifest.append(row)
    print(('OK ' if res.ok else 'SK ' if res.skipped else 'KO '), sid, row['duration_s'], len(vids), flush=True)
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')

swept = nt.sweep_test_witnesses()
print('witness files swept:', swept)

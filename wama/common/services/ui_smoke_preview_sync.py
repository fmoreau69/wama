"""Scénario nocturne `common.preview_sync` — la PRÉCISION de la lecture de l'aperçu, mesurée.

Né le 2026-11-05 (demande de Fabien : aligner la lecture de l'aperçu sur celle du monde Data
« sans rien perdre, sans rien casser, en vérifiant que la synchronisation est au moins aussi bonne
que l'actuelle. Aucune régression admise »). Les gardes V8 tiennent les RÈGLES de l'axe et de la
surcouche ; aucune ne voit ce que l'ÉCRAN montre. Celui-ci le voit :

  • des vidéos TÉMOINS, fabriquées à chaque passe par le ffmpeg de WAMA : chaque image porte son
    numéro en dix blocs noirs ou blancs — l'image réellement montrée se lit à ses pixels ;
  • les briques de l'aperçu telles qu'elles sont SERVIES (`staticfiles/common/js/`), dans une page
    nue servie à part — ni compte, ni élément, ni serveur WAMA ; `js_root` en lit d'autres (la
    contre-épreuve sur le code d'avant) ;
  • les gestes d'un `<video controls>` (lecture, pause, position, vitesse) puis le clavier de la
    visionneuse (Espace, J/K/L, Début, Espace sur le lecteur natif qui a le focus), joués dans
    Chromium ;
  • le juge : l'image PRÉSENTÉE à l'écran (`requestVideoFrameCallback`, `mediaTime`) — une lecture
    de pixels par `drawImage` devance l'écran d'une image, mesuré sur le banc du 2026-11-05.
    À L'ARRÊT seulement, le juge est le PIXEL (2026-11-12) : une vidéo posée ne bouge plus, et le
    navigateur ne rappelle pas toujours l'image qu'un positionnement vient de poser — sous charge,
    le dernier rappel restait celui de la lecture d'avant, deux images plus loin.

Seuils (absolus, jamais relatifs au code d'avant) : la surcouche sur l'image présentée ≥ 99 % en
lecture, et sur l'image montrée à l'arrêt ; Comparer à l'arrêt sur la même image, toujours ; l'écart d'horloge entre les deux vidéos de
Comparer ≤ la tolérance de l'axe (p95) et sous son seuil de repositionnement (max) ; la vitesse
choisie tenue par les deux ; chaque touche du magnéto prise et suivie de son effet.

⚠ Le rendu d'un Chromium sans écran sur une machine chargée saute des images : la part d'images
IDENTIQUES entre les deux vidéos pendant la lecture n'est pas un seuil (±15 points d'une passe à
l'autre, `WAMA_APP_GENERATION_ROUTE.md` §F3b, palier du 2026-11-05) ; l'écart d'horloge, si.
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

#: Les vidéos témoins : dix bits de numéro d'image (blocs de 40 px), 25 i/s, 10 s.
BITS = 10
FPS = 25
SECONDS = 10
JS_FILES = ('wama-keys.js', 'wama-axis.js', 'wama-shuttle.js', 'wama-preview-overlay.js',
            'media-preview.js')

#: Les phases où la vidéo joue, et celles où elle est arrêtée.
PLAYING = ('play1', 'play2', 'rate2')
STILL = ('pause1', 'seek', 'pause2')

#: Le clavier de la visionneuse : phase, touche, attente (ms). `focus` donne le focus à la vidéo.
KEYS = (('space', 'Space', 1500), ('space2', 'Space', 600), ('L', 'l', 1200), ('K', 'k', 600),
        ('J', 'j', 1000), ('K2', 'k', 600), ('home', 'Home', 600), ('focus', None, 0),
        ('native', 'Space', 1000), ('native2', 'Space', 600))

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>preview sync</title>
<style>body{margin:0;background:#222}.wama-compare{position:relative;display:inline-block}
.wama-compare-top{position:absolute;left:0;top:0;overflow:hidden;pointer-events:none}
.wama-compare-base,.wama-viewer-media{width:800px;display:block}.modal{display:none}</style>
<script>
(function () {
  // Chaque rappel d'image et d'animation porte l'instant de SON image ; chaque texte que dessine la
  // surcouche est noté avec cet instant. Rien du code mesuré n'est modifié.
  var raf = window.requestAnimationFrame.bind(window);
  window.__frameTs = 0;
  window.requestAnimationFrame = function (fn) { return raf(function (ts) { window.__frameTs = ts; fn(ts); }); };
  var rvfc = HTMLVideoElement.prototype.requestVideoFrameCallback;
  if (rvfc) HTMLVideoElement.prototype.requestVideoFrameCallback = function (fn) {
    return rvfc.call(this, function (now, meta) { window.__frameTs = now; fn(now, meta); });
  };
  window.__drawn = [];
  var fill = CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.fillText = function (text) {
    window.__drawn.push({ts: window.__frameTs, text: String(text)});
    return fill.apply(this, arguments);
  };
  window.bootstrap = {Modal: {getOrCreateInstance: function (m) {
    return {show: function () { m.classList.add('show'); m.style.display = 'block'; },
            hide: function () { m.classList.remove('show'); }}; }}};
})();
</script></head><body><div id="stage"></div>
%(scripts)s
<script>%(probe)s</script></body></html>"""

PROBE = """(function () {
  var BITS = %(bits)d, samples = [], presented = [], recording = false, phase = '';
  var probe = document.createElement('canvas');
  probe.width = BITS; probe.height = 1;
  var pctx = probe.getContext('2d', {willReadFrequently: true});
  function pixels(v) {
    if (!v || v.readyState < 2) return null;
    var h = v.videoHeight, block = v.videoWidth / BITS, idx = 0;
    pctx.drawImage(v, 0, Math.floor(h / 2) - 2, block * BITS, 4, 0, 0, BITS, 1);
    var px = pctx.getImageData(0, 0, BITS, 1).data;
    for (var k = 0; k < BITS; k++) if (px[k * 4] > 128) idx |= (1 << k);
    return idx;
  }
  function videos(mode) {
    return mode === 'compare'
      ? [document.querySelector('.wama-compare-base'), document.querySelector('.wama-compare-top video')]
      : [document.querySelector('.wama-viewer-media')];
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  async function mount(mode) {
    var input = {url: 'in.webm', mime_type: 'video/webm', name: 'in',
                 overlay: {url: 'doc.json', boxes: true, labels: true, confidence: false}};
    if (mode === 'compare') {
      document.getElementById('stage').appendChild(window.WamaMediaPreview.compareView(
        input, {url: 'out.webm', mime_type: 'video/webm', name: 'out'}, 'Entrée'));
    } else {
      window.WamaMediaPreview.show(input);
    }
    for (var i = 0; i < 200 && videos(mode).some(function (v) { return !v || v.readyState < 2; }); i++) await sleep(50);
    var vs = videos(mode);
    vs.forEach(function (v, n) {
      if (!v.requestVideoFrameCallback) return;
      var cb = function (now, meta) {
        if (recording) presented.push({n: n, at: now, phase: phase, mediaTime: meta.mediaTime});
        v.requestVideoFrameCallback(cb);
      };
      v.requestVideoFrameCallback(cb);
    });
    (function loop() { requestAnimationFrame(function (ts) {
      if (recording) samples.push({ts: ts, phase: phase, shown: vs.map(pixels),
                                   t: vs.map(function (v) { return v.currentTime; }),
                                   paused: vs.map(function (v) { return v.paused; })});
      loop(); }); })();
    await sleep(400);
    return vs;
  }
  window.__sync = {
    native: async function (mode) {
      var base = (await mount(mode))[0];
      recording = true;
      phase = 'play1'; base.play(); await sleep(3000);
      phase = 'pause1'; base.pause(); await sleep(800);
      phase = 'seek'; base.currentTime = 2.3; await sleep(800);
      phase = 'play2'; base.play(); await sleep(2000);
      phase = 'rate2'; base.playbackRate = 2; await sleep(2000);
      phase = 'pause2'; base.pause(); await sleep(800);
      recording = false;
      return {samples: samples, presented: presented, drawn: window.__drawn};
    },
    keys: async function () {
      var base = (await mount('viewer'))[0], log = [];
      document.addEventListener('keydown', function (e) {
        setTimeout(function () { log.push({phase: phase, code: e.code, taken: e.defaultPrevented}); }, 0);
      });
      recording = true;
      window.__keysLog = log;
      return true;
    },
    setPhase: function (p) { phase = p; },
    state: function () { var v = videos('viewer')[0];
      return {paused: v.paused, t: v.currentTime, rate: v.playbackRate}; },
    focus: function () { videos('viewer')[0].focus(); return document.activeElement === videos('viewer')[0]; },
    keysLog: function () { return window.__keysLog; },
  };
})();"""


# ── Les lectures du résultat (pures, gardées par `tests_preview_navigation.PreviewSyncVerdictTest`) ──

def presented_frames(result: dict, fps: float = FPS) -> list:
    """Pour chaque échantillon, l'image que chaque vidéo PRÉSENTE à cet instant d'écran : le dernier
    rappel d'image de la même mise à jour ou d'avant (`round(mediaTime × fps)`, l'instant d'une
    image étant le sien) ; None tant que la vidéo n'a rien montré."""
    per = {}
    for p in result.get('presented') or []:
        per.setdefault(p['n'], []).append(p)
    out = []
    for s in result.get('samples') or []:
        row = []
        for n in range(len(s['shown'])):
            seen = [p for p in per.get(n, []) if p['at'] <= s['ts'] + 0.5]
            row.append(int(round(seen[-1]['mediaTime'] * fps)) if seen else None)
        out.append(row)
    return out


def overlay_on_presented(result: dict, frames: list) -> tuple:
    """(images justes, images jugées) : le numéro que la surcouche a dessiné en dernier, à l'instant
    d'écran d'un échantillon de LECTURE, contre l'image que la vidéo de référence présente."""
    drawn = sorted(result.get('drawn') or [], key=lambda d: d['ts'])
    j, last, right, judged = 0, None, 0, 0
    for s, row in zip(result.get('samples') or [], frames):
        while j < len(drawn) and drawn[j]['ts'] <= s['ts']:
            last = drawn[j]
            j += 1
        if s['phase'] not in PLAYING or last is None or row[0] is None:
            continue
        judged += 1
        right += int(last['text'] == str(row[0]))
    return right, judged


def rest_frames(result: dict) -> dict:
    """Les images MONTRÉES par chaque vidéo à la FIN de chaque phase d'arrêt — lues à leurs
    PIXELS. Pas au dernier rappel d'image : posée à l'arrêt, une vidéo n'en reçoit pas toujours un
    (mesuré sous charge le 2026-11-12 : les deux vidéos montraient l'image 206, le dernier rappel
    de la première disait 208 — le scénario rougissait deux nuits de suite sur un écart que
    l'écran n'avait pas)."""
    out = {}
    for s in result.get('samples') or []:
        if s['phase'] in STILL:
            out[s['phase']] = list(s['shown'])
    return out


def overlay_at_rest(result: dict) -> dict:
    """Pour chaque phase d'arrêt : (le numéro que la surcouche a dessiné en dernier, l'image que
    la vidéo de référence montre) à la fin de la phase. Un dessin porte l'instant du dernier rendu
    d'AVANT lui : celui qui suit le dernier relevé d'une phase (le positionnement de la phase
    suivante) a le même instant que ce relevé — d'où la comparaison stricte."""
    drawn = sorted(result.get('drawn') or [], key=lambda d: d['ts'])
    out = {}
    for s in result.get('samples') or []:
        if s['phase'] not in STILL:
            continue
        before = [d for d in drawn if d['ts'] < s['ts']]
        out[s['phase']] = (before[-1]['text'] if before else None, s['shown'][0])
    return out


def clock_gaps_ms(result: dict) -> list:
    """L'écart d'horloge (`currentTime`, ms) entre les deux vidéos, quand elles jouent toutes deux —
    ce que tient le recalage lui-même ; les images présentées y ajoutent la gigue des décodeurs."""
    return [abs(s['t'][0] - s['t'][1]) * 1000 for s in result.get('samples') or []
            if s['phase'] in PLAYING and len(s['t']) == 2 and not any(s['paused'])]


def speed_of(result: dict, frames: list, phase: str, n: int, fps: float = FPS):
    """La vitesse tenue par la vidéo `n` sur la seconde moitié d'une phase (images / s réelle)."""
    rows = [(s['ts'], row[n]) for s, row in zip(result.get('samples') or [], frames)
            if s['phase'] == phase and row[n] is not None]
    rows = rows[len(rows) // 2:]
    if len(rows) < 5 or rows[-1][0] <= rows[0][0]:
        return None
    return (rows[-1][1] - rows[0][1]) / fps / ((rows[-1][0] - rows[0][0]) / 1000)


def p95(values: list):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(0.95 * (len(values) - 1))))]


# ── Le banc ──────────────────────────────────────────────────────────────────────────────────

class _Handler(SimpleHTTPRequestHandler):
    """La page et les témoins depuis `directory`, les briques depuis `js_root` (`/js/<fichier>`),
    avec les PLAGES d'octets — sans elles un navigateur ne positionne pas une vidéo, il repart de 0
    (mesuré sur le premier passage du banc)."""

    js_root = ''

    def log_message(self, *a):
        pass

    def translate_path(self, path):
        clean = path.split('?', 1)[0]
        if clean.startswith('/js/'):
            return os.path.join(self.js_root, os.path.basename(clean))
        return super().translate_path(path)

    def send_head(self):
        rng = self.headers.get('Range')
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        start, _, end = rng.replace('bytes=', '').partition('-')
        start = int(start or 0)
        end = min(int(end) if end else size - 1, size - 1)
        handle = open(path, 'rb')
        handle.seek(start)
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(end - start + 1))
        self.end_headers()
        self._left = end - start + 1
        return handle

    def copyfile(self, source, outputfile):
        left = getattr(self, '_left', None)
        if left is None:
            return super().copyfile(source, outputfile)
        while left > 0:
            chunk = source.read(min(65536, left))
            if not chunk:
                break
            try:
                outputfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                break
            left -= len(chunk)


def _witnesses(folder: str):
    """Deux vidéos témoins (l'entrée, la sortie réencodée : deux décodages indépendants) et le
    document de détections dont chaque image porte son numéro pour libellé."""
    from wama.common.utils.ffmpeg_utils import adapt_path_for_ffmpeg, get_ffmpeg_exe
    ffmpeg = get_ffmpeg_exe()
    lum = (f"lum=if(bitand(floor(N/pow(2\\,floor(X/40)))\\,1)\\,235\\,16):cb=128:cr=128")
    common = ['-c:v', 'libvpx-vp9', '-b:v', '0', '-g', str(FPS), '-deadline', 'realtime', '-cpu-used', '8']
    src = os.path.join(folder, 'in.webm')
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    f'color=c=black:s=400x224:r={FPS}:d={SECONDS},format=yuv420p', '-vf', f'geq={lum}',
                    *common, '-crf', '30', adapt_path_for_ffmpeg(src, ffmpeg)], check=True, timeout=180)
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', adapt_path_for_ffmpeg(src, ffmpeg), *common,
                    '-crf', '40', adapt_path_for_ffmpeg(os.path.join(folder, 'out.webm'), ffmpeg)],
                   check=True, timeout=180)
    doc = {'version': 1, 'media': 'video', 'width': 400, 'height': 224, 'fps': FPS,
           'frame_count': FPS * SECONDS,
           'frames': [{'i': i, 'd': [{'box': [8, 8, 120, 60], 'label': str(i), 'conf': None}]}
                      for i in range(FPS * SECONDS)]}
    with open(os.path.join(folder, 'doc.json'), 'w', encoding='utf-8') as fh:
        json.dump(doc, fh)


def check_preview_sync(js_root: str = ''):
    """La lecture de l'aperçu, mesurée à l'image présentée (cf. en-tête). (ok, détail)"""
    from django.conf import settings
    from playwright.sync_api import sync_playwright

    from .nightly_tests import SkipScenario
    from .ui_smoke import IGNORED_CONSOLE

    js_root = js_root or os.path.join(settings.BASE_DIR, 'staticfiles', 'common', 'js')
    missing = [f for f in JS_FILES if not os.path.isfile(os.path.join(js_root, f))]
    if missing:
        raise SkipScenario(f'briques absentes de {js_root} : {missing}')
    folder = tempfile.mkdtemp(prefix='wama_preview_sync_')
    verdicts = []

    def verdict(ok, text):
        verdicts.append((bool(ok), text))

    try:
        _witnesses(folder)
        with open(os.path.join(folder, 'index.html'), 'w', encoding='utf-8') as fh:
            fh.write(PAGE % {'scripts': '\n'.join(f'<script src="/js/{f}"></script>' for f in JS_FILES),
                             'probe': PROBE % {'bits': BITS}})
        handler = type('Handler', (_Handler,), {'js_root': js_root})
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(handler, directory=folder))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_address[1]}/index.html'
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
                try:
                    for mode in ('viewer', 'compare'):
                        _native_gestures(browser, url, mode, verdict, IGNORED_CONSOLE)
                    _viewer_keys(browser, url, verdict, IGNORED_CONSOLE)
                finally:
                    browser.close()
        finally:
            server.shutdown()
    finally:
        shutil.rmtree(folder, ignore_errors=True)       # le dossier CRÉÉ ici, par son chemin
    failed = [text for ok, text in verdicts if not ok]
    detail = f"{len(verdicts) - len(failed)}/{len(verdicts)} mesures"
    return (not failed), detail + (f" — ÉCHECS : {failed}" if failed else '')


def _page(browser, url, ignored):
    page = browser.new_page(viewport={'width': 900, 'height': 700})
    errors = []
    page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
    page.on('console', lambda m: errors.append(f'console: {m.text}') if m.type == 'error' else None)
    page.goto(url, wait_until='load')
    return page, (lambda: [e for e in errors if not any(t in e for t in ignored)])


def _native_gestures(browser, url, mode, verdict, ignored):
    page, errors = _page(browser, url, ignored)
    try:
        result = page.evaluate('(m) => window.__sync.native(m)', mode)
    finally:
        shown = errors()
        page.close()
    frames = presented_frames(result)
    right, judged = overlay_on_presented(result, frames)
    verdict(judged and right >= 0.99 * judged,
            f"{mode} : la surcouche est sur l'image présentée ({right}/{judged})")
    verdict(not shown, f"{mode} : aucune erreur JS ({shown[:3]})")
    still = overlay_at_rest(result)
    verdict(set(still) == set(STILL) and all(text == str(frame) for text, frame in still.values()),
            f"{mode} : à l'arrêt, la surcouche est sur l'image montrée ({still})")
    if mode != 'compare':
        return
    rest = rest_frames(result)
    verdict(set(rest) == set(STILL) and all(r[0] is not None and r[0] == r[1] for r in rest.values()),
            f"Comparer : à l'arrêt, les deux vidéos sur la même image ({rest})")
    gaps = clock_gaps_ms(result)
    verdict(gaps and p95(gaps) <= 20 and max(gaps) < 150,
            f"Comparer : écart d'horloge p95 {p95(gaps) or 0:.1f} ms (≤ 20), max {max(gaps or [0]):.1f} ms (< 150)")
    speeds = [speed_of(result, frames, 'rate2', n) for n in (0, 1)]
    verdict(all(s is not None and 1.7 <= s <= 2.3 for s in speeds),
            f"Comparer : la vitesse choisie sur la référence (×2) est tenue par les deux ({speeds})")


def _viewer_keys(browser, url, verdict, ignored):
    page, errors = _page(browser, url, ignored)
    states = {}
    try:
        page.evaluate('() => window.__sync.keys()')
        for phase, key, wait in KEYS:
            if key is None:
                verdict(page.evaluate('() => window.__sync.focus()'), 'visionneuse : la vidéo a le focus')
                continue
            page.evaluate('(p) => window.__sync.setPhase(p)', phase)
            before = page.evaluate('() => window.__sync.state()')
            page.keyboard.press(key)
            page.wait_for_timeout(wait)
            states[phase] = (before, page.evaluate('() => window.__sync.state()'))
        log = {e['phase']: e['taken'] for e in page.evaluate('() => window.__sync.keysLog()')}
    finally:
        shown = errors()
        page.close()
    after = {k: v[1] for k, v in states.items()}
    moved = lambda k: after[k]['t'] - states[k][0]['t']
    verdict(log.get('space') and not after['space']['paused'], f"Espace : la vidéo joue ({after['space']})")
    verdict(log.get('space2') and after['space2']['paused'], f"Espace : elle s'arrête ({after['space2']})")
    verdict(log.get('L') and not after['L']['paused'] and moved('L') > 0.8,
            f"L : en avant ({moved('L'):.2f} s en 1,2 s)")
    verdict(log.get('K') and after['K']['paused'], 'K : arrêt')
    verdict(log.get('J') and moved('J') < -0.5 and after['J']['paused'],
            f"J : en arrière, la vidéo muette ({moved('J'):.2f} s en 1 s)")
    verdict(log.get('home') and after['home']['t'] < 0.05, f"Début : au début ({after['home']['t']:.3f})")
    verdict(log.get('native') is False and not after['native']['paused'] and log.get('native2') is False
            and after['native2']['paused'],
            "Espace sur le lecteur natif qui a le focus : il le garde, une bascule par frappe "
            f"({after['native']['paused']} → {after['native2']['paused']})")
    verdict(not shown, f"visionneuse : aucune erreur JS au clavier ({shown[:3]})")


def register_preview_sync_scenarios():
    from .nightly_tests import register
    register(
        id='common.preview_sync', app='common', stage='ui',
        description=("Lecture de l'aperçu, MESURÉE à l'image présentée (vidéos témoins numérotées) : "
                     "la surcouche sur l'image montrée, les deux vidéos de Comparer sur la même image "
                     "à l'arrêt et à moins de la tolérance de l'axe en lecture, la vitesse choisie "
                     "tenue, le clavier de la visionneuse (Espace, J/K/L, Début, lecteur natif) — "
                     "briques servies, page nue, aucun compte ni GPU"),
        run=lambda ctx: check_preview_sync(),
        timeout_s=240, vram_gb=0.0,
    )

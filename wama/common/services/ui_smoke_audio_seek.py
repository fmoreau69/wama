"""Scénario nocturne `common.audio_seek` — le POSITIONNEMENT d'un audio dans un <audio>, mesuré par
format (2026-11-18).

Né d'une mesure du chantier « cohérence des pistes séparées » : après un positionnement, un MP3 à
débit variable fait entendre, dans Chromium, un endroit du fichier jusqu'à 771 ms avant ce que dit
son `currentTime` ; une partition, une piste ou une ligne de temps qui suit l'axe tombe alors à
côté. Décision de Fabien : un format NON positionnable reçoit une copie de lecture AAC en M4A
(`video_compat.SEEK_INEXACT_AUDIO`, déclarée une fois). Ce banc en fait un FAIT mesuré :

  • un TÉMOIN fabriqué à chaque passe par le ffmpeg de WAMA (un bruit rose découpé en plages de
    six secondes : sans répétition, et au débit qui varie comme celui d'une musique), encodé dans
    chaque format que WAMA reçoit (`FORMATS`) — et sa COPIE DE LECTURE, faite par la recette de
    WAMA (`video_compat.audio_copy_args`) ;
  • chaque fichier positionné à trois instants dans un <audio> Chromium, page nue servie à part
    (plages d'octets) — ni compte, ni élément, ni serveur WAMA ;
  • le juge : ce qu'on ENTEND, enregistré sur le fil audio (AudioWorklet) puis retrouvé dans le
    témoin par corrélation — l'écart avec `currentTime`.

Verdicts : un format est positionnable si ses trois écarts restent sous `TOLERANCE_MS` ; la
déclaration (`seekability` de la sonde commune) doit dire la même chose que la mesure, pour CHAQUE
format ; la copie de lecture est positionnable ; chaque format déclaré a un témoin ici.
"""
import os
import shutil
import subprocess
import tempfile
import threading
import wave
from functools import partial
from http.server import ThreadingHTTPServer

#: Au-delà, un audio ne tombe pas où il dit (la moitié de la tolérance de recalage de l'axe).
TOLERANCE_MS = 10.0
#: Le témoin : bruit rose sur les plages paires de six secondes, silence sur les impaires.
SECONDS = 170
SR = 44100
#: Les instants mesurés (début, milieu, fin du témoin) : à une seconde du début d'une plage de
#: bruit, ce qui s'enregistre ensuite (`SETTLE_MS`, `RECORD_MS`) y reste.
POSITIONS = (13.0, 73.0, 157.0)
#: Ce qui s'enregistre après chaque positionnement, et ce qui est cherché dans le témoin.
SETTLE_MS, RECORD_MS, WINDOW_S = 600, 1800, 1.0

#: Les formats que WAMA reçoit : (nom, extension, options ffmpeg).
FORMATS = (
    ('mp3_vbr', 'mp3', ['-c:a', 'libmp3lame', '-q:a', '4']),
    ('mp3_cbr', 'mp3', ['-c:a', 'libmp3lame', '-b:a', '192k']),
    ('aac_adts', 'aac', ['-c:a', 'aac', '-b:a', '160k']),
    ('m4a', 'm4a', ['-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart']),
    ('ogg_vorbis', 'ogg', ['-c:a', 'libvorbis', '-q:a', '5']),
    ('ogg_opus', 'opus', ['-c:a', 'libopus', '-b:a', '128k']),
    ('webm_opus', 'webm', ['-c:a', 'libopus', '-b:a', '128k']),
    ('flac', 'flac', ['-c:a', 'flac', '-sample_fmt', 's16']),
    ('wav', 'wav', ['-c:a', 'pcm_s16le']),
)
#: Le format dont la COPIE DE LECTURE est mesurée aussi (celui de la décision de Fabien).
COPIED = 'mp3_vbr'

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>audio seek</title></head><body>
<script>
window.__seek = async function (url, pos, settle, record) {
  const ac = new AudioContext({sampleRate: %(sr)d});
  const code = "class R extends AudioWorkletProcessor { constructor(){ super(); this.on = false; " +
    "this.port.onmessage = e => { this.on = e.data; }; } process(inputs){ if (this.on && inputs[0].length) " +
    "this.port.postMessage(inputs[0][0].slice()); return true; } } registerProcessor('rec', R);";
  await ac.audioWorklet.addModule(URL.createObjectURL(new Blob([code], {type: 'application/javascript'})));
  const node = new AudioWorkletNode(ac, 'rec', {channelCount: 1, channelCountMode: 'explicit'});
  const blocks = []; node.port.onmessage = e => blocks.push(e.data);
  const el = new Audio(); el.preload = 'auto'; el.src = url;
  const ready = await Promise.race([
    new Promise(r => el.addEventListener('canplay', () => r(true), {once: true})),
    new Promise(r => el.addEventListener('error', () => r(false), {once: true})),
    new Promise(r => setTimeout(() => r(false), 30000))]);
  if (!ready) { await ac.close(); return {error: 'illisible'}; }
  ac.createMediaElementSource(el).connect(node); node.connect(ac.destination);
  el.currentTime = pos;
  await new Promise(r => el.addEventListener('seeked', r, {once: true}));
  await el.play();
  await new Promise(r => setTimeout(r, settle));
  node.port.postMessage(true);
  const at = el.currentTime;
  await new Promise(r => setTimeout(r, record));
  node.port.postMessage(false); el.pause();
  await new Promise(r => setTimeout(r, 200));
  const n = blocks.length * 128, all = new Float32Array(n);
  blocks.forEach((b, k) => all.set(b, k * 128));
  el.removeAttribute('src'); el.load(); await ac.close();
  return {at: at, samples: Array.from(all)};
};
</script></body></html>"""


# ── Les lectures du résultat (pures, gardées par `tests_playback_copy.AudioSeekBenchTest`) ──────

def heard_offset_ms(recorded, reference, at: float, sr: int = SR, window_s: float = WINDOW_S):
    """L'écart (ms) entre ce qu'on ENTEND et ce que dit `currentTime` (`at`, au début de
    l'enregistrement) : où la fenêtre enregistrée tombe dans le témoin, moins `at` — négatif quand
    le son entendu vient d'AVANT. (écart, corrélation normalisée), ou (None, 0) sans signal."""
    import numpy as np
    rec = np.asarray(recorded, dtype=np.float64)
    ref = np.asarray(reference, dtype=np.float64)
    skip = int(0.2 * sr)
    win = rec[skip:skip + int(window_s * sr)]
    if len(win) < sr // 10 or not (win ** 2).mean() > 1e-8:
        return None, 0.0
    guess = int(round(at * sr)) + skip
    lo = max(0, guess - sr)
    seg = ref[lo:guess + sr + len(win)]
    if len(seg) <= len(win):
        return None, 0.0
    n = 1 << int(np.ceil(np.log2(len(seg) + len(win))))
    corr = np.fft.irfft(np.fft.rfft(seg, n) * np.conj(np.fft.rfft(win, n)), n)[:len(seg) - len(win) + 1]
    cs = np.concatenate([[0.0], np.cumsum(seg ** 2)])
    energy = np.sqrt(np.maximum(cs[len(win):] - cs[:-len(win)], 0)) * np.sqrt((win ** 2).sum()) + 1e-12
    c = corr / energy
    k = int(np.argmax(c))
    return round(1000.0 * (lo + k - guess) / sr, 1), float(c[k])


def measured_seekable(offsets, tolerance_ms: float = TOLERANCE_MS):
    """Positionnable d'après la mesure : un écart au-delà de la tolérance le PROUVE non
    positionnable ; sinon chaque écart doit être lu (None : un instant n'a rien donné — un format ne
    se dit pas juste sur une mesure manquante). Mesuré le 2026-11-18 : l'AAC brut (ADTS) se pose
    à −23 ms deux fois et ne rend rien à 157 s."""
    if not offsets:
        return None
    if any(o is not None and abs(o) > tolerance_ms for o in offsets):
        return False
    if any(o is None for o in offsets):
        return None
    return True


def disagreements(rows) -> list:
    """Les formats dont la déclaration (`declared`) et la mesure (`measured`) divergent."""
    return [r['name'] for r in rows if r['measured'] is None or r['declared'] != r['measured']]


# ── Le banc ──────────────────────────────────────────────────────────────────────────────────

def _witness(folder: str, ffmpeg: str):
    """Le témoin (WAV) : bruit rose sur les plages paires de six secondes."""
    from wama.common.utils.ffmpeg_utils import adapt_path_for_ffmpeg
    src = os.path.join(folder, 'source.wav')
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    f'anoisesrc=d={SECONDS}:c=pink:r={SR}:a=0.4:seed=20261118',
                    '-af', "volume='lt(mod(t,12),6)':eval=frame", '-ac', '2', '-c:a', 'pcm_s16le',
                    adapt_path_for_ffmpeg(src, ffmpeg)], check=True, timeout=180)
    return src


def _mono(path: str):
    import numpy as np
    with wave.open(path) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, w.getnchannels())
    return x.astype(np.float64).mean(axis=1) / 32768


def check_audio_seek():
    """Le positionnement de chaque format audio, mesuré, contre la déclaration (cf. en-tête).
    (ok, détail)"""
    from playwright.sync_api import sync_playwright

    from wama.common.utils.ffmpeg_utils import adapt_path_for_ffmpeg, get_ffmpeg_exe
    from wama.common.utils.media_probe import probe_audio_format
    from wama.common.utils.video_compat import (SEEK_INEXACT_AUDIO, _transcode, audio_copy_args,
                                                seekability)

    from .nightly_tests import SkipScenario
    from .ui_smoke_preview_sync import _Handler

    ffmpeg = get_ffmpeg_exe()
    if not ffmpeg:
        raise SkipScenario('ffmpeg absent')
    folder = tempfile.mkdtemp(prefix='wama_audio_seek_')
    rows, verdicts = [], []
    try:
        source = _witness(folder, ffmpeg)
        reference = _mono(source)
        files = []
        for name, ext, args in FORMATS:
            path = os.path.join(folder, f'{name}.{ext}')
            subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', adapt_path_for_ffmpeg(source, ffmpeg),
                            *args, adapt_path_for_ffmpeg(path, ffmpeg)], check=True, timeout=300)
            files.append((name, path))
        copied = dict(files)[COPIED]
        copy = os.path.join(folder, 'playback_copy.m4a')
        if not _transcode(copied, copy, audio_copy_args(probe_audio_format(copied).get('codec', '')),
                          timeout=300):
            raise RuntimeError('copie de lecture du témoin impossible')
        files.append(('playback_copy', copy))
        with open(os.path.join(folder, 'index.html'), 'w', encoding='utf-8') as fh:
            fh.write(PAGE % {'sr': SR})
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(_Handler, directory=folder))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_address[1]}/'
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
                try:
                    page = browser.new_page()
                    page.goto(base + 'index.html', wait_until='load')
                    for name, path in files:
                        offsets = []
                        for pos in POSITIONS:
                            got = page.evaluate('(a) => window.__seek(a[0], a[1], a[2], a[3])',
                                                [base + os.path.basename(path), pos, SETTLE_MS, RECORD_MS])
                            offsets.append(None if got.get('error') else
                                           heard_offset_ms(got['samples'], reference, got['at'])[0])
                        info = probe_audio_format(path)
                        rows.append({'name': name, 'offsets': offsets, 'declared': seekability(info)[0],
                                     'format': (info.get('container', ''), info.get('codec', '')),
                                     'measured': measured_seekable(offsets)})
                finally:
                    browser.close()
        finally:
            server.shutdown()
    finally:
        shutil.rmtree(folder, ignore_errors=True)       # le dossier CRÉÉ ici, par son chemin
    wrong = disagreements([r for r in rows if r['name'] != 'playback_copy'])
    verdicts.append((not wrong, f"déclaration = mesure pour chaque format ({wrong or 'tous'})"))
    copy_row = next(r for r in rows if r['name'] == 'playback_copy')
    verdicts.append((copy_row['measured'] is True,
                     f"la copie de lecture se positionne juste ({copy_row['offsets']} ms)"))
    # Chaque format DÉCLARÉ a un témoin ici, reconnu par la sonde commune (pas par son extension).
    unmeasured = sorted(set(SEEK_INEXACT_AUDIO) - {r['format'] for r in rows})
    verdicts.append((not unmeasured, f"chaque format déclaré a son témoin (sans témoin : {unmeasured})"))
    failed = [text for ok, text in verdicts if not ok]
    detail = ' ; '.join(f"{r['name']} {r['offsets']}" for r in rows)
    return (not failed), detail + (f" — ÉCHECS : {failed}" if failed else '')


def register_audio_seek_scenarios():
    from .nightly_tests import register
    register(
        id='common.audio_seek', app='common', stage='ui',
        description=("Positionnement d'un audio dans un <audio> Chromium, MESURÉ par format (témoin "
                     "bruit rose encodé en MP3, AAC, Vorbis, Opus, FLAC, WAV…) : la déclaration "
                     "`video_compat.SEEK_INEXACT_AUDIO` dit la même chose que la mesure, et la copie "
                     "de lecture se positionne juste — page nue, aucun compte ni GPU"),
        run=lambda ctx: check_audio_seek(),
        timeout_s=600, vram_gb=0.0,
    )

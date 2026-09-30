"""
TalkingHead Backend — avatar 3D parlant (GLB riggé) rendu en VIDÉO, sans modèle génératif.

Le moteur est TalkingHead (met4citizen, MIT, three.js), le même que l'avatar de l'assistant
(`common/static/common/js/wama-avatar.js`) : ici il tourne dans un Chromium SANS ÉCRAN, et le
temps y est PILOTÉ image par image (`wama-avatar-render.js`). Le son est le WAV d'origine,
multiplexé par ffmpeg au décalage relevé sur l'horloge de l'avatar. Veille et mesures :
`docs/construction/archive/PROSPECTION_AVATARS_2026-09-30.md` (voie légère n°1).

Mesures du 2026-09-30 (WSL2) : WebGL sur la 4090 via D3D12 → 10,7 s de vidéo 1280×720 à 25 i/s
rendues en 14,8 à 20,6 s par ce backend (2 rendus), 40,1 s en SwiftShader/CPU. Le pas-à-pas rend la CADENCE de la
vidéo indépendante de cette vitesse : seul le temps de calcul change. ⚠ Le GPU n'est atteint que
par le `chrome-headless-shell` de Playwright (cf. `html_render.launch_chromium`).

Ce que ce moteur ne fait PAS : animer une photo. Son entrée est un avatar 3D riggé (squelette
Mixamo + 52 blendshapes ARKit + visèmes Oculus — annexe A du README TalkingHead). Une photo va
à MuseTalk ; le worker de l'avatarizer choisit le moteur d'après la NATURE de l'avatar.
AUCUN ORM ici (contrat commun des backends).
"""

import base64
import logging
import math
import subprocess
import wave
from pathlib import Path
from typing import Optional

from wama.common.backends.base import BaseModelBackend

logger = logging.getLogger(__name__)

#: Origine FICTIVE de la page de rendu : aucune URL WAMA n'est appelée, chaque requête est
#: interceptée et servie depuis le disque (`page.route`). Elle ne sort jamais du navigateur.
RENDER_ORIGIN = 'http://wama-avatar-render.local'
#: Cadrage vidéo par défaut (16:9, buste) — le cadrage du VOLET (`PANEL_CAMERA` de
#: wama-avatar.js) est réglé pour 200 px de haut et se surcharge ici. Choisi sur deux planches
#: de 4 variantes (2026-09-30) : `cameraX` NÉGATIF recentre (la pose de repos penche à droite,
#: avec `cameraX = 0` le visage sort décalé), `cameraY` négatif laisse de l'air au-dessus.
DEFAULT_CAMERA = {'cameraView': 'upper', 'cameraDistance': -0.9, 'cameraY': -0.15, 'cameraX': -0.15}
#: Images rendues par aller-retour navigateur ↔ Python (compromis mémoire / appels).
FRAMES_PER_BATCH = 25


def audio_offset_in_video_ms(audio_offset_ms: float, step_ms: float) -> float:
    """Instant de DÉPART du son dans la vidéo.

    L'image i (instant vidéo i·pas) montre l'avatar à `clock0 + (i+1)·pas` : l'horloge avance
    AVANT chaque capture. Le son, calé sur `clock0 + audio_offset_ms`, commence donc un pas plus
    tôt dans la vidéo. Jamais négatif.
    """
    return max(0.0, float(audio_offset_ms) - float(step_ms))


def frame_count(audio_seconds: float, offset_ms: float, step_ms: float, tail_ms: float = 500.0) -> int:
    """Nombre d'images pour couvrir l'audio + une courte fin muette (la bouche se referme)."""
    return max(1, math.ceil((audio_seconds * 1000.0 + offset_ms + tail_ms) / step_ms))


def _wav_seconds(path: str) -> float:
    try:
        with wave.open(path, 'rb') as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        import soundfile as sf                 # WAV non PCM (float), ou autre format lisible
        info = sf.info(path)
        return info.frames / float(info.samplerate or 1)


def _static_file(url_path: str) -> Optional[str]:
    """Chemin disque d'un fichier statique DEMANDÉ par la page (`/static/...`), par les finders
    Django — les SOURCES (`wama/**/static/`), pas `staticfiles/` : rien à collecter d'abord."""
    from django.conf import settings
    from django.contrib.staticfiles import finders
    prefix = settings.STATIC_URL
    if not url_path.startswith(prefix):
        return None
    return finders.find(url_path[len(prefix):])


_CONTENT_TYPES = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.glb': 'model/gltf-binary',
                  '.html': 'text/html', '.json': 'application/json'}


class TalkingHeadBackend(BaseModelBackend):
    """Rendu vidéo d'un avatar 3D parlant (TalkingHead dans Chromium sans écran)."""

    #: Moteur piloté (contrat commun) — le même nom que le modèle catalogue déclare.
    ENGINE = 'talkinghead'
    REQUIRED_PACKAGES = ['playwright']
    PIP_PACKAGES = ['playwright==1.61.0']      # version du venv_linux au 2026-09-30
    #: VRAM du Chromium de rendu — MESURÉE le 2026-09-30 : pic +181 puis +193 Mio (`nvidia-smi` échantillonné
    #: à 0,3 s pendant un rendu 1280×720 de 10,7 s, WebGL D3D12). Mesure bruitée (la base bouge
    #: avec les autres processus) : c'est un ordre de grandeur, sans marge ajoutée.
    recommended_vram_gb = 0.2
    description = ("TalkingHead — avatar 3D riggé (GLB) animé par l'audio, rendu image par image "
                   "dans un Chromium sans écran ; aucun modèle génératif, visèmes français natifs.")
    _warm = False

    @classmethod
    def is_available(cls) -> bool:
        """Playwright importable ET la bibliothèque vendorisée présente (sans elle, page vide)."""
        if cls.missing_packages():
            return False
        try:
            return bool(_static_file('/static/vendors/talkinghead-1.7/talkinghead.mjs'))
        except Exception:
            return False

    def load(self, model=None) -> bool:
        # Le navigateur vit le temps d'un rendu : rien à garder en mémoire entre deux jobs.
        self._warm = True
        return True

    @property
    def is_loaded(self) -> bool:
        return self._warm

    def unload(self) -> None:
        self._warm = False

    # ── Rendu ────────────────────────────────────────────────────────────────
    def process(self, avatar_path: str, audio_path: str, output_path: str, text: str = '',
                language: str = 'fr', width: int = 1280, height: int = 720, fps: int = 25,
                camera: Optional[dict] = None, background: str = '#f4f1ea', mood: str = 'neutral',
                progress=None, **_ignored) -> str:
        """Rend `output_path` (MP4) : l'avatar `avatar_path` (GLB) dit `audio_path`.

        `text` : ce qui est dit — il donne les timings de mots, donc les visèmes (sans lui, pas
        de lèvres). `progress(fraction)` : rappel optionnel, 0 → 1 pendant le rendu.
        """
        from django.template.loader import render_to_string
        from playwright.sync_api import sync_playwright
        from wama.common.utils.ffmpeg_utils import adapt_path_for_ffmpeg, get_ffmpeg_exe
        from wama.common.utils.html_render import launch_chromium

        avatar_path, audio_path = str(avatar_path), str(audio_path)
        if not Path(avatar_path).exists():
            raise FileNotFoundError(f"Avatar 3D introuvable : {avatar_path}")
        if not (text or '').strip():
            raise ValueError("TalkingHead a besoin du TEXTE dit : il donne les visèmes. "
                             "Sans lui, l'avatar resterait bouche fermée.")
        audio_seconds = _wav_seconds(audio_path)
        page_html = render_to_string('common/avatar_render.html', {
            'width': int(width), 'height': int(height), 'background': background})
        wav_b64 = base64.b64encode(Path(audio_path).read_bytes()).decode('ascii')

        def serve(route):
            from urllib.parse import urlparse
            path = urlparse(route.request.url).path
            if path == '/render.html':
                return route.fulfill(status=200, content_type='text/html', body=page_html)
            if path == '/avatar.glb':
                return route.fulfill(status=200, content_type='model/gltf-binary', path=avatar_path)
            disk = _static_file(path)
            if not disk:
                logger.warning('[talkinghead] fichier statique introuvable : %s', path)
                return route.fulfill(status=404, body='')
            return route.fulfill(status=200, path=disk,
                                 content_type=_CONTENT_TYPES.get(Path(disk).suffix,
                                                                 'application/octet-stream'))

        ffmpeg = get_ffmpeg_exe()
        output_path = str(output_path)
        # Le GPU est tenu par le processus Chromium, invisible du gouverneur : on déclare sa
        # réservation le temps du rendu — même patron que MuseTalk (`musetalk_backend.py`).
        import os
        from wama.common.services.resource_governor import vram_reservation
        with vram_reservation(f"avatarizer.talkinghead:{os.getpid()}", self.recommended_vram_gb), \
                sync_playwright() as p:
            browser = launch_chromium(p, gpu=True,
                                      extra_args=('--autoplay-policy=no-user-gesture-required',))
            try:
                page = browser.new_page(viewport={'width': int(width), 'height': int(height)})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.route(f'{RENDER_ORIGIN}/**', serve)
                page.goto(f'{RENDER_ORIGIN}/render.html')
                page.wait_for_function('!!(window.WamaAvatar && window.WamaAvatarRender)', timeout=60000)
                info = page.evaluate('o => window.WamaAvatarRender.prepare(o)', {
                    'glbUrl': f'{RENDER_ORIGIN}/avatar.glb', 'lang': language, 'mood': mood,
                    'camera': {**DEFAULT_CAMERA, **(camera or {})}, 'fps': int(fps),
                    'background': background})
                logger.info('[talkinghead] rendu %sx%s, WebGL : %s', info['width'], info['height'],
                            info.get('renderer'))
                timing = page.evaluate('a => window.WamaAvatarRender.speak(a[0], a[1], a[2])',
                                       [wav_b64, text, language])
                step_ms = float(info['stepMs'])
                offset_ms = audio_offset_in_video_ms(timing['audioOffsetMs'], step_ms)
                total = frame_count(audio_seconds, offset_ms, step_ms)

                cmd = [ffmpeg, '-y', '-loglevel', 'error',
                       '-f', 'image2pipe', '-framerate', str(int(fps)), '-c:v', 'mjpeg', '-i', '-',
                       '-i', adapt_path_for_ffmpeg(audio_path, ffmpeg),
                       '-filter_complex', f'[1:a]adelay={int(round(offset_ms))}:all=1[a]',
                       '-map', '0:v', '-map', '[a]',
                       '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18',
                       '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
                       adapt_path_for_ffmpeg(output_path, ffmpeg)]
                enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    done = 0
                    while done < total:
                        n = min(FRAMES_PER_BATCH, total - done)
                        for frame in page.evaluate('n => window.WamaAvatarRender.step(n)', n):
                            enc.stdin.write(base64.b64decode(frame))
                        done += n
                        if progress:
                            progress(done / total)
                    enc.stdin.close()
                    stderr = enc.stderr.read().decode('utf-8', 'replace')
                    if enc.wait(timeout=600) != 0:
                        raise RuntimeError(f"ffmpeg a échoué : {stderr[-1500:]}")
                finally:
                    if enc.poll() is None:
                        enc.kill()
                if errors:
                    logger.warning('[talkinghead] erreurs de page : %s', errors[:3])
            finally:
                browser.close()

        if not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
            raise RuntimeError("TalkingHead n'a produit aucune vidéo.")
        logger.info('[talkinghead] %s : %d images, son décalé de %.0f ms', output_path, total, offset_ms)
        return output_path

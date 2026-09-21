"""Routes MÉDIA (image / vidéo) de l'enhancer — contrat commun « fichier » (cf. `ROUTES`).

Ce qui vivait dans `tasks.py` (`_enhance_image`, `_enhance_video`, portage 2026-09-21) —
couplé au modèle `Enhancement` et à la console de la tâche — devient deux callables SANS
Django ni item : un chemin d'entrée, un chemin de sortie, des options, une progression.
La glu (tasks.py) garde ce qui est à elle : le modèle résolu, le nommage, le stockage,
l'aperçu « pendant » (par `frame_callback`) et la conversion de sortie.

Le moteur est CELUI du catalogue : le modèle porte son moteur (`onnxruntime`), la classe
s'en dérive (`backend_for_key`) — aucune classe nommée ici, aucun repli muet.
"""
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)


def _upscaler_for(model_name: str, tile_size: int = 0):
    """La classe résolue par le CATALOGUE pour `enhancer:<model_name>` (2ᵉ adoptant de
    `backend_for_key`, 2026-09-07) — les 7 modèles déclarent `onnxruntime` et résolvent tous
    `AIUpscaler`. Une clé absente ou sans moteur déclaré est une erreur DITE, pas un repli."""
    from wama.common.backends.manager import backend_for_key
    catalog_key = f'enhancer:{model_name}'
    classe = backend_for_key(catalog_key)
    if classe is None:
        raise RuntimeError(
            f"Modèle « {model_name} » : aucun backend résolu depuis le catalogue "
            f"({catalog_key} absent, ou sans moteur déclaré)")
    return classe(model_name=model_name, tile_size=tile_size)


def _model_of(options: dict) -> str:
    model = (options or {}).get('ai_model')
    if not model:
        raise ValueError("Aucun modèle d'upscaling dans les options (`ai_model`) — la glu "
                         "résout « auto » AVANT d'appeler la route.")
    return str(model)


def enhance_image(input_path: str, output_path: str, output_format=None, options=None,
                  progress_callback=None) -> dict:
    """Upscale (et débruitage optionnel) d'UNE image. Options : `ai_model` (résolu),
    `denoise` (passe IRCNN avant), `blend_factor` (0 = tout IA, 1 = original).
    Écrit `output_path` (même format que l'entrée) ; rend {'width', 'height'}."""
    from wama.common.backends.ai_upscaler import upscale_image_file
    opts = dict(options or {})
    width, height = upscale_image_file(
        input_path=input_path,
        output_path=output_path,
        model_name=_model_of(opts),
        denoise=bool(opts.get('denoise')),
        blend_factor=float(opts.get('blend_factor') or 0.0),
        progress_callback=progress_callback,
        factory=_upscaler_for,
    )
    if not os.path.exists(output_path):
        raise FileNotFoundError(f"Upscaler did not create output file at {output_path}")
    return {'width': width, 'height': height}


def enhance_video(input_path: str, output_path: str, output_format=None, options=None,
                  progress_callback=None, frame_callback=None) -> dict:
    """Upscale d'une vidéo image par image : extraction ffmpeg → upscale de chaque frame →
    ré-encodage H.264 au FPS d'origine dans `output_path`. Options : `ai_model` (résolu),
    `blend_factor`, `tile_size` (0 = 512 par défaut vidéo). `frame_callback(frame_bgr, i)`
    reçoit la frame améliorée courante (aperçu « pendant » — best-effort, jamais bloquant).
    Rend {'width', 'height', 'frames'}."""
    import cv2
    from wama.common.utils.ffmpeg_utils import (adapt_path_for_ffmpeg, get_ffmpeg_exe,
                                                get_ffprobe_exe)
    from wama.common.utils.work_dir import work_dir

    opts = dict(options or {})
    model_name = _model_of(opts)
    tile = int(opts.get('tile_size') or 0)
    progress = progress_callback or (lambda p: None)

    # Dossier de travail JETABLE — brique commune `work_dir` : le `with` couvre le retour
    # anticipé et les BaseException (dont la garde-temps du squelette).
    with work_dir('enhancer') as _work:
        frames_dir = os.path.join(str(_work), 'frames')
        enhanced_dir = os.path.join(str(_work), 'enhanced')
        os.makedirs(frames_dir, exist_ok=True)
        os.makedirs(enhanced_dir, exist_ok=True)

        # 1) Extraction des frames
        progress(2)
        frame_pattern = os.path.join(frames_dir, 'frame_%05d.png')
        _ff = get_ffmpeg_exe()
        extract = subprocess.run([
            _ff, '-y', '-i', adapt_path_for_ffmpeg(input_path, _ff),
            '-qscale:v', '1', adapt_path_for_ffmpeg(frame_pattern, _ff),
        ], capture_output=True, text=True)
        if extract.returncode != 0:
            logger.error(f"ffmpeg frame extraction failed: {extract.stderr}")
            raise RuntimeError(f"ffmpeg frame extraction failed: {extract.stderr}")
        frame_files = sorted(f for f in os.listdir(frames_dir) if f.endswith('.png'))
        total = len(frame_files)
        if not total:
            raise RuntimeError("Aucune frame extraite de la vidéo")
        progress(5)

        # 2) Upscale frame par frame
        upscaler = _upscaler_for(model_name, tile_size=tile if tile > 0 else 512)
        width = height = 0
        last_emit = 0.0
        try:
            for i, frame_file in enumerate(frame_files):
                progress(5 + int((i / total) * 80))
                frame = cv2.imread(os.path.join(frames_dir, frame_file))
                enhanced = upscaler.upscale_image(
                    frame, blend_factor=float(opts.get('blend_factor') or 0.0))
                cv2.imwrite(os.path.join(enhanced_dir, frame_file), enhanced)
                if i == 0:
                    height, width = enhanced.shape[:2]
                now = time.time()
                if frame_callback and now - last_emit >= 2.0:
                    last_emit = now
                    try:
                        frame_callback(enhanced, i)
                    except Exception:
                        pass    # l'aperçu est un confort, jamais une condition
        finally:
            upscaler.close()

        # 3) Ré-encodage au FPS d'origine
        progress(88)
        _fp = get_ffprobe_exe()
        probe = subprocess.run([
            _fp, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=r_frame_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            adapt_path_for_ffmpeg(input_path, _fp),
        ], capture_output=True, text=True)
        fps = _parse_fps(probe.stdout)
        enhanced_pattern = os.path.join(enhanced_dir, 'frame_%05d.png')
        encode = subprocess.run([
            _ff, '-y', '-framerate', str(fps),
            '-i', adapt_path_for_ffmpeg(enhanced_pattern, _ff),
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
            adapt_path_for_ffmpeg(output_path, _ff),
        ], capture_output=True, text=True)
        if encode.returncode != 0:
            logger.error(f"ffmpeg encoding failed: {encode.stderr}")
            raise RuntimeError(f"ffmpeg encoding failed: {encode.stderr}")
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"ffmpeg did not create output file at {output_path}")
        progress(100)
        return {'width': width, 'height': height, 'frames': total}


def _parse_fps(raw: str):
    """`r_frame_rate` de ffprobe ('30000/1001', '25') → nombre ; 30 si illisible.
    (Remplace l'`eval()` historique de tasks.py sur la sortie d'un sous-processus.)"""
    s = (raw or '').strip()
    if not s:
        return 30
    try:
        if '/' in s:
            num, den = s.split('/', 1)
            return float(num) / float(den) if float(den) else 30
        return float(s)
    except (TypeError, ValueError, ZeroDivisionError):
        return 30

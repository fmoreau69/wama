"""
Post-traitement cross-app du converter (wiring Phase 2 — ROADMAP §Converter, 2026-08-18).

POLITIQUE ici (quelles options, sur quel media_type, dans quel ordre) ; MÉCANISMES = les
fonctions inline de l'enhancer (`upscale_image_file`, `run_audio_enhancement`) — même
convention d'appel direct inter-apps que `apply_inline_conversion` dans l'autre sens
(4 apps importent déjà le converter inline).

Appelé par tasks._convert APRÈS la conversion réussie, sur le fichier de sortie
(remplacement via os.replace — jamais de fichier partiel visible). Peut charger des
modèles GPU depuis la queue CPU 'default' — anticipé par la garde anti-boucle-de-crash
du squelette commun (cf. docstring tasks.py).

DIFFÉRÉ : upscale vidéo frame par frame — mécanisme enfoui dans
enhancer/tasks.py::_enhance_video (couplé au modèle Enhancement) ; à extraire en brique
au titre du 2ᵉ consommateur, APRÈS la validation GPU du during enhancer (18/08).
"""
import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)

# Facteur d'upscale → modèle ONNX enhancer (clés de model_config.ENHANCER_MODELS).
_UPSCALE_MODELS = {'x2': 'BSRGANx2', 'x4': 'RealESRGANx4'}
_DENOISE_MODEL = 'IRCNN_Mx1'   # débruitage pur ×1 (quand denoise coché SANS upscale)


def apply_cross_app_options(job, output_path: str, console, progress) -> None:
    """Applique les options cross-app du job sur `output_path` (remplacé en place).

    Filtre par le catalogue du media_type (une option enregistrée puis sortie du
    catalogue est ignorée). Une exception = FAILURE du job : le post-traitement a été
    demandé explicitement, un résultat silencieusement non traité serait un mensonge.
    """
    from .format_router import CROSS_APP_OPTIONS
    xa = job.cross_app_options or {}
    allowed = {o['id'] for o in CROSS_APP_OPTIONS.get(job.media_type, [])}
    xa = {k: v for k, v in xa.items() if k in allowed and v}
    if not xa:
        return

    if job.media_type == 'image':
        _enhance_image(xa, output_path, console, progress)
    elif job.media_type == 'audio':
        _enhance_audio_file(job, xa, output_path, console, progress)
    elif job.media_type == 'video':
        _enhance_video_audio(xa, output_path, console, progress)


def _enhance_image(xa, output_path, console, progress):
    """Upscale et/ou débruitage Real-ESRGAN/IRCNN (enhancer inline, ONNX)."""
    from wama.enhancer.utils.ai_upscaler import upscale_image_file

    factor = xa.get('upscale') or ''
    model = _UPSCALE_MODELS.get(factor) or (_DENOISE_MODEL if xa.get('denoise') else None)
    if model is None:
        return
    # denoise=True sur upscale_image_file = passe IRCNN AVANT l'upscale ; inutile si le
    # modèle choisi EST déjà le débruiteur.
    denoise = bool(xa.get('denoise')) and model != _DENOISE_MODEL
    console(f"Post-traitement IA : {'upscaling ' + factor if factor else 'débruitage'} ({model})…")

    suffix = os.path.splitext(output_path)[1] or '.png'
    fd, tmp = tempfile.mkstemp(prefix='wama_xa_', suffix=suffix)
    os.close(fd)
    try:
        w, h = upscale_image_file(
            output_path, tmp, model_name=model, denoise=denoise,
            progress_callback=lambda p: progress(90 + int(p * 0.08)))
        os.replace(tmp, output_path)
        console(f"Post-traitement IA terminé : {w}×{h}")
    finally:
        _cleanup(tmp)


def _enhance_audio_file(job, xa, output_path, console, progress):
    """Enhancement DeepFilterNet (enhancer inline) ; sortie WAV ré-encodée au format cible."""
    if not xa.get('audio_enhance'):
        return
    from wama.enhancer.utils.audio_enhancer import run_audio_enhancement

    console("Post-traitement IA : enhancement audio (DeepFilterNet)…")
    fd, tmp_wav = tempfile.mkstemp(prefix='wama_xa_', suffix='.wav')
    os.close(fd)
    fd, tmp_out = tempfile.mkstemp(prefix='wama_xa_out_',
                                   suffix=f".{(job.output_format or 'wav').lower()}")
    os.close(fd)
    try:
        run_audio_enhancement(output_path, tmp_wav, engine='deepfilternet',
                              progress_callback=lambda p: progress(90 + int(p * 0.05)))
        fmt = (job.output_format or '').lower()
        if fmt in ('', 'wav'):
            os.replace(tmp_wav, output_path)
        else:
            # Ré-encodage au format demandé par la conversion (le moteur DeepFilterNet
            # sort du WAV) — mêmes options moteur que la conversion initiale.
            from ..backends.audio_backend import convert_audio
            convert_audio(tmp_wav, tmp_out, fmt, options=job.options or {})
            os.replace(tmp_out, output_path)
        progress(97)
        console("Enhancement audio terminé.")
    finally:
        _cleanup(tmp_wav, tmp_out)


def _enhance_video_audio(xa, output_path, console, progress):
    """Enhancement DeepFilterNet de la PISTE AUDIO d'une vidéo : demux → enhance → remux
    (flux vidéo copié tel quel — pas de ré-encodage vidéo)."""
    if not xa.get('audio_enhance'):
        return
    from wama.common.utils.ffmpeg_utils import (adapt_path_for_ffmpeg, get_ffmpeg_exe,
                                                get_ffprobe_exe)

    _fp = get_ffprobe_exe()
    probe = subprocess.run(
        [_fp, '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index',
         '-of', 'csv=p=0', adapt_path_for_ffmpeg(output_path, _fp)],
        capture_output=True, text=True)
    if not probe.stdout.strip():
        console("Enhancement audio ignoré : la vidéo n'a pas de piste audio.")
        return

    from wama.enhancer.utils.audio_enhancer import run_audio_enhancement
    console("Post-traitement IA : enhancement de la piste audio (DeepFilterNet)…")
    _ff = get_ffmpeg_exe()
    ext = os.path.splitext(output_path)[1].lower() or '.mp4'
    fd, raw_wav = tempfile.mkstemp(prefix='wama_xa_', suffix='.wav')
    os.close(fd)
    fd, enh_wav = tempfile.mkstemp(prefix='wama_xa_enh_', suffix='.wav')
    os.close(fd)
    fd, tmp_out = tempfile.mkstemp(prefix='wama_xa_out_', suffix=ext)
    os.close(fd)
    try:
        r = subprocess.run(
            [_ff, '-y', '-i', adapt_path_for_ffmpeg(output_path, _ff),
             '-vn', '-acodec', 'pcm_s16le', adapt_path_for_ffmpeg(raw_wav, _ff)],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"Extraction de la piste audio échouée : {r.stderr[-400:]}")
        progress(92)

        run_audio_enhancement(raw_wav, enh_wav, engine='deepfilternet',
                              progress_callback=lambda p: progress(92 + int(p * 0.04)))

        acodec = 'libopus' if ext == '.webm' else 'aac'
        r = subprocess.run(
            [_ff, '-y', '-i', adapt_path_for_ffmpeg(output_path, _ff),
             '-i', adapt_path_for_ffmpeg(enh_wav, _ff),
             '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', acodec,
             adapt_path_for_ffmpeg(tmp_out, _ff)],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"Remux de la piste audio échoué : {r.stderr[-400:]}")
        os.replace(tmp_out, output_path)
        progress(97)
        console("Piste audio améliorée et remuxée (vidéo copiée sans ré-encodage).")
    finally:
        _cleanup(raw_wav, enh_wav, tmp_out)


def _cleanup(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.unlink(p)
        except OSError:
            pass

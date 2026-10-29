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
import time

logger = logging.getLogger(__name__)


def _upscaler_for(model_name: str, tile_size: int = 0):
    """La classe résolue par le CATALOGUE pour ce modèle (2ᵉ adoptant de `backend_for_key`,
    2026-09-07). `model_name` est une CLÉ de catalogue depuis la route F4b ⑤ (2026-10-06) — un
    identifiant nu (le débruitage `IRCNN_Mx1` d'`upscale_image_file`, une ligne d'avant la
    migration) est lu dans l'espace de l'enhancer. Le backend reçoit l'identifiant qu'il connaît
    (`model_id`). Une clé absente ou sans moteur déclaré est une erreur DITE, pas un repli."""
    from wama.common.backends.manager import backend_for_key
    from wama.common.utils.model_keys import backend_model_id, catalog_key
    key = catalog_key(model_name, 'enhancer')
    classe = backend_for_key(key)
    if classe is None:
        raise RuntimeError(
            f"Modèle « {model_name} » : aucun backend résolu depuis le catalogue "
            f"({key} absent, ou sans moteur déclaré)")
    # L'identifiant de SON vocabulaire (`SUPPORTED_MODELS`), celui que la résolution vient de
    # comparer — pas l'espace de clés de l'app (une version GitHub les sépare, 2026-10-07).
    return classe(model_name=backend_model_id(key), tile_size=tile_size)


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
    """Upscale d'une vidéo image par image, par le rendu COMMUN `video_render.render_video` :
    chaque image agrandie écrite à SON horodatage d'origine, l'audio de la source recopié à ses
    propres temps, dans le conteneur de `output_path` (celui de l'entrée : la glu y met son
    extension), en un seul encodage — le geste du floutage de l'anonymizer (2026-10-29, décision de
    Fabien : « on porte l'upscale vidéo sur le rendu commun en conservant le son comme
    Anonymizer »). Jusque-là : extraction de PNG par ffmpeg, puis réencodage H.264 à la cadence
    NOMINALE (`r_frame_rate`) — la vidéo sortait MUETTE, et une cadence variable s'étirait.

    Options : `ai_model` (résolu), `blend_factor`, `tile_size` (0 = 512 par défaut vidéo).
    `frame_callback(frame_bgr, i)` reçoit l'image améliorée courante (aperçu « pendant » —
    best-effort, jamais bloquant, ~2 s). Rend {'width', 'height', 'frames', 'path'} — `path` est le
    fichier RÉELLEMENT écrit : un conteneur hors de la table des rendus sort en `.mp4`."""
    from wama.common.utils.video_render import render_video

    opts = dict(options or {})
    model_name = _model_of(opts)
    tile = int(opts.get('tile_size') or 0)
    blend = float(opts.get('blend_factor') or 0.0)
    progress = progress_callback or (lambda p: None)
    size = {}
    last_emit = [0.0]

    upscaler = _upscaler_for(model_name, tile_size=tile if tile > 0 else 512)

    def paint(index, image):
        enhanced = upscaler.upscale_image(image, blend_factor=blend)
        if not size:
            size['height'], size['width'] = enhanced.shape[:2]
        size['frames'] = index + 1
        return enhanced

    def preview(index, _original, enhanced):
        now = time.time()
        if now - last_emit[0] < 2.0:
            return
        last_emit[0] = now
        try:
            frame_callback(enhanced, index)
        except Exception:
            pass    # l'aperçu est un confort, jamais une condition

    progress(2)
    try:
        written = render_video(
            input_path, paint, output_path, on_frame=preview if frame_callback else None,
            progress=lambda done, total: progress(2 + int(done * 96 / max(total, 1))))
    finally:
        upscaler.close()
    progress(100)
    return {'width': size.get('width', 0), 'height': size.get('height', 0),
            'frames': size.get('frames', 0), 'path': written}

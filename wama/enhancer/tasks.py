"""
Celery tasks for Enhancer app.

Squelette (gardes, progress, chrono, statuts, ETA, console, notifications, tâche déclarée au
gouverneur, garde-temps) = brique COMMUNE `common/utils/task_skeleton.run_item_task`
(portage 2026-09-21, marche A2). Ce fichier ne porte plus que la GLU des deux branches :
résolution du modèle « auto », nommage et stockage de la sortie, aperçu « pendant » (vidéo),
conversion de format inline. Les MÉCANISMES (upscale image/vidéo, restauration audio) sont
les routes déclarées dans `backends/` (ROUTES, contrat commun « fichier »).

Deux modèles d'item, deux identifiants d'app pour le squelette : `enhancer` (Enhancement)
et `audio_enhancer` (AudioEnhancement) — le même nom que les registres de preview et de
détail donnent déjà à la branche audio. Sans lui, la ligne « tâche en cours » du gouverneur
(`app:item:tenant`) et le cache de progression (`<app>_progress_<pk>`) confondraient le
média #5 et l'audio #5 ; et `audio_enhancer_progress_<pk>` est précisément la clé que les
vues audio lisent depuis toujours.
"""

import logging
import os
from importlib import import_module

from celery import shared_task

from .models import AudioEnhancement, Enhancement

logger = logging.getLogger(__name__)


# ── Tâches : squelette commun ───────────────────────────────────────────────────────────

@shared_task(bind=True)
def enhance_media(self, enhancement_id: int):
    """Amélioration image / vidéo (file `gpu`)."""
    from wama.common.utils.task_skeleton import run_item_task
    run_item_task(self, app_id='enhancer', model=Enhancement, item_id=enhancement_id,
                  process=_enhance_media, ingest_derive=_derive_media_type,
                  model_key=lambda e: f'enhancer:{e.ai_model}',
                  notify_label='Enhancer')


@shared_task(bind=True)
def enhance_audio(self, audio_enhancement_id: int):
    """Restauration de parole (Resemble Enhance / DeepFilterNet 3)."""
    from wama.common.utils.task_skeleton import run_item_task
    run_item_task(self, app_id='audio_enhancer', model=AudioEnhancement,
                  item_id=audio_enhancement_id, process=_enhance_audio,
                  model_key=lambda a: f'enhancer:{a.engine}',
                  notify_label='Enhancer (audio)')


# ── Glu MÉDIA ───────────────────────────────────────────────────────────────────────────

def _derive_media_type(inst, path, fname):
    """Hook `derive` de l'ingest URL (WAMA_INGEST) : renseigne media_type au téléchargement.
    CLASSER est le geste du commun (`normalize_types`) ; ce qu'on RETIENT du classement est la
    politique de l'app — ici image/vidéo, '' pour tout le reste."""
    if inst.media_type:
        return []
    from wama.common.app_registry import normalize_types
    cat = (normalize_types([os.path.splitext(fname)[1]]) or [''])[0]
    inst.media_type = cat if cat in ('image', 'video') else ''
    return ['media_type'] if inst.media_type else []


def _route(nature: str):
    """Le callable déclaré par `backends.ROUTES` pour cette nature — import RELATIF AU PAQUET,
    la même résolution que le corps composé par `tasks_gen`."""
    from .backends import ROUTES
    chemin = ROUTES.get(nature)
    if not chemin:
        raise ValueError(f"Type de média non supporté : {nature!r} (aucune route déclarée)")
    mod, fonc = chemin.rsplit('.', 1)
    return getattr(import_module('.' + mod, __package__), fonc)


def _store_output(item, local_path: str, storage_name: str) -> str:
    """Range le fichier produit dans le stockage à un nom CONNU (écrasement forcé : l'ancien
    résultat de l'item et un éventuel orphelin homonyme sont supprimés d'abord). Rend le nom
    de stockage effectif."""
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    if item.output_file:
        try:
            item.output_file.delete(save=False)
        except Exception as exc:
            logger.warning(f"Could not delete old output file: {exc}")
    if default_storage.exists(storage_name):
        try:
            default_storage.delete(storage_name)
        except Exception as exc:
            logger.warning(f"Could not delete existing storage file: {exc}")
    with open(local_path, 'rb') as f:
        return default_storage.save(storage_name, ContentFile(f.read()))


def _enhance_media(enhancement, ctx):
    """GLU image/vidéo (contrat task_skeleton) : route par nature, nommage commun, stockage,
    aperçu « pendant » (vidéo), conversion de sortie inline. Une exception = FAILURE (le
    squelette pose statut/console/notification) ; l'aperçu partiel est retiré ICI."""
    from wama.common.utils.output_naming import compose_output_name
    from wama.common.utils.preview_utils import clear_partial
    from wama.common.utils.work_dir import work_dir

    nature = (enhancement.media_type or '').strip()
    route = _route(nature)
    input_path = enhancement.input_file.path
    model = enhancement.ai_model
    output_filename = compose_output_name(app='enhancer', model=model, source_name=input_path)
    ctx.console(f"Processing {nature}: {enhancement.get_input_filename()} ({model})")
    ctx.progress(5)

    options = {
        'ai_model': model,
        'denoise': bool(enhancement.denoise),
        'blend_factor': float(enhancement.blend_factor or 0.0),
        'tile_size': int(enhancement.tile_size or 0),
    }
    extra = {}
    if nature == 'video':
        extra['frame_callback'] = _during_preview(enhancement)

    try:
        with work_dir('enhancer') as _work:
            local = os.path.join(str(_work), output_filename)
            produced = route(input_path, local, enhancement.output_format,
                             options=options,
                             progress_callback=lambda p: ctx.progress(5 + int(p * 0.9)),
                             **extra) or {}
            file_size = os.path.getsize(local)
            saved = _store_output(
                enhancement, local, f'enhancer/{enhancement.user_id}/output/media/{output_filename}')
    finally:
        if nature == 'video':
            clear_partial('enhancer', enhancement.id)   # la face SORTIE prend le relais

    enhancement.output_file.name = saved
    _apply_enhancer_output_format(enhancement)          # conversion inline (converter)
    ctx.progress(95)
    return {
        'fields': {
            'output_file': enhancement.output_file.name,
            'output_width': int(produced.get('width') or 0),
            'output_height': int(produced.get('height') or 0),
            'output_file_size': file_size,
        },
        'eta': enhancer_eta_key_size(enhancement),
        'label': output_filename,
        'models': [f'enhancer:{model}'],
    }


def _during_preview(enhancement):
    """Aperçu « PENDANT » (brique COMMUNE preview_utils, `?side=during`) : la frame AMÉLIORÉE
    courante publiée ~toutes les 2 s (la cadence est tenue par la route). Les frames
    temporaires vivent hors MEDIA : on copie un JPEG partiel sous l'output utilisateur (même
    patron que l'anonymizer). Rend le `frame_callback` de la route vidéo."""
    import cv2
    from django.conf import settings
    from wama.common.utils.media_paths import get_app_media_path
    from wama.common.utils.preview_utils import publish_partial

    pdir = os.path.join(str(get_app_media_path('enhancer', enhancement.user_id, 'output')),
                        'partials')
    os.makedirs(pdir, exist_ok=True)
    partial_abs = os.path.join(pdir, f'during_{enhancement.id}.jpg')
    partial_url = (settings.MEDIA_URL
                   + os.path.relpath(partial_abs, settings.MEDIA_ROOT).replace('\\', '/'))

    def _publish(frame, index):
        cv2.imwrite(partial_abs, frame)
        publish_partial('enhancer', enhancement.id, f'{partial_url}?v={index}')

    return _publish


# ── Glu AUDIO ───────────────────────────────────────────────────────────────────────────

def _enhance_audio(ae, ctx):
    """GLU audio (contrat task_skeleton) : route 'audio', nommage commun (`{base}_enhanced_
    {moteur}.wav`), stockage, conversion de sortie inline."""
    from wama.common.utils.output_naming import compose_output_name
    from wama.common.utils.work_dir import work_dir

    route = _route('audio')
    input_path = ae.input_file.path
    engine = ae.engine
    output_filename = compose_output_name(app='enhancer', model=engine,
                                          source_name=input_path, ext='.wav')
    ctx.console(f"Traitement audio: {ae.get_input_filename()} ({ae.get_engine_display()})")
    ctx.progress(5)

    options = {
        'engine': engine,
        'mode': ae.mode,
        'denoising_strength': float(ae.denoising_strength),
        'quality': int(ae.quality),
    }
    with work_dir('enhancer') as _work:
        local = os.path.join(str(_work), output_filename)
        route(input_path, local, ae.output_format, options=options,
              progress_callback=lambda p: ctx.progress(5 + int(p * 0.9)))
        saved = _store_output(ae, local, f'enhancer/{ae.user_id}/output/audio/{output_filename}')

    ae.output_file.name = saved
    _apply_enhancer_output_format(ae)                   # conversion inline (converter)
    return {
        'fields': {'output_file': ae.output_file.name},
        'eta': audio_enhancer_eta_key_size(ae),
        'label': output_filename,
        'models': [f'enhancer:{engine}'],
    }


# ── Partagé avec les vues (ETA) et la conversion de sortie ─────────────────────────────

def enhancer_eta_key_size(enhancement) -> tuple[str, float, str]:
    """(model_key, size, unit) pour le seeding ETA d'une Enhancement image/vidéo.
    Image → mégapixels d'entrée ; vidéo → durée. Clé par modèle + facteur d'upscale.
    Partagé entre la glu (record) et la vue progress (estimate)."""
    mt = (getattr(enhancement, 'media_type', '') or '').lower()
    model = getattr(enhancement, 'ai_model', '') or 'auto'
    factor = getattr(enhancement, 'upscale_factor', '') or ''
    if mt == 'video':
        return f'enhancer:vid:{model}:x{factor}', float(getattr(enhancement, 'duration', 0) or 0), 'video_sec'
    mp = (int(getattr(enhancement, 'width', 0) or 0) * int(getattr(enhancement, 'height', 0) or 0)) / 1e6
    return f'enhancer:img:{model}:x{factor}', mp, 'megapixel'


def audio_enhancer_eta_key_size(ae) -> tuple[str, float, str]:
    """(model_key, size, unit) pour le seeding ETA d'une AudioEnhancement (durée audio)."""
    engine = getattr(ae, 'engine', '') or 'auto'
    return f'enhancer:audio:{engine}', float(getattr(ae, 'duration', 0) or 0), 'audio_sec'


def _apply_enhancer_output_format(obj) -> None:
    """Convert the enhanced output to the user-chosen format (Phase 3).

    Works for both Enhancement (image/video) and AudioEnhancement (audio).
    Updates obj.output_file in place; no-op when output_format is 'original'.
    """
    fmt = (getattr(obj, 'output_format', '') or 'original').lower()
    if fmt in ('', 'original') or not obj.output_file:
        return
    try:
        from django.conf import settings
        from wama.converter.utils.inline_convert import apply_inline_conversion
        new_path = apply_inline_conversion(
            obj.output_file.path, fmt,
            getattr(obj, 'output_quality', 'balanced') or 'balanced',
        )
        rel = os.path.relpath(new_path, settings.MEDIA_ROOT).replace('\\', '/')
        obj.output_file.name = rel
    except Exception as exc:
        logger.warning(f"[enhancer] conversion format sortie échouée: {exc}")

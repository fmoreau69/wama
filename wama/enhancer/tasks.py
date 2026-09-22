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

from wama.common.utils.media_paths import app_media_dir

from .models import AudioEnhancement, Enhancement

logger = logging.getLogger(__name__)


# ── Tâches : squelette commun ───────────────────────────────────────────────────────────

@shared_task(bind=True)
def enhance_media(self, enhancement_id: int):
    """Amélioration image / vidéo (file `gpu`)."""
    from wama.common.utils.task_skeleton import run_item_task
    run_item_task(self, app_id='enhancer', model=Enhancement, item_id=enhancement_id,
                  process=_enhance_media, ingest_derive=_derive_media_type,
                  vram_needed=lambda e: _vram_needed(f'enhancer:{_media_model(e)}'),
                  model_key=lambda e: f'enhancer:{_media_model(e)}',
                  notify_label='Enhancer')


@shared_task(bind=True)
def enhance_audio(self, audio_enhancement_id: int):
    """Restauration de parole (Resemble Enhance / DeepFilterNet 3)."""
    from wama.common.utils.task_skeleton import run_item_task
    run_item_task(self, app_id='audio_enhancer', model=AudioEnhancement,
                  item_id=audio_enhancement_id, process=_enhance_audio,
                  vram_needed=lambda a: _vram_needed(f'enhancer:{_audio_engine(a)}'),
                  model_key=lambda a: f'enhancer:{_audio_engine(a)}',
                  notify_label='Enhancer (audio)')


# ── Tirage « auto » AU LANCEMENT (curseur C, 2026-09-21) ──────────────────────────────────
# Résolu UNE fois par lancement et mémorisé sur l'instance : le squelette interroge le besoin
# VRAM (`vram_needed`) et la clé des poids (`model_key`) AVANT la glu, qui doit parler du même
# modèle. L'item GARDE « auto » (une relance ré-arbitre avec la VRAM du moment) ; le modèle
# retenu vit dans la console, l'ETA et la ligne d'exécution (`models`).

def _media_model(enhancement) -> str:
    if not getattr(enhancement, '_resolved_model', None):
        from .utils.auto_model import resolve_media_model
        enhancement._resolved_model = resolve_media_model(enhancement)
    return enhancement._resolved_model


def _audio_engine(ae) -> str:
    if not getattr(ae, '_resolved_engine', None):
        from .utils.auto_model import resolve_audio_engine
        ae._resolved_engine = resolve_audio_engine(ae)
    return ae._resolved_engine


def _vram_needed(model_key: str):
    from .utils.auto_model import vram_needed_gb
    return vram_needed_gb(model_key)


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
    path = ROUTES.get(nature)
    if not path:
        raise ValueError(f"Type de média non supporté : {nature!r} (aucune route déclarée)")
    mod, fn = path.rsplit('.', 1)
    return getattr(import_module('.' + mod, __package__), fn)


def _store_output(item, local_path: str, storage_name: str) -> str:
    """Range le fichier produit dans le stockage à un nom CONNU (écrasement forcé : l'ancien
    résultat de l'item et un éventuel orphelin homonyme sont supprimés d'abord). Rend le nom
    de stockage effectif."""
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    # L'ancien résultat : par la brique (propriété + partage) — une copie faite par « Dupliquer »
    # peut encore le désigner. La référence est remplacée plus bas dans tous les cas.
    from wama.common.utils.queue_duplication import safe_delete_file
    safe_delete_file(item, 'output_file')
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

    from wama.common.utils.auto_model import is_auto, quality_intent_of

    nature = (enhancement.media_type or '').strip()
    route = _route(nature)
    input_path = enhancement.input_file.path
    model = _media_model(enhancement)
    output_filename = compose_output_name(app='enhancer', model=model, source_name=input_path)
    if is_auto(enhancement.ai_model):
        ctx.console(f"[Enhancer] 🧠 Auto → {model} (×{enhancement.upscale_factor}, VRAM libre au "
                    f"lancement, curseur qualité {quality_intent_of(enhancement, 'enhancer')}/100)")
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
            # Le nom de STOCKAGE vient de la brique : il décide où le fichier atterrit ET ce que
            # la base retient. Composé à la main (`f'enhancer/{uid}/output/…'`) jusqu'au
            # 2026-09-22, il aurait recréé l'ancien arbre à la première sortie après la bascule.
            saved = _store_output(
                enhancement, local,
                f"{app_media_dir('enhancer', enhancement.user_id, 'output/media')}/{output_filename}")
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
        'eta': enhancer_eta_key_size(enhancement, model=model),
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
    from wama.common.utils.auto_model import is_auto, quality_intent_of
    from wama.common.utils.output_naming import compose_output_name
    from wama.common.utils.work_dir import work_dir
    from .utils.auto_model import audio_nfe

    route = _route('audio')
    input_path = ae.input_file.path
    engine = _audio_engine(ae)
    nfe = audio_nfe(ae, engine)
    output_filename = compose_output_name(app='enhancer', model=engine,
                                          source_name=input_path, ext='.wav')
    if is_auto(ae.engine):
        ctx.console(f"[Enhancer] 🧠 Auto → {engine} (VRAM libre au lancement, curseur qualité "
                    f"{quality_intent_of(ae, 'enhancer')}/100"
                    + (f", NFE {nfe}" if engine == 'resemble' else '') + ')')
    ctx.console(f"Traitement audio: {ae.get_input_filename()} ({engine})")
    ctx.progress(5)

    options = {
        'engine': engine,
        'mode': ae.mode,
        'denoising_strength': float(ae.denoising_strength),
        'quality': nfe,
    }
    with work_dir('enhancer') as _work:
        local = os.path.join(str(_work), output_filename)
        route(input_path, local, ae.output_format, options=options,
              progress_callback=lambda p: ctx.progress(5 + int(p * 0.9)))
        saved = _store_output(
            ae, local, f"{app_media_dir('enhancer', ae.user_id, 'output/audio')}/{output_filename}")

    ae.output_file.name = saved
    _apply_enhancer_output_format(ae)                   # conversion inline (converter)
    return {
        'fields': {'output_file': ae.output_file.name},
        'eta': audio_enhancer_eta_key_size(ae, engine=engine),
        'label': output_filename,
        'models': [f'enhancer:{engine}'],
    }


# ── Partagé avec les vues (ETA) et la conversion de sortie ─────────────────────────────

def enhancer_eta_key_size(enhancement, model: str = None) -> tuple[str, float, str]:
    """(model_key, size, unit) pour le seeding ETA d'une Enhancement image/vidéo.
    Image → mégapixels d'entrée ; vidéo → durée. Clé par modèle + facteur d'upscale.
    Partagé entre la glu (record, qui passe le modèle RÉSOLU) et la vue progress (estimate,
    qui ne connaît que la colonne — « auto » y est sa propre famille d'estimation)."""
    mt = (getattr(enhancement, 'media_type', '') or '').lower()
    model = model or getattr(enhancement, 'ai_model', '') or 'auto'
    factor = getattr(enhancement, 'upscale_factor', '') or ''
    if mt == 'video':
        return f'enhancer:vid:{model}:x{factor}', float(getattr(enhancement, 'duration', 0) or 0), 'video_sec'
    mp = (int(getattr(enhancement, 'width', 0) or 0) * int(getattr(enhancement, 'height', 0) or 0)) / 1e6
    return f'enhancer:img:{model}:x{factor}', mp, 'megapixel'


def audio_enhancer_eta_key_size(ae, engine: str = None) -> tuple[str, float, str]:
    """(model_key, size, unit) pour le seeding ETA d'une AudioEnhancement (durée audio)."""
    engine = engine or getattr(ae, 'engine', '') or 'auto'
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

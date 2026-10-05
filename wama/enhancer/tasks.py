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

# La card porte un PIPELINE de deux process (`function_specs.PIPELINE`) : `generate` (la glu de sa
# file) puis `output` (`_output`, format et qualité — brique commune). Un lancement ne rejoue que
# ce qui n'est plus à jour : changer le format ne relance pas l'amélioration. `process` borne le
# lancement à UN process (⚠ argument de tâche nouveau : workers à relancer).

def _forget_lost(model, pk) -> None:
    """La sortie repart du fichier que l'amélioration a laissé : s'il n'est plus là, elle rejoue."""
    from wama.common.services.output_process import forget_lost_generation
    known = model.objects.filter(pk=pk).first()
    if known is not None:
        forget_lost_generation(known, 'output_file', 'generate')


@shared_task(bind=True)
def enhance_media(self, enhancement_id: int, process: str = None):
    """Amélioration image / vidéo (file `gpu`)."""
    from wama.common.utils.task_skeleton import run_item_task
    from .function_specs import PIPELINE
    _forget_lost(Enhancement, enhancement_id)
    run_item_task(self, app_id='enhancer', model=Enhancement, item_id=enhancement_id,
                  pipeline=PIPELINE, processes={'generate': _enhance_media, 'output': _output},
                  ingest_derive=_derive_media_type,
                  vram_needed=lambda e: _vram_needed(f'enhancer:{_media_model(e)}'),
                  model_key=lambda e: f'enhancer:{_media_model(e)}',
                  notify_label='Enhancer', only=process)


@shared_task(bind=True)
def enhance_audio(self, audio_enhancement_id: int, process: str = None):
    """Restauration de parole (Resemble Enhance / DeepFilterNet 3)."""
    from wama.common.utils.task_skeleton import run_item_task
    from .function_specs import PIPELINE
    _forget_lost(AudioEnhancement, audio_enhancement_id)
    run_item_task(self, app_id='audio_enhancer', model=AudioEnhancement,
                  item_id=audio_enhancement_id,
                  pipeline=PIPELINE, processes={'generate': _enhance_audio, 'output': _output},
                  vram_needed=lambda a: _vram_needed(f'enhancer:{_audio_engine(a)}'),
                  model_key=lambda a: f'enhancer:{_audio_engine(a)}',
                  notify_label='Enhancer (audio)', only=process)


def _output(item, ctx):
    """GLU du process `output` (les DEUX files) : format et qualité de sortie, par la glu COMMUNE
    (`output_process.output_step`) — le fichier amélioré d'origine est gardé tant que la sortie
    le transforme. La taille relevée est celle du fichier FINAL (file image/vidéo)."""
    from wama.common.services.output_process import output_step
    media = isinstance(item, Enhancement)
    domain = ((item.media_type or 'image') if media else 'audio')

    def sizes(_item, finals):
        return {'output_file_size': os.path.getsize(finals[0])} if media else {}

    return output_step('output_file', domain=domain, app_id='enhancer',
                       extra_fields=sizes)(item, ctx)


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
    # (`drop_previous_outputs` retire aussi l'original que la brique de sortie en gardait.)
    from wama.common.services.output_process import drop_previous_outputs
    drop_previous_outputs(item, 'output_file')
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
    frames = _partial_frames(enhancement) if nature == 'video' else None
    if frames is not None:
        extra['frame_callback'] = lambda frame, index: frames.publish(
            {'enhanced': ('Amélioration', frame)}, index=index)

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
        if frames is not None:
            frames.close()           # la face SORTIE prend le relais ; le JPEG partiel part

    enhancement.output_file.name = saved
    ctx.progress(95)
    # Le format et la qualité de sortie sont le process suivant, `output` (`_output`).
    from wama.common.services.output_process import generated
    return generated(
        [enhancement.output_file.path],
        fields={
            'output_file': enhancement.output_file.name,
            'output_width': int(produced.get('width') or 0),
            'output_height': int(produced.get('height') or 0),
            'output_file_size': file_size,
        },
        eta=enhancer_eta_key_size(enhancement, model=model),
        label=output_filename,
        models=[f'enhancer:{model}'])


def _partial_frames(enhancement):
    """Aperçu « PENDANT » d'une vidéo : la frame AMÉLIORÉE courante, par la brique commune
    `preview_utils.PartialFrames` (JPEG sous l'output utilisateur, URL versionnée, retiré en fin
    de run). La cadence (~2 s) est tenue par la route vidéo, d'où `every=0`. Jusqu'au 2026-10-04
    l'enhancer recopiait ce patron de l'anonymizer, à la main, sans retirer son JPEG."""
    from wama.common.utils.media_paths import get_app_media_path
    from wama.common.utils.preview_utils import PartialFrames
    folder = os.path.join(str(get_app_media_path('enhancer', enhancement.user_id, 'output')),
                          'partials')
    return PartialFrames('enhancer', enhancement.id, folder, every=0)


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
    from wama.common.services.output_process import generated
    return generated(
        [ae.output_file.path],
        fields={'output_file': ae.output_file.name},
        eta=audio_enhancer_eta_key_size(ae, engine=engine),
        label=output_filename,
        models=[f'enhancer:{engine}'])


# ── Partagé avec les vues (ETA) ─────────────────────────────────────────────────────────

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



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
from celery import shared_task

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
                  # Le modèle résolu EST une clé de catalogue (route F4b ⑤, 2026-10-06) : le
                  # squelette en tire le besoin VRAM du process GPU (2026-10-14).
                  model_key=_media_model,
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
                  # Le moteur résolu EST une clé de catalogue (route F4b ⑤, 2026-10-07) : le
                  # squelette en tire le besoin VRAM du process GPU (2026-10-14).
                  model_key=_audio_engine,
                  notify_label='Enhancer (audio)', only=process)


def _output(item, ctx):
    """GLU du process `output` (les DEUX files) : format et qualité de sortie, par la glu COMMUNE
    (`output_process.output_step`) — le fichier amélioré d'origine est gardé tant que la sortie
    le transforme. La taille relevée est celle du fichier FINAL (file image/vidéo) : poids ET
    dimensions — « Garder la résolution d'origine » (2026-10-16) ramène la sortie aux dimensions
    de l'entrée (`width`/`height` de l'élément), et décocher la rend à celles de l'amélioration."""
    from wama.common.services.output_process import output_step
    from wama.common.utils.video_utils import get_media_info
    media = isinstance(item, Enhancement)
    domain = ((item.media_type or 'image') if media else 'audio')

    def sizes(_item, finals):
        if not media:
            return {}
        fields = {'output_file_size': os.path.getsize(finals[0])}
        try:
            info = get_media_info(finals[0])
        except Exception:
            return fields      # dimensions illisibles : celles de l'amélioration restent
        if info.get('width') and info.get('height'):
            fields.update(output_width=int(info['width']), output_height=int(info['height']))
        return fields

    return output_step('output_file', domain=domain, app_id='enhancer', extra_fields=sizes,
                       input_size=(lambda e: (e.width, e.height)) if media else None)(item, ctx)


# ── Tirage « auto » AU LANCEMENT (curseur C, 2026-09-21) ──────────────────────────────────
# Résolu UNE fois par lancement et mémorisé sur l'instance : le squelette interroge la clé des
# poids (`model_key`) — et, depuis le 2026-10-14, en tire le besoin VRAM — AVANT la glu, qui doit
# parler du même modèle. L'item GARDE « auto » (une relance ré-arbitre avec la VRAM du moment) ;
# le modèle retenu vit dans la console, l'ETA et la ligne d'exécution (`models`).

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
    from wama.common.utils.work_dir import work_dir

    from wama.common.utils.auto_model import is_auto, quality_intent_of

    from wama.common.backends.manager import route_for_nature
    nature = (enhancement.media_type or '').strip()
    route = route_for_nature(__package__, nature)
    input_path = enhancement.input_file.path
    from wama.common.utils.model_keys import model_id
    model = _media_model(enhancement)              # clé de catalogue (route F4b ⑤)
    # Le NOM porte l'identifiant (comme l'imager) : `RealESR_Gx4`, pas `enhancer-RealESR_Gx4`.
    # Sa place et son nom par la brique (`ctx.output_place`) : la souche d'une entrée déposée
    # suffit à l'unicité, le nom ne porte donc pas l'identifiant de la card (inchangé au portage).
    storage_name, _path = ctx.output_place('', model=model_id(model), source_name=input_path,
                                           folder='output/media', card_id=False)
    output_filename = os.path.basename(storage_name)
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
            # Le fichier RÉELLEMENT écrit (route vidéo, rendu commun) : un conteneur hors de la
            # table des rendus sort en `.mp4`, et le nom rangé suit son extension.
            written = produced.get('path') or local
            if written != local:
                storage_name = os.path.splitext(storage_name)[0] + os.path.splitext(written)[1]
                output_filename = os.path.basename(storage_name)
                local = written
            file_size = os.path.getsize(local)
            # Le nom de STOCKAGE vient de la brique : il décide où le fichier atterrit ET ce que
            # la base retient. Composé à la main (`f'enhancer/{uid}/output/…'`) jusqu'au
            # 2026-09-22, il aurait recréé l'ancien arbre à la première sortie après la bascule.
            saved = _store_output(enhancement, local, storage_name)
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
        models=[model])


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
    from wama.common.utils.work_dir import work_dir
    from wama.common.backends.manager import route_for_nature
    from .utils.auto_model import audio_nfe

    from wama.common.utils.model_keys import model_id
    route = route_for_nature(__package__, 'audio')
    input_path = ae.input_file.path
    engine = _audio_engine(ae)                     # clé de catalogue (route F4b ⑤)
    name = model_id(engine)                        # l'identifiant : ce que le moteur commun lit
    nfe = audio_nfe(ae, engine)
    # Le NOM porte l'identifiant (comme la branche média) : `resemble`, pas `enhancer-resemble`.
    storage_name, _path = ctx.output_place('.wav', model=name, source_name=input_path,
                                           folder='output/audio', card_id=False)
    output_filename = os.path.basename(storage_name)
    if is_auto(ae.engine):
        ctx.console(f"[Enhancer] 🧠 Auto → {engine} (VRAM libre au lancement, curseur qualité "
                    f"{quality_intent_of(ae, 'enhancer')}/100"
                    + (f", NFE {nfe}" if name == 'resemble' else '') + ')')
    ctx.console(f"Traitement audio: {ae.get_input_filename()} ({engine})")
    ctx.progress(5)

    options = {
        # Le backend reçoit l'IDENTIFIANT du moteur (`run_audio_enhancement(engine='resemble')`).
        'engine': name,
        'mode': ae.mode,
        'denoising_strength': float(ae.denoising_strength),
        'quality': nfe,
    }
    with work_dir('enhancer') as _work:
        local = os.path.join(str(_work), output_filename)
        route(input_path, local, ae.output_format, options=options,
              progress_callback=lambda p: ctx.progress(5 + int(p * 0.9)))
        saved = _store_output(ae, local, storage_name)

    ae.output_file.name = saved
    from wama.common.services.output_process import generated
    return generated(
        [ae.output_file.path],
        fields={'output_file': ae.output_file.name},
        eta=audio_enhancer_eta_key_size(ae, engine=engine),
        label=output_filename,
        models=[engine])


# ── Partagé avec les vues (ETA) ─────────────────────────────────────────────────────────

def enhancer_eta_key_size(enhancement, model: str = None) -> tuple[str, float, str]:
    """(model_key, size, unit) pour le seeding ETA d'une Enhancement image/vidéo.
    Image → mégapixels d'entrée ; vidéo → durée. Clé par modèle + facteur d'upscale.
    Partagé entre la glu (record, qui passe le modèle RÉSOLU) et la vue progress (estimate,
    qui ne connaît que la colonne — « auto » y est sa propre famille d'estimation)."""
    from wama.common.utils.model_keys import model_id
    mt = (getattr(enhancement, 'media_type', '') or '').lower()
    # L'ETA apprend sous l'IDENTIFIANT (2026-10-06) : la colonne et le modèle résolu sont des
    # clés depuis la route F4b ⑤ — l'identifiant garde l'historique appris (`…:RealESR_Gx4:x4`).
    model = model_id(model or getattr(enhancement, 'ai_model', '') or 'auto')
    factor = getattr(enhancement, 'upscale_factor', '') or ''
    if mt == 'video':
        return f'enhancer:vid:{model}:x{factor}', float(getattr(enhancement, 'duration', 0) or 0), 'video_sec'
    mp = (int(getattr(enhancement, 'width', 0) or 0) * int(getattr(enhancement, 'height', 0) or 0)) / 1e6
    return f'enhancer:img:{model}:x{factor}', mp, 'megapixel'


def audio_enhancer_eta_key_size(ae, engine: str = None) -> tuple[str, float, str]:
    """(model_key, size, unit) pour le seeding ETA d'une AudioEnhancement (durée audio)."""
    from wama.common.utils.model_keys import model_id
    # Sous l'IDENTIFIANT (2026-10-07), comme la branche média : l'historique appris reste
    # `enhancer:audio:resemble`, que la colonne porte une clé ou un identifiant d'avant.
    engine = model_id(engine or getattr(ae, 'engine', '') or 'auto')
    return f'enhancer:audio:{engine}', float(getattr(ae, 'duration', 0) or 0), 'audio_sec'


def generate_eta_key_size(item) -> tuple[str, float, str]:
    """ETA déclarée du process `generate` (`ProcessSpec.eta`) — UN pipeline pour les deux files :
    le triplet de la file de l'élément, celui que sa glu apprend."""
    if isinstance(item, AudioEnhancement):
        return audio_enhancer_eta_key_size(item)
    return enhancer_eta_key_size(item)



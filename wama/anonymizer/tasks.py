import os
import logging
from celery import shared_task
from django.db import close_old_connections
from django.core.cache import cache
from django.contrib.auth import get_user_model
from .models import Media
from wama.common.backends import anonymize
from .utils.media_utils import get_input_media_path
from .utils.yolo_utils import get_model_path
from wama.common.app_registry import normalize_types
from wama.common.utils.media_paths import get_app_media_path
from .utils.sam3_manager import check_sam3_installed, validate_sam3_prompt
from wama.common.utils.console_utils import push_console_line

# Couverture multi-modèles : seule `needs_parallel_detection` survit au retrait du second
# pipeline (2026-08-13) — elle ne fait que consulter la couverture, elle n'orchestre plus rien.
from .parallel_detection import needs_parallel_detection

logger = logging.getLogger(__name__)


def anonymizer_eta_key_size(media):
    """Clé + taille ETA — PARTAGÉE entre record_run (fin de tâche) et estimate
    (endpoint progress) : même clé des deux côtés ou l'EMA n'apprend jamais."""
    from .utils.yolo_utils import catalogue_id_for
    engine = ('sam3' if media.target_mode == 'description'
              else (catalogue_id_for(media.model_to_use) or 'auto'))
    is_video = (media.media_type == 'video' or
                normalize_types([media.file_ext]) == ['video'])
    if is_video:
        return (f'anonymizer:vid:{engine}', float(media.duration_inSec or 1.0), 'video_sec')
    mpx = (media.width or 0) * (media.height or 0) / 1_000_000.0 or 1.0
    return (f'anonymizer:img:{engine}', mpx, 'megapixel')


def anonymizer_blur_eta_key_size(media):
    """Clé + taille ETA du FLOUTAGE (process à part depuis le 2026-10-04) : décoder, flouter,
    réencoder — le coût suit la durée de la vidéo ou la surface de l'image, pas le détecteur."""
    is_video = (media.media_type == 'video' or
                normalize_types([media.file_ext]) == ['video'])
    if is_video:
        return ('anonymizer:blur:vid', float(media.duration_inSec or 1.0), 'video_sec')
    mpx = (media.width or 0) * (media.height or 0) / 1_000_000.0 or 1.0
    return ('anonymizer:blur:img', mpx, 'megapixel')


def blur_eta(media):
    """ETA déclarée du process `blur` (`ProcessSpec.eta`) : APPRISE seulement (a priori nul) — une
    clé de PROCESS n'a pas d'a priori de domaine, ceux de l'estimateur décrivent des modèles
    (6 s par seconde de vidéo produite : faux d'un ordre de grandeur pour un floutage)."""
    return (*anonymizer_blur_eta_key_size(media), True, 0.0)


def _record_output(media, written):
    """Pose sur le média le fichier que le moteur a RÉELLEMENT écrit (2026-09-27).

    Avant : `_resolve_output_rel` DEVINAIT la sortie par `glob('<entrée>_blurred*')`, trié par
    ordre ALPHABÉTIQUE — donc des cards dupliquées (même entrée) se voyaient attribuer le même
    fichier, et un média passé de YOLO à SAM3 pouvait garder la sortie de l'autre moteur.
    La sortie précédente de CETTE card — et l'original que la brique de sortie en gardait — part
    si elle n'est plus la même (moteur ou format changé) ; un fichier qu'une autre card désigne
    encore est laissé (`output_process.drop_previous_outputs`).
    """
    from django.conf import settings
    from wama.common.services.output_process import drop_previous_outputs
    rel = ''
    if written and os.path.exists(written):
        rel = os.path.relpath(written, settings.MEDIA_ROOT).replace(chr(92), '/')
    drop_previous_outputs(media, 'output_file', keep=[written] if rel else [])
    media.output_file.name = rel



def _console(user_id: int, message: str, level: str = None) -> None:
    """Push console message to user."""
    try:
        if level is None:
            msg_lower = message.lower()
            if any(w in msg_lower for w in ['error', 'failed', '\u2717', 'erreur']):
                level = 'error'
            elif any(w in msg_lower for w in ['warning', 'attention']):
                level = 'warning'
            elif any(w in msg_lower for w in ['[debug]', '[parallel']):
                level = 'debug'
            else:
                level = 'info'
        push_console_line(user_id, message, level=level, app='anonymizer')
    except Exception:
        pass


def _output_format_for(media, source) -> str:
    """Le format de sortie DEMANDÉ pour ce média — résolu ici parce que le réglage de
    l'anonymizer n'est pas toujours un format :
        'original' → ce que le moteur a écrit (rien à faire) ;
        'input'    → le format du fichier SOURCE (le moteur a écrit du .mp4, l'utilisateur avait
                     déposé du .mov → retour au .mov) ;
        '<fmt>'    → ce format.
    Un format égal à celui du fichier d'origine ne demande rien non plus."""
    fmt = (getattr(media, 'output_format', '') or 'original').lower()
    if fmt in ('', 'original'):
        return 'original'
    wanted = (media.file_ext or '').lower().lstrip('.') if fmt == 'input' else fmt
    if not wanted or os.path.splitext(str(source))[1].lower().lstrip('.') == wanted:
        return 'original'
    return wanted


def _output(media, ctx):
    """GLU du process `output` : format et qualité de sortie, par la glu COMMUNE
    (`output_process.output_step`) — le fichier flouté d'origine est gardé tant que la sortie le
    transforme."""
    from wama.common.services.output_process import output_step
    video = normalize_types([media.file_ext]) == ['video']
    return output_step('output_file', domain='video' if video else 'image', app_id='anonymizer',
                       console=lambda item, message: _console(item.user_id, message),
                       format_of=_output_format_for)(media, ctx)


# ----------------------------------------------------------------------
# Tâche principale pour traiter un média
# ----------------------------------------------------------------------
@shared_task(bind=True)
def process_single_media(self, media_id, force_individual=False, process=None):
    """
    Traite un média unique en DB — avec SES réglages, et eux seuls — par le squelette COMMUN
    (`run_item_task`, marche P6 du 2026-10-03) : garde de redélivrance après crash, ingestion
    d'une source distante, statuts canoniques, durée max, chrono, ETA, console, notifications,
    ligne d'exécution, révision. L'app ne garde que ses GLUS (`_detect`, `_blur`, `_output`) et
    ce qui lui est propre : le verrou de dédoublonnage (deux tâches pour un même média) et l'arrêt demandé par
    l'utilisateur.

    Depuis le 2026-09-27 un média NAÎT avec les réglages de son auteur (brique `user_settings`,
    `ROADMAP §23.2quater`) : la tâche ne lit plus que ses colonnes.

    force_individual : conservé pour les appelants existants ; il n'a plus d'effet.
    process : lancement BORNÉ à ce process du pipeline (⚠ argument de tâche nouveau : workers à
    relancer).
    """
    from wama.common.services.output_process import forget_lost_generation
    from wama.common.utils.task_skeleton import run_item_task
    from .function_specs import PIPELINE

    # Dedup: check if another task already owns this media
    owner_key = f"anon_task_owner:media:{media_id}"
    current_owner = cache.get(owner_key)
    my_task_id = self.request.id

    if current_owner and current_owner != my_task_id:
        logger.info(f"[Dedup] Skipping media {media_id}: already owned by task {current_owner}")
        return {"skipped": True, "media_id": media_id, "reason": "duplicate"}

    # Claim ownership
    cache.set(owner_key, my_task_id, timeout=7200)
    cache.set(f"anon_lock:media:{media_id}", True, timeout=7200)

    try:
        # Vérifie si un stop a été demandé (avant tout traitement).
        user_id = Media.objects.filter(pk=media_id).values_list('user_id', flat=True).first()
        if user_id is not None and cache.get(f"stop_process_{user_id}", False):
            cache.delete(f"stop_process_{user_id}")
            return {"stopped": media_id}

        # « En cours » est posé par TOUS les lanceurs (`begin_processing`), y compris celui de
        # la file entière (`process_user_media_batch`) : la tâche ne bascule rien avant la garde
        # anti-re-livraison du squelette — sans quoi un message re-livré PÉRIMÉ remettait en
        # cours, pour toujours, un média terminé (2026-10-03).
        # La card porte un PIPELINE de trois process (`function_specs.PIPELINE`) : `detect`
        # (`_detect`, les détections du média), `blur` (`_blur`, le floutage depuis elles) puis
        # `output` (`_output`, format et qualité). Un lancement ne rejoue que ce qui n'est plus à
        # jour : changer l'intensité du flou ne redétecte pas, changer le format ne re-floute
        # pas. La sortie repart du fichier que le floutage a laissé : s'il n'est plus là, le
        # floutage rejoue (un document de détections disparu, lui, se voit à sa ligne).
        known = Media.objects.filter(pk=media_id).first()
        if known is not None:
            forget_lost_generation(known, 'output_file', 'blur')
        run_item_task(self, app_id='anonymizer', model=Media, item_id=media_id,
                      pipeline=PIPELINE,
                      processes={'detect': _detect, 'blur': _blur, 'output': _output},
                      notify_label='Anonymizer', only=process,
                      ingest_derive=_ingested_metadata,
                      progress_fn=lambda item, pct, msg: set_media_progress(item.pk, pct))
    finally:
        # Release dedup locks — succès, échec, arrêt : dans tous les cas.
        cache.delete(f"anon_lock:media:{media_id}")
        cache.delete(f"anon_task_owner:media:{media_id}")
    return {"processed": media_id}


def _ingested_metadata(inst, save_path, fname):
    """Métadonnées relevées sur le fichier téléchargé (mêmes champs que l'upload) — déclaré à
    l'ingestion commune (`source_ingest.ensure_local_input`, `derive=`)."""
    from wama.anonymizer.views import add_media_to_db
    add_media_to_db(inst, save_path)
    inst.file_ext = os.path.splitext(save_path)[1].lstrip('.').lower()
    return ['file_ext', 'width', 'height', 'fps',
            'duration_inSec', 'duration_inMinSec', 'media_type']


def _catalogue_key(value):
    """La clé de catalogue (`anonymizer:<id>`) d'un modèle désigné par son identifiant, son
    fichier ou son chemin — None s'il n'est pas au catalogue (on ne nomme pas ce qu'on ignore)."""
    from .utils.yolo_utils import catalogue_id_for
    try:
        found = catalogue_id_for(os.path.basename(str(value))) or catalogue_id_for(value)
    except Exception:
        return None
    return f'anonymizer:{found}' if found else None


def _detection_kwargs(media, user):
    """Ce que le détecteur reçoit, et les modèles qu'il emploiera (clés de catalogue) : choix du
    ou des modèles par la couverture des classes demandées, ou SAM3 pour une description."""
    precision_level = media.precision_level
    use_segmentation = media.use_segmentation
    # Mode DESCRIPTION (`app_modes`) : la seule désignation par texte branchée au moteur de
    # floutage est SAM3 — LocateAnything, au catalogue, n'y est pas encore relié.
    use_sam3 = media.target_mode == 'description'
    sam3_prompt = media.sam3_prompt

    # SAM3 = concepts EN → pipeline commune (§16.6) ; KIND déclaré dans app_metadata.
    # Bug d'origine : « Floute les visages » (FR) → 0 masque. process_prompt_for est fail-safe.
    if use_sam3 and sam3_prompt and sam3_prompt.strip():
        from wama.common.utils.app_metadata import process_prompt_for
        sam3_prompt = process_prompt_for('anonymizer', 'sam3_prompt', sam3_prompt,
                                         instance=media, user=user,
                                         console=lambda m: _console(user.id, f"[SAM3] {m}"))

    _console(user.id, f"[DEBUG] SAM3 settings: use_sam3={use_sam3}, prompt='{sam3_prompt[:30] if sam3_prompt else ''}'")

    kwargs = {
        'media_path': get_input_media_path(media.file.name, user.id),
        'file_ext': media.file_ext,
        # Assaini : un vieux chemin de sauvegarde a injecté le BOOLÉEN sérialisé 'false'
        # dans des listes de classes (médias 220/221/225 constatés le 2026-08-17) — une
        # classe est un nom, jamais true/false/none/vide.
        'classes2blur': _classes_saines(media.classes2blur),
        'detection_threshold': media.detection_threshold,
        'precision_level': precision_level,
        'use_segmentation': use_segmentation,
        # SAM3 parameters
        'use_sam3': use_sam3,
        'sam3_prompt': sam3_prompt,
        'user_id': user.id,  # For console logging
    }

    # ======================================================================
    # PARALLEL DETECTION: Check if multiple models are needed
    # ======================================================================
    # Determine user's specified model (if any)
    # Identifiant du catalogue, chemin d'avant, ou « auto » → '' (`catalogue_id_for`).
    from .utils.yolo_utils import catalogue_id_for, model_path_for
    user_specified_model = '' if use_sam3 else catalogue_id_for(media.model_to_use)

    # Check if specialty classes (face, plate) are requested
    # These often require dedicated models even if user has a default COCO model
    specialty_classes_set = {'face', 'plate', 'license_plate', 'license plate'}
    specialty_classes_requested = any(
        c.lower() in specialty_classes_set for c in kwargs['classes2blur']
    )

    # Enable parallel detection check if:
    # - SAM3 is not being used AND
    # - Either no user model is specified OR specialty classes are requested
    #   (specialty classes need dedicated models, can't rely on user's COCO model)
    should_check_parallel = not use_sam3 and (not user_specified_model or specialty_classes_requested)

    # Debug: Log parallel detection decision
    logger.info(f"[ParallelCheck] use_sam3={use_sam3}, user_specified_model={user_specified_model}")
    logger.info(f"[ParallelCheck] specialty_classes_requested={specialty_classes_requested}, should_check_parallel={should_check_parallel}")
    logger.info(f"[ParallelCheck] classes2blur={kwargs['classes2blur']}, precision_level={precision_level}")
    _console(user.id, f"[Parallel Check] SAM3={use_sam3}, user_model={user_specified_model}, specialty={specialty_classes_requested}")

    if should_check_parallel:
        parallel_info = needs_parallel_detection(kwargs['classes2blur'], precision_level)

        logger.info(f"[ParallelCheck] parallel_info: parallel={parallel_info.get('parallel')}, "
                    f"models={len(parallel_info.get('models', []))}, coverage={parallel_info.get('coverage')}")
        _console(user.id, f"[Parallel Check] parallel={parallel_info.get('parallel')}, "
                          f"models={len(parallel_info.get('models', []))}")

        if parallel_info.get('unsupported_classes'):
            _console(user.id, f"[Parallel Check] Unsupported classes: {parallel_info['unsupported_classes']}")

        if parallel_info['parallel'] and len(parallel_info['models']) > 1:
            # ── MULTI-MODÈLES : UNE SEULE TÂCHE (2026-08-13) ──────────────────────────
            # Auparavant : une chaîne Celery `detect_with_model` × N + `merge_and_blur`,
            # avec les masques sérialisés en base64 dans Redis. Ce second pipeline avait
            # PERDU l'interpolation, le format de sortie, le statut RUNNING, l'ETA, la
            # notification et l'annulation — et décodait la vidéo N+1 fois.
            # Désormais on reste dans CETTE tâche : `Anonymize` sait charger N modèles et
            # unir leurs zones frame par frame. Tout ce qui suit (statut, ETA, format,
            # notification, verrous) s'applique donc au multi-modèles comme au reste.
            _console(user.id, f"[Multi] {len(parallel_info['models'])} modèles retenus")
            for m in parallel_info['models']:
                _console(user.id, f"  - {m['id']} : {m['classes']}")
            kwargs['models'] = [
                {'path': m['path'], 'name': m.get('name'), 'classes': m.get('classes')}
                for m in parallel_info['models']
            ]

        elif not parallel_info['parallel'] and len(parallel_info['models']) == 1:
            # Single model selected by ModelSelector.
            # The override is only legitimate when the user's model does NOT
            # support the requested classes (e.g. user has yolo11n.pt but needs
            # face detection). If the user EXPLICITLY chose a model that already
            # covers the requested classes (e.g. yolov9s-face-lindevs.pt for
            # 'face'), respect that choice instead of forcing another model.
            selected = parallel_info['models'][0]
            from .utils.yolo_utils import get_model_path as _gmp

            keep_user_model = False
            if user_specified_model:
                try:
                    from .utils.model_selector import get_model_classes
                    user_model_abs = model_path_for(user_specified_model)
                    user_classes = set(get_model_classes(user_model_abs).values())
                    requested = {c.lower() for c in kwargs['classes2blur']}
                    if requested and requested.issubset(user_classes):
                        keep_user_model = True
                except Exception as e:
                    logger.warning(f"[ModelSelection] Could not verify user model classes: {e}")

            if keep_user_model:
                kwargs['model_path'] = model_path_for(user_specified_model)
                _console(user.id, f"Respecting user-specified model: {user_specified_model}")
                logger.info(f"[ModelSelection] Keeping user-specified model {user_specified_model} "
                            f"(already covers {kwargs['classes2blur']}) — no override")
            else:
                # La couverture rend déjà le chemin disque du catalogue : le re-résoudre
                # depuis l'identifiant rouvrirait une seconde route (et échouerait pour un
                # modèle rangé hors de l'arborescence historique). `_gmp` reste le repli.
                kwargs['model_path'] = selected.get('path') or _gmp(selected['id'])
                _console(user.id, f"Auto-selected model: {selected['id']} for classes {selected['classes']}")
                logger.info(f"[ModelSelection] Using ModelSelector result: {selected['id']} (overriding user default)")

    # ======================================================================
    # SINGLE MODEL PATH: Standard processing (existing flow)
    # ======================================================================
    # Model selection (only if not already set by parallel check above).
    # `models` (multi-modèles) court-circuite : la couverture a déjà tranché, refaire une
    # sélection mono-modèle ici ne servirait à rien et brouillerait la trace console.
    if 'model_path' not in kwargs and 'models' not in kwargs:
        try:
            from .utils.yolo_utils import get_model_path as _gmp
            from .utils.model_selector import select_model_by_precision

            # Le modèle du média s'il en porte un, sinon la sélection automatique.
            model_to_use = user_specified_model or None
            if model_to_use:
                _console(user.id, f"Using media-specific model: {model_to_use}")

            if model_to_use:
                kwargs['model_path'] = model_path_for(model_to_use)
            else:
                # Auto-select model based on precision level and classes
                selected_model = select_model_by_precision(
                    classes_to_blur=kwargs['classes2blur'],
                    precision_level=precision_level
                )

                if selected_model:
                    kwargs['model_path'] = _gmp(selected_model)
                    _console(user.id, f"Auto-selected model (precision {precision_level}): {selected_model}")
                # Fallback to custom face/plate model if needed
                elif any(c in kwargs['classes2blur'] for c in ['face', 'plate']):
                    kwargs['model_path'] = _gmp("yolov8m_faces&plates_720p.pt")
                    _console(user.id, f"Using custom face/plate model")
        except Exception as e:
            _console(user.id, f"Warning: Model selection failed ({e}), using default")
            pass

    # Les modèles EMPLOYÉS, en clés de catalogue, pour la ligne d'exécution — ce que le réglage
    # ne dit pas quand il est resté « auto ». SAM3 n'est pas nommé : `detect_media` peut se
    # replier sur YOLO sans le rendre, et une ligne ne nomme pas un modèle qui n'a pas tourné.
    used_models = []
    if not use_sam3:
        paths = [m['path'] for m in kwargs.get('models') or []] or [kwargs.get('model_path')]
        used_models = [key for key in (_catalogue_key(p) for p in paths if p) if key]
    return kwargs, used_models


def _partial_frames(media):
    """L'aperçu « pendant » d'une VIDÉO (une image n'a qu'une frame), si la card le demande
    (`show_preview`) — brique commune `preview_utils.PartialFrames`."""
    if normalize_types([media.file_ext]) != ['video'] or not media.show_preview:
        return None
    from wama.common.utils.preview_utils import PartialFrames
    folder = os.path.join(get_app_media_path('anonymizer', media.user_id, 'output'), 'partials')
    return PartialFrames('anonymizer', media.id, folder)


def _drawn(media, image, found):
    """La vue « Détection » d'une frame : ce que la card demande d'afficher (`show_boxes`,
    `show_labels`, `show_conf`) — ces réglages pilotaient une fenêtre OpenCV côté serveur
    (`track(show=…)`), que personne ne voyait ; ils pilotent désormais l'aperçu."""
    from wama.common.utils.detections import draw
    return draw(image, found, boxes=media.show_boxes, labels=media.show_labels,
                confidence=media.show_conf)


def _segmentation_note(media, doc):
    """Ce qui empêche la SEGMENTATION demandée, dit en clair — ou '' quand elle a eu lieu ou
    n'était pas demandée. Demandée : le curseur au-delà de son seuil, ou le réglage explicite.

    Né de la card #1026 (2026-10-05) : curseur à 50, des visages en RECTANGLES, et rien ne le
    disait. Le seul modèle qui segmente les visages au catalogue n'était pas INSTALLÉ ; la
    couverture retombait sur un détecteur sans un mot. On nomme ce qui manque, et où l'obtenir."""
    from wama.common.services.model_coverage import segmentation_for_intent
    wanted = bool(media.use_segmentation) or segmentation_for_intent(media.precision_level)
    if not wanted or doc.get('engine') != 'yolo':
        return ''
    if any(d.get('polygons') for f in doc.get('frames') or [] for d in f['d']):
        return ''
    if not doc.get('frames'):
        return ''
    from wama.common.services.model_coverage import formes_equivalentes
    from wama.model_manager.models import AIModel
    asked = set()
    for name in doc.get('classes') or []:
        asked |= formes_equivalentes(name)
    missing = []
    for key, caps in (AIModel.objects.filter(source='anonymizer', is_available=False)
                      .values_list('model_key', 'capabilities')):
        caps = caps or {}
        covered = {c.lower() for c in (caps.get('classes') or [])}
        if caps.get('task') == 'segment' and covered & asked:
            missing.append(key.split(':')[-1])
    if missing:
        return ("Segmentation demandée, mais aucun modèle de segmentation INSTALLÉ ne couvre "
                f"{', '.join(sorted(doc.get('classes') or []))} : contours rectangulaires. À "
                f"installer depuis le Model Manager : {', '.join(sorted(missing))}.")
    return ("Segmentation demandée, mais aucun modèle du catalogue ne segmente "
            f"{', '.join(sorted(doc.get('classes') or []))} : contours rectangulaires.")


def _detect(media, ctx):
    """GLU du process `detect` (« Détection », 2026-10-04) : choix du ou des modèles, détection
    (YOLO ou SAM3), document `detections` écrit dans la sortie de l'app et posé sur la card
    (`detections_file`). Rien n'est flouté ici : c'est le process suivant, qui le relit.

    Pendant une vidéo, l'aperçu montre la frame courante avec ses détections dessinées."""
    from django.conf import settings
    from wama.common.services.output_process import drop_previous_outputs
    from wama.common.utils import detections
    from wama.common.utils.output_naming import compose_output_name
    if not media.file:
        raise ValueError("Média sans fichier (ni URL rapatriée) : rien à traiter.")
    user = media.user
    kwargs, used_models = _detection_kwargs(media, user)
    _console(user.id, f"Détection — média {media.id}…")
    ctx.progress(2)

    frames = _partial_frames(media)

    def on_frame(index, image, found):
        if frames is not None and frames.due():
            frames.publish({'detection': ('Détection', _drawn(media, image, found))}, index=index)

    kwargs['on_frame'] = on_frame
    kwargs['progress'] = lambda done, total: ctx.progress(min(99, int(done * 100 / max(total, 1))))
    try:
        doc = detect_media(**kwargs)
    finally:
        if frames is not None:
            frames.close()

    folder = get_app_media_path('anonymizer', user.id, 'output')
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, compose_output_name(
        app='anonymizer', model=doc.get('tag') or doc.get('engine') or 'yolo',
        source_name=kwargs['media_path'], item_id=media.id, nature='detections', ext='.json'))
    detections.write(target, doc)
    # Le document d'avant part s'il n'a plus le même nom (moteur changé) ; l'original que garde
    # la SORTIE n'est pas le sien : il reste (`natives=False`).
    drop_previous_outputs(media, 'detections_file', keep=[target], natives=False)
    rel = os.path.relpath(target, settings.MEDIA_ROOT).replace(chr(92), '/')
    media.detections_file.name = rel
    found = detections.count(doc)
    shown = len(doc.get('frames') or [])
    _console(user.id, f"Détection : {found} objet(s) sur {shown} image(s)"
             + ("" if found else " — rien ne sera flouté"), 'info' if found else 'warning')
    note = _segmentation_note(media, doc)
    if note:
        _console(user.id, note, 'warning')
    return {
        'fields': {'detections_file': rel},
        'output_ref': rel,
        'eta': anonymizer_eta_key_size(media),
        'label': os.path.basename(getattr(media.file, 'name', '') or '') or f"média #{media.id}",
        'console_success': f"Détection : {found} objet(s) ✔",
        'models': used_models or None,
    }


def _blur(media, ctx):
    """GLU du process `blur` (« Floutage », 2026-10-04) : le média réécrit depuis son document de
    détections — intensité, contour progressif, agrandissement de la zone, interpolation des
    trous d'une piste. Aucun modèle n'est chargé : changer un réglage de flou ne redétecte pas.

    Pendant une vidéo, l'aperçu offre DEUX vues de la frame courante — détections dessinées,
    frame floutée — entre lesquelles l'inspecteur bascule (variantes de `preview_utils`)."""
    from wama.common.utils import detections
    from wama.common.utils.blur_utils import blur_detections
    from wama.common.utils.output_naming import compose_output_name
    if not media.file:
        raise ValueError("Média sans fichier (ni URL rapatriée) : rien à traiter.")
    if not media.detections_file:
        raise RuntimeError("Floutage : aucune détection — relancer la détection.")
    try:
        doc = detections.read(media.detections_file.path)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Floutage : détections illisibles ({exc}) — relancer la "
                           "détection.") from exc
    user = media.user
    source = get_input_media_path(media.file.name, user.id)
    video = doc.get('media') == 'video'
    frames_map = detections.by_frame(
        doc, interpolate=video and media.interpolate_detections,
        max_gap=detections.max_gap_for(doc.get('fps'), media.max_interpolation_frames),
        max_extrapolation=media.max_extrapolation_frames if video else 0)
    settings_ = {'blur_ratio': media.blur_ratio, 'rounded_edges': media.rounded_edges,
                 'progressive_blur': media.progressive_blur,
                 'roi_enlargement': media.roi_enlargement}

    def paint(image, found):
        return blur_detections(image, found, **settings_)

    folder = get_app_media_path('anonymizer', user.id, 'output')
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, compose_output_name(
        app='anonymizer', model=doc.get('tag') or doc.get('engine') or 'yolo',
        source_name=source, item_id=media.id))
    preview = _partial_frames(media)

    def on_frame(index, original, painted, found):
        if preview is not None and preview.due():
            preview.publish({'detection': ('Détection', _drawn(media, original, found)),
                             'blur': ('Floutage', painted)}, index=index)

    _console(user.id, f"Floutage — média {media.id}…")
    ctx.progress(2)
    try:
        written = detections.paint_media(
            source, frames_map, paint, target, on_frame=on_frame,
            progress=lambda done, total: ctx.progress(min(99, int(done * 100 / max(total, 1)))))
    finally:
        if preview is not None:
            preview.close()

    # La sortie RÉELLEMENT écrite, posée sur le média (l'ancienne part si elle n'est plus la
    # même). Le format et la qualité de sortie sont le process suivant, `output` (`_output`).
    try:
        media.refresh_from_db(fields=['output_file'])
    except media.__class__.DoesNotExist:
        raise RuntimeError("Le média a été supprimé pendant son traitement.")
    _record_output(media, written)
    if not media.output_file.name:
        raise RuntimeError("Le floutage n'a écrit aucun fichier.")
    from wama.common.services.output_process import generated
    return generated(
        [written],
        fields={'output_file': media.output_file.name},
        eta=anonymizer_blur_eta_key_size(media),
        label=os.path.basename(getattr(media.file, 'name', '') or '') or f"média #{media.id}",
        console_success=f"Floutage ✔ ({detections.count(doc)} objet(s))")


# ----------------------------------------------------------------------
# Fonction pour lancer le traitement du média
# ----------------------------------------------------------------------
def detect_media(**kwargs):
    """Les DÉTECTIONS d'un média, en document `detections` (`common/utils/detections`) : SAM3
    quand la card décrit en texte ce qu'il faut flouter (et que SAM3 est là, et le prompt
    valide), sinon le détecteur YOLO (un ou plusieurs modèles). Rien n'est écrit ni flouté :
    la tâche range le document, le process « Floutage » le relit (2026-10-04)."""
    use_sam3 = kwargs.get('use_sam3', False)
    sam3_prompt = kwargs.get('sam3_prompt', '')
    user_id = kwargs.get('user_id')
    source_dir = get_app_media_path('anonymizer', user_id, 'input') if user_id else None
    dest_dir = get_app_media_path('anonymizer', user_id, 'output') if user_id else None

    if use_sam3 and sam3_prompt and sam3_prompt.strip():
        reason = None
        if not check_sam3_installed():
            reason = "SAM3 not installed"
        else:
            is_valid, error = validate_sam3_prompt(sam3_prompt)
            if not is_valid:
                reason = f"Invalid SAM3 prompt: {error}"
        if reason is None:
            try:
                # Le MODÈLE porte son moteur ; le backend s'en dérive (2026-09-07).
                from wama.common.backends.manager import backend_for_key
                SAM3Processor = backend_for_key('anonymizer:sam3')
                if SAM3Processor is None:
                    raise ImportError("anonymizer:sam3 : aucun backend résolu depuis le "
                                      "catalogue (ligne absente, ou sans moteur déclaré)")
                if user_id:
                    _console(user_id, f"Using SAM3 with prompt: {sam3_prompt[:50]}...")
                processor = SAM3Processor(source_dir=source_dir, destination_dir=dest_dir)
                processor.load_model('auto')
                _last_pct = [0]

                def _sam3_progress(pct):
                    if user_id and (pct - _last_pct[0] >= 10 or pct >= 100):
                        _last_pct[0] = pct
                        _console(user_id, f"SAM3 progress: {pct}%")
                return processor.detect(progress_callback=_sam3_progress, **kwargs)
            except Exception as e:
                reason = f"SAM3 error: {e}"
        if user_id:
            _console(user_id, f"Warning: {reason}. Falling back to YOLO.")

    if user_id:
        _console(user_id, f"Using YOLO with classes: {kwargs.get('classes2blur', [])}")
    model = anonymize.Anonymize(source_dir=source_dir, destination_dir=dest_dir)
    model.load_model(**kwargs)
    return model.detect(**kwargs)


# ----------------------------------------------------------------------
# Arrêt d'un traitement utilisateur
# ----------------------------------------------------------------------
def stop_process(user_id):
    """
    Demande l'arrêt d'un traitement utilisateur en cours.
    Le flag sera vérifié dans la boucle de process_single_media.
    """
    cache.set(f"stop_process_{user_id}", True, timeout=60)
    print(f"Process stop demandé pour user {user_id}")


# ----------------------------------------------------------------------
# Tâche pour traiter tous les médias d'un utilisateur (file batch)
# ----------------------------------------------------------------------
@shared_task(bind=True)
def process_user_media_batch(self, user_id):
    """
    Enfile tous les médias non traités d'un utilisateur dans des tâches individuelles.
    """
    import logging
    logger = logging.getLogger('celery')

    logger.info(f"[process_user_media_batch] Starting batch process for user_id={user_id}")

    close_old_connections()

    User = get_user_model()
    user = User.objects.get(pk=user_id)
    logger.info(f"[process_user_media_batch] User: {user.username}")

    medias_list = Media.objects.filter(user=user).exclude(status='SUCCESS')
    logger.info(f"[process_user_media_batch] Found {medias_list.count()} unprocessed media(s)")

    if not medias_list.exists():
        logger.warning(f"[process_user_media_batch] No media to process for user {user.username}")
        cache.delete(f"anon_lock:batch:{user_id}")
        return {"processed": 0}

    # « En cours » est posé par le LANCEUR, sous verrou, avant l'envoi — la règle de tous les
    # lanceurs (`begin_processing`, `PROJECT_STATUS §PALIER 2026-09-14`) ; la tâche ne bascule
    # jamais un élément elle-même. Le `task_id` enregistré est ce qui permet à la garde
    # anti-re-livraison de reconnaître un message PÉRIMÉ (cas de la card #741, 2026-09-29).
    from wama.common.utils.process_control import begin_processing
    from .views import _reset_for_relaunch
    task_ids = []
    for media in medias_list:
        locked, err = begin_processing(Media, media.pk, user=user, reset=_reset_for_relaunch)
        if err:                     # déjà en cours : sa tâche le porte
            continue
        cache.set(f"anon_lock:media:{locked.id}", True, timeout=7200)
        logger.info(f"[process_user_media_batch] Launching task for media {locked.id} ({locked.title})")
        task = process_single_media.delay(locked.id)
        locked.task_id = task.id
        locked.save(update_fields=['task_id'])
        task_ids.append(task.id)
        logger.info(f"[process_user_media_batch] Task {task.id} launched for media {locked.id}")

    # Clear batch lock (individual media locks remain until tasks complete)
    cache.delete(f"anon_lock:batch:{user_id}")

    logger.info(f"[process_user_media_batch] Total tasks launched: {len(task_ids)}")
    return {"queued_tasks": task_ids, "total": medias_list.count()}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _classes_saines(classes) -> list:
    """Filtre les intrus non-classe d'une liste classes2blur ('false' booléen sérialisé par
    un ancien chemin de sauvegarde — constat 2026-08-17). Une classe est un NOM."""
    return [c for c in (classes or [])
            if isinstance(c, str) and c.strip().lower() not in ('true', 'false', 'none', '')]


def set_media_progress(media_id: int, percent: int) -> None:
    """Persist media progress in cache and DB (clamped 0..100)."""
    try:
        pct = max(0, min(100, int(percent)))
        cache.set(f"media_progress_{media_id}", pct, timeout=3600)
        Media.objects.filter(pk=media_id).update(blur_progress=pct)
    except Exception:
        # best effort only
        pass

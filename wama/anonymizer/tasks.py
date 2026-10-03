import os
import logging
import threading
import time
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
from wama.common.utils.queue_duplication import safe_delete_file

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


def _record_output(media, written):
    """Pose sur le média le fichier que le moteur a RÉELLEMENT écrit (2026-09-27).

    Avant : `_resolve_output_rel` DEVINAIT la sortie par `glob('<entrée>_blurred*')`, trié par
    ordre ALPHABÉTIQUE — donc des cards dupliquées (même entrée) se voyaient attribuer le même
    fichier, et un média passé de YOLO à SAM3 pouvait garder la sortie de l'autre moteur.
    La sortie précédente de CETTE card part si elle n'est plus la même (moteur ou format
    changé) — par `safe_delete_file`, qui la garde si une autre ligne la désigne encore.
    """
    from django.conf import settings
    rel = ''
    if written and os.path.exists(written):
        rel = os.path.relpath(written, settings.MEDIA_ROOT).replace(chr(92), '/')
    if media.output_file and media.output_file.name != rel:
        safe_delete_file(media, 'output_file')
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


def _apply_anonymizer_output_format(media, written):
    """Convert the blurred output to the chosen format (Phase 3 élargie); return the final path.

    output_format:
        'original' → keep whatever the pipeline produced (no-op)
        'input'    → reconvert to the SOURCE file's format (e.g. pipeline
                     produced .mp4 but the user uploaded .mov → back to .mov)
        '<fmt>'    → explicit target format
    Works on the file the engine WROTE (2026-09-27). It used to glob `<input>_blurred*`, which
    converted the outputs of every card sharing the input — duplicates included.
    """
    fmt = (getattr(media, 'output_format', '') or 'original').lower()
    if fmt in ('', 'original') or not written or not os.path.exists(written):
        return written

    src_ext = (media.file_ext or '').lower().lstrip('.')
    target = src_ext if fmt == 'input' else fmt
    if not target or os.path.splitext(written)[1].lower().lstrip('.') == target:
        return written

    try:
        from wama.converter.utils.inline_convert import apply_inline_conversion
        preset = getattr(media, 'output_quality', 'balanced') or 'balanced'
        return apply_inline_conversion(written, target, preset)
    except Exception as exc:
        logger.warning(f"[anonymizer] conversion format sortie échouée: {exc}")
        return written


# ----------------------------------------------------------------------
# Tâche principale pour traiter un média
# ----------------------------------------------------------------------
@shared_task(bind=True)
def process_single_media(self, media_id, force_individual=False):
    """
    Traite un média unique en DB — avec SES réglages, et eux seuls — par le squelette COMMUN
    (`run_item_task`, marche P6 du 2026-10-03) : garde de redélivrance après crash, ingestion
    d'une source distante, statuts canoniques, durée max, chrono, ETA, console, notifications,
    ligne d'exécution, révision. L'app ne garde que sa GLU (`_anonymize`) et ce qui lui est
    propre : le verrou de dédoublonnage (deux tâches pour un même média) et l'arrêt demandé par
    l'utilisateur.

    Depuis le 2026-09-27 un média NAÎT avec les réglages de son auteur (brique `user_settings`,
    `ROADMAP §23.2quater`) : la tâche ne lit plus que ses colonnes.

    force_individual : conservé pour les appelants existants ; il n'a plus d'effet.
    """
    from wama.common.utils.task_skeleton import run_item_task

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

        if not (getattr(self.request, 'retries', 0) or 0):
            # « En cours » est posé par les lanceurs d'UN média (`begin_processing`). Le lanceur
            # de TOUTE la file (`process_user_media_batch`) remet les médias « en attente » et
            # envoie les tâches : c'est ici qu'ils passent en cours — à la première livraison
            # seulement (une re-livraison ne remet pas en cours ce que l'utilisateur a arrêté).
            Media.objects.filter(pk=media_id).exclude(status='RUNNING').update(
                status='RUNNING', error_message='')

        run_item_task(self, app_id='anonymizer', model=Media, item_id=media_id,
                      process=_anonymize, notify_label='Anonymizer',
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


def _anonymize(media, ctx):
    """La GLU de l'anonymizer : choix du ou des modèles (couverture des classes demandées),
    floutage (YOLO ou SAM3), conversion au format de sortie, sortie posée sur le média."""
    if not media.file:
        raise ValueError("Média sans fichier (ni URL rapatriée) : rien à traiter.")
    user = media.user
    media_id = media.id

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

    # Determine if this is an image (interpolation doesn't apply to images)
    image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp', '.tiff', '.tif']
    is_image = media.file_ext and media.file_ext.lower() in image_extensions

    # Get interpolation setting (disabled for images)
    interpolate_detections = False if is_image else media.interpolate_detections

    kwargs = {
        'media_path': get_input_media_path(media.file.name, user.id),
        'file_ext': media.file_ext,
        # Assaini : un vieux chemin de sauvegarde a injecté le BOOLÉEN sérialisé 'false'
        # dans des listes de classes (médias 220/221/225 constatés le 2026-08-17) — une
        # classe est un nom, jamais true/false/none/vide.
        'classes2blur': _classes_saines(media.classes2blur),
        'blur_ratio': media.blur_ratio,
        'roi_enlargement': media.roi_enlargement,
        'progressive_blur': media.progressive_blur,
        'detection_threshold': media.detection_threshold,
        'interpolate_detections': interpolate_detections,
        'max_interpolation_frames': media.max_interpolation_frames,
        'show_preview': media.show_preview,
        'show_boxes': media.show_boxes,
        'show_labels': media.show_labels,
        'show_conf': media.show_conf,
        'precision_level': precision_level,
        'use_segmentation': use_segmentation,
        # SAM3 parameters
        'use_sam3': use_sam3,
        'sam3_prompt': sam3_prompt,
        'user_id': user.id,  # For console logging
        # Nom de sortie PROPRE à la card (`compose_output_name(item_id=…)`) : des cards
        # dupliquées partagent leur entrée, jamais leur sortie.
        'item_id': media.id,
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
    # ne dit pas quand il est resté « auto ». SAM3 n'est pas nommé : `start_process` peut se
    # replier sur YOLO sans le rendre, et une ligne ne nomme pas un modèle qui n'a pas tourné.
    used_models = []
    if not use_sam3:
        paths = [m['path'] for m in kwargs.get('models') or []] or [kwargs.get('model_path')]
        used_models = [key for key in (_catalogue_key(p) for p in paths if p) if key]

    _console(user.id, f"Start processing media {media.id} ...")

    # Load model (early progress)
    try:
        cache.set(f"media_stage_{media.id}", "loading_model", timeout=3600)
        ctx.progress(5)
        _console(user.id, f"Loading model for media {media.id} ...")
    except Exception:
        pass

    # Run process with simulated progress
    ctx.progress(10)
    _console(user.id, f"Running anonymization for media {media.id} ...")

    # Durée estimée pour la simulation de progression : ETA apprise (EMA par
    # clé modèle/taille) avec repli sur l'a-priori historique 60 s vidéo / 10 s image.
    is_video = normalize_types([media.file_ext]) == ['video']
    estimated_duration = 60 if is_video else 10
    eta_key, eta_size, eta_unit = anonymizer_eta_key_size(media)
    try:
        from wama.model_manager.services.eta_estimator import estimate
        _est = estimate(eta_key, size=eta_size, unit=eta_unit, model_loaded=True,
                        fallback_seconds=estimated_duration)
        if _est:
            estimated_duration = max(3, int(_est))
    except Exception:
        pass

    # Start progress simulation in background thread (10% -> 90%)
    stop_flag = f"stop_progress_sim_{media.id}"
    cache.delete(stop_flag)  # Ensure it's clear
    progress_thread = threading.Thread(
        target=simulate_progress,
        args=(media.id, 10, 90, estimated_duration, stop_flag),
        daemon=True
    )
    progress_thread.start()

    # Aperçu « PENDANT » (brique COMMUNE preview_utils, `?side=during`) : la frame floutée
    # COURANTE publiée ~toutes les 2 s (vidéo seulement — une image n'a qu'une frame).
    # Le hook `on_frame` traverse kwargs jusqu'à la boucle de floutage (anonymize.py),
    # qui ne connaît ni pk ni URLs ; le throttle et l'écriture JPEG vivent ICI.
    from wama.common.utils.preview_utils import clear_partial, publish_partial
    _partial_abs = None
    if is_video:
        import cv2 as _cv2
        from django.conf import settings as _settings
        _pdir = os.path.join(get_app_media_path('anonymizer', user.id, 'output'), 'partials')
        os.makedirs(_pdir, exist_ok=True)
        _partial_abs = os.path.join(_pdir, f'during_{media.id}.jpg')
        _partial_url = (_settings.MEDIA_URL
                        + os.path.relpath(_partial_abs, _settings.MEDIA_ROOT).replace('\\', '/'))
        _last_emit = [0.0]

        def _on_frame(idx, img):
            now = time.time()
            if now - _last_emit[0] < 2.0:
                return
            _last_emit[0] = now
            try:
                _cv2.imwrite(_partial_abs, img)
                publish_partial('anonymizer', media.id, f'{_partial_url}?v={idx}')
            except Exception:
                pass

        kwargs['on_frame'] = _on_frame

    written = None
    try:
        # Run the actual processing
        written = start_process(**kwargs)
    finally:
        # Stop the progress simulation
        cache.set(stop_flag, True, timeout=10)
        progress_thread.join(timeout=2)  # Wait max 2 seconds for thread to finish
        # Fin du « pendant » : la face SORTIE prend le relais ; fichier partiel retiré.
        clear_partial('anonymizer', media.id)
        if _partial_abs:
            try:
                os.remove(_partial_abs)
            except OSError:
                pass

    # Conversion de format de sortie (Phase 3 élargie)
    written = _apply_anonymizer_output_format(media, written)

    # La sortie RÉELLEMENT écrite, posée sur le média (l'ancienne part si elle n'est plus la
    # même). Le statut, le chrono, l'ETA et la notification sont l'affaire du squelette.
    try:
        media.refresh_from_db(fields=['output_file'])
    except media.__class__.DoesNotExist:
        _console(user.id, f"Warning: Media {media_id} was deleted during processing")
        raise RuntimeError("Le média a été supprimé pendant son traitement.")
    _record_output(media, written)
    return {
        'fields': {'output_file': media.output_file.name},
        'eta': (eta_key, eta_size, eta_unit),
        'label': os.path.basename(getattr(media.file, 'name', '') or '') or f"média #{media_id}",
        'console_success': f"Finished media {media_id} ✔",
        'models': used_models or None,
        'output_ref': media.output_file.name,
    }


# ----------------------------------------------------------------------
# Fonction pour lancer le traitement du média
# ----------------------------------------------------------------------
def start_process(**kwargs):
    """
    Route processing to SAM3 or YOLO based on settings.

    If use_sam3=True and sam3_prompt is provided, uses SAM3 for segmentation.
    Otherwise, uses the standard YOLO-based Anonymize class.

    Returns the path the engine ACTUALLY wrote (2026-09-27) — the task records it on the
    media; nothing is guessed from the input's name any more.
    """
    media_path = kwargs.get('media_path', 'unknown')
    use_sam3 = kwargs.get('use_sam3', False)
    sam3_prompt = kwargs.get('sam3_prompt', '')
    user_id = kwargs.get('user_id')

    # Debug: Log SAM3 routing decision
    print(f"[start_process] DEBUG: use_sam3={use_sam3} (type={type(use_sam3)})")
    print(f"[start_process] DEBUG: sam3_prompt='{sam3_prompt}' (type={type(sam3_prompt)})")
    print(f"[start_process] DEBUG: Condition check: use_sam3={bool(use_sam3)}, sam3_prompt={bool(sam3_prompt)}, strip={bool(sam3_prompt and sam3_prompt.strip())}")
    if user_id:
        _console(user_id, f"[DEBUG] use_sam3={use_sam3}, sam3_prompt='{sam3_prompt[:30] if sam3_prompt else ''}'...")

    # Route to SAM3 if enabled and prompt provided
    if use_sam3 and sam3_prompt and sam3_prompt.strip():
        print(f"[SAM3] Process started for media: {media_path} ...")

        # Validate SAM3 is available
        if not check_sam3_installed():
            error_msg = "SAM3 not installed. Falling back to YOLO."
            print(f"Warning: {error_msg}")
            if user_id:
                _console(user_id, f"Warning: {error_msg}")
            # Fall through to YOLO
        else:
            # Validate prompt
            is_valid, error = validate_sam3_prompt(sam3_prompt)
            if not is_valid:
                error_msg = f"Invalid SAM3 prompt: {error}. Falling back to YOLO."
                print(f"Warning: {error_msg}")
                if user_id:
                    _console(user_id, f"Warning: {error_msg}")
                # Fall through to YOLO
            else:
                # Use SAM3 processor
                try:
                    # Le MODÈLE porte son moteur ; le backend s'en dérive (2026-09-07). La
                    # bascule SAM3/YOLO reste une option utilisateur ; ce qu'elle désigne est
                    # le modèle `anonymizer:sam3`, et c'est lui qui donne sa classe.
                    from wama.common.backends.manager import backend_for_key
                    SAM3Processor = backend_for_key('anonymizer:sam3')
                    if SAM3Processor is None:
                        raise ImportError("anonymizer:sam3 : aucun backend résolu depuis le "
                                          "catalogue (ligne absente, ou sans moteur déclaré)")

                    if user_id:
                        _console(user_id, f"Using SAM3 with prompt: {sam3_prompt[:50]}...")

                    # Get user-specific paths for SAM3
                    source_dir = get_app_media_path('anonymizer', user_id, 'input') if user_id else None
                    dest_dir = get_app_media_path('anonymizer', user_id, 'output') if user_id else None

                    processor = SAM3Processor(source_dir=source_dir, destination_dir=dest_dir)
                    processor.load_model('auto')

                    # Progress callback → console (throttled to every 10%)
                    _last_pct = [0]
                    def _sam3_progress(pct):
                        if user_id and (pct - _last_pct[0] >= 10 or pct >= 100):
                            _last_pct[0] = pct
                            _console(user_id, f"SAM3 progress: {pct}%")

                    kwargs['progress_callback'] = _sam3_progress
                    processor.process(**kwargs)

                    if user_id:
                        _console(user_id, f"SAM3 processing complete")
                    return processor.output_path
                except ImportError as e:
                    error_msg = f"SAM3 import error: {e}. Falling back to YOLO."
                    print(f"Warning: {error_msg}")
                    if user_id:
                        _console(user_id, f"Warning: {error_msg}")
                except Exception as e:
                    error_msg = f"SAM3 processing error: {e}. Falling back to YOLO."
                    print(f"Warning: {error_msg}")
                    if user_id:
                        _console(user_id, f"Warning: {error_msg}")

    # Default: Use YOLO-based Anonymize
    print(f"[YOLO] Process started for media: {media_path} ...")
    if user_id:
        _console(user_id, f"Using YOLO with classes: {kwargs.get('classes2blur', [])}")

    # Get user-specific paths for YOLO
    source_dir = get_app_media_path('anonymizer', user_id, 'input') if user_id else None
    dest_dir = get_app_media_path('anonymizer', user_id, 'output') if user_id else None

    model = anonymize.Anonymize(source_dir=source_dir, destination_dir=dest_dir)
    anonymize.Anonymize.load_model(model, **kwargs)
    anonymize.Anonymize.process(model, **kwargs)
    return model.output_path


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

    task_ids = []
    for media in medias_list:
        # Set individual media lock before dispatching
        cache.set(f"anon_lock:media:{media.id}", True, timeout=7200)
        # Chaque média est traité dans sa propre tâche Celery
        logger.info(f"[process_user_media_batch] Launching task for media {media.id} ({media.title})")
        task = process_single_media.delay(media.id)
        task_ids.append(task.id)
        logger.info(f"[process_user_media_batch] Task {task.id} launched for media {media.id}")

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


def simulate_progress(media_id: int, start_pct: int, end_pct: int, duration_seconds: int, stop_flag_key: str):
    """
    Simule une progression graduelle de start_pct à end_pct sur duration_seconds.
    S'arrête si le flag stop_flag_key est détecté dans le cache.
    """
    if duration_seconds <= 0 or start_pct >= end_pct:
        return

    steps = min(duration_seconds, end_pct - start_pct)  # Max 1 step per second
    interval = duration_seconds / steps
    increment = (end_pct - start_pct) / steps

    current = start_pct
    for _ in range(steps):
        if cache.get(stop_flag_key, False):
            break
        time.sleep(interval)
        current += increment
        set_media_progress(media_id, int(current))

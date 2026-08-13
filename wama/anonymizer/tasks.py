import os
import logging
import threading
import time
from celery import shared_task, chord, group
from django.db import close_old_connections
from django.core.cache import cache
from django.contrib.auth import get_user_model
from .models import Media, UserSettings
from .core import anonymize
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
    engine = 'sam3' if media.use_sam3 else (media.model_to_use or 'auto')
    is_video = (media.media_type == 'video' or
                normalize_types([media.file_ext]) == ['video'])
    if is_video:
        return (f'anonymizer:vid:{engine}', float(media.duration_inSec or 1.0), 'video_sec')
    mpx = (media.width or 0) * (media.height or 0) / 1_000_000.0 or 1.0
    return (f'anonymizer:img:{engine}', mpx, 'megapixel')


def _resolve_output_rel(media):
    """Chemin MEDIA-relatif de la sortie floutée. Sortie RÉELLE = dossier output/ de
    l'utilisateur, base sans extension + _blurred* (ext vidéo coercée .mp4, variante
    _blurred_sam3) — même logique que get_blurred_media_path/download_media."""
    import glob
    import os
    from django.conf import settings
    from wama.common.utils.media_paths import get_app_media_path
    base = os.path.splitext(os.path.basename(media.file.name))[0]
    out_dir = str(get_app_media_path('anonymizer', media.user_id, 'output'))
    candidates = sorted(glob.glob(os.path.join(out_dir, base + '_blurred*')))
    if not candidates:
        return ''
    return os.path.relpath(candidates[0], settings.MEDIA_ROOT).replace(chr(92), '/')



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


def _apply_anonymizer_output_format(media):
    """Convert the blurred output to the chosen format (Phase 3 élargie).

    output_format:
        'original' → keep whatever the pipeline produced (no-op)
        'input'    → reconvert to the SOURCE file's format (e.g. pipeline
                     produced .mp4 but the user uploaded .mov → back to .mov)
        '<fmt>'    → explicit target format
    The blurred file name carries a backend suffix ({base}_blurred*{ext}),
    so we glob for it like the download view does.
    """
    import glob as _glob
    from .utils.media_utils import get_blurred_media_path

    fmt = (getattr(media, 'output_format', '') or 'original').lower()
    if fmt in ('', 'original'):
        return

    src_ext = (media.file_ext or '').lower().lstrip('.')
    target = src_ext if fmt == 'input' else fmt
    if not target:
        return

    try:
        canonical = get_blurred_media_path(media.file.name, media.file_ext, media.user_id)
        out_dir = os.path.dirname(canonical)
        base = os.path.splitext(os.path.basename(canonical))[0]
        if base.endswith('_blurred'):
            base = base[:-len('_blurred')]
        ext = os.path.splitext(canonical)[1]
        matches = _glob.glob(os.path.join(out_dir, f"{base}_blurred*{ext}"))
        if not matches:
            return
        from wama.converter.utils.inline_convert import apply_inline_conversion
        preset = getattr(media, 'output_quality', 'balanced') or 'balanced'
        for m in matches:
            if os.path.splitext(m)[1].lower().lstrip('.') == target:
                continue  # already in target format
            apply_inline_conversion(m, target, preset)
    except Exception as exc:
        logger.warning(f"[anonymizer] conversion format sortie échouée: {exc}")


# ----------------------------------------------------------------------
# Tâche principale pour traiter un média
# ----------------------------------------------------------------------
@shared_task(bind=True)
def process_single_media(self, media_id, force_individual=False):
    """
    Traite un média unique en DB, en respectant les settings utilisateur.

    force_individual : quand True (lancement individuel depuis la card), on
        utilise les paramètres de la *Media* sans condition — `MSValues_customised`
        est ignoré. Pour le batch (file d'attente globale ou "Tout lancer"),
        laisser False : le fonctionnement historique est conservé (settings
        globaux sauf si l'utilisateur a explicitement customisé le média).
    """

    close_old_connections()

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
        media = Media.objects.get(pk=media_id)

        # Garde anti-boucle-de-crash (brique COMMUNE) : message `redelivered` = worker
        # mort sans acquitter (freeze/panic machine) → ne PAS rejouer l'exécution qui
        # l'a tué. Le dedup par cache ci-dessus ne couvre PAS ce cas (cache Redis vidé
        # ou TTL expiré au reboot, et le propriétaire enregistré est ce même task_id).
        from wama.common.utils.process_control import refuse_crash_redelivery
        if refuse_crash_redelivery(self, media, error_field='error_message'):
            logger.warning(f"[anonymizer] Media #{media_id}: reprise après crash refusée — relancer manuellement.")
            return {"skipped": True, "media_id": media_id, "reason": "crash_redelivery"}

        user = media.user
        user_settings, _ = UserSettings.objects.get_or_create(user=user)

        # ── Ingest commun (WAMA_INGEST sur le modèle, brique source_ingest) :
        # télécharge source_url vers le FileField si pas encore local — idempotent. ──
        try:
            from wama.common.utils.source_ingest import ensure_local_input

            def _derive(inst, save_path, fname):
                # Métadonnées relevées sur le fichier téléchargé (mêmes champs que l'upload)
                from wama.anonymizer.views import add_media_to_db
                add_media_to_db(inst, save_path)
                inst.file_ext = os.path.splitext(save_path)[1].lstrip('.').lower()
                return ['file_ext', 'width', 'height', 'fps',
                        'duration_inSec', 'duration_inMinSec', 'media_type']

            ensure_local_input(media, console=lambda m: _console(user.id, m), derive=_derive)
        except Exception as dl_err:
            _console(user.id, f"[Batch] Erreur téléchargement : {dl_err}", level='error')
            logger.error(f"[Batch] Download failed for media {media_id}: {dl_err}")
            return {"error": "download_failed", "media_id": media_id}
        if not media.file:
            _console(user.id, f"[Batch] Média {media_id} sans fichier — ignoré", level='error')
            return {"error": "no_file", "media_id": media_id}
        # ────────────────────────────────────────────────────────────────────

        # When the user clicks "Process this media" on the card, the
        # individual settings are the explicit signal of intent — apply them
        # regardless of MSValues_customised. The historical batch path keeps
        # the original "global unless customised" semantics.
        ms_custom = bool(force_individual) or bool(media.MSValues_customised)
        if force_individual:
            logger.info(f"[process_single_media] force_individual=True → using media settings unconditionally")

        # Get precision level and use_segmentation from media or user settings
        precision_level = media.precision_level if ms_custom else user_settings.precision_level
        use_segmentation = media.use_segmentation if ms_custom else user_settings.use_segmentation

        # Get SAM3 settings from media or user settings
        use_sam3 = media.use_sam3 if ms_custom else user_settings.use_sam3
        sam3_prompt = media.sam3_prompt if ms_custom else user_settings.sam3_prompt

        # SAM3 = concepts EN → pipeline commune (§16.6) ; KIND déclaré dans app_metadata.
        # Bug d'origine : « Floute les visages » (FR) → 0 masque. process_prompt_for est fail-safe.
        if use_sam3 and sam3_prompt and sam3_prompt.strip():
            from wama.common.utils.app_metadata import process_prompt_for
            sam3_prompt = process_prompt_for('anonymizer', 'sam3_prompt', sam3_prompt,
                                             instance=media, user=user,
                                             console=lambda m: _console(user.id, f"[SAM3] {m}"))

        # Debug: Log SAM3 settings retrieval
        print(f"[process_single_media] DEBUG: ms_custom={ms_custom}")
        print(f"[process_single_media] DEBUG: media.use_sam3={media.use_sam3}, user_settings.use_sam3={user_settings.use_sam3}")
        print(f"[process_single_media] DEBUG: media.sam3_prompt='{media.sam3_prompt}', user_settings.sam3_prompt='{user_settings.sam3_prompt}'")
        print(f"[process_single_media] DEBUG: Final use_sam3={use_sam3}, sam3_prompt='{sam3_prompt}'")
        _console(user.id, f"[DEBUG] SAM3 settings: use_sam3={use_sam3}, prompt='{sam3_prompt[:30] if sam3_prompt else ''}'")

        # Determine if this is an image (interpolation doesn't apply to images)
        image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp', '.tiff', '.tif']
        is_image = media.file_ext and media.file_ext.lower() in image_extensions

        # Get interpolation setting (disabled for images)
        interpolate_detections = False if is_image else (
            media.interpolate_detections if ms_custom else user_settings.interpolate_detections
        )

        kwargs = {
            'media_path': get_input_media_path(media.file.name, user.id),
            'file_ext': media.file_ext,
            'classes2blur': media.classes2blur if ms_custom else user_settings.classes2blur,
            'blur_ratio': media.blur_ratio if ms_custom else user_settings.blur_ratio,
            'roi_enlargement': media.roi_enlargement if ms_custom else user_settings.roi_enlargement,
            'progressive_blur': media.progressive_blur if ms_custom else user_settings.progressive_blur,
            'detection_threshold': media.detection_threshold if ms_custom else user_settings.detection_threshold,
            'interpolate_detections': interpolate_detections,
            'max_interpolation_frames': media.max_interpolation_frames if ms_custom else user_settings.max_interpolation_frames,
            'show_preview': user_settings.show_preview,
            'show_boxes': user_settings.show_boxes,
            'show_labels': user_settings.show_labels,
            'show_conf': user_settings.show_conf,
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
        user_specified_model = (
            (ms_custom and media.model_to_use and media.model_to_use.strip()) or
            (hasattr(user_settings, 'model_to_use') and user_settings.model_to_use and user_settings.model_to_use.strip())
        )

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
                        user_model_abs = _gmp(user_specified_model)
                        user_classes = set(get_model_classes(user_model_abs).values())
                        requested = {c.lower() for c in kwargs['classes2blur']}
                        if requested and requested.issubset(user_classes):
                            keep_user_model = True
                    except Exception as e:
                        logger.warning(f"[ModelSelection] Could not verify user model classes: {e}")

                if keep_user_model:
                    kwargs['model_path'] = _gmp(user_specified_model)
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

                # Priority: 1) Media-specific model, 2) User's global model, 3) Auto-select
                model_to_use = None

                # Check if media has a specific model set (only if customised)
                if ms_custom and media.model_to_use and media.model_to_use.strip():
                    model_to_use = media.model_to_use.strip()
                    _console(user.id, f"Using media-specific model: {model_to_use}")
                # Otherwise check user's global setting
                elif hasattr(user_settings, 'model_to_use') and user_settings.model_to_use and user_settings.model_to_use.strip():
                    model_to_use = user_settings.model_to_use.strip()
                    _console(user.id, f"Using user's global model: {model_to_use}")

                if model_to_use:
                    kwargs['model_path'] = _gmp(model_to_use)
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

        # Vérifie si un stop a été demandé
        if cache.get(f"stop_process_{user.id}", False):
            cache.delete(f"stop_process_{user.id}")
            return {"stopped": media.id}

        # Reset progress at start + statut canonique (audit 2026-07-11)
        media.status = 'RUNNING'
        media.error_message = ''
        media.save(update_fields=['status', 'error_message'])
        _proc_t0 = time.time()
        set_media_progress(media.id, 0)
        _console(user.id, f"Start processing media {media.id} ...")

        # Load model (early progress)
        try:
            cache.set(f"media_stage_{media.id}", "loading_model", timeout=3600)
            set_media_progress(media.id, 5)
            _console(user.id, f"Loading model for media {media.id} ...")
        except Exception:
            pass

        # Run process with simulated progress
        set_media_progress(media.id, 10)
        _console(user.id, f"Running anonymization for media {media.id} ...")

        # Durée estimée pour la simulation de progression : ETA apprise (EMA par
        # clé modèle/taille) avec repli sur l'a-priori historique 60 s vidéo / 10 s image.
        is_video = normalize_types([media.file_ext]) == ['video']
        estimated_duration = 60 if is_video else 10
        try:
            from wama.model_manager.services.eta_estimator import estimate
            _k, _s, _u = anonymizer_eta_key_size(media)
            _est = estimate(_k, size=_s, unit=_u, model_loaded=True,
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

        try:
            # Run the actual processing
            start_process(**kwargs)
        finally:
            # Stop the progress simulation
            cache.set(stop_flag, True, timeout=10)
            progress_thread.join(timeout=2)  # Wait max 2 seconds for thread to finish

        # Conversion de format de sortie (Phase 3 élargie)
        _apply_anonymizer_output_format(media)

        # Marque le média comme traité
        try:
            media.refresh_from_db()
            media.status = 'SUCCESS'
            media.processing_seconds = time.time() - _proc_t0
            media.output_file = _resolve_output_rel(media)
            media.save(update_fields=["status", "processing_seconds", "output_file"])
            set_media_progress(media.id, 100)
            # ETA auto-apprenante : consigne le temps réel (même clé que estimate)
            try:
                from wama.model_manager.services.eta_estimator import record_run
                _k, _s, _u = anonymizer_eta_key_size(media)
                record_run(_k, size=_s, unit=_u,
                           process_seconds=media.processing_seconds, load_seconds=None)
            except Exception:
                pass
            _console(user.id, f"Finished media {media.id} ✔")
            try:
                from wama.common.utils.notifications import notify_job
                notify_job(user, 'Anonymizer', os.path.basename(getattr(media.file, 'name', '') or '') or f"média #{media.id}", True)
            except Exception:
                pass
        except media.__class__.DoesNotExist:
            _console(user.id, f"Warning: Media {media.id} was deleted during processing")
            return {"error": "Media was deleted", "media_id": media_id}
        finally:
            # Release dedup locks
            cache.delete(f"anon_lock:media:{media_id}")
            cache.delete(f"anon_task_owner:media:{media_id}")

        return {"processed": media.id}

    except Exception as e:
        print(f"Erreur sur media {media_id}: {e}")
        try:
            media.refresh_from_db()
            media.status = 'FAILURE'
            media.error_message = str(e)[:2000]
            media.save(update_fields=['status', 'error_message'])
        except Exception:
            pass
        try:
            _console(user.id, f"Error on media {media_id}: {e}")
        except Exception:
            pass
        # Release dedup locks on error
        cache.delete(f"anon_lock:media:{media_id}")
        cache.delete(f"anon_task_owner:media:{media_id}")
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(user, 'Anonymizer', f"média #{media_id}", False, detail=str(e))
        except Exception:
            pass
        return {"error": str(e), "media_id": media_id}


# ----------------------------------------------------------------------
# Fonction pour lancer le traitement du média
# ----------------------------------------------------------------------
def start_process(**kwargs):
    """
    Route processing to SAM3 or YOLO based on settings.

    If use_sam3=True and sam3_prompt is provided, uses SAM3 for segmentation.
    Otherwise, uses the standard YOLO-based Anonymize class.
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
                    from .core.sam3_processor import SAM3Processor

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
                    return
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

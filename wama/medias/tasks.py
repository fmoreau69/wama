import os
from celery import shared_task
from django.db import close_old_connections
from django.core.cache import cache
from django.contrib.auth import get_user_model
from .models import Media, UserSettings
from anonymizer import anonymize
from .utils.media_utils import get_input_media_path
from .utils.yolo_utils import get_model_path

# ----------------------------------------------------------------------
# Tâche principale pour traiter un média
# ----------------------------------------------------------------------
@shared_task(bind=True)
def process_single_media(self, media_id):
    """
    Traite un média unique en DB, en respectant les settings utilisateur.
    """

    close_old_connections()

    try:
        media = Media.objects.get(pk=media_id)
        user = media.user
        user_settings, _ = UserSettings.objects.get_or_create(user=user)
        ms_custom = media.MSValues_customised

        kwargs = {
            'media_path': get_input_media_path(media.file.name),
            'file_ext': media.file_ext,
            'classes2blur': media.classes2blur if ms_custom else user_settings.classes2blur,
            'blur_ratio': media.blur_ratio if ms_custom else user_settings.blur_ratio,
            'roi_enlargement': media.roi_enlargement if ms_custom else user_settings.roi_enlargement,
            'progressive_blur': media.progressive_blur if ms_custom else user_settings.progressive_blur,
            'detection_threshold': media.detection_threshold if ms_custom else user_settings.detection_threshold,
            'show_preview': user_settings.show_preview,
            'show_boxes': user_settings.show_boxes,
            'show_labels': user_settings.show_labels,
            'show_conf': user_settings.show_conf,
        }

        if any(c in kwargs['classes2blur'] for c in ['face', 'plate']):
            kwargs['model_path'] = get_model_path("yolov8m_faces&plates_720p.pt")

        # Vérifie si un stop a été demandé
        if cache.get(f"stop_process_{user.id}", False):
            cache.delete(f"stop_process_{user.id}")
            return {"stopped": media.id}

        # Reset progress at start
        set_media_progress(media.id, 0)

        # Load model (early progress)
        try:
            cache.set(f"media_stage_{media.id}", "loading_model", timeout=3600)
            set_media_progress(media.id, 5)
        except Exception:
            pass

        # Run process (we cannot hook internal progress; mark mid-progress)
        set_media_progress(media.id, 10)
        start_process(**kwargs)

        # Marque le média comme traité
        media.processed = True
        media.save(update_fields=["processed"])
        set_media_progress(media.id, 100)

        return {"processed": media.id}

    except Exception as e:
        print(f"Erreur sur media {media_id}: {e}")
        # mark as failed state (keep last known progress)
        return {"error": str(e), "media_id": media_id}


# ----------------------------------------------------------------------
# Fonction pour lancer le traitement du média
# ----------------------------------------------------------------------
def start_process(**kwargs):
    print(f"Process started for media: {kwargs['media_path']} ...")
    model = anonymize.Anonymize()
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
    close_old_connections()

    User = get_user_model()
    user = User.objects.get(pk=user_id)
    medias_list = Media.objects.filter(user=user, processed=False)

    if not medias_list.exists():
        return {"processed": 0}

    task_ids = []
    for media in medias_list:
        # Chaque média est traité dans sa propre tâche Celery
        task = process_single_media.delay(media.id)
        task_ids.append(task.id)

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

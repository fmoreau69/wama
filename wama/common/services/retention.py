"""
Rétention des médias — purge automatique des sorties au-delà de la durée choisie par l'utilisateur
(`UserProfile.media_retention_days`, bornée par `settings.WAMA_MAX_RETENTION_DAYS`).

Déclaratif + introspection : on enregistre seulement le modèle (et d'éventuels champs de chemins JSON) ;
les **FileField/ImageField sont découverts automatiquement** et supprimés via `safe_delete_file`
(qui respecte les références partagées). Puis l'enregistrement est supprimé. Fail-safe, idempotent.

Pré-avis : `upcoming_expirations(days)` liste ce qui expirera bientôt (pour notifier — câblage séparé).
"""
import logging
import os

from django.apps import apps as django_apps
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)

# Modèles soumis à rétention. Défauts : date='created_at', user='user'. `path_lists` = champs
# contenant une liste de chemins de fichiers hors FileField (ex. imager.generated_images).
# `pin` (optionnel) = champ booléen d'épinglage/favori : les enregistrements épinglés sont EXEMPTÉS
# de la purge. (Aucun modèle n'a de champ pin pour l'instant ; ajouter ex. 'pin': 'is_pinned'.)
RETENTION_MODELS = [
    {'model': 'imager.ImageGeneration', 'path_lists': ['generated_images']},
    {'model': 'enhancer.Enhancement'},
    {'model': 'enhancer.AudioEnhancement'},
    {'model': 'composer.ComposerGeneration'},
    {'model': 'synthesizer.VoiceSynthesis'},
    {'model': 'transcriber.Transcript'},
]


def _delete_path(path):
    """Supprime un fichier (absolu ou relatif à MEDIA_ROOT). Fail-safe."""
    try:
        if not path:
            return
        if not os.path.isabs(path):
            from django.conf import settings
            path = os.path.join(settings.MEDIA_ROOT, path)
        if os.path.isfile(path):
            os.remove(path)
    except Exception as e:  # pragma: no cover
        logger.debug("retention: échec suppression chemin %s : %s", path, e)


def _purge_instance(obj, path_lists):
    from wama.common.utils.queue_duplication import safe_delete_file
    # 1) FileField/ImageField découverts automatiquement → safe_delete (respecte refs partagées).
    for f in obj._meta.fields:
        if isinstance(f, models.FileField):  # ImageField hérite de FileField
            try:
                if getattr(obj, f.name):
                    safe_delete_file(obj, f.name)
            except Exception as e:  # pragma: no cover
                logger.debug("retention: safe_delete %s.%s a échoué : %s", obj, f.name, e)
    # 2) Champs de chemins (listes JSON) → suppression disque directe.
    for pl in path_lists or []:
        val = getattr(obj, pl, None)
        if isinstance(val, (list, tuple)):
            for p in val:
                _delete_path(p if isinstance(p, str) else (p or {}).get('path') if isinstance(p, dict) else None)
    # 3) Supprimer l'enregistrement.
    obj.delete()


def _users_with_retention():
    """{user_id: effective_days} pour les users concernés (plafond global inclus)."""
    from django.conf import settings
    from wama.accounts.models import UserProfile
    cap = int(getattr(settings, 'WAMA_MAX_RETENTION_DAYS', 0) or 0)
    out = {}
    qs = UserProfile.objects.all() if cap else UserProfile.objects.filter(media_retention_days__gt=0)
    for p in qs.select_related('user'):
        days = p.effective_retention_days()
        if days and days > 0:
            out[p.user_id] = days
    return out


def purge_expired_media(dry_run=False):
    """
    Purge les médias expirés de tous les modèles enregistrés, par utilisateur (selon sa rétention).
    Retourne {'deleted': n, 'by_model': {...}, 'users': k, 'dry_run': bool}.
    """
    retentions = _users_with_retention()
    summary = {'deleted': 0, 'by_model': {}, 'users': len(retentions), 'dry_run': dry_run}
    if not retentions:
        return summary

    now = timezone.now()
    for entry in RETENTION_MODELS:
        try:
            Model = django_apps.get_model(entry['model'])
        except Exception:
            continue
        date_field = entry.get('date', 'created_at')
        user_field = entry.get('user', 'user')
        path_lists = entry.get('path_lists', [])
        pin_field = entry.get('pin')
        count = 0
        for user_id, days in retentions.items():
            cutoff = now - timezone.timedelta(days=days)
            qs = Model.objects.filter(**{f'{user_field}_id': user_id, f'{date_field}__lt': cutoff})
            if pin_field:  # exempter les éléments épinglés/favoris
                qs = qs.exclude(**{pin_field: True})
            if dry_run:
                count += qs.count()
                continue
            for obj in list(qs):
                try:
                    _purge_instance(obj, path_lists)
                    count += 1
                except Exception as e:  # pragma: no cover
                    logger.warning("retention: échec purge %s #%s : %s", entry['model'], obj.pk, e)
        if count:
            summary['by_model'][entry['model']] = count
            summary['deleted'] += count
    return summary


def upcoming_expirations(days_ahead):
    """
    {user_id: [(model_label, count), ...]} des médias expirant dans <= days_ahead jours.
    Pour pré-avis email (câblage notification séparé).
    """
    retentions = _users_with_retention()
    now = timezone.now()
    out = {}
    for entry in RETENTION_MODELS:
        try:
            Model = django_apps.get_model(entry['model'])
        except Exception:
            continue
        date_field = entry.get('date', 'created_at')
        user_field = entry.get('user', 'user')
        for user_id, days in retentions.items():
            soon = now - timezone.timedelta(days=days) + timezone.timedelta(days=days_ahead)
            still = now - timezone.timedelta(days=days)
            n = Model.objects.filter(**{
                f'{user_field}_id': user_id,
                f'{date_field}__lt': soon, f'{date_field}__gte': still,
            }).count()
            if n:
                out.setdefault(user_id, []).append((entry['model'], n))
    return out

"""
Rétention des médias — purge automatique des sorties au-delà de la durée choisie par l'utilisateur
(`UserProfile.media_retention_days`, bornée par `settings.WAMA_MAX_RETENTION_DAYS`).

Déclaratif + introspection : on enregistre seulement le modèle (et d'éventuels champs de chemins JSON) ;
les **FileField/ImageField sont découverts automatiquement** et EFFACÉS via `safe_delete_file`
(propriété + partage respectés : un fichier qu'une autre card porte encore reste). Puis
l'enregistrement est supprimé. Fail-safe, idempotent.

⚠ LA RÉTENTION EFFACE, et c'est voulu (Fabien, 2026-10-01) : *« si l'utilisateur applique une
période de rétention qui n'est pas nulle, c'est qu'il souhaite la suppression des fichiers au bout
de la durée qu'il indique. Il n'est pas question de retirer ce fonctionnement. »* La durée choisie
EST le consentement, et le pré-avis (J-N) prévient. Du 2026-09-30 au 2026-10-01 la purge LIBÉRAIT
au lieu d'effacer (`4e441a80`) — une lecture trop large de la décision D34, qui ne visait que le
retrait d'une card par l'utilisateur. Une rétention INFINIE (aucune durée) ne purge rien : c'est
là que `released_files` prévient des fichiers inutilisés.

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


def _relative_to_media(path):
    """Chemin relatif à MEDIA_ROOT (la forme que `owns_file` compare) ; '' s'il est HORS de
    MEDIA_ROOT — et alors `owns_file` refuse, ce qui est voulu : la purge ne sort jamais de là."""
    from django.conf import settings
    if not os.path.isabs(path):
        return path.replace('\\', '/')
    root = os.path.abspath(settings.MEDIA_ROOT)
    absolute = os.path.abspath(path)
    if os.path.commonpath([root, absolute]) != root:
        return ''
    return os.path.relpath(absolute, root).replace('\\', '/')


def _delete_path(rel):
    """Efface un fichier relatif à MEDIA_ROOT et oublie sa note de fichier libéré. Fail-safe."""
    from django.conf import settings
    from wama.common.models import ReleasedFile
    try:
        path = os.path.join(settings.MEDIA_ROOT, rel)
        if os.path.isfile(path):
            os.remove(path)
        ReleasedFile.objects.filter(path=rel).delete()
    except Exception as e:  # pragma: no cover
        logger.debug("retention: suppression %s a échoué : %s", rel, e)


def _purge_instance(obj, path_lists):
    from wama.common.utils.queue_duplication import owns_file, safe_delete_file
    from wama.common.services.released_files import still_used
    # 1) FileField/ImageField découverts automatiquement → EFFACÉS (propriété + partage respectés).
    for f in obj._meta.fields:
        if isinstance(f, models.FileField):  # ImageField hérite de FileField
            try:
                if getattr(obj, f.name):
                    safe_delete_file(obj, f.name)
            except Exception as e:  # pragma: no cover
                logger.debug("retention: suppression %s.%s a échoué : %s", obj, f.name, e)
    # 2) Champs de chemins (listes JSON) → seulement ce qui vit CHEZ l'app (`owns_file`, la même
    #    règle que pour les FileField) et que rien d'autre ne porte. Jusqu'au 2026-09-22 ces listes
    #    étaient effacées sans aucune règle : un chemin référencé hors du domicile de l'app y
    #    passait comme le reste.
    for pl in path_lists or []:
        val = getattr(obj, pl, None)
        if isinstance(val, (list, tuple)):
            for p in val:
                path = p if isinstance(p, str) else (p or {}).get('path') if isinstance(p, dict) else None
                rel = _relative_to_media(path) if path else ''
                if rel and owns_file(obj, rel) and not still_used(rel):
                    _delete_path(rel)
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


def retention_days_for(user):
    """Rétention EFFECTIVE d'un utilisateur, en jours (plafond global inclus) ; 0 = aucune."""
    return _users_with_retention().get(getattr(user, 'pk', None), 0)


def expirations_for(user, start, end):
    """Médias de `user` qui EXPIRENT dans `[start, end)` : `[{app, model, id, expires_at}]`.

    Même règle que la purge (`date + rétention`, épinglés exemptés) — c'est ce qui les rend
    affichables au calendrier sans deuxième définition de l'expiration (2026-09-28).
    """
    days = retention_days_for(user)
    if not days:
        return []
    delta = timezone.timedelta(days=days)
    out = []
    for entry in RETENTION_MODELS:
        try:
            Model = django_apps.get_model(entry['model'])
        except Exception:
            continue
        date_field = entry.get('date', 'created_at')
        qs = Model.objects.filter(**{
            f"{entry.get('user', 'user')}_id": user.pk,
            f'{date_field}__gte': start - delta, f'{date_field}__lt': end - delta,
        })
        if entry.get('pin'):
            qs = qs.exclude(**{entry['pin']: True})
        for pk, created in qs.values_list('pk', date_field)[:1000]:
            out.append({'app': Model._meta.app_label, 'model': entry['model'], 'id': pk,
                        'expires_at': created + delta})
    return out


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

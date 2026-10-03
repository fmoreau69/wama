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
#
# ⚠ Les DIX apps de file y sont depuis le 2026-10-02 (D9, décision de Fabien) : cinq en étaient
# absentes (anonymizer, avatarizer, converter, describer, reader) — pour elles, la durée choisie
# au profil ne valait rien, sans que rien ne le dise. `anonymizer.Media` date sa ligne par
# `uploaded_at` (il n'a pas de `created_at`).
RETENTION_MODELS = [
    # `native_outputs` : les fichiers d'origine gardés par la brique de sortie
    # (`common.models.NativeOutputsMixin`) — une app qui hérite le champ le déclare ICI.
    {'model': 'imager.ImageGeneration', 'path_lists': ['generated_images', 'native_outputs']},
    {'model': 'enhancer.Enhancement', 'path_lists': ['native_outputs']},
    {'model': 'enhancer.AudioEnhancement', 'path_lists': ['native_outputs']},
    {'model': 'composer.ComposerGeneration', 'path_lists': ['native_outputs']},
    {'model': 'synthesizer.VoiceSynthesis', 'path_lists': ['native_outputs']},
    {'model': 'transcriber.Transcript'},
    {'model': 'anonymizer.Media', 'date': 'uploaded_at', 'path_lists': ['native_outputs']},
    {'model': 'avatarizer.AvatarJob'},
    {'model': 'converter.ConversionJob'},
    {'model': 'describer.Description'},
    {'model': 'reader.ReadingItem'},
]


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


def _purge_instance(obj):
    from wama.common.utils.file_references import is_referenced_elsewhere, listed_paths
    from wama.common.utils.queue_duplication import owns_file, safe_delete_file
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
    #    passait comme le reste. Les entrées se lisent par `file_references.listed_paths`, comme
    #    au retrait d'une card (`queue_duplication.release_card_files`) — une lecture, deux gestes.
    #    L'index des références lit les listes (2026-10-02) : l'élément purgé s'EXCLUT lui-même,
    #    sans quoi sa propre liste le ferait passer pour encore utilisé.
    for field, rel in listed_paths(obj):
        if owns_file(obj, rel) and not is_referenced_elsewhere(
                rel, label=obj._meta.label, pk=obj.pk, field=field):
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
                    _purge_instance(obj)
                    count += 1
                except Exception as e:  # pragma: no cover
                    logger.warning("retention: échec purge %s #%s : %s", entry['model'], obj.pk, e)
        if count:
            summary['by_model'][entry['model']] = count
            summary['deleted'] += count
    return summary


def retention_days_by_user():
    """{user_id: jours} de tous les utilisateurs à rétention FINIE (plafond global inclus) — lu une
    fois par passe par ceux qui traitent tous les utilisateurs (`released_files`)."""
    return _users_with_retention()


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


# ── Le DOSSIER TEMPORAIRE (`users/<id>/temp`) — le second réglage (2026-10-02, D9) ───────────────
#
# Décision de Fabien : deux réglages au profil, pas trois — les cards et leurs fichiers (ci-dessus),
# et le dossier temporaire (ici) ; la médiathèque n'a PAS de durée. Défaut 0 = illimité : le temp
# sert aussi de rangement personnel (médias de test, de présentation). Ce que la purge respecte :
#   - un fichier qu'une card ou un asset DÉSIGNE (`file_references.is_referenced_elsewhere`, listes de
#     chemins comprises) n'est jamais supprimé — le pointage (D23) rend ce cas courant ;
#   - l'âge est celui de la DERNIÈRE MODIFICATION du fichier (un fichier remplacé repart à zéro) ;
#   - le pré-avis (J-N) prévient avant, comme pour les cards.

def _temp_retentions():
    """{user_id: jours} des utilisateurs dont le dossier temporaire a une durée (plafond inclus)."""
    from django.conf import settings
    from wama.accounts.models import UserProfile
    cap = int(getattr(settings, 'WAMA_MAX_RETENTION_DAYS', 0) or 0)
    qs = UserProfile.objects.all() if cap else UserProfile.objects.filter(temp_retention_days__gt=0)
    out = {}
    for p in qs:
        days = p.effective_temp_retention_days()
        if days and days > 0:
            out[p.user_id] = days
    return out


def _temp_files(user_id):
    """[(chemin absolu, chemin relatif à MEDIA_ROOT, date de modification)] du temp d'un utilisateur."""
    from pathlib import Path
    from django.conf import settings
    root = Path(settings.MEDIA_ROOT) / f'users/{user_id}/temp'
    if not root.is_dir():
        return []
    from datetime import datetime
    from datetime import timezone as dt_timezone
    out = []
    for path in root.rglob('*'):
        if path.is_file():
            rel = path.relative_to(settings.MEDIA_ROOT).as_posix()
            out.append((path, rel, datetime.fromtimestamp(path.stat().st_mtime, tz=dt_timezone.utc)))
    return out


def _expiring_temp(user_id, cutoff):
    """Les fichiers du temp modifiés avant `cutoff` et que RIEN ne désigne."""
    from wama.common.utils.file_references import is_referenced_elsewhere
    return [(path, rel) for path, rel, mtime in _temp_files(user_id)
            if mtime < cutoff and not is_referenced_elsewhere(rel)]


def purge_expired_temp(dry_run=False):
    """Supprime, pour chaque utilisateur à durée finie, les fichiers de son dossier temporaire plus
    vieux que cette durée et que rien ne désigne. Rend {'deleted', 'users', 'dry_run'}."""
    retentions = _temp_retentions()
    summary = {'deleted': 0, 'users': len(retentions), 'dry_run': dry_run}
    now = timezone.now()
    for user_id, days in retentions.items():
        for _path, rel in _expiring_temp(user_id, now - timezone.timedelta(days=days)):
            if not dry_run:
                _delete_path(rel)
            summary['deleted'] += 1
    return summary


def upcoming_temp_expirations(days_ahead):
    """{user_id: n} des fichiers du temp qui seront supprimés dans <= days_ahead jours (pré-avis)."""
    from wama.common.utils.file_references import is_referenced_elsewhere
    out = {}
    now = timezone.now()
    for user_id, days in _temp_retentions().items():
        soon = now - timezone.timedelta(days=days) + timezone.timedelta(days=days_ahead)
        still = now - timezone.timedelta(days=days)
        n = sum(1 for _path, rel, mtime in _temp_files(user_id)
                if still <= mtime < soon and not is_referenced_elsewhere(rel))
        if n:
            out[user_id] = n
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

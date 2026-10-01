"""Fichiers LIBÉRÉS — plus aucune card ne les appelle ; on PRÉVIENT, on ne supprime pas.

DÉCISION DE FABIEN (2026-09-30) : *« Les cards doivent référencer le fichier. Si une card est
retirée, on vérifie si une autre card porte aussi le fichier. »* Puis, sur la suppression : *« prévenir
l'utilisateur que le fichier devient orphelin à la suppression d'une card ; sinon une notification
lorsqu'un fichier reste inutilisé trop longtemps, et l'afficher dans les infos du fichier, en rouge.
La suppression est un geste explicite de l'utilisateur, mais il est prévenu. »*

AVANT : retirer une card EFFAÇAIT son fichier sur-le-champ (`safe_delete_file`) dès qu'aucune autre
ligne ne le portait — sans le dire. DÉSORMAIS :
  1. retirer une card (supprimer, tout effacer, lot) LIBÈRE ses fichiers : ils restent
     sur le disque, une ligne `ReleasedFile` note qui, quand, d'où (`release_path`) ;
  2. la confirmation de suppression le DEMANDE d'avance, case décochée (`freed_by` → aperçu,
     puis `delete_released` ou `keep_released` sur ces chemins — complément du 2026-10-01) ; un
     retrait qui ne passe pas par elle (assistant, `data-confirm="false"`) est ANNONCÉ une fois à la page qui
     suit (`take_unannounced` → `released-files.js`) ;
  3. un fichier encore inutilisé après `UNUSED_NOTICE_DAYS` fait l'objet d'UNE notification
     groupée (`notify_long_unused`, tâche quotidienne) ;
  4. ses informations dans le gestionnaire de fichiers le disent en rouge (`status_of`).
Un fichier libéré qu'une card reprend (redésigné, renvoyé vers une app) n'est plus « inutilisé » :
chaque lecture REVÉRIFIE les références (`file_references.is_referenced_elsewhere`) et oublie la
ligne — l'état écrit n'est jamais cru sur parole.

⚠ Ce qui reste un EFFACEMENT réel, hors de ce module : le résultat qu'une card RÉGÉNÈRE (relance :
l'ancien rendu est remplacé par le sien, `safe_delete_file`), les fichiers de travail internes d'une
tâche, la suppression VOULUE d'un asset de la médiathèque ou d'un fichier du gestionnaire — et la
PURGE DE RÉTENTION : une durée choisie par l'utilisateur vaut consentement à la suppression
(Fabien, 2026-10-01 ; `services/retention.py`). Ce module sert donc surtout la rétention INFINIE.
"""
import logging
import os

from django.utils import timezone

logger = logging.getLogger(__name__)

#: Rétention INFINIE : au-delà, un fichier libéré et toujours inutilisé fait l'objet d'une
#: notification. Réglable par `settings.WAMA_UNUSED_FILE_NOTICE_DAYS`. Avec une rétention FINIE,
#: c'est la durée choisie qui s'applique (pré-avis, puis suppression — `purge_expired_released`).
UNUSED_NOTICE_DAYS = 30


def _norm(path) -> str:
    return str(path or '').replace('\\', '/').strip().lstrip('/')


def still_used(path) -> bool:
    """Une card (ou un asset de médiathèque) appelle-t-elle ce fichier ? — mesuré, jamais supposé."""
    from wama.common.utils.file_references import is_referenced_elsewhere
    return is_referenced_elsewhere(_norm(path))


def release_path(path, user, origin: str = ''):
    """Note que plus aucune card n'appelle `path` (relatif à MEDIA_ROOT). Ne touche pas au fichier.
    Rend la ligne `ReleasedFile`, ou None (chemin vide, fichier absent). Ne lève jamais."""
    from django.conf import settings
    from wama.common.models import ReleasedFile
    path = _norm(path)
    try:
        if not path or not os.path.isfile(os.path.join(settings.MEDIA_ROOT, path)):
            return None
        row, _ = ReleasedFile.objects.update_or_create(
            path=path, defaults={'user': user if getattr(user, 'pk', None) else None,
                                 'origin': (origin or '')[:200], 'released_at': timezone.now(),
                                 'announced_at': None, 'notified_at': None})
        return row
    except Exception as exc:  # pragma: no cover
        logger.warning('[released_files] %s non noté : %s', path, exc)
        return None


def _forget_if_used(rows):
    """Les lignes dont le fichier est REPRIS par une card (ou a disparu) sont oubliées ; rend le reste."""
    from django.conf import settings
    alive = []
    for row in rows:
        if still_used(row.path) or not os.path.isfile(os.path.join(settings.MEDIA_ROOT, row.path)):
            row.delete()
        else:
            alive.append(row)
    return alive


def _as_dict(row) -> dict:
    return {'id': row.pk, 'path': row.path, 'name': os.path.basename(row.path),
            'origin': row.origin, 'released_at': row.released_at.isoformat()}


def origin_label(origin: str) -> str:
    """L'origine LISIBLE d'un fichier libéré : « Composer · fichier de lot » plutôt que la clé
    technique `composer.ComposerBatch#151 · batch_file` (qui reste stockée, pour la trace)."""
    from django.apps import apps as django_apps
    try:
        target, field = [part.strip() for part in origin.split('·', 1)]
        label = target.split('#', 1)[0]
        model = django_apps.get_model(label)
        app = django_apps.get_app_config(model._meta.app_label).verbose_name
        name = field.split(' ')[0]
        role = ('fichier de lot' if 'batch' in name
                else 'sortie' if any(k in name for k in ('output', 'result', 'generated'))
                else 'entrée' if any(k in name for k in ('input', 'source', 'reference', 'text_file'))
                else str(model._meta.get_field(name).verbose_name))
        return f'{app} · {role}'
    except Exception:
        return origin or ''


def list_unused(user) -> dict:
    """TOUS les fichiers inutilisés de `user` — la liste de la médiathèque (onglet « Inutilisés »,
    décision de Fabien du 2026-10-01 : *« la médiathèque est l'endroit où l'on gère ses médias »*),
    où il les supprime un par un ou par sélection. Ne marque rien comme annoncé (c'est une lecture),
    mais oublie ceux qu'une card a repris ou qui ont disparu : la liste ne montre que du vrai.
    Rend `{'files': [...], 'total_size': octets}`, le plus anciennement inutilisé d'abord."""
    from datetime import timedelta
    from django.conf import settings
    from wama.common.models import ReleasedFile
    from wama.common.services.retention import retention_days_for
    now = timezone.now()
    days = retention_days_for(user)
    files, total = [], 0
    for row in _forget_if_used(ReleasedFile.objects.filter(user=user).order_by('released_at')):
        try:
            size = os.path.getsize(os.path.join(settings.MEDIA_ROOT, row.path))
        except OSError:
            size = 0
        total += size
        # Rétention FINIE : la date à laquelle il partira (au plus tôt après le pré-avis).
        deletes_on = (max(row.released_at + timedelta(days=days),
                          (row.notified_at or now) + timedelta(days=min(pre_notice_days(), days)))
                      if days else None)
        files.append({**_as_dict(row), 'size': size, 'unused_days': (now - row.released_at).days,
                      'origin_label': origin_label(row.origin),
                      'deletes_on': deletes_on.date().isoformat() if deletes_on else None})
    return {'files': files, 'total_size': total, 'retention_days': days}


def count_unused(user) -> int:
    """Le compte affiché sur l'onglet — lu sur les lignes, sans revérifier chaque fichier (la liste,
    elle, revérifie à l'ouverture)."""
    from wama.common.models import ReleasedFile
    return ReleasedFile.objects.filter(user=user).count() if getattr(user, 'pk', None) else 0


def take_unannounced(user) -> list:
    """Les fichiers libérés de `user` pas encore annoncés — et ils le sont désormais (une fois)."""
    from wama.common.models import ReleasedFile
    rows = _forget_if_used(ReleasedFile.objects.filter(user=user, announced_at__isnull=True))
    ReleasedFile.objects.filter(pk__in=[r.pk for r in rows]).update(announced_at=timezone.now())
    return [_as_dict(r) for r in rows]


def freed_by(instances) -> list:
    """AVANT de retirer `instances` (une card, un lot et ses éléments, toute une file) : les
    fichiers qu'elles POSSÈDENT et que plus rien d'autre ne désignera ensuite — ceux que le retrait
    va libérer, donc ceux sur lesquels on peut demander « supprimer aussi le fichier ? ».

    Décision de Fabien du 2026-10-01 (complète D34) : *« à la suppression de la dernière card
    utilisant un même média, on demande à l'utilisateur s'il veut supprimer le média »* — case
    DÉCOCHÉE par défaut. Mêmes règles que `release_card_file` (propriété par `owns_file`, partage
    dans TOUT le dépôt), mais sur l'ENSEMBLE retiré : un fichier partagé entre deux cards d'un même
    lot est libéré quand le lot part, alors que la question posée card par card dirait « partagé ».
    """
    from django.conf import settings
    from django.db import models as dj_models
    from wama.common.utils.file_references import referenced_outside
    from wama.common.utils.queue_duplication import owns_file
    inside, candidates = set(), set()
    for obj in instances:
        inside.add((obj._meta.label, obj.pk))
        for f in obj._meta.concrete_fields:
            if not isinstance(f, dj_models.FileField):
                continue
            name = _norm(getattr(getattr(obj, f.name, None), 'name', '') or '')
            if (name and owns_file(obj, name)
                    and os.path.isfile(os.path.join(settings.MEDIA_ROOT, name))):
                candidates.add(name)
    return sorted(candidates - referenced_outside(candidates, inside))


def _rows_for(user, ids=None, paths=None):
    from wama.common.models import ReleasedFile
    rows = ReleasedFile.objects.filter(user=user)
    if paths:
        return rows.filter(path__in=[_norm(p) for p in paths])
    return rows.filter(pk__in=list(ids or []))


def keep_released(user, ids=None, paths=None) -> int:
    """L'utilisateur a choisi de GARDER (case laissée décochée) : rien n'est supprimé, et ces
    fichiers ne sont plus annoncés — la question a déjà été posée. Ils restent signalés dans leurs
    informations et par la notification « inutilisé depuis… »."""
    return _rows_for(user, ids, paths).filter(announced_at__isnull=True) \
        .update(announced_at=timezone.now())


def delete_released(user, ids=None, paths=None) -> dict:
    """LE geste explicite : supprimer des fichiers libérés (désignés par leur ligne ou leur chemin).
    Chacun est REVÉRIFIÉ — appartenance, toujours inutilisé — juste avant ; un fichier repris par
    une card entre-temps est GARDÉ."""
    from django.conf import settings
    deleted, kept = [], []
    for row in _rows_for(user, ids, paths):
        if still_used(row.path):
            kept.append(row.path)
            row.delete()
            continue
        try:
            os.remove(os.path.join(settings.MEDIA_ROOT, row.path))
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning('[released_files] suppression de %s impossible : %s', row.path, exc)
            kept.append(row.path)
            continue
        deleted.append(row.path)
        row.delete()
    return {'deleted': deleted, 'kept': kept}


def status_of(path) -> dict:
    """Ce que les informations d'un fichier doivent dire de son USAGE (gestionnaire de fichiers) :
    `{'cards': n, 'unused': bool, 'unused_since': iso | None, 'unused_days': int | None}`.
    `unused_since` n'est connu que pour un fichier LIBÉRÉ par une card ; un fichier jamais utilisé
    est dit inutilisé, sans date."""
    from wama.common.models import ReleasedFile
    from wama.common.utils.file_references import usage
    path = _norm(path)
    count = usage(path)['count']
    row = ReleasedFile.objects.filter(path=path).first()
    if count and row is not None:
        row.delete()                                          # repris : plus orphelin
        row = None
    since = row.released_at if row is not None else None
    return {'cards': count, 'unused': not count,
            'unused_since': since.isoformat() if since else None,
            'unused_days': (timezone.now() - since).days if since else None}


def pre_notice_days() -> int:
    """Combien de jours AVANT sa suppression un fichier inutilisé est annoncé — le même pré-avis que
    les médias des cards (`settings.WAMA_RETENTION_NOTICE_DAYS`, 3 par défaut), au moins un jour."""
    from django.conf import settings
    return max(1, int(getattr(settings, 'WAMA_RETENTION_NOTICE_DAYS', 3) or 3))


def unused_notice_days() -> int:
    """Rétention INFINIE : au-delà, un fichier inutilisé fait l'objet d'UNE notification."""
    from django.conf import settings
    return int(getattr(settings, 'WAMA_UNUSED_FILE_NOTICE_DAYS', UNUSED_NOTICE_DAYS) or UNUSED_NOTICE_DAYS)


def _names(rows) -> str:
    names = ', '.join(os.path.basename(r.path) for r in rows[:5])
    return names + (f' (et {len(rows) - 5} autre(s))' if len(rows) > 5 else '')


def notify_long_unused(now=None) -> int:
    """UNE notification par utilisateur pour ses fichiers inutilisés, jamais deux fois pour le même
    fichier. Rend le nombre de notifications créées. Deux régimes (décisions de Fabien, 2026-10-01) :

      * rétention INFINIE — au-delà de `unused_notice_days()`, « inutilisés depuis… » : rien n'est
        supprimé sans lui, il fait le ménage dans la médiathèque (onglet « Inutilisés ») ;
      * rétention FINIE de N jours — `pre_notice_days()` avant le terme, « seront supprimés le… » :
        la durée qu'il a choisie s'applique aussi aux fichiers qu'il a gardés, mais il est PRÉVENU
        (il peut avoir oublié sa durée) et « Garder » leur redonne N jours (`renew_released`).
    """
    from collections import defaultdict
    from datetime import timedelta
    from wama.common.models import ReleasedFile
    from wama.common.services.retention import retention_days_by_user
    from wama.common.utils.notifications import notify_in_app
    now = now or timezone.now()
    retention = retention_days_by_user()
    pre = pre_notice_days()
    by_user = defaultdict(list)
    rows = ReleasedFile.objects.filter(notified_at__isnull=True, user__isnull=False).select_related('user')
    for row in _forget_if_used(rows):
        days = retention.get(row.user_id)
        threshold = max(0, days - pre) if days else unused_notice_days()
        if row.released_at <= now - timedelta(days=threshold):
            by_user[row.user].append(row)
    sent = 0
    for user, files in by_user.items():
        days = retention.get(user.pk)
        if days:
            first = min(r.released_at for r in files) + timedelta(days=days)
            # Jamais avant le pré-avis : une durée raccourcie ne supprime rien sans prévenir.
            first = max(first, now + timedelta(days=pre))
            title = f'{len(files)} fichier(s) inutilisé(s) bientôt supprimé(s)'
            body = (f"Plus aucune card ne les utilise : {_names(files)}. Votre durée de conservation "
                    f"est de {days} jours : ils seront supprimés à partir du {first:%d/%m/%Y}. "
                    "« Garder », dans la médiathèque (onglet « Inutilisés »), leur redonne cette "
                    "durée ; elle se règle dans votre profil.")
        else:
            title = f'{len(files)} fichier(s) inutilisé(s) depuis plus de {unused_notice_days()} jours'
            body = (f"Plus aucune card ne les utilise : {_names(files)}. Ils occupent encore votre "
                    "espace ; supprimez-les depuis la médiathèque (onglet « Inutilisés ») si vous n'en "
                    "avez plus besoin — rien n'est supprimé sans vous.")
        sent += notify_in_app([user], 'files_unused', title, body=body, url='/media-library/?tab=unused')
        ReleasedFile.objects.filter(pk__in=[r.pk for r in files]).update(notified_at=now)
    return sent


def renew_released(user, ids=None, paths=None) -> int:
    """« Garder » (rétention finie) : le fichier repart pour une durée complète — compté depuis
    maintenant, annoncé de nouveau avant son prochain terme."""
    return _rows_for(user, ids, paths).update(released_at=timezone.now(), notified_at=None)


def purge_expired_released(now=None) -> dict:
    """Rétention FINIE : un fichier inutilisé resté au-delà de la durée choisie est SUPPRIMÉ — mais
    seulement s'il a été annoncé au moins `pre_notice_days()` avant (sinon il le sera d'abord), et
    l'utilisateur reçoit ensuite la liste de ce qui a été supprimé. Rétention infinie : rien.
    Rend `{'deleted': n, 'users': k}`."""
    from collections import defaultdict
    from datetime import timedelta
    from django.urls import reverse
    from wama.common.models import ReleasedFile
    from wama.common.services.retention import retention_days_by_user
    from wama.common.utils.notifications import notify_in_app
    now = now or timezone.now()
    retention = retention_days_by_user()
    if not retention:
        return {'deleted': 0, 'users': 0}
    pre = pre_notice_days()
    due = defaultdict(list)
    for row in ReleasedFile.objects.filter(user_id__in=list(retention), notified_at__isnull=False) \
            .select_related('user'):
        days = retention[row.user_id]
        if (row.released_at <= now - timedelta(days=days)
                and row.notified_at <= now - timedelta(days=min(pre, days))):
            due[row.user].append(row)
    deleted = 0
    for user, rows in due.items():
        result = delete_released(user, ids=[r.pk for r in rows])
        gone = [r for r in rows if r.path in result['deleted']]
        if not gone:
            continue
        deleted += len(gone)
        notify_in_app(
            [user], 'files_deleted', f'{len(gone)} fichier(s) inutilisé(s) supprimé(s)',
            body=(f"Supprimés au terme de votre durée de conservation ({retention[user.pk]} jours) : "
                  f"{_names(gone)}. Plus aucune card ne les utilisait. La durée se règle dans votre "
                  "profil."),
            url=reverse('accounts:profile'))
    return {'deleted': deleted, 'users': len(due)}

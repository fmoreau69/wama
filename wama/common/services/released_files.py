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

#: Au-delà, un fichier libéré et toujours inutilisé fait l'objet d'une notification. Réglable par
#: `settings.WAMA_UNUSED_FILE_NOTICE_DAYS` ; la rétention de l'utilisateur, si elle est plus courte,
#: prime (c'est la durée qu'il a lui-même choisie pour ses médias).
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


def notice_days_for(user) -> int:
    from django.conf import settings
    days = int(getattr(settings, 'WAMA_UNUSED_FILE_NOTICE_DAYS', UNUSED_NOTICE_DAYS) or UNUSED_NOTICE_DAYS)
    try:
        own = user.profile.effective_retention_days()
    except Exception:
        own = 0
    return min(days, own) if own else days


def notify_long_unused(now=None) -> int:
    """UNE notification par utilisateur pour ses fichiers libérés restés inutilisés au-delà du
    seuil, jamais deux fois pour le même fichier. Rend le nombre de notifications créées."""
    from collections import defaultdict
    from datetime import timedelta
    from wama.common.models import ReleasedFile
    from wama.common.utils.notifications import notify_in_app
    now = now or timezone.now()
    by_user = defaultdict(list)
    rows = ReleasedFile.objects.filter(notified_at__isnull=True, user__isnull=False).select_related('user')
    for row in _forget_if_used(rows):
        if row.released_at <= now - timedelta(days=notice_days_for(row.user)):
            by_user[row.user].append(row)
    sent = 0
    for user, files in by_user.items():
        names = ', '.join(os.path.basename(r.path) for r in files[:5])
        more = f' (et {len(files) - 5} autre(s))' if len(files) > 5 else ''
        days = notice_days_for(user)
        sent += notify_in_app(
            [user], 'files_unused',
            f'{len(files)} fichier(s) inutilisé(s) depuis plus de {days} jours',
            body=(f"Plus aucune card ne les utilise : {names}{more}. Ils occupent encore votre "
                  "espace ; supprimez-les depuis le gestionnaire de fichiers si vous n'en avez "
                  "plus besoin — rien n'est supprimé sans vous."),
            url='/filemanager/')
        ReleasedFile.objects.filter(pk__in=[r.pk for r in files]).update(notified_at=now)
    return sent

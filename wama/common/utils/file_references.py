"""QUI DÉSIGNE CE FICHIER ? — l'index des cards qui utilisent un chemin, et les deux gestes qui
le tiennent à jour quand le fichier bouge ou disparaît.

Décision de Fabien du 2026-09-22 (`MEDIA_STORAGE_TIERING §8.6` D20) sur les gestes du
gestionnaire de fichiers :
  * DÉPLACER ou RENOMMER un fichier met à jour le lien des cards qui le désignent, sans rien
    demander à l'utilisateur (`repoint`) ;
  * SUPPRIMER un fichier qu'une card utilise demande d'abord une confirmation qui dit combien de
    cards il touche ; confirmée, la suppression laisse les cards en place et les DÉTACHE du
    fichier disparu (`detach`) — l'utilisateur recharge une entrée s'il veut la réutiliser.

DEUX FAÇONS DE DÉSIGNER UN FICHIER, et une seule met la card en péril :
  * DIRECTEMENT — un `FileField` porte ce chemin : la copie de travail de la card, sa sortie, ou
    un POINTEUR vers une source (`text_file` du synthesizer importé depuis le serveur, `-i` de
    l'avatarizer). Si le fichier disparaît, la card perd son entrée. C'est ce que compte la
    confirmation.
  * PAR SA SOURCE — `InputProvenance` dit que la copie de travail d'une card VIENT de ce fichier.
    La card a sa copie : supprimer la source ne lui ôte rien, on dit seulement qu'elle a disparu
    (décision du 2026-09-11, `utils/provenance.py::referenced_by`). Déplacer la source, en
    revanche, doit suivre — sinon l'index inverse et la déduplication perdent leur adresse.

⚠ `filemanager.UserFile` est EXCLU : c'est l'index du gestionnaire lui-même, tenu par ses propres
gestes (chaque vue le met à jour à côté). Le compter ferait dire « utilisé par une card » à tout
fichier du temp.

⚠ Ce module ne supprime ni ne déplace AUCUN fichier : il lit les liens et les réécrit. Le geste
sur le disque reste à la vue qui le fait, qui appelle ceci dans la même transaction.
"""
from django.db import transaction

#: Modèles dont les `FileField` ne sont PAS des cards (cf. docstring).
EXCLUDED_MODELS = frozenset({'filemanager.UserFile'})


def _normalized(path) -> str:
    return str(path or '').replace('\\', '/').strip().rstrip('/')


def file_field_models():
    """`[(modèle, [FileField…])]` pour tout le dépôt — UNE énumération, plusieurs lecteurs
    (cet index, `check_media_integrity`)."""
    from django.apps import apps as django_apps
    from django.db import models as dj_models
    found = []
    for model in django_apps.get_models():
        fields = [f for f in model._meta.get_fields() if isinstance(f, dj_models.FileField)]
        if fields:
            found.append((model, fields))
    return found


def _lookup(field_name: str, path: str, folder: bool) -> dict:
    return {f'{field_name}__startswith': path + '/'} if folder else {field_name: path}


def direct_references(path, *, folder=False) -> list:
    """Les cards dont un `FileField` porte ce chemin (ou, `folder=True`, un chemin SOUS ce dossier).

    Rend `[{'label', 'app', 'object_type', 'pk', 'field', 'name'}]`, trié. Ne lève jamais : un
    modèle illisible (table absente d'une jumelle, par exemple) est sauté, pas fatal.
    """
    path = _normalized(path)
    if not path:
        return []
    out = []
    for model, fields in file_field_models():
        if model._meta.label in EXCLUDED_MODELS:
            continue
        for field in fields:
            try:
                rows = model.objects.filter(**_lookup(field.name, path, folder)) \
                    .values_list('pk', field.name)
                for pk, name in rows:
                    out.append({'label': model._meta.label, 'app': model._meta.app_label,
                                'object_type': model.__name__, 'pk': pk,
                                'field': field.name, 'name': name})
            except Exception:
                continue
    return sorted(out, key=lambda r: (r['label'], r['pk'], r['field']))


def source_references(path, *, folder=False) -> list:
    """Les provenances dont la SOURCE est ce chemin (ou un chemin sous ce dossier)."""
    path = _normalized(path)
    if not path:
        return []
    try:
        from wama.common.models import InputProvenance
        qs = (InputProvenance.objects.filter(ref__startswith=path + '/') if folder
              else InputProvenance.objects.filter(ref=path))
        return list(qs.order_by('app', 'object_type', 'object_id'))
    except Exception:
        return []


def usage(path, *, folder=False) -> dict:
    """Ce que le gestionnaire de fichiers doit savoir AVANT de supprimer.

    `cards` = les cards qui PERDRAIENT leur fichier (références directes) — c'est ce que la
    confirmation annonce ; `copies` = les cards dont la copie de travail vient de ce fichier
    (elles gardent leur copie : information, jamais un blocage).
    """
    direct = direct_references(path, folder=folder)
    return {
        'cards': direct,
        'count': len({(r['label'], r['pk']) for r in direct}),
        'copies': len(source_references(path, folder=folder)),
    }


def repoint(old_path, new_path, *, folder=False) -> dict:
    """Le fichier (ou le dossier) a bougé : chaque lien suit, directs et sources.

    À appeler APRÈS le déplacement réussi sur le disque. Rend `{'direct': n, 'sources': m}`.
    """
    old, new = _normalized(old_path), _normalized(new_path)
    counts = {'direct': 0, 'sources': 0}
    if not old or not new or old == new:
        return counts

    def _moved(name: str) -> str:
        name = _normalized(name)
        return new + name[len(old):] if folder else new

    with transaction.atomic():
        for model, fields in file_field_models():
            if model._meta.label in EXCLUDED_MODELS:
                continue
            for field in fields:
                try:
                    rows = list(model.objects.filter(**_lookup(field.name, old, folder))
                                .values_list('pk', field.name))
                except Exception:
                    continue
                for pk, name in rows:
                    model.objects.filter(pk=pk).update(**{field.name: _moved(name)})
                    counts['direct'] += 1
        for prov in source_references(old, folder=folder):
            prov.ref = _moved(prov.ref)
            prov.save(update_fields=['ref'])
            counts['sources'] += 1
    return counts


def detach(path, *, folder=False) -> int:
    """Le fichier a été supprimé (après confirmation) : les cards qui le désignaient restent,
    leur champ est VIDÉ — elles n'annoncent plus un fichier qui n'existe pas, et
    `check_media_integrity` ne les compte pas en « référencé mais absent ».

    Les provenances ne sont PAS touchées : qu'une source ait disparu est un fait qu'on garde
    (la card, elle, a sa copie). Rend le nombre de liens détachés.
    """
    detached = 0
    with transaction.atomic():
        for ref in direct_references(path, folder=folder):
            from django.apps import apps as django_apps
            model = django_apps.get_model(ref['label'])
            detached += model.objects.filter(pk=ref['pk']).update(**{ref['field']: ''})
    return detached

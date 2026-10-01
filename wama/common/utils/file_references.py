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
    confirmation. Une entrée d'une LISTE DE CHEMINS déclarée (`path_list_fields` — les images
    d'une génération de l'imager) désigne le fichier au même titre : depuis le 2026-10-02 chaque
    question et chaque geste de ce module lit les deux formes.
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


def path_list_fields():
    """(modèle, champ) portant une LISTE de chemins (JSON) hors `FileField` — lus dans la
    déclaration que la rétention tient DÉJÀ (`retention.RETENTION_MODELS[…]['path_lists']`),
    jamais une 2ᵉ liste. Lecteurs : la purge de rétention, le retrait d'une card
    (`queue_duplication.release_card_files`), l'aperçu de ce qu'un retrait libère
    (`released_files.freed_by`), le réalignement de `migrate_media_to_user_home`, et l'index de ce
    module (`_rows_listing`).

    ⚠ Le TROU que la migration du 2026-09-12 a laissé (relevé le 2026-09-23 par Fabien : « on a
    perdu la preview imager image à 4 images ») : `champs_fichier` balaie les `FileField` et les
    champs TEXTE, pas les `JSONField`. Les images de l'imager ont été DÉPLACÉES (le plan part du
    disque) mais `generated_images` a gardé ses chemins ABSOLUS d'avant — l'aperçu, qui ne rend
    que les fichiers existants, restait vide sur toutes les générations multi-images.

    ⚠ Le MÊME trou, dans l'index, jusqu'au 2026-10-02 : `direct_references`,
    `is_referenced_elsewhere`, `referenced_outside`, `repoint` et `detach` ne lisaient que les
    `FileField`. Une image de l'imager était dite « inutilisée » par le gestionnaire de fichiers,
    et la ranger dans la médiathèque (qui DÉPLACE le fichier, puis `repoint`) la faisait
    disparaître de sa card.
    """
    from django.apps import apps as django_apps
    from wama.common.services.retention import RETENTION_MODELS
    for entry in RETENTION_MODELS:
        for name in entry.get('path_lists') or ():
            try:
                yield django_apps.get_model(entry['model']), name
            except LookupError:
                continue


def relative_to_media(path) -> str:
    """Chemin relatif à MEDIA_ROOT (la forme que `owns_file` compare) ; '' s'il est HORS de
    MEDIA_ROOT — et alors `owns_file` refuse, ce qui est voulu : rien ne sort jamais de là."""
    import os
    from django.conf import settings
    path = str(path or '')
    if not os.path.isabs(path):
        return path.replace('\\', '/')
    root = os.path.abspath(settings.MEDIA_ROOT)
    absolute = os.path.abspath(path)
    if os.path.commonpath([root, absolute]) != root:
        return ''
    return os.path.relpath(absolute, root).replace('\\', '/')


def listed_paths(instance) -> list:
    """`[(champ, chemin relatif à MEDIA_ROOT)]` pour chaque entrée des listes de chemins DÉCLARÉES
    de cette card (`path_list_fields`). Une entrée est un chemin, ou un dict qui le porte sous
    `path` ; absolue ou relative, elle est rendue relative. Une entrée hors de MEDIA_ROOT est
    sautée. Modèle sans liste déclarée : `[]`."""
    out = []
    for model, name in path_list_fields():
        if not isinstance(instance, model):
            continue
        value = getattr(instance, name, None)
        if not isinstance(value, (list, tuple)):
            continue
        for entry in value:
            rel = _entry_rel(entry)
            if rel:
                out.append((name, rel))
    return out


def _entry_path(entry) -> str:
    """Le chemin que porte une entrée de liste : la chaîne elle-même, ou la clé `path` d'un dict."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return str(entry.get('path') or '')
    return ''


def _entry_rel(entry) -> str:
    path = _entry_path(entry)
    return relative_to_media(path) if path else ''


def _entry_moved(entry, new_rel: str):
    """La même entrée à sa nouvelle adresse, FORME CONSERVÉE : absolue reste absolue (c'est ce
    que lisent l'aperçu et les téléchargements de l'app), un dict garde ses autres clés."""
    import os
    from django.conf import settings
    new = (os.path.join(settings.MEDIA_ROOT, *new_rel.split('/'))
           if os.path.isabs(_entry_path(entry)) else new_rel)
    return {**entry, 'path': new} if isinstance(entry, dict) else new


def relocated_list(value, mapping) -> list:
    """La liste `value` dont chaque entrée désignant un chemin de `mapping` (relatif → nouveau
    relatif) est réécrite à sa nouvelle adresse, FORME CONSERVÉE (`_entry_moved`) ; les autres
    entrées sont inchangées. Pour une COPIE de fichier (transfert, duplication d'une card reçue —
    2026-10-02) : `repoint` réécrirait aussi l'original, seule l'entrée de la copie doit changer."""
    return [_entry_moved(entry, mapping[_entry_rel(entry)]) if _entry_rel(entry) in mapping else entry
            for entry in (value or [])]


#: Au-delà de ce nombre de chemins cherchés d'un coup (l'aperçu d'un « Tout effacer »), les listes
#: non vides sont balayées plutôt que filtrées condition par condition.
_PREFILTER_MAX = 20


def _rows_listing(paths, *, folder=False):
    """`(modèle, champ, pk, liste, [index])` pour chaque ligne dont une liste de chemins DÉCLARÉE
    porte l'un de `paths` (ou, `folder=True`, un chemin SOUS l'un d'eux) ; `index` = les entrées
    concernées. Le jumeau, pour les listes, de la requête par `FileField` des fonctions
    ci-dessous.

    La base PRÉFILTRE sur le DERNIER segment du chemin (nom du fichier, ou du dossier) : c'est la
    seule sous-chaîne commune à toutes les formes stockées — relative, absolue, et absolue écrite
    depuis Windows, dont les séparateurs sont échappés dans le JSON (mesuré : le chemin relatif
    entier n'y est pas une sous-chaîne, six tests rouges depuis `venv_win`). L'égalité est ensuite
    jugée ici, entrée par entrée, sur le chemin rendu relatif — une sous-chaîne n'est pas une
    désignation. Ne lève jamais : un modèle illisible est sauté, comme pour les champs fichier.
    """
    from django.db.models import Q
    wanted = {p for p in map(_normalized, paths) if p}
    if not wanted:
        return
    for model, name in path_list_fields():
        rows = model.objects.all()
        if len(wanted) <= _PREFILTER_MAX:
            condition = Q()
            for path in wanted:
                condition |= Q(**{f'{name}__icontains': path.rsplit('/', 1)[-1]})
            rows = rows.filter(condition)
        try:
            rows = list(rows.values_list('pk', name))
        except Exception:
            continue
        for pk, value in rows:
            if not isinstance(value, list):
                continue
            hits = [i for i, entry in enumerate(value)
                    if _designates(_entry_rel(entry), wanted, folder)]
            if hits:
                yield model, name, pk, value, hits


def _designates(rel: str, wanted, folder: bool) -> bool:
    if not rel:
        return False
    if folder:
        return any(rel.startswith(path + '/') for path in wanted)
    return rel in wanted


def _lookup(field_name: str, path: str, folder: bool) -> dict:
    return {f'{field_name}__startswith': path + '/'} if folder else {field_name: path}


def direct_references(path, *, folder=False) -> list:
    """Les cards dont un `FileField` — ou une entrée d'une liste de chemins déclarée — porte ce
    chemin (ou, `folder=True`, un chemin SOUS ce dossier).

    Rend `[{'label', 'app', 'object_type', 'pk', 'field', 'name'}]`, trié ; une référence portée
    par une liste a en plus `'listed': True` (son champ ne se vide pas, on en retire l'entrée —
    cf. `detach`). Ne lève jamais : un modèle illisible (table absente d'une jumelle, par
    exemple) est sauté, pas fatal.
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
    for model, name, pk, value, hits in _rows_listing([path], folder=folder):
        for i in hits:
            out.append({'label': model._meta.label, 'app': model._meta.app_label,
                        'object_type': model.__name__, 'pk': pk,
                        'field': name, 'name': _entry_rel(value[i]), 'listed': True})
    return sorted(out, key=lambda r: (r['label'], r['pk'], r['field']))


def is_referenced_elsewhere(path, *, label='', pk=None, field='') -> bool:
    """Une AUTRE ligne, DE N'IMPORTE QUEL MODÈLE, désigne-t-elle ce fichier ?

    La moitié « partage » de la suppression, élargie le 2026-09-23 à tout le dépôt. Elle ne
    regardait que le même modèle et le même champ — ce qui suffisait tant que le partage venait de
    « Dupliquer » (une card copiée dans sa propre app). Mesuré sur les données réelles ce jour-là,
    le partage entre apps existe DÉJÀ : trois jobs du converter désignent un fichier rangé chez
    l'anonymizer, et la voix de la médiathèque partage son fichier avec la voix clonée du
    synthesizer. La garde locale ne les voyait pas.

    Sortie ANTICIPÉE au premier porteur trouvé : c'est une existence, pas un inventaire (55 champs
    fichier au 2026-09-23 — ~30 ms quand personne ne désigne le fichier, moins dès qu'un le fait).
    """
    path = _normalized(path)
    if not path:
        return False
    for model, fields in file_field_models():
        if model._meta.label in EXCLUDED_MODELS:
            continue
        for f in fields:
            try:
                qs = model.objects.filter(**{f.name: path})
                if model._meta.label == label and f.name == field and pk is not None:
                    qs = qs.exclude(pk=pk)
                if qs.exists():
                    return True
            except Exception:
                continue
    # Les listes de chemins déclarées désignent au même titre (2026-10-02) — même exclusion :
    # la ligne pour laquelle on pose la question ne se compte pas elle-même.
    for model, name, row_pk, _value, _hits in _rows_listing([path]):
        if not (model._meta.label == label and name == field and row_pk == pk):
            return True
    return False


def referenced_outside(paths, inside) -> set:
    """Parmi `paths`, ceux qu'une ligne HORS de `inside` (ensemble de `(label, pk)`) désigne.

    La question d'une SUPPRESSION GROUPÉE (2026-10-01) : « si je retire ces cards-là, lesquels de
    leurs fichiers ne servent plus à personne ? ». `is_referenced_elsewhere` y répond pour UN
    chemin et UNE ligne exclue ; ici l'ensemble à retirer est quelconque (une card, un lot, toute
    une file), et la réponse tient en UNE requête par champ fichier du dépôt, quel que soit le
    nombre de chemins — c'est ce qui rend l'aperçu d'un « Tout effacer » abordable.
    """
    wanted = {_normalized(p) for p in paths if _normalized(p)}
    if not wanted:
        return set()
    outside = set()
    for model, fields in file_field_models():
        label = model._meta.label
        if label in EXCLUDED_MODELS:
            continue
        for field in fields:
            try:
                rows = model.objects.filter(**{f'{field.name}__in': list(wanted)}) \
                    .values_list('pk', field.name)
                for pk, name in rows:
                    if (label, pk) not in inside:
                        outside.add(_normalized(name))
            except Exception:
                continue
    for model, _name, pk, value, hits in _rows_listing(wanted):
        if (model._meta.label, pk) not in inside:
            outside.update(_entry_rel(value[i]) for i in hits)
    return outside


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

    # ⚠ ASYMÉTRIE VOULUE (2026-09-27) : le repointage ne SAUTE PAS `filemanager.UserFile`, alors que
    # `direct_references`/`usage` l'écartent. Les deux questions sont différentes : « qui UTILISE ce
    # fichier ? » ne doit pas compter l'index du gestionnaire (sinon tout fichier du temp paraîtrait
    # utilisé), mais « le fichier a bougé » doit tenir cet index à jour — sans quoi il DÉRIVE, et
    # c'est exactement le défaut mesuré sur lui (20 lignes vers des fichiers disparus). Les vues du
    # gestionnaire le mettent déjà à jour de leur côté : réécrire la même valeur est sans effet.
    with transaction.atomic():
        for model, fields in file_field_models():
            for field in fields:
                try:
                    rows = list(model.objects.filter(**_lookup(field.name, old, folder))
                                .values_list('pk', field.name))
                except Exception:
                    continue
                for pk, name in rows:
                    model.objects.filter(pk=pk).update(**{field.name: _moved(name)})
                    counts['direct'] += 1
        # Les entrées des listes de chemins suivent aussi, forme conservée (2026-10-02) : sans
        # cela, ranger une image dans la médiathèque la faisait disparaître de sa card.
        for model, name, pk, value, hits in _rows_listing([old], folder=folder):
            for i in hits:
                value[i] = _entry_moved(value[i], _moved(_entry_rel(value[i])))
            model.objects.filter(pk=pk).update(**{name: value})
            counts['direct'] += len(hits)
        for prov in source_references(old, folder=folder):
            prov.ref = _moved(prov.ref)
            prov.save(update_fields=['ref'])
            counts['sources'] += 1
        # Un fichier LIBÉRÉ (aucune card ne l'appelle, 2026-09-30) garde sa note à sa nouvelle
        # adresse : déplacé, il reste inutilisé depuis la même date.
        from wama.common.models import ReleasedFile
        rows = (ReleasedFile.objects.filter(path__startswith=old + '/') if folder
                else ReleasedFile.objects.filter(path=old))
        for row in rows:
            row.path = _moved(row.path)
            row.save(update_fields=['path'])
    return counts


def detach(path, *, folder=False) -> int:
    """Le fichier a été supprimé (après confirmation) : les cards qui le désignaient restent,
    leur champ est VIDÉ — elles n'annoncent plus un fichier qui n'existe pas, et
    `check_media_integrity` ne les compte pas en « référencé mais absent ». Une LISTE de chemins
    perd la seule entrée concernée : ses autres fichiers restent.

    Les provenances ne sont PAS touchées : qu'une source ait disparu est un fait qu'on garde
    (la card, elle, a sa copie). Rend le nombre de liens détachés.
    """
    detached = 0
    with transaction.atomic():
        for ref in direct_references(path, folder=folder):
            if ref.get('listed'):
                continue
            from django.apps import apps as django_apps
            model = django_apps.get_model(ref['label'])
            detached += model.objects.filter(pk=ref['pk']).update(**{ref['field']: ''})
        for model, name, pk, value, hits in _rows_listing([path], folder=folder):
            kept = [entry for i, entry in enumerate(value) if i not in hits]
            model.objects.filter(pk=pk).update(**{name: kept})
            detached += len(hits)
    return detached

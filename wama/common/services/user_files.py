"""
Retrouver un fichier de l'utilisateur PAR SON NOM, partout où le gestionnaire de fichiers le
montre — dossier temporaire, entrées et sorties de chaque app, dossiers CONNECTÉS (locaux,
réseau, nuage).

POURQUOI UNE BRIQUE (2026-10-11, fil web n° 32). L'assistant ne savait regarder que six dossiers
écrits à la main (`tool_api._FOLDER_MAP`, retiré le 2026-11-16 : `list_folder` lit un dossier de
l'arbre, `locations` les nomme), sans recherche par nom ni dossier connecté ; la
recherche du gestionnaire (`filemanager.views.api_search`) tient sa propre liste de 25 dossiers,
écrite à la main elle aussi, sans les dossiers connectés. Deux listes du même ensemble, aucune
juste : *« deux listes du même ensemble finissent par en décrire deux »* (`_app_folders_config`).

LE PÉRIMÈTRE N'EST PAS DÉCLARÉ ICI : il est LU là où l'arbre du gestionnaire le lit —
`_app_folders_config` (dossiers d'app dérivés du registre d'apps), le dossier temporaire, et les
`MountedFolder` de l'utilisateur résolus par `resolve_mount_path`. Ce que l'utilisateur voit dans
l'arbre est exactement ce qu'on cherche ; une app ajoutée y entre toute seule. La médiathèque n'a
pas de dossier dans l'arbre : elle se cherche par son propre outil (`list_media_assets`).

BORNÉE, parce qu'un dossier connecté peut être un nuage lent ou un partage énorme : un budget de
temps et d'entrées par racine. Une racine non parcourue jusqu'au bout est DITE (`complete: False`)
— une recherche tronquée en silence ferait conclure à une absence.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from wama.common.utils.text_fold import fold

logger = logging.getLogger(__name__)

#: Secondes accordées à UNE racine locale (sous `MEDIA_ROOT`), puis à UN dossier connecté —
#: un nuage monté par rclone répond plus lentement qu'un disque.
LOCAL_BUDGET_S = 3.0
MOUNT_BUDGET_S = 5.0
#: Entrées (fichiers et dossiers) visitées au plus par racine.
MAX_ENTRIES_PER_ROOT = 20000
#: Préfixe des chemins VIRTUELS d'un dossier connecté (`mounts/<id>/…`), celui du gestionnaire.
MOUNT_PREFIX = 'mounts/'
#: Le nom court du dossier TEMPORAIRE, première racine de l'arbre (`search_roots`) : là où
#: arrivent les dépôts, et le dossier que `list_folder` lit quand on ne lui en nomme pas d'autre.
TEMP_FOLDER = 'temp'


def is_mount_path(path) -> bool:
    """Ce chemin désigne-t-il un dossier CONNECTÉ (`mounts/<id>/…`) ?"""
    return str(path or '').replace('\\', '/').lstrip('/').startswith(MOUNT_PREFIX)


def mounted_file(path, user):
    """Le chemin DISQUE d'un fichier `mounts/<id>/…` de CET utilisateur, ou None.

    La résolution est celle du gestionnaire (`resolve_mount_path` : le montage doit appartenir à
    l'utilisateur, `..` refusé) — aucune seconde règle. None aussi si le fichier n'existe pas."""
    from wama.filemanager.views import resolve_mount_path
    target, _mount = resolve_mount_path(str(path).replace('\\', '/').lstrip('/'), user)
    if target is None:
        return None
    try:
        return target if target.is_file() else None
    except OSError:                      # montage décroché, nuage injoignable
        return None


def _collect_app_leaves(nodes, parents, roots):
    """Les dossiers-FEUILLES de la déclaration de l'arbre (ceux qui portent un `path`), avec le
    chemin de libellés qui y mène — « Anonymizer › Entrées » —, dans l'ordre de l'arbre."""
    for node in nodes:
        trail = [*parents, node.get('text') or '']
        if node.get('path'):
            roots.append({'path': node['path'], 'location': ' › '.join(trail), 'mount': False})
        children = node.get('children')
        if isinstance(children, list):
            _collect_app_leaves(children, trail, roots)


def search_roots(user) -> list:
    """Les racines de recherche de cet utilisateur, dans l'ordre de l'arbre du gestionnaire :
    `[{'path', 'location', 'abs', 'mount'}]` — `path` est le chemin par lequel le gestionnaire et
    les outils le désignent (relatif à `MEDIA_ROOT`, ou `mounts/<id>`)."""
    from django.conf import settings

    from wama.filemanager.models import MountedFolder
    from wama.filemanager.views import _app_folders_config, resolve_mount_path

    roots = [{'path': f'users/{user.id}/temp', 'location': 'Temporaires', 'mount': False}]
    _collect_app_leaves(_app_folders_config(user.id), [], roots)
    media_root = Path(settings.MEDIA_ROOT)
    for root in roots:
        root['abs'] = media_root / root['path']

    for mount in MountedFolder.objects.filter(user=user).order_by('name'):
        virtual = f'{MOUNT_PREFIX}{mount.id}'
        target, _mount = resolve_mount_path(virtual, user)
        if target is not None:
            roots.append({'path': virtual, 'location': mount.name, 'abs': Path(target),
                          'mount': True})
    return roots


def _walk_root(root, terms, found, budget_s):
    """Parcourt UNE racine, ajoute les fichiers dont le nom porte TOUS les termes ; rend
    `(complete, error)`. Les dossiers cachés (`.git`, `.cache`…) ne sont pas descendus."""
    started = time.monotonic()
    visited = 0
    base = root['abs']
    try:
        if not base.is_dir():
            return True, ''
        for current, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for name in files:
                visited += 1
                if all(term in fold(name) for term in terms):
                    full = Path(current) / name
                    relative = full.relative_to(base).as_posix()
                    try:
                        stat = full.stat()
                    except OSError:
                        continue
                    found.append({
                        'name': name,
                        'path': f"{root['path']}/{relative}",
                        'location': root['location'],
                        'connected': root['mount'],
                        'size_mb': round(stat.st_size / 1_048_576, 2),
                        'modified': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                                            .isoformat(timespec='seconds'),
                    })
            visited += len(dirs)
            if visited >= MAX_ENTRIES_PER_ROOT or time.monotonic() - started > budget_s:
                return False, ''
    except OSError as e:                 # montage décroché, droits refusés
        logger.warning('[user_files] racine %s illisible : %s', root['path'], e)
        return False, str(e)
    return True, ''


def locations(user) -> list:
    """Les dossiers de l'arbre de cet utilisateur, tels qu'on les DÉSIGNE :
    `[{'path', 'location', 'connected'}]`, dans l'ordre de l'arbre."""
    return [{'path': r['path'], 'location': r['location'], 'connected': r['mount']}
            for r in search_roots(user)]


def _folder_root(user, folder: str):
    """Le dossier `folder` de l'arbre de `user`, sous la forme d'une racine de parcours
    (`{'path', 'location', 'abs', 'mount'}`), ou None : une racine de `search_roots` ou l'un de ses
    sous-dossiers, jamais un chemin hors de l'arbre (`..` refusé ; un dossier connecté se résout
    par la règle du gestionnaire, `resolve_mount_path`)."""
    folder = str(folder or '').replace('\\', '/').strip('/')
    if not folder or '..' in folder.split('/'):
        return None
    roots = search_roots(user)
    if folder == TEMP_FOLDER:
        folder = roots[0]['path']
    for root in roots:
        if folder != root['path'] and not folder.startswith(root['path'] + '/'):
            continue
        if root['mount']:
            from wama.filemanager.views import resolve_mount_path
            target, _mount = resolve_mount_path(folder, user)
            if target is None:
                return None
            base = Path(target)
        else:
            base = root['abs'] / folder[len(root['path']):].lstrip('/')
        return {'path': folder, 'location': root['location'], 'abs': base, 'mount': root['mount']}
    return None


def list_folder(user, folder: str, *, limit: int = 200) -> dict:
    """Les fichiers d'UN dossier de l'arbre (sous-dossiers compris), les plus récents d'abord :
    `{'files': [...], 'count', 'folder', 'location', 'complete', 'unreadable'?}`, chaque fichier sous
    la forme de `find_user_files`. Même parcours BORNÉ que la recherche : `complete: False` dit
    qu'un dossier trop grand ou injoignable n'a pas été lu jusqu'au bout. Un dossier hors de
    l'arbre rend `{'error', 'locations'}` — les dossiers qu'on peut nommer."""
    root = _folder_root(user, folder)
    if root is None:
        return {'error': f"Dossier inconnu ou hors de votre espace : {folder!r}.",
                'locations': locations(user)}
    found = []
    complete, error = _walk_root(root, [], found,
                                 MOUNT_BUDGET_S if root['mount'] else LOCAL_BUDGET_S)
    found.sort(key=lambda f: f['modified'], reverse=True)
    try:
        limit = max(1, min(int(limit or 200), 500))
    except (TypeError, ValueError):
        limit = 200
    return {'files': found[:limit], 'count': len(found), 'folder': root['path'],
            'location': root['location'], 'complete': complete,
            **({'unreadable': error} if error else {})}


def find_user_files(user, query: str, *, limit: int = 20) -> dict:
    """Les fichiers de `user` dont le NOM contient tous les mots de `query` (casse et accents
    ignorés), dans toutes les racines de `search_roots`.

    Rend `{'results': [...], 'count', 'roots_searched', 'incomplete': [{'location', 'error'?}]}`
    — le nom exact d'abord, puis le plus récent. `incomplete` nomme les racines qui n'ont pas pu
    être parcourues jusqu'au bout (budget, montage injoignable) : l'absence n'y est pas prouvée.
    `path` est directement désignable : `designate` et les outils de l'assistant l'acceptent tel
    quel, dossier connecté compris (copié à l'entrée).
    """
    terms = [fold(t) for t in (query or '').split() if t.strip()]
    if not terms:
        return {'error': 'query vide', 'results': [], 'count': 0}
    found, incomplete = [], []
    roots = search_roots(user)
    for root in roots:
        complete, error = _walk_root(root, terms, found,
                                     MOUNT_BUDGET_S if root['mount'] else LOCAL_BUDGET_S)
        if not complete:
            incomplete.append({'location': root['location'], **({'error': error} if error else {})})

    wanted = fold(' '.join((query or '').split()))
    found.sort(key=lambda f: f['modified'], reverse=True)
    found.sort(key=lambda f: fold(f['name']) != wanted)        # tri stable : l'exact devant
    try:
        limit = max(1, min(int(limit or 20), 100))
    except (TypeError, ValueError):
        limit = 20
    return {'results': found[:limit], 'count': len(found), 'roots_searched': len(roots),
            'incomplete': incomplete}

"""
Filemanager — gestes de fichier réutilisables hors de la vue web.

POURQUOI CE MODULE (2026-08-21). Les endpoints `/filemanager/api/…` sont écrits pour un
NAVIGATEUR : authentification par session, CSRF, et surtout `get_user()` qui retombe sur
l'utilisateur ANONYME PARTAGÉ quand la requête n'est pas authentifiée par session. Un client
porteur d'un token DRF (bot Matrix/Tchap, Discord — cf. `ROADMAP.md` §19) n'est donc pas
seulement refusé : dans un montage sans CSRF il déposerait silencieusement ses fichiers dans
l'espace de l'utilisateur anonyme au lieu de celui du membre du labo. Le geste de dépôt et
celui de lecture sont extraits ici pour que la surface token (`/api/v1/files/…`) les partage
avec la vue web au lieu d'en recopier une variante — la duplication d'une garde de sécurité
étant la pire espèce de duplication : les deux copies divergent, et c'est la moins relue qui
laisse passer.

Ce module NE décide PAS de l'authentification : il reçoit un `user` déjà résolu et déjà
autorisé par l'appelant.
"""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)


def enregistrer_fichier_utilisateur(user, django_file) -> dict:
    """
    Enregistre un fichier téléversé dans l'espace de `user` et rend sa description.

    C'est le chemin « dépôt simple » (sans arborescence) de `filemanager.api_upload`, dont
    il est désormais l'implémentation unique. Le placement sur disque reste celui du modèle
    (`UserFile.file.upload_to`) — ne jamais le recalculer ici, sinon les deux surfaces
    écriraient à deux endroits différents.

    Returns: {'id', 'name', 'path', 'size'} — `path` est relatif à MEDIA_ROOT, c'est la clé
    que les outils de l'assistant (`list_user_files`, `add_to_<app>`) savent consommer.
    """
    from .models import UserFile

    user_file = UserFile.objects.create(
        user=user,
        file=django_file,
        original_name=django_file.name,
        mime_type=(django_file.content_type
                   or mimetypes.guess_type(django_file.name)[0] or ''),
        file_size=django_file.size,
    )
    return {
        'id': user_file.id,
        'name': user_file.original_name,
        'path': user_file.file.name,
        'size': user_file.file_size,
    }


def resoudre_chemin_lisible(user, path: str):
    """
    Résout un chemin relatif à MEDIA_ROOT en chemin absolu LISIBLE par `user`.

    Applique la garde d'accès existante `is_path_allowed()` — dérivée d'APP_CATALOG, scopée
    par `user.id` et refusant le segment `..`. Ne la réimplémente PAS : ajouter une app au
    catalogue doit continuer à suffire pour que ses fichiers deviennent accessibles.

    Returns: (chemin_absolu, None) si lisible · (None, (message, code_http)) sinon.
    """
    from .views import is_path_allowed, resolve_mount_path

    path = (path or '').replace('\\', '/').lstrip('/')
    if not path:
        return None, ("Paramètre 'path' manquant.", 400)

    if not is_path_allowed(path, user):
        return None, ("Accès refusé à ce chemin.", 403)

    if path.startswith('mounts/'):
        chemin, _mount = resolve_mount_path(path, user)
        if chemin is None:
            return None, ("Accès refusé à ce chemin.", 403)
    else:
        chemin = Path(settings.MEDIA_ROOT) / path

    if not Path(chemin).exists():
        return None, ("Fichier introuvable.", 404)

    return Path(chemin), None

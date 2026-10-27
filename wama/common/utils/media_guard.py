"""Garde-fou PROCESSUS : aucun `shutil.rmtree` ne peut effacer `media/` en bloc.

POURQUOI (2026-10-27, perte de TOUS les médias des utilisateurs)
    Un test (`SurfaceLayoutTest`) empruntait le `setUp` d'une autre classe sans son
    `override_settings(MEDIA_ROOT=…)` ; ce `setUp` programmait `addCleanup(shutil.rmtree,
    settings.MEDIA_ROOT)`. Lancé HORS du lanceur de tests — un script de contre-épreuve qui fait
    `django.setup()` sur les vrais réglages —, `MEDIA_ROOT` désignait le vrai `media/` : effacé à
    16:34, restauré depuis la sauvegarde du NAS. Les fichiers créés depuis la sauvegarde de 02:30
    sont perdus.

    La redirection du lanceur (`runners.WamaTestRunner`) et la garde par AST
    (`tests_media_tests_hygiene`) ne voient pas un script ; ce garde-fou, lui, vit dans TOUT
    processus qui a chargé Django : gunicorn, Celery, commandes, scripts `django.setup()`, tests.

CE QUI EST REFUSÉ
    `shutil.rmtree` d'un dossier qui EST la racine des médias, qui est l'un des domiciles des
    données réelles (`users/`, `media_library/`, `MEDIA_STORAGE_TIERING`), ou qui CONTIENT la
    racine (le dépôt, `D:/WAMA`…). Les autres dossiers de premier niveau restent effaçables :
    les smokes y montent des dossiers jetables (`smoke_preview_*`) qu'ils retirent. La racine
    est celle des RÉGLAGES au démarrage, avant toute redirection de test : la garde protège le
    vrai `media/` même quand `settings.MEDIA_ROOT` pointe ailleurs.
    Le reste est permis : un dossier d'utilisateur (`users/<id>/`, purge des visiteurs), un
    dossier de travail, un dossier de test.

    Le refus LÈVE `PermissionError` avant tout effacement — `ignore_errors=True` ne l'avale donc
    pas — et l'écrit au journal en ERREUR, pour qu'un appelant qui l'attrape laisse une trace.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

#: Racines protégées, résolues au démarrage (`install`).
_PROTECTED: list[Path] = []

#: Les domiciles des données RÉELLES sous la racine — jamais effacés en bloc. Leur FORME vit dans
#: `media_paths` (`app_media_dir` : `users/<id>/<app>/…`, tous mondes ; `SYSTEM_ASSET_ROOT`) :
#: déplacer un domicile, c'est aussi le déclarer ici.
DATA_HOMES = ('users', 'media_library')


def _resolve(path) -> Path | None:
    try:
        return Path(os.fspath(path)).resolve()
    except (TypeError, OSError, ValueError):
        return None


def refusal(path, roots=None) -> str:
    """La raison de refuser d'effacer `path` en bloc, ou '' s'il peut l'être."""
    target = _resolve(path)
    if target is None:
        return ''
    for root in (_PROTECTED if roots is None else roots):
        if target == root:
            return f'{target} est la racine des médias'
        if target.parent == root and target.name in DATA_HOMES:
            return f'{target} est un domicile des données réelles ({root})'
        if target in root.parents:
            return f'{target} contient la racine des médias ({root})'
    return ''


def install(media_root) -> bool:
    """Protège `media_root` dans ce processus. Idempotent ; rend True si la garde est en place."""
    root = _resolve(media_root)
    if root is None:
        return False
    if root not in _PROTECTED:
        _PROTECTED.append(root)
    if getattr(shutil.rmtree, 'wama_media_guard', False):
        return True
    original = shutil.rmtree

    def guarded_rmtree(path, *args, **kwargs):
        reason = refusal(path)
        if reason:
            logger.error('[media_guard] effacement REFUSÉ : %s', reason, stack_info=True)
            raise PermissionError(f'[media_guard] effacement refusé : {reason}')
        return original(path, *args, **kwargs)

    guarded_rmtree.wama_media_guard = True
    guarded_rmtree.original = original
    guarded_rmtree.avoids_symlink_attacks = getattr(original, 'avoids_symlink_attacks', False)
    shutil.rmtree = guarded_rmtree
    return True

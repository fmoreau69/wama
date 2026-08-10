"""
Sauvegarde des SECRETS / fichiers d'installation — `.env` → NAS `DEEP_LEARNING/INSTALL`.

POURQUOI (trou mesuré le 2026-08-10)
====================================
Les trois sauvegardes existantes (modèles, base, médias) ne suffisaient PAS à refaire une
installation : `.env` est ignoré par git (`.gitignore:94`) et n'était nulle part sur le NAS.
Sans lui, une machine neuve ne peut se connecter ni à Postgres ni à Redis — et le mot de passe
dont `pg_restore` a besoin s'y trouve précisément. Fabien en a déposé une copie manuelle le
10/08 ; ce module la maintient à jour.

VERSIONNÉ, PAS ÉCRASÉ — et c'est le point de conception
=======================================================
Contrairement aux médias, écraser la copie distante détruirait l'état PRÉCÉDENT des secrets.
Or le moment où l'on a besoin d'une sauvegarde de `.env`, c'est justement après une rotation
de secrets qui s'est mal passée. D'où deux sorties complémentaires :

  INSTALL/.env                      ← toujours la version COURANTE, chemin stable pour un tirage
  INSTALL/history/.env.<horodatage> ← historique, purgé au-delà de `keep`

L'historique n'est alimenté QUE si le contenu a changé (comparaison SHA-256) : sinon une tâche
quotidienne fabriquerait 365 copies identiques par an et chasserait les versions utiles.

⚠ CONFIDENTIALITÉ — décision assumée par Fabien
===============================================
Ceci écrit des secrets en clair sur un partage réseau. L'historique git a justement été réécrit
en juillet pour les en sortir ([[project_secrets_externalization]]) : le dépôt sur le NAS est un
choix DIFFÉRENT et délibéré, pris le 10/08 (copie manuelle dans `INSTALL/`). Ce module ne fait
qu'automatiser ce choix — il ne l'élargit pas. Vérifier les droits du partage avant d'y compter.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path

from django.conf import settings

from wama.common.services.mirror_sync import (
    copy_file,
    purge_keep_latest,
    remote_is_available,
    resolve_remote_root,
)

logger = logging.getLogger(__name__)

REMOTE_SUBDIR = "INSTALL"
REMOTE_ENV_VAR = "WAMA_CONFIG_BACKUP_PATH"
HISTORY_DIR = "history"
DEFAULT_KEEP = 10

#: Fichiers d'installation NON versionnés par git. `.env.example` en est exclu : il est
#: dans le dépôt, donc déjà sauvegardé par git — l'ajouter serait une redondance.
CONFIG_FILES = (".env",)


def remote_config_path() -> str:
    return resolve_remote_root(REMOTE_SUBDIR, env_var=REMOTE_ENV_VAR)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_status() -> dict:
    remote = remote_config_path()
    base = Path(settings.BASE_DIR)
    return {
        'available': remote_is_available(remote),
        'remote_path': remote,
        'files': {name: (base / name).is_file() for name in CONFIG_FILES},
    }


def backup_config(keep: int = DEFAULT_KEEP, force: bool = False) -> dict:
    """
    Copie les fichiers de configuration vers le distant SI leur contenu a changé.

    Args:
        keep: nombre de versions conservées dans `history/`.
        force: versionne même si le contenu est identique (utile pour un premier dépôt).

    Returns: {'copied': [...], 'unchanged': [...], 'errors': [...], 'remote_path': str}
    """
    remote_root = Path(remote_config_path())
    summary = {'copied': [], 'unchanged': [], 'errors': [], 'remote_path': str(remote_root)}

    if not remote_is_available(remote_root):
        summary['errors'].append(f"Espace distant indisponible : {remote_root}")
        return summary

    base = Path(settings.BASE_DIR)
    history = remote_root / HISTORY_DIR
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")

    for name in CONFIG_FILES:
        source = base / name
        if not source.is_file():
            summary['errors'].append(f"Absent en local : {source}")
            continue

        current = remote_root / name
        try:
            unchanged = (not force and current.is_file()
                         and _sha256(current) == _sha256(source))
        except OSError as exc:
            summary['errors'].append(f"{name}: lecture distante impossible ({exc})")
            continue

        if unchanged:
            summary['unchanged'].append(name)
            continue

        # Historique AVANT d'écraser la version courante : si la copie de `current`
        # échoue, on n'a encore rien détruit.
        history.mkdir(parents=True, exist_ok=True)
        ok, _, error = copy_file(source, history / f"{name}.{stamp}")
        if not ok:
            summary['errors'].append(f"{name}: historique impossible ({error})")
            continue

        ok, _, error = copy_file(source, current)
        if ok:
            summary['copied'].append(name)
            purge_keep_latest(history, f"{name}.*", keep)
        else:
            summary['errors'].append(f"{name}: copie impossible ({error})")

    logger.info("[config_backup] %s", summary)
    return summary

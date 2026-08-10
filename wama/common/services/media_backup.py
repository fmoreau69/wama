"""
Sauvegarde des MÉDIAS utilisateurs vers l'espace distant — `media/` → NAS `DEEP_LEARNING/MEDIAS`.

Troisième domaine sauvegardé, après les modèles (`model_manager/services/remote_backup.py`)
et la base (`model_manager/management/commands/backup_db.py`). Toute la mécanique de copie
vient de la brique commune `mirror_sync` : ce module ne porte que les spécificités médias.

SENS UNIQUE — le dossier `~Archives` du NAS
===========================================
Le distant contenait déjà un espace de sauvegarde médias. Le 2026-08-10, Fabien en a
archivé le contenu sous `~Archives/` puis a copié `media/` à côté — les deux arbres sont
donc déjà cohérents, ce qui évite un premier transfert massif.

`~Archives` n'existe PAS en local. Comme le miroir n'itère que sur les fichiers locaux et
ne supprime jamais rien à distance, ce dossier est préservé **par construction** : aucune
liste d'exclusion n'est nécessaire, et il ne faut surtout pas en ajouter une « par
prudence » (elle donnerait l'illusion que le mécanisme protège quelque chose qu'il ne
regarde de toute façon jamais).

VOLUMÉTRIE
==========
Opération potentiellement longue (beaucoup de petits fichiers sur un montage réseau) :
à n'appeler QUE depuis une tâche Celery. Voir `common.backup_media` dans `common/tasks.py`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

from wama.common.services.mirror_sync import (
    mirror_tree,
    new_summary,
    remote_is_available,
    resolve_remote_root,
)

logger = logging.getLogger(__name__)

#: Sous-dossier de l'espace distant. Surchargeable pour un montage non standard.
REMOTE_SUBDIR = "MEDIAS"
REMOTE_ENV_VAR = "WAMA_MEDIA_BACKUP_PATH"


def media_root() -> Path:
    """Racine locale des médias (`settings.MEDIA_ROOT`)."""
    return Path(settings.MEDIA_ROOT)


def remote_media_path() -> str:
    """Espace distant des médias, du bon côté de la frontière WSL/Windows."""
    return resolve_remote_root(REMOTE_SUBDIR, env_var=REMOTE_ENV_VAR)


def get_status() -> dict:
    """
    État du service — VOLONTAIREMENT LÉGER.

    Aucun parcours de l'arbre distant : côté modèles, un `rglob` + `stat` complet sur le
    montage 9p prenait ~140 s et faisait tomber Apache en 502 avant la réponse. Un
    endpoint de statut ne doit jamais toucher au réseau plus que nécessaire.
    """
    remote = remote_media_path()
    return {
        'available': remote_is_available(remote),
        'remote_path': remote,
        'local_path': str(media_root()),
    }


def backup_all_media(overwrite: bool = False, progress_cb=None) -> dict:
    """
    Miroir incrémental `media/` → distant. Sens unique, aucune suppression distante.

    Args:
        overwrite: si True, recopie même les fichiers déjà présents (resync complet).
        progress_cb: callable(dict) appelé périodiquement avec l'avancement.

    Returns: dict de synthèse (clés de `mirror_sync.new_summary`).
    """
    remote = remote_media_path()
    root = media_root()

    if not root.is_dir():
        summary = new_summary(remote)
        summary['errors'].append(f"Racine locale des médias introuvable : {root}")
        return summary

    logger.info("[media_backup] miroir %s → %s (overwrite=%s)", root, remote, overwrite)
    return mirror_tree(root, remote, overwrite=overwrite, progress_cb=progress_cb)

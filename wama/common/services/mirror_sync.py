"""
Miroir incrémental d'une arborescence locale vers un espace distant — brique COMMUNE.

POURQUOI ICI (extrait le 2026-08-10)
====================================
Ce moteur vivait dans `model_manager/services/remote_backup.py`, câblé en dur sur
`AI-models/models/`. Au moment d'ajouter la sauvegarde des MÉDIAS, la règle
« zéro duplication » interdisait d'en recopier la boucle : elle est donc extraite
ici, et les deux domaines l'appellent — modèles (`remote_backup.backup_all_models`)
et médias (`common/services/media_backup.py`). Un troisième domaine s'y branchera
sans écrire une ligne de copie.

DOCTRINE — SENS UNIQUE, JAMAIS DE SUPPRESSION DISTANTE
======================================================
Ce n'est PAS un miroir d'état : on itère sur les fichiers LOCAUX uniquement. Un
fichier présent à distance et absent en local n'est jamais visité, donc jamais
supprimé. Le distant est une **archive cumulative**.

C'est voulu et structurant, pour deux raisons éprouvées :
  - côté modèles, après une conversion .pt → .onnx le local ne garde que le .onnx
    tandis que le distant conserve les deux formats ;
  - côté médias, le dossier `~Archives` du NAS (contenu antérieur mis de côté par
    Fabien le 2026-08-10) n'existe pas en local — il est donc préservé **par
    construction**, sans avoir besoin d'une liste d'exclusions.

N'ajoutez JAMAIS de passe de purge « pour synchroniser » : elle effacerait
précisément ce que cette archive existe pour conserver.

INCRÉMENTAL
===========
Un fichier déjà présent avec la MÊME TAILLE est sauté sans être relu. Indispensable :
côté modèles ~335 Go pour ~325 Go déjà distants, et chaque `stat()` sur un montage
réseau (9p/CIFS) coûte un aller-retour.

La taille — et non la date — parce que `copy2` préserve le mtime mais que les
horloges et les résolutions de mtime diffèrent entre ext4, 9p et le NAS : comparer
les dates produisait des recopies fantômes. Un fichier modifié à taille identique
échappe donc au miroir ; c'est un compromis assumé, `overwrite=True` force le resync.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

#: Au-delà, on cesse d'accumuler le détail : un summary sérialisé en cache Redis et
#: réaffiché dans l'UI ne doit pas enfler avec des milliers de lignes d'erreur.
MAX_ERRORS = 20

#: Publication de l'avancement tous les N fichiers — assez fin pour une barre fluide,
#: assez rare pour ne pas marteler Redis sur des dizaines de milliers de fichiers.
PROGRESS_EVERY = 200


#: Racine de l'espace de sauvegarde, des deux côtés de la frontière WSL/Windows.
#: Le partage `\\vrlescot\SAVES` est monté sur `/mnt/shares/SAVES` côté WSL2.
_REMOTE_ROOT_WSL = "/mnt/shares/SAVES/DEEP_LEARNING"
_REMOTE_ROOT_WIN = r"\\vrlescot\SAVES\DEEP_LEARNING"


def _is_wsl() -> bool:
    proc_version = Path("/proc/version")
    try:
        return "microsoft" in proc_version.read_text().lower()
    except OSError:
        return False


def resolve_remote_root(subdir: str, env_var: str | None = None) -> str:
    """
    Chemin de l'espace distant pour un domaine (`MODELS`, `DB`, `MEDIAS`…).

    Auto-détecte le côté de la frontière plutôt que d'exiger une variable
    d'environnement : un chemin UNC est inutilisable depuis WSL2 tant que le partage
    n'est pas monté, et l'inverse vaut côté Windows. `env_var` reste prioritaire pour
    les cas particuliers (montage ailleurs, tests).

    Convention déjà appliquée par `backup_db` depuis le 27/07 ; centralisée ici le
    10/08 au moment d'ajouter les médias, pour ne pas en avoir une 3ᵉ copie.
    """
    if env_var:
        override = os.environ.get(env_var)
        if override:
            return override
    root = _REMOTE_ROOT_WSL if _is_wsl() else _REMOTE_ROOT_WIN
    return str(Path(root) / subdir) if _is_wsl() else f"{root}\\{subdir}"


def remote_is_available(remote_path) -> bool:
    """
    L'espace distant est-il utilisable EN ÉCRITURE, sans effet de bord ?

    Deux garde-fous, tous deux issus d'incidents réels :

    1. Un chemin UNC (`\\\\serveur\\partage`) hors Windows n'est pas résoluble tant que
       le partage n'est pas monté. Ne PAS tenter de le créer : Python fabriquerait un
       dossier nommé « \\\\vrlescot\\SAVES\\… » dans le répertoire courant. On désactive
       proprement à la place.

    2. On ne CRÉE jamais la racine distante ici. Créer un dossier dans une fonction
       qui s'appelle « est-ce disponible » est un effet de bord interdit — c'était la
       cause du dossier-poubelle. La racine doit préexister.
    """
    path = Path(remote_path)
    raw = str(remote_path)

    if (raw.startswith('\\\\') or raw.startswith('//')) and os.name != 'nt':
        logger.info(
            "[mirror_sync] Chemin UNC '%s' non monté hors Windows → sauvegarde désactivée. "
            "Pointer la variable d'environnement vers le point de montage.", raw
        )
        return False

    try:
        if not (path.exists() and path.is_dir()):
            return False
        probe = path / ".wama_test"
        probe.touch()
        probe.unlink()
        return True
    except OSError as exc:
        logger.warning("[mirror_sync] cible non inscriptible (%s) : %s", raw, exc)
        return False


def copy_file(source: Path, dest: Path) -> tuple[bool, float, str | None]:
    """
    PRIMITIVE DE COPIE UNIQUE du projet : crée les dossiers parents et copie.
    → (succès, Mo, erreur).

    Publique et non préfixée : `RemoteBackupService._copy_one` l'appelle aussi, pour que la
    sauvegarde PAR MODÈLE et le miroir GLOBAL n'aient pas deux façons de copier un fichier.
    """
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        return True, dest.stat().st_size / (1024 * 1024), None
    except OSError as exc:
        return False, 0.0, str(exc)


def new_summary(remote_path) -> dict:
    """
    Squelette de compte rendu, partagé par les appelants pour publier un état initial
    cohérent avant même le premier fichier.

    `processed` fait partie du summary LUI-MÊME et pas seulement des dicts d'avancement :
    le résultat final est republié tel quel en fin de tâche, et sans cette clé l'UI
    retombait sur 0 → « Terminé — 0/1149 (0 %) » alors que tout avait été traité.
    """
    return {
        'success': False, 'total_files': 0, 'processed': 0, 'copied': 0,
        'skipped': 0, 'failed': 0, 'copied_mb': 0.0, 'errors': [],
        'remote_path': str(remote_path),
    }


def mirror_tree(source_root, dest_root, *, overwrite: bool = False, exclude=None,
                dry_run: bool = False, progress_cb=None, on_file=None,
                progress_every: int = PROGRESS_EVERY) -> dict:
    """
    Réplique `source_root` vers `dest_root` en conservant l'arborescence relative.

    MOTEUR UNIQUE du projet : miroir global (modèles, médias, config), sauvegarde par
    modèle (via `on_file`) et TIRAGE (mêmes appels, source et destination inversées).

    Opération longue (des dizaines de milliers de fichiers sur un montage réseau) :
    à n'appeler QUE depuis une tâche Celery ou une commande, jamais dans le cycle
    requête/réponse.

    Args:
        source_root: racine à lire.
        dest_root:   racine à écrire (doit exister — voir `remote_is_available`).
        overwrite:   si True, recopie même les fichiers déjà présents (resync complet).
        exclude:     noms de dossiers/fichiers à ignorer, comparés à CHAQUE segment du
                     chemin relatif. Sert au TIRAGE (`~Archives` ne doit pas revenir dans
                     `media/`) ; inutile au sens sauvegarde, où le dossier n'existe pas en
                     local et n'est donc jamais visité.
        dry_run:     compte ce qui SERAIT copié sans rien écrire. Indispensable au tirage,
                     où l'on veut mesurer l'écart avant de toucher à une installation.
        progress_cb: callable(dict) — avancement agrégé, tous les `progress_every` fichiers.
        on_file:     callable(source, dest, action, size_mb, error) par fichier, avec
                     action ∈ {'copied', 'skipped', 'failed'}. Permet à un appelant de
                     produire un compte rendu détaillé sans réécrire le parcours.

    Returns: dict de synthèse (clés de `new_summary`).
    """
    summary = new_summary(dest_root)
    source_root = Path(source_root)
    dest_root = Path(dest_root)
    excluded = set(exclude or ())

    if not remote_is_available(dest_root):
        summary['errors'].append(f"Destination indisponible : {dest_root}")
        return summary
    if not source_root.is_dir():
        summary['errors'].append(f"Racine source introuvable : {source_root}")
        return summary

    # Phase 1 — inventaire de la SOURCE (disque rapide) : connaître le total AVANT de
    # copier permet un vrai pourcentage côté UI plutôt qu'un spinner aveugle.
    local_files = []
    for path in source_root.rglob('*'):
        if not path.is_file():
            continue
        if excluded and excluded.intersection(path.relative_to(source_root).parts):
            continue
        local_files.append(path)
    summary['total_files'] = len(local_files)
    if progress_cb:
        progress_cb(dict(summary, phase='copy', current=''))

    # Phase 2 — copie incrémentale.
    for index, source in enumerate(local_files, start=1):
        summary['processed'] = index   # compté AVANT tout `continue`
        dest = None
        try:
            dest = dest_root / source.relative_to(source_root)
            if not overwrite and dest.exists() and dest.stat().st_size == source.stat().st_size:
                summary['skipped'] += 1
                if on_file:
                    on_file(source, dest, 'skipped', dest.stat().st_size / (1024 * 1024), None)
            elif dry_run:
                # Compté comme « à copier » sans rien écrire : c'est ce chiffre que la
                # commande de tirage affiche avant de demander confirmation.
                summary['copied'] += 1
                summary['copied_mb'] += source.stat().st_size / (1024 * 1024)
                if on_file:
                    on_file(source, dest, 'copied', source.stat().st_size / (1024 * 1024), None)
            else:
                ok, size_mb, error = copy_file(source, dest)
                if ok:
                    summary['copied'] += 1
                    summary['copied_mb'] += size_mb
                    if on_file:
                        on_file(source, dest, 'copied', size_mb, None)
                else:
                    summary['failed'] += 1
                    if len(summary['errors']) < MAX_ERRORS:
                        summary['errors'].append(f"{source.name}: {error}")
                    if on_file:
                        on_file(source, dest, 'failed', 0.0, error)
        except (OSError, ValueError) as exc:
            # Un fichier disparu en cours de route (purge de rétention, tâche qui
            # nettoie) ne doit pas interrompre la sauvegarde des dizaines de milliers
            # d'autres : on compte l'échec et on continue.
            summary['failed'] += 1
            if len(summary['errors']) < MAX_ERRORS:
                summary['errors'].append(f"{source.name}: {exc}")
            if on_file:
                on_file(source, dest, 'failed', 0.0, str(exc))

        if progress_cb and (index % progress_every == 0 or index == summary['total_files']):
            try:
                current = str(source.relative_to(source_root))
            except ValueError:
                current = source.name
            progress_cb(dict(summary, phase='copy', current=current))

    summary['success'] = summary['failed'] == 0
    return summary


def purge_keep_latest(directory, pattern: str, keep: int) -> list[str]:
    """
    Ne conserve que les `keep` fichiers les plus récents de `directory` correspondant à
    `pattern` (glob). Le tri se fait sur le NOM, les noms étant horodatés — c'est plus fiable
    que le mtime, que `copy2` recopie depuis la source et que le NAS peut arrondir.

    Rotation par PURGE, à ne pas confondre avec le DÉCALAGE `.log.1 → .log.2` de
    `common/utils/log_rotation.py` : mécanismes distincts, motifs distincts.
    Partagée par `backup_db` (dumps) et `config_backup` (historique des secrets).
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    files = sorted(directory.glob(pattern), key=lambda p: p.name, reverse=True)
    removed = []
    for old in files[keep:]:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError:
            pass
    return removed


def run_mirror_job(runner, *, cache_key, task_id, label, ttl=24 * 3600):
    """
    Exécute un miroir en publiant son avancement dans le cache — enveloppe COMMUNE aux
    tâches Celery de sauvegarde (modèles, médias, config… et demain le tirage).

    Passer par le cache plutôt que par l'`AsyncResult` permet de retrouver une sauvegarde
    en cours après un simple F5 : le navigateur n'a plus le task_id.

    Args:
        runner: callable(progress_cb) -> summary. Le miroir proprement dit.
        cache_key: clé DISTINCTE par domaine — deux sauvegardes peuvent tourner ensemble
                   sans écraser mutuellement leur avancement.
        task_id: identifiant Celery, republié à chaque publication pour que la vue de
                 démarrage puisse vérifier auprès de Celery qu'une tâche est bien vivante.
        label: préfixe de journalisation.
    """
    from django.core.cache import cache

    def publish(state: str, payload: dict):
        # `state`/`task_id` en DERNIER : ils doivent gagner sur le contenu du summary,
        # jamais l'inverse (une clé homonyme dans le payload écraserait l'état publié).
        cache.set(cache_key, dict(payload, state=state, task_id=task_id), ttl)

    publish('RUNNING', {'phase': 'scan', 'total_files': 0, 'processed': 0,
                        'copied': 0, 'skipped': 0, 'failed': 0, 'copied_mb': 0.0})
    logger.info("[%s] démarrage", label)

    try:
        result = runner(lambda p: publish('RUNNING', p))
        publish('SUCCESS' if result['success'] else 'PARTIAL', result)
        logger.info(
            "[%s] terminé : +%s copiés, %s déjà présents, %s échecs (%.1f Mo)",
            label, result['copied'], result['skipped'], result['failed'], result['copied_mb'],
        )
        return result
    except Exception as exc:
        logger.error("[%s] échec : %s", label, exc)
        publish('FAILURE', {'errors': [str(exc)]})
        raise

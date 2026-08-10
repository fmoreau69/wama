"""
Remote Backup Service - Backup models to network storage after conversion.
"""

import logging
from pathlib import Path
from typing import Optional, List, Dict
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings

logger = logging.getLogger(__name__)

# Remote backup configuration — l'env reste PRIORITAIRE (export de `start_wama_prod.sh:52`),
# seul le DÉFAUT change : auto-détecté par la brique commune au lieu d'un UNC figé.
#
# ⚠ CE N'ÉTAIT PAS UN BUG — ne pas relire ce changement comme une réparation.
# Le bouton « Backup Models » a toujours fonctionné : gunicorn et celery sont lancés PAR
# `start_wama_prod.sh`, donc ils héritent de `WAMA_MODEL_BACKUP_PATH` et le défaut UNC
# n'était jamais atteint. Ce qui ne marchait pas, c'est l'appel depuis un contexte SANS
# cet export (shell, commande de gestion, tâche planifiée) — d'où la valeur de
# l'auto-détection, et rien de plus.
#
# Ce piège a déjà fait consigner une fausse « dette » dans PROJECT_STATUS le 2026-07-27,
# et il m'a repris le 2026-08-10 : constater `is_available() == False` dans un shell ne dit
# RIEN de l'état des process de production. Suivre la variable jusqu'à son export avant de
# conclure (règle « tracer le chaînage d'exécution »).
from wama.common.services.mirror_sync import resolve_remote_root

REMOTE_BACKUP_PATH = resolve_remote_root('MODELS', env_var='WAMA_MODEL_BACKUP_PATH')


@dataclass
class BackupResult:
    """Result of a backup operation."""
    success: bool
    source_path: str
    dest_path: str
    size_mb: float = 0
    duration_seconds: float = 0
    error: Optional[str] = None


class RemoteBackupService:
    """Service for backing up converted models to remote storage."""

    def __init__(self, remote_path: str = REMOTE_BACKUP_PATH):
        self.remote_path = Path(remote_path)
        self._is_available = None

    def is_available(self) -> bool:
        """
        Check if the remote path is accessible (résultat mémorisé).

        Les deux garde-fous (chemin UNC non monté hors Windows, jamais de création de
        la racine) vivent désormais dans la brique commune `mirror_sync` — ils sont
        identiques pour les modèles et pour les médias.
        """
        if self._is_available is None:
            from wama.common.services.mirror_sync import remote_is_available
            self._is_available = remote_is_available(self.remote_path)
        return self._is_available

    def get_backup_path(self, model_type: str, model_name: str, format_type: str) -> Path:
        r"""
        Get the destination path for a model backup.

        Structure (LEGACY / fallback uniquement) : \\remote\MODELS\{format}\{type}\{model_name}
        N'est utilisé que pour les sources HORS de AI-models/models/. Le cas normal passe par
        mirror_dest() qui réplique l'arborescence locale (voir backup_file/backup_directory).
        """
        return self.remote_path / format_type / model_type / model_name

    def _models_root(self) -> Optional[Path]:
        """Racine locale des modèles : AI-models/models/."""
        base = getattr(settings, 'AI_MODELS_DIR', None)
        return (Path(base) / 'models') if base else None

    def mirror_dest(self, source_path) -> Optional[Path]:
        """
        Destination MIROIR : réplique le chemin du modèle relatif à AI-models/models/ sous le
        remote → garantit la cohérence remote ↔ local (même arbo domaine/famille/models--org--name/
        {blobs,refs,snapshots}). Retourne None si la source est hors de AI-models/models/.
        """
        root = self._models_root()
        if not root:
            return None
        try:
            rel = Path(source_path).resolve().relative_to(root.resolve())
        except (ValueError, OSError):
            return None
        return self.remote_path / rel

    def _copy_one(self, source: Path, dest_file: Path, overwrite: bool):
        """
        Copie UN fichier et renvoie un `BackupResult` (contrat de l'API par modèle).

        La copie elle-même vient de `mirror_sync.copy_file` — primitive unique du projet.
        Ne reste ici que l'habillage `BackupResult` et la règle « déjà présent = succès
        marqué skipped », dont dépend le comptage de `api_backup_model`.
        """
        import time

        from wama.common.services.mirror_sync import copy_file

        start = time.time()
        try:
            if dest_file.exists() and not overwrite:
                return BackupResult(
                    success=True, source_path=str(source), dest_path=str(dest_file),
                    size_mb=dest_file.stat().st_size / (1024 * 1024),
                    error="File already exists (skipped)",
                )
        except OSError as exc:
            return BackupResult(success=False, source_path=str(source), dest_path="", error=str(exc))

        ok, size_mb, error = copy_file(source, dest_file)
        if not ok:
            logger.error(f"Backup copy failed: {error}")
            return BackupResult(success=False, source_path=str(source), dest_path="", error=error)
        return BackupResult(
            success=True, source_path=str(source), dest_path=str(dest_file),
            size_mb=size_mb, duration_seconds=time.time() - start,
        )

    def backup_file(
        self,
        source_path: str,
        model_type: str,
        model_name: str,
        format_type: str,
        overwrite: bool = False
    ) -> BackupResult:
        """
        Backup a single file to remote storage.

        Args:
            source_path: Path to the source file
            model_type: Type of model (diffusion, vision, speech, etc.)
            model_name: Name of the model
            format_type: Format type (safetensors, onnx, etc.)
            overwrite: Whether to overwrite existing files

        Returns:
            BackupResult with success status and details
        """
        import time
        start_time = time.time()

        source = Path(source_path)
        if not source.exists():
            return BackupResult(
                success=False,
                source_path=str(source),
                dest_path="",
                error=f"Source file not found: {source}"
            )

        if not self.is_available():
            return BackupResult(
                success=False,
                source_path=str(source),
                dest_path="",
                error=f"Remote path not accessible: {self.remote_path}"
            )

        # Destination : MIROIR de l'arbo AI-models/models/ si la source en provient,
        # sinon fallback legacy {format}/{type}/{name}.
        mirror = self.mirror_dest(source)
        if mirror is not None:
            dest_file = mirror
        else:
            dest_file = self.get_backup_path(model_type, model_name, format_type) / source.name

        logger.info(f"Backing up {source} -> {dest_file}")
        result = self._copy_one(source, dest_file, overwrite)
        if result.success and result.duration_seconds:
            logger.info(f"Backup complete: {result.size_mb:.1f} MB in {result.duration_seconds:.1f}s")
        return result

    def backup_directory(
        self,
        source_dir: str,
        model_type: str,
        model_name: str,
        format_type: str,
        file_patterns: List[str] = None,
        overwrite: bool = False
    ) -> List[BackupResult]:
        """
        Backup a directory of model files.

        Args:
            source_dir: Path to the source directory
            model_type: Type of model
            model_name: Name of the model
            format_type: Format type
            file_patterns: List of file patterns to include (e.g., ['*.safetensors', '*.json'])
            overwrite: Whether to overwrite existing files

        Returns:
            List of BackupResult for each file
        """
        source = Path(source_dir)
        if not source.exists():
            return [BackupResult(
                success=False,
                source_path=str(source),
                dest_path="",
                error=f"Source directory not found: {source}"
            )]

        results = []
        mirror_root = self.mirror_dest(source)

        if mirror_root is not None:
            # Cas normal : MIROIR RÉCURSIF — réplique TOUTE l'arbo (blobs/refs/snapshots/…)
            # exactement comme en local, à l'emplacement domaine/famille/models--org--name.
            #
            # Délègue au MOTEUR COMMUN (`mirror_tree`) depuis le 2026-08-10 : le parcours
            # récursif dupliquait celui du miroir global. Le compte rendu par fichier attendu
            # par `api_backup_model` est reconstruit via le callback `on_file`.
            #
            # ⚠ Nuance de comportement, volontaire : le saut se fait désormais sur « présent ET
            # de même taille » au lieu de « présent » seul — une copie distante tronquée est
            # donc refaite au lieu d'être conservée indéfiniment.
            from wama.common.services.mirror_sync import mirror_tree

            # `mirror_tree` REFUSE une destination inexistante — invariant volontaire qui
            # empêche de fabriquer un dossier-poubelle local quand l'UNC n'est pas monté.
            # Ici le sous-dossier du modèle n'existe pas encore au premier passage, d'où
            # sa création explicite — mais SEULEMENT après avoir vérifié que la RACINE
            # distante, elle, est bien disponible. Sans ce garde, un `mkdir` sur un chemin
            # UNC non monté recréerait exactement le bug que l'invariant évite.
            if not self.is_available():
                return [BackupResult(
                    success=False, source_path=str(source), dest_path="",
                    error=f"Remote path not accessible: {self.remote_path}",
                )]
            mirror_root.mkdir(parents=True, exist_ok=True)

            def collect(src, dst, action, size_mb, error):
                results.append(BackupResult(
                    success=action != 'failed',
                    source_path=str(src),
                    dest_path=str(dst) if action != 'failed' else "",
                    size_mb=size_mb,
                    error="File already exists (skipped)" if action == 'skipped' else error,
                ))

            mirror_tree(source, mirror_root, overwrite=overwrite, on_file=collect)
        else:
            # Fallback legacy (source hors AI-models/models/) : copie plate filtrée par patterns.
            if file_patterns is None:
                file_patterns = [
                    '*.safetensors', '*.onnx', '*.pt', '*.bin',
                    '*.json', '*.txt', 'config.*', 'tokenizer*'
                ]
            for pattern in file_patterns:
                for file_path in source.glob(pattern):
                    if file_path.is_file():
                        results.append(self.backup_file(
                            str(file_path), model_type, model_name, format_type, overwrite
                        ))

        return results

    def offload_file(self, source_path, overwrite: bool = True) -> dict:
        """
        OFFLOAD : sauvegarde un fichier sur le remote, VÉRIFIE la copie (présence + taille
        identique), puis supprime le fichier LOCAL. Destructif → utilisé uniquement sur demande
        explicite (flag). Garde-fou : ne supprime JAMAIS le local si la vérification échoue.

        Retourne {success, backed_up, verified, deleted, dest_path, freed_mb, error}.
        """
        src = Path(source_path)
        out = {'success': False, 'backed_up': False, 'verified': False,
               'deleted': False, 'dest_path': '', 'freed_mb': 0.0, 'error': None}

        if not src.exists() or not src.is_file():
            out['error'] = f"Source introuvable ou non-fichier: {src}"
            return out
        if not self.is_available():
            out['error'] = f"Remote inaccessible: {self.remote_path}"
            return out

        local_size = src.stat().st_size
        result = self.backup_file(str(src), 'unknown', src.stem, 'unknown', overwrite=overwrite)
        out['backed_up'] = result.success
        out['dest_path'] = result.dest_path
        if not result.success:
            out['error'] = result.error or "backup échoué"
            return out

        # Vérification AVANT toute suppression : le distant existe et a la même taille.
        dest = Path(result.dest_path)
        try:
            if dest.exists() and dest.stat().st_size == local_size:
                out['verified'] = True
            else:
                out['error'] = "Vérification échouée (absent ou taille différente) — local conservé"
                return out
        except OSError as e:
            out['error'] = f"Vérification impossible ({e}) — local conservé"
            return out

        # Vérifié → suppression locale sûre.
        try:
            src.unlink()
            out['deleted'] = True
            out['freed_mb'] = local_size / (1024 * 1024)
            out['success'] = True
        except OSError as e:
            out['error'] = f"Suppression locale échouée: {e}"
        return out

    def list_backups(self, format_type: str = None, model_type: str = None) -> List[Dict]:
        """
        List existing backups.

        Args:
            format_type: Filter by format type
            model_type: Filter by model type

        Returns:
            List of backup info dicts
        """
        if not self.is_available():
            return []

        backups = []

        try:
            # Iterate through format directories
            for fmt_dir in self.remote_path.iterdir():
                if not fmt_dir.is_dir():
                    continue
                if format_type and fmt_dir.name != format_type:
                    continue

                # Iterate through type directories
                for type_dir in fmt_dir.iterdir():
                    if not type_dir.is_dir():
                        continue
                    if model_type and type_dir.name != model_type:
                        continue

                    # Iterate through model directories
                    for model_dir in type_dir.iterdir():
                        if not model_dir.is_dir():
                            continue

                        # UN SEUL parcours récursif + UN SEUL stat() par fichier : sur un
                        # montage réseau (9p/CIFS) chaque appel coûte un aller-retour, donc
                        # les 3 rglob() séparés d'avant triplaient une opération déjà lente.
                        total_size = 0
                        mtime = 0.0
                        file_count = 0
                        for f in model_dir.rglob('*'):
                            if not f.is_file():
                                continue
                            st = f.stat()
                            total_size += st.st_size
                            mtime = max(mtime, st.st_mtime)
                            file_count += 1

                        backups.append({
                            'format': fmt_dir.name,
                            'type': type_dir.name,
                            'name': model_dir.name,
                            'path': str(model_dir),
                            'size_mb': total_size / (1024 * 1024),
                            'modified': datetime.fromtimestamp(mtime).isoformat() if mtime else None,
                            'file_count': file_count,
                        })

        except Exception as e:
            logger.error(f"Error listing backups: {e}")

        return backups

    def count_backups(self) -> int:
        r"""
        Nombre de modèles sauvegardés — VERSION LÉGÈRE : ne descend QUE dans les 3 niveaux
        de dossiers, sans jamais stat() les fichiers. Indispensable pour un endpoint de
        statut : `list_backups()` fait un rglob+stat sur tout l'arbre distant (≈140 s sur le
        montage 9p \\vrlescot\SAVES → Apache coupait en 502 avant la réponse).
        """
        if not self.is_available():
            return 0
        count = 0
        try:
            for fmt_dir in self.remote_path.iterdir():
                if not fmt_dir.is_dir():
                    continue
                for type_dir in fmt_dir.iterdir():
                    if not type_dir.is_dir():
                        continue
                    for model_dir in type_dir.iterdir():
                        if model_dir.is_dir():
                            count += 1
        except Exception as e:
            logger.error(f"Error counting backups: {e}")
        return count

    def get_status(self) -> Dict:
        """Get backup service status (léger — voir count_backups)."""
        return {
            'available': self.is_available(),
            'remote_path': str(self.remote_path),
            'backup_count': self.count_backups(),
        }

    def backup_all_models(self, overwrite: bool = False, progress_cb=None) -> Dict:
        """
        SAUVEGARDE GLOBALE INCRÉMENTALE de AI-models/models/ vers l'espace distant.

        ⚠ SENS UNIQUE, JAMAIS DE SUPPRESSION DISTANTE. Ce n'est PAS un miroir d'état :
        seuls les CHEMINS sont répliqués (mirror_dest → même arborescence
        domaine/famille/models--org--name/{blobs,refs,snapshots}), pas le contenu du
        dossier. On itère sur les fichiers LOCAUX uniquement : un fichier présent sur le
        distant et absent en local n'est jamais visité, donc jamais supprimé.

        C'est VOULU et structurant : le distant est une ARCHIVE CUMULATIVE. Après une
        conversion .pt → .onnx, le local ne garde que le .onnx tandis que le distant
        conserve les deux. N'ajoutez JAMAIS de passe de prune « pour synchroniser » :
        elle effacerait précisément les formats d'origine que cette archive existe pour
        conserver (voir aussi FormatConverter._retire_source).

        INCRÉMENTAL : un fichier déjà présent à l'identique (même taille) est sauté sans
        être relu — indispensable, le local fait ~335 Go pour ~325 Go déjà distants.

        Opération longue (des dizaines de milliers de fichiers sur un montage réseau) :
        à n'appeler QUE depuis une tâche Celery, jamais dans le cycle requête/réponse.

        Args:
            overwrite: si True, recopie même les fichiers déjà présents (resync complet).
            progress_cb: callable(dict) appelé périodiquement avec l'avancement.

        Returns: dict de synthèse (voir clés ci-dessous).
        """
        # La MÉCANIQUE (inventaire, saut par taille identique, copie, avancement, plafond
        # d'erreurs) vit dans `common/services/mirror_sync.py` depuis le 2026-08-10 : elle est
        # rigoureusement la même pour les modèles et pour les médias, et la dupliquer aurait
        # été le doublon silencieux que la règle « zéro duplication » vise. Ne restent ici que
        # les SPÉCIFICITÉS modèles : la racine `AI-models/models/`.
        from wama.common.services.mirror_sync import mirror_tree, new_summary

        root = self._models_root()
        if not root or not Path(root).exists():
            summary = new_summary(self.remote_path)
            summary['errors'].append(f"Racine locale des modèles introuvable : {root}")
            return summary

        return mirror_tree(root, self.remote_path, overwrite=overwrite, progress_cb=progress_cb)


# Singleton instance
_backup_service: Optional[RemoteBackupService] = None


def get_backup_service() -> RemoteBackupService:
    """Get the singleton backup service instance."""
    global _backup_service
    if _backup_service is None:
        _backup_service = RemoteBackupService()
    return _backup_service

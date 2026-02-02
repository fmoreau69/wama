"""
Remote Backup Service - Backup models to network storage after conversion.
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Optional, List, Dict
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings

logger = logging.getLogger(__name__)

# Remote backup configuration
REMOTE_BACKUP_PATH = r"\\vrlescot\SAVES\DEEP_LEARNING\MODELS"


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
        """Check if the remote path is accessible."""
        if self._is_available is not None:
            return self._is_available

        try:
            # Try to access the remote path
            if self.remote_path.exists():
                # Try to list contents (verifies read access)
                list(self.remote_path.iterdir())
                self._is_available = True
            else:
                # Try to create a test file (verifies write access)
                test_file = self.remote_path / ".wama_test"
                try:
                    self.remote_path.mkdir(parents=True, exist_ok=True)
                    test_file.touch()
                    test_file.unlink()
                    self._is_available = True
                except Exception:
                    self._is_available = False
        except Exception as e:
            logger.warning(f"Remote backup path not accessible: {e}")
            self._is_available = False

        return self._is_available

    def get_backup_path(self, model_type: str, model_name: str, format_type: str) -> Path:
        """
        Get the destination path for a model backup.

        Structure: \\remote\MODELS\{format}\{type}\{model_name}
        Example: \\remote\MODELS\safetensors\diffusion\stable-diffusion-v1-5
        """
        return self.remote_path / format_type / model_type / model_name

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

        try:
            # Create destination directory
            dest_dir = self.get_backup_path(model_type, model_name, format_type)
            dest_dir.mkdir(parents=True, exist_ok=True)

            # Destination file path
            dest_file = dest_dir / source.name

            # Check if already exists
            if dest_file.exists() and not overwrite:
                return BackupResult(
                    success=True,
                    source_path=str(source),
                    dest_path=str(dest_file),
                    size_mb=dest_file.stat().st_size / (1024 * 1024),
                    error="File already exists (skipped)"
                )

            # Copy file
            logger.info(f"Backing up {source} to {dest_file}")
            shutil.copy2(source, dest_file)

            duration = time.time() - start_time
            size_mb = dest_file.stat().st_size / (1024 * 1024)

            logger.info(f"Backup complete: {size_mb:.1f} MB in {duration:.1f}s")

            return BackupResult(
                success=True,
                source_path=str(source),
                dest_path=str(dest_file),
                size_mb=size_mb,
                duration_seconds=duration
            )

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return BackupResult(
                success=False,
                source_path=str(source),
                dest_path="",
                error=str(e)
            )

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

        # Default patterns for model files
        if file_patterns is None:
            file_patterns = [
                '*.safetensors', '*.onnx', '*.pt', '*.bin',
                '*.json', '*.txt', 'config.*', 'tokenizer*'
            ]

        # Find all matching files
        for pattern in file_patterns:
            for file_path in source.glob(pattern):
                if file_path.is_file():
                    result = self.backup_file(
                        str(file_path),
                        model_type,
                        model_name,
                        format_type,
                        overwrite
                    )
                    results.append(result)

        return results

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

                        # Calculate total size
                        total_size = sum(
                            f.stat().st_size
                            for f in model_dir.rglob('*')
                            if f.is_file()
                        )

                        # Get modification time
                        mtime = max(
                            (f.stat().st_mtime for f in model_dir.rglob('*') if f.is_file()),
                            default=0
                        )

                        backups.append({
                            'format': fmt_dir.name,
                            'type': type_dir.name,
                            'name': model_dir.name,
                            'path': str(model_dir),
                            'size_mb': total_size / (1024 * 1024),
                            'modified': datetime.fromtimestamp(mtime).isoformat() if mtime else None,
                            'file_count': sum(1 for _ in model_dir.rglob('*') if _.is_file())
                        })

        except Exception as e:
            logger.error(f"Error listing backups: {e}")

        return backups

    def get_status(self) -> Dict:
        """Get backup service status."""
        return {
            'available': self.is_available(),
            'remote_path': str(self.remote_path),
            'backup_count': len(self.list_backups()) if self.is_available() else 0,
        }


# Singleton instance
_backup_service: Optional[RemoteBackupService] = None


def get_backup_service() -> RemoteBackupService:
    """Get the singleton backup service instance."""
    global _backup_service
    if _backup_service is None:
        _backup_service = RemoteBackupService()
    return _backup_service

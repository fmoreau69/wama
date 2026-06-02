"""
WAMA Converter — Archive Backend

Repacks an archive into another archive format (extract → recompress).

    Input  : zip, tar, tar.gz/tgz, tar.bz2, tar.xz, 7z, rar (read-only)
    Output : zip, tar, tar.gz, tar.bz2, tar.xz, 7z

Stdlib covers zip + all tar variants. 7z needs `py7zr` (optional), rar input
needs `rarfile` + an `unrar` binary (optional). Missing optional deps raise a
clear error only when that specific format is requested.
"""

import logging
import os
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Output format → tarfile open mode (None = not a tar variant)
_TAR_MODES = {
    'tar':     'w',
    'tar.gz':  'w:gz',
    'tar.bz2': 'w:bz2',
    'tar.xz':  'w:xz',
}


def _extract_to(src: str, dest_dir: str) -> None:
    """Extract any supported archive into dest_dir (auto-detects the type)."""
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as zf:
            zf.extractall(dest_dir)
        return
    if tarfile.is_tarfile(src):
        with tarfile.open(src) as tf:
            tf.extractall(dest_dir)
        return
    # 7z
    try:
        import py7zr
        if py7zr.is_7zfile(src):
            with py7zr.SevenZipFile(src, mode='r') as z:
                z.extractall(path=dest_dir)
            return
    except ImportError:
        pass
    # rar (read-only)
    if str(src).lower().endswith('.rar'):
        try:
            import rarfile
            with rarfile.RarFile(src) as rf:
                rf.extractall(dest_dir)
            return
        except ImportError as exc:
            raise RuntimeError(
                "Lecture .rar : installez 'rarfile' + le binaire 'unrar'."
            ) from exc
    raise RuntimeError(
        "Format d'archive en entrée non reconnu ou non supporté "
        "(7z nécessite 'py7zr', rar nécessite 'rarfile')."
    )


def _repack(src_dir: str, output_path: str, output_format: str) -> None:
    """Pack the contents of src_dir into output_path in the target format."""
    fmt = output_format.lower()
    src = Path(src_dir)

    if fmt == 'zip':
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for p in src.rglob('*'):
                if p.is_file():
                    zf.write(p, p.relative_to(src))
        return

    if fmt in _TAR_MODES:
        with tarfile.open(output_path, _TAR_MODES[fmt]) as tf:
            for p in src.iterdir():
                tf.add(p, arcname=p.name)
        return

    if fmt == '7z':
        try:
            import py7zr
        except ImportError as exc:
            raise RuntimeError("Sortie .7z : installez 'py7zr' (pip install py7zr).") from exc
        with py7zr.SevenZipFile(output_path, 'w') as z:
            for p in src.iterdir():
                z.writeall(p, arcname=p.name)
        return

    raise ValueError(f"Format d'archive en sortie non supporté : {output_format}")


def convert_archive(input_path: str, output_path: str, output_format: str,
                    options: dict = None, progress_callback=None) -> None:
    """Extract `input_path` and repack its contents into `output_format`."""
    tmp_dir = tempfile.mkdtemp(prefix='wama_archive_')
    try:
        if progress_callback:
            progress_callback(10)
        _extract_to(input_path, tmp_dir)
        if progress_callback:
            progress_callback(55)
        _repack(tmp_dir, output_path, output_format)
        if progress_callback:
            progress_callback(95)
        if not os.path.exists(output_path):
            raise RuntimeError(f"Archive de sortie introuvable : {output_path}")
        logger.info(f"Archive convertie : {input_path} → {output_path} [{output_format}]")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

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


class HostileArchive(ValueError):
    """Une archive dont un membre sortirait du dossier d'extraction (nom absolu, `..`, lien)."""


def _check_member_names(names) -> None:
    """Refuse une archive dont un membre, par son NOM, sortirait du dossier d'extraction. Pour les
    formats que la bibliothèque standard ne filtre pas elle-même (7z, rar), c'est la seule garde
    possible avant d'extraire. Le converter est ouvert au visiteur sans compte (2026-11-06)."""
    for name in names:
        clean = str(name).replace('\\', '/')
        if clean.startswith('/') or (len(clean) > 1 and clean[1] == ':') or '..' in clean.split('/'):
            raise HostileArchive(f"Archive refusée : le membre « {name} » sortirait du dossier "
                                 "d'extraction.")


def _extract_to(src: str, dest_dir: str) -> None:
    """Extract any supported archive into dest_dir (auto-detects the type).

    Une archive est un fichier DÉPOSÉ par l'utilisateur — par un visiteur sans compte, le converter
    étant public — : aucun membre ne doit écrire hors de `dest_dir` ni y poser un lien symbolique
    (relu ensuite par `_repack`, qui suit les liens — mesuré le 2026-11-06, audit de sécurité).
    `zipfile` neutralise déjà les noms absolus et `..` ; `tarfile` ne le fait qu'avec le filtre
    `data` (le défaut de Python 3.12 est `fully_trusted`) ; 7z et rar sont jugés sur leurs noms.
    """
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as zf:
            zf.extractall(dest_dir)
        _drop_links(dest_dir)
        return
    if tarfile.is_tarfile(src):
        with tarfile.open(src) as tf:
            try:
                tf.extractall(dest_dir, filter='data')
            except tarfile.FilterError as exc:
                raise HostileArchive(f"Archive refusée : {exc}") from exc
        _drop_links(dest_dir)
        return
    # 7z
    try:
        import py7zr
        if py7zr.is_7zfile(src):
            with py7zr.SevenZipFile(src, mode='r') as z:
                _check_member_names(z.getnames())
                z.extractall(path=dest_dir)
            _drop_links(dest_dir)
            return
    except ImportError:
        pass
    # rar (read-only)
    if str(src).lower().endswith('.rar'):
        try:
            import rarfile
            with rarfile.RarFile(src) as rf:
                _check_member_names(rf.namelist())
                rf.extractall(dest_dir)
            _drop_links(dest_dir)
            return
        except ImportError as exc:
            raise RuntimeError(
                "Lecture .rar : installez 'rarfile' + le binaire 'unrar'."
            ) from exc
    raise RuntimeError(
        "Format d'archive en entrée non reconnu ou non supporté "
        "(7z nécessite 'py7zr', rar nécessite 'rarfile')."
    )


def _drop_links(dest_dir: str) -> None:
    """Retire tout lien symbolique déposé par l'extraction : `_repack` lit ce qu'un lien VISE
    (`Path.is_file()` et `ZipFile.write` suivent les liens) — un lien vers un fichier du serveur
    en mettrait le contenu dans l'archive de sortie, téléchargeable."""
    for root, dirs, files in os.walk(dest_dir):
        for name in dirs + files:
            path = os.path.join(root, name)
            if os.path.islink(path):
                os.unlink(path)
                logger.warning(f"Archive : lien symbolique « {name} » retiré de l'extraction")


def _repack(src_dir: str, output_path: str, output_format: str) -> None:
    """Pack the contents of src_dir into output_path in the target format."""
    fmt = output_format.lower()
    src = Path(src_dir)

    if fmt == 'zip':
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for p in src.rglob('*'):
                if p.is_file() and not p.is_symlink():
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

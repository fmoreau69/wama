"""Kinds de manifeste fournis. L'import peuple `MANIFEST_KINDS` (effet de bord)."""

from . import app as _app  # noqa: F401  (register_kind au chargement)

__all__ = ['_app']

"""Kinds de manifeste fournis. L'import peuple `MANIFEST_KINDS` (effet de bord)."""

from . import app as _app        # noqa: F401  (register_kind au chargement)
from . import dataset as _dataset  # noqa: F401
from . import model as _model      # noqa: F401

__all__ = ['_app', '_dataset', '_model']

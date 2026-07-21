"""Kinds de manifeste fournis. L'import peuple `MANIFEST_KINDS` (effet de bord)."""

from . import app as _app          # noqa: F401  (register_kind au chargement)
from . import dataset as _dataset  # noqa: F401
from . import model as _model      # noqa: F401
from . import pipeline as _pipeline  # noqa: F401
from . import project as _project  # noqa: F401
from . import function as _function  # noqa: F401

__all__ = ['_app', '_dataset', '_model', '_pipeline', '_project', '_function']

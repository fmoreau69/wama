"""io/ — ingest & RESTITUTION de formats (WAMA Data).

L'ingest (`rtmaps_rec`) fait entrer un format source ; l'export (`export`) fait sortir un corpus.
Même domaine, sens inverse — les loger ensemble évite un domaine à un seul module.
"""
from .rtmaps_rec import parse_rec  # noqa: F401
from . import export               # noqa: F401  (l'import enregistre le FunctionSpec)

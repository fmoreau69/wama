"""io/ — ingest & parsing de formats source, et SORTIE de fichiers (WAMA Data)."""
from .rtmaps_rec import parse_rec  # noqa: F401
#: ⚠ `export` n'enregistre AUCUN `FunctionSpec` — un puits n'a pas de `FunctionCategory` et la
#: question relève de la décision D13. L'import ne sert donc qu'à la découvrabilité du module.
from . import export  # noqa: F401

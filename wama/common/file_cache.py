"""
Cache par EMPREINTE de fichier — une valeur calculée depuis un fichier, gardée tant que le
fichier n'a pas changé.

POURQUOI UNE BRIQUE (2026-09-14)

    Le même geste vivait en dur dans le catalogue des docs (compte de lignes, rendu markdown), et
    manquait là où il coûtait le plus : l'inventaire des backends relisait par AST les mêmes
    fichiers à chaque résolution — 48 fois, soit 6 237 analyses, pour UNE extraction du manifeste
    de l'anonymizer (mesuré ce jour, ~12 s sur 21). Trois copies d'un idiome = une brique.

L'EMPREINTE : (date de modification en nanosecondes, taille)

    Un fichier modifié est RELU — jamais servi périmé. La valeur reste donc DÉRIVÉE : le cache
    n'est qu'une mémoire du dernier calcul pour la même empreinte, pas une copie à entretenir.
    ⚠ À ne pas employer pour ce qui dépend d'autre chose que le fichier (une base, un réglage) :
    l'empreinte ne le verrait pas changer.

Mémoire du PROCESSUS : chaque worker a la sienne, rien n'est partagé ni écrit sur disque.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Hashable, Optional


def file_stamp(path) -> Optional[tuple]:
    """`(mtime_ns, taille)` du fichier (ou du dossier), `None` s'il est illisible."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


class FileCache:
    """`get(chemin, calcul)` : `calcul(chemin)` n'est rappelé que si l'empreinte a changé.

    Un fichier absent lève `OSError` (comme le ferait sa lecture) : c'est à l'appelant de dire
    ce que vaut une absence, le cache ne l'invente pas.
    """

    def __init__(self):
        self._data: dict = {}

    def get(self, path, compute: Callable, key: Optional[Hashable] = None):
        chemin = Path(path)
        st = chemin.stat()
        empreinte = (st.st_mtime_ns, st.st_size)
        cle = str(chemin) if key is None else key
        hit = self._data.get(cle)
        if hit is not None and hit[0] == empreinte:
            return hit[1]
        valeur = compute(chemin)
        self._data[cle] = (empreinte, valeur)
        return valeur

    def clear(self) -> None:
        self._data.clear()

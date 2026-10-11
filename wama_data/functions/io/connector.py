"""
Adaptateur du CONNECTOR — une base déjà constituée (`.wdat`, `.trip`, `.rec`…) branchée SANS copie.

Décision de Fabien (`WAMA_DATA_WORLD §7` du 19/08, `§11.5` du 24/08) : l'IMPORTER rassemble des
fichiers volants dans un nouveau `.wdat` ; le CONNECTOR connecte une base existante, telle qu'elle
est, là où elle est — un fichier, ou un dossier de fichiers de travail parcouru récursivement (une
passation, une expérimentation). On RÉFÉRENCE, on n'absorbe pas (`§13.16`).

Aucune lecture de format ici : le registre des lecteurs (`sources/`) sait lire, `frames.py` sait
convertir en `TypedFrame`. Ce module ne fait que les ENCHAÎNER, paresseusement :
  • `connect()` ne fait qu'un INVENTAIRE (`probe`) — une base réelle pèse 1,28 Go (§6.7) ;
  • `ConnectedLot.frames(streams)` ne lit que les flux demandés, au moment où un consommateur
    (l'export, un process) les demande.

Le LOT est l'unité de l'Exporter (`core/export.py`, un lot = un essai = un fichier, §11.6) : son
nom est celui du fichier, ses méta sont les attributs que le lecteur déclare, et `trip_id` y vaut le
nom du fichier quand la base n'en déclare pas — c'est le champ d'identité par défaut de l'export
(`Identity`), sans lequel une concaténation entre lots ne dit plus d'où vient une ligne.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from wama.common.catalog.data_types import TypedFrame

__all__ = ['ConnectedLot', 'connect', 'connectable']


@dataclass
class ConnectedLot:
    """Une base connectée : où elle est, ce qu'elle contient, ses méta — pas encore ses données."""
    name: str
    path: str
    format: str
    streams: List[str]
    meta: Dict[str, Any] = field(default_factory=dict)
    #: Ce qui a été CONNECTÉ — le fichier lui-même, ou le dossier parcouru. C'est « le dossier d'où
    #: viennent les données » de la règle d'export (§11.1) : pour un dossier connecté, ce dossier,
    #: pas celui du premier fichier trouvé dedans.
    root: str = ''

    @property
    def home(self) -> Path:
        """Le dossier d'où viennent les données (destination d'export par défaut)."""
        root = Path(self.root or self.path)
        return root if root.is_dir() else root.parent

    def frames(self, streams: Optional[Iterable[str]] = None) -> Dict[str, TypedFrame]:
        """Les flux demandés (tous si `None`), en `TypedFrame`, en temps de session.

        Un flux absent de la base est REFUSÉ en le nommant : le rendre vide ferait sortir un export
        amputé d'une colonne sans un mot."""
        from ... import sources
        from ...frames import frame_from_referential
        wanted = list(dict.fromkeys(streams)) if streams is not None else list(self.streams)
        missing = [s for s in wanted if s not in self.streams]
        if missing:
            raise ValueError(f"« {self.name} » : flux absent(s) de la base — {', '.join(missing)} "
                             f"(présents : {', '.join(self.streams) or '— aucun'})")
        ref = sources.load(self.path, streams=wanted, name=self.name)
        return {name: frame_from_referential(ref, name) for name in wanted}

    def summary(self) -> str:
        return f"{self.name} ({self.format}, {len(self.streams)} flux)"


def connectable(path: Path) -> bool:
    """Un fichier que le Connector branche : un lecteur le lit ET en POSSÈDE la nature `dataset`.
    Un `.csv` se lit (lecteur opportuniste `tabular`) mais n'est pas une base : il relève de
    l'Importer, qui le rassemble dans un `.wdat`."""
    from ... import sources
    reader = sources.reader_for(path)
    return reader is not None and getattr(reader, 'nature', None) == 'dataset'


def _lot(path: Path, root: Path) -> ConnectedLot:
    from ... import sources
    info = sources.probe(path)
    meta = dict(info.attributes or {})
    meta.setdefault('trip_id', path.stem)
    return ConnectedLot(name=path.stem, path=str(path), format=info.format,
                        streams=list(info.streams), meta=meta, root=str(root))


def connect(path) -> List[ConnectedLot]:
    """Connecte une base (un fichier) ou un dossier de bases (parcouru récursivement, ordre stable).

    Rend toujours une LISTE de lots : un fichier en donne un, un dossier autant qu'il contient de
    bases. Un dossier sans aucune base est une erreur nommée, pas une liste vide qui laisserait la
    suite du pipeline tourner sur rien."""
    p = Path(path)
    if p.is_dir():
        files = sorted((f for f in p.rglob('*') if f.is_file() and connectable(f)),
                       key=lambda f: str(f).lower())
        if not files:
            raise ValueError(f"« {p.name} » : aucune base connectable dans ce dossier "
                             f"(formats : {', '.join(_dataset_extensions()) or '—'})")
        return [_lot(f, p) for f in files]
    if not connectable(p):
        raise ValueError(f"« {p.name} » : ce n'est pas une base connectable "
                         f"(formats : {', '.join(_dataset_extensions()) or '—'}) — un fichier "
                         "volant se rassemble par l'Importer")
    return [_lot(p, p)]


def _dataset_extensions() -> List[str]:
    from ... import sources
    return sorted({e for r in sources.READERS.values() if getattr(r, 'nature', None) == 'dataset'
                   for e in r.extensions})

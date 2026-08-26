"""
Importer UNIVERSEL de WAMA Data — un registre de capacités de lecture, pas un lecteur.

POURQUOI UN REGISTRE ET PAS UN LECTEUR
    Précision Fabien (2026-08-20) : « l'importer n'est pas qu'un importer de fichiers .rec, c'est un
    importer universel auquel on ajoute des capacités d'import progressives ». Le périmètre visé :
    LSL (`.xdf`), RTMaps (`.rec`), Rosbag (`.ros`), dataframes (`.dt`), fichiers de données
    (`.xlsx`, `.csv`, `.txt`…), et les bases `.trip` existantes.

    Conséquence de conception : **aucun format n'est privilégié dans le moteur**. Ajouter une
    capacité = enregistrer un lecteur, jamais éditer ce fichier. C'est le même geste que le registre
    de renderers de `WamaParams` — et pour la même raison : une cascade de `if format == …` rend
    l'extension impossible depuis ailleurs.

CE QUE TOUT LECTEUR DOIT RENDRE — le contrat qui rend les formats interchangeables
    Un `SourceReader` produit des `StreamSpec` : un nom, des instants, un accesseur de lignes, et
    des métadonnées déclarées. Le référentiel temporel (`temporal.py`) sait alors les aligner sans
    rien connaître du format d'origine. Un lecteur ne construit JAMAIS le référentiel lui-même.

L'HORODATAGE EST UNE DÉCISION D'INGESTION, PAR FLUX
    C'est ici, et nulle part ailleurs, qu'on décide du temps d'un échantillon. Trois stratégies
    (cf. `WAMA_DATA_WORLD.md` §6.6) — et une distinction que la confusion courante écrase :
      • `TimestampTS`   : l'horodatage porté par la donnée ;
      • `TimeOfIssueTS` : l'heure d'émission du système d'acquisition ;
      • `ResamplingTS`  : RÉ-HORODATAGE depuis une fréquence théorique — **conserve tous les
        échantillons, n'interpole RIEN**. À n'utiliser que si le pas dérive alors que l'équipement
        a une cadence connue, et **uniquement à la demande** (Fabien, 20/08).
    Le rééchantillonnage qui INTERPOLE vers une grille commune n'est PAS ici et n'est jamais
    systématique : il se fait après import, en table annexe, pour un usage précis (D10).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from ..core.temporal import Signal, SignalMeta, TemporalReferential

# ──────────────────────────────────────────────────────────────────────────────────────────────
# Horodatage — la seule couche autorisée à décider du temps d'un échantillon
# ──────────────────────────────────────────────────────────────────────────────────────────────

class Timestamper:
    """Décide l'instant d'un échantillon. Une instance par FLUX, choisie à l'import."""

    def timestamp(self, time_of_issue: float, idx: int,
                  timestamp: Optional[float] = None) -> float:
        raise NotImplementedError

    @property
    def label(self) -> str:
        return type(self).__name__


class TimestampTS(Timestamper):
    """L'horodatage porté par la donnée. Repli sur l'heure d'émission s'il manque.

    Le repli est SIGNALÉ (`missing`) plutôt que silencieux : un flux qui bascule discrètement
    d'une source de temps à l'autre produit un décalage qu'on ne saurait plus expliquer après coup.
    """

    def __init__(self):
        self.missing = 0

    def timestamp(self, time_of_issue, idx, timestamp=None):
        if timestamp is None:
            self.missing += 1
            return time_of_issue
        return timestamp


class TimeOfIssueTS(Timestamper):
    """L'heure d'émission du système d'acquisition, quoi qu'il arrive."""

    def timestamp(self, time_of_issue, idx, timestamp=None):
        return time_of_issue


class ResamplingTS(Timestamper):
    """RÉ-HORODATAGE : `origine + idx / fréquence`.

    ⚠ Le nom est trompeur (hérité) : **il ne rééchantillonne pas**. Tous les échantillons sont
    conservés, seule leur étiquette de temps est recalculée depuis la cadence théorique de
    l'équipement. Aucune valeur n'est créée ni interpolée. C'est le geste à faire quand le pas
    dérive alors qu'on connaît la cadence réelle du matériel — **sur demande explicite**.
    """

    def __init__(self, frequency: float, origin: Optional[float] = None):
        if frequency <= 0:
            raise ValueError("la fréquence de ré-horodatage doit être > 0")
        self.frequency = frequency
        self._origin = origin

    def timestamp(self, time_of_issue, idx, timestamp=None):
        if self._origin is None:
            self._origin = timestamp if timestamp is not None else time_of_issue
        return self._origin + idx / self.frequency

    @property
    def label(self) -> str:
        return f"ResamplingTS({self.frequency} Hz)"


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Contrat de lecture
# ──────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class StreamSpec:
    """Un flux tel qu'un lecteur le rend. Indépendant du format d'origine."""

    meta: SignalMeta
    times: Sequence[float]
    #: `(i0, i1) -> lignes`. Optionnel : un flux peut n'exposer que ses instants (ex. événements).
    rows: Optional[Callable[[int, int], Any]] = None
    #: Décalage vis-à-vis de la base de temps commune (médias externes non ré-horodatés).
    offset: float = 0.0
    #: Bornes de FIN si le flux est une collection de segments — sans elles, « quel segment
    #: contient t ? » est indécidable.
    ends: Optional[Sequence[float]] = None
    #: `(i0, i1, colonne) -> (min, max)` quand la source sait agréger elle-même. Une base SQL le
    #: fait sans rien transférer ; c'est ce qui rend une vue décimée fidèle abordable.
    extent: Optional[Callable[[float, float, str], Any]] = None
    #: `(t0, t1, buckets, colonne) -> {n° tranche: (min, max)}` — TOUTES les tranches en
    #: une passe. Optionnel, mais c'est le seul niveau viable pour une vue d'interface.
    extents: Optional[Callable[[float, float, int, str], Any]] = None

    def to_signal(self) -> Signal:
        return Signal(self.meta, self.times, self.rows,
                      ends=self.ends, extent=self.extent, extents=self.extents)


@dataclass
class SourceInfo:
    """Ce qu'on sait d'une source AVANT de la lire — pour proposer un import sans l'exécuter."""

    format: str
    path: str
    streams: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    media: List[Dict[str, Any]] = field(default_factory=list)
    notes: str = ''


class SourceReader:
    """Capacité d'import d'un format. À sous-classer, puis à enregistrer via `register_reader`."""

    #: Identifiant stable du format (« trip », « rtmaps », « lsl », « tabular »…).
    format = ''
    #: Extensions reconnues, en minuscules.
    extensions: tuple = ()
    description = ''

    def can_read(self, path: Path) -> bool:
        """Par défaut : sur l'extension. Un lecteur peut renifler le contenu s'il sait le faire."""
        return path.suffix.lower() in self.extensions

    def probe(self, path: Path) -> SourceInfo:
        """Inventaire SANS charger les données — ce qui permet de proposer avant d'exécuter."""
        raise NotImplementedError

    def read(self, path: Path, streams: Optional[Iterable[str]] = None,
             timestampers: Optional[Dict[str, Timestamper]] = None) -> List[StreamSpec]:
        """Lit les flux demandés (tous si `streams` est None).

        `timestampers` permet d'imposer une stratégie d'horodatage **par flux** — c'est le point
        d'entrée du ré-horodatage à la demande.
        """
        raise NotImplementedError


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Registre
# ──────────────────────────────────────────────────────────────────────────────────────────────

READERS: Dict[str, SourceReader] = {}


def register_reader(reader: SourceReader) -> SourceReader:
    if not reader.format:
        raise ValueError("un lecteur doit déclarer un `format`")
    if reader.format in READERS:
        raise ValueError(f"format '{reader.format}' déjà enregistré")
    READERS[reader.format] = reader
    return reader


def reader_for(path) -> Optional[SourceReader]:
    """Le lecteur capable de lire ce chemin, ou None. Premier enregistré qui accepte."""
    p = Path(path)
    for r in READERS.values():
        try:
            if r.can_read(p):
                return r
        except Exception:
            continue
    return None


def supported_extensions() -> List[str]:
    return sorted({e for r in READERS.values() for e in r.extensions})


def probe(path) -> SourceInfo:
    """Inventaire d'une source, quel que soit son format."""
    p = Path(path)
    r = reader_for(p)
    if r is None:
        raise ValueError(
            f"aucune capacité d'import pour '{p.name}' "
            f"(extensions connues : {', '.join(supported_extensions()) or '—'})"
        )
    return r.probe(p)


def load(path, streams=None, timestampers=None, name: str = '') -> TemporalReferential:
    """Lit une source et rend un référentiel temporel prêt à interroger.

    C'est le point d'entrée unique de l'import : l'appelant ne sait pas quel lecteur a travaillé.
    """
    p = Path(path)
    r = reader_for(p)
    if r is None:
        raise ValueError(
            f"aucune capacité d'import pour '{p.name}' "
            f"(extensions connues : {', '.join(supported_extensions()) or '—'})"
        )
    ref = TemporalReferential(name=name or p.stem)
    for spec in r.read(p, streams=streams, timestampers=timestampers):
        ref.add(spec.to_signal(), offset=spec.offset)
    return ref


def reader_modules() -> List[str]:
    """Modules de lecture du paquet — **DÉCOUVERTS, jamais cités**.

    ⚠ C'EST LE GARDE-FOU **G1** LUI-MÊME : « aucun format privilégié — le moteur ne cite aucun
    format ; **ajouter un lecteur ne le modifie pas** ». Il était en défaut : `_register_builtins`
    écrivait `from . import trip, tabular`, donc livrer un troisième lecteur obligeait à éditer le
    moteur. C'est le même anti-patron que la liste de suites nocturnes (§9quinquies.6bis) — une
    énumération là où une découverte s'impose. Troisième occurrence en deux jours.

    Domicile UNIQUE de cette découverte : le rafraîchisseur du registre (`wama_data/apps.py`)
    l'utilise aussi, au lieu d'en tenir une seconde copie.
    """
    import pkgutil
    return sorted(m.name for m in pkgutil.iter_modules(__path__)
                  if not m.name.startswith(('_', 'test')))


def _register_builtins():
    """Enregistre les lecteurs livrés, **chacun isolé des autres**.

    ⚠ L'ISOLATION ÉTAIT PROMISE ET N'EXISTAIT PAS. La docstring précédente annonçait « isolé pour
    qu'un format manquant n'empêche pas les autres (un `.trip` reste lisible même si `openpyxl`
    n'est pas installé) » — mais le code était un `from . import trip, tabular` **sans aucun
    `try`**. Une seule dépendance absente faisait donc échouer l'import du PAQUET ENTIER, donc
    tout le monde Data, pour un format optionnel. La propriété est désormais implémentée, pas
    seulement écrite.
    """
    import importlib
    for name in reader_modules():
        try:
            importlib.import_module(f'{__name__}.{name}')
        except Exception:
            logging.getLogger(__name__).warning(
                "lecteur '%s' non enregistré — les autres formats restent disponibles",
                name, exc_info=True)


_register_builtins()

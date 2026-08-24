"""
Capacité d'import : bases `.trip` (SQLite).

Format d'un framework d'analyse de données expérimentales existant, dont des jeux réels sont
disponibles. Retenu comme PREMIER lecteur pour une raison pratique : c'est le seul format dont on
dispose d'un exemplaire réel (1,28 Go, 5,26 M lignes, 6 cadences natives), donc le seul qui permette
d'éprouver le contrat d'import sur autre chose que des données inventées.

⚠ `.trip` EST UN FORMAT ÉTRANGER, PAS CELUI DE WAMA — décision **D3**, tranchée le 2026-08-23
(`WAMA_DATA_WORLD.md §9quater.2`). Le conteneur natif de WAMA Data s'appelle **`.wrec`**
(« enregistrement WAMA ») : `trip` présuppose un DÉPLACEMENT là où le besoin est une **acquisition
multi-flux datée**, et un labo qui analyse des données temporelles sans aucun trajet n'a pas à
manipuler des « trips ». Même motif que le renommage `SECTIONS` → `SEGMENTS` du 2026-08-20
(`data_types.py`), où « section » était jugé trop connoté routier.

**Ce module NE SERA PAS renommé pour autant** : il lit le format de l'autre, et l'appeler autrement
le rendrait faux. L'écrivain existe depuis le 2026-08-24 (`wama_data/containers/`), et le lecteur du
conteneur natif est `sources/wrec.py`.

⚠ CE MODULE NE PORTE PLUS QUE LA CONNAISSANCE DU SCHÉMA. Toute la mécanique SQLite — ouverture en
lecture seule, décodage du texte, colonnes, valeurs triées, les trois niveaux d'agrégation — vit
dans `_sqlite.SqliteSourceReader`, dont il hérite. Elle n'avait jamais rien dû au format de BIND ;
c'est l'arrivée du second lecteur de base qui l'a rendu visible.

Schéma (relevé sur le format, cf. `WAMA_DATA_WORLD.md` §6.2-6.3) : un catalogue de métadonnées fixe
(`MetaDatas`, `MetaDataVariables`, `MetaEvents`, `MetaSituations`, `MetaTripVideos`…) et **une table
par élément** — `data_<nom>` (colonne `timecode`), `event_<nom>` (`timecode`), `situation_<nom>`
(`startTimecode`/`endTimecode`).

⚠ La lecture est PARESSEUSE sur les valeurs : on charge les instants (nécessaires à l'indexation
temporelle) mais les lignes ne sont lues qu'à la demande, par tranche. Sur une base réelle, charger
toutes les valeurs de tous les flux dépasserait le gigaoctet pour une seule passation.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from wama.common.catalog.data_types import DataType

from ..core.temporal import NEAREST, PREVIOUS, SignalMeta
from . import SourceInfo, StreamSpec, register_reader
from ._sqlite import SqliteSourceReader

#: Préfixes de table → famille. Les situations portent DEUX bornes, d'où un traitement distinct.
_PREFIXES = {'data_': 'data', 'event_': 'event', 'situation_': 'situation'}

#: Famille de table → type de la taxonomie PARTAGÉE. Le lecteur connaissait DÉJÀ la famille (il la
#: tire du préfixe) et la jetait dans une chaîne de commentaire ; elle est désormais portée comme
#: DONNÉE, dans `SignalMeta.data_type`. Le vocabulaire vient de `DataType`, jamais recopié.
_TYPE_DE_FAMILLE = {'data': DataType.TIMESERIES, 'event': DataType.EVENTS,
                    'situation': DataType.SEGMENTS}


class TripReader(SqliteSourceReader):
    format = 'trip'
    extensions = ('.trip',)
    table_temoin = 'MetaDatas'
    description = "Base SQLite d'expérimentation (flux, événements, segments, médias liés)"

    # ── Inventaire ────────────────────────────────────────────────────────────────────────────
    def probe(self, path: Path) -> SourceInfo:
        with self._open(path) as con:
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            flux = [t for t in tables if any(t.startswith(p) for p in _PREFIXES)]

            attributs: Dict[str, Any] = {}
            try:
                attributs = {k: v for k, v in con.execute(
                    'SELECT key, value FROM "MetaTripDatas"')}
            except sqlite3.Error:
                pass

            medias: List[Dict[str, Any]] = []
            try:
                for nom, offset, desc in con.execute(
                        'SELECT filename, offset, description FROM "MetaTripVideos"'):
                    medias.append({'file': nom, 'offset': offset, 'description': desc})
            except sqlite3.Error:
                pass

            declares = {}
            try:
                for nom, typ, freq, base in con.execute(
                        'SELECT name, type, frequency, isBase FROM "MetaDatas"'):
                    declares[nom] = {'type': typ, 'frequency': freq, 'is_base': bool(base)}
            except sqlite3.Error:
                pass

        return SourceInfo(
            format=self.format, path=str(path), streams=flux,
            attributes=attributs, media=medias,
            notes=(f"{len(flux)} flux ; {len(medias)} média(s) lié(s) ; "
                   f"{len(declares)} déclaration(s) MetaDatas"),
        )

    # ── Lecture ───────────────────────────────────────────────────────────────────────────────
    def read(self, path: Path, streams: Optional[Iterable[str]] = None,
             timestampers: Optional[Dict[str, Any]] = None) -> List[StreamSpec]:
        timestampers = timestampers or {}
        info = self.probe(path)
        voulus = list(streams) if streams is not None else info.streams

        declares = self._declarations(path)
        offsets = self._media_offsets(info)
        out: List[StreamSpec] = []

        for table in voulus:
            famille = next((f for p, f in _PREFIXES.items() if table.startswith(p)), None)
            if famille is None:
                raise ValueError(f"'{table}' n'est pas un flux reconnu de cette source")
            nom = table.split('_', 1)[1]
            cols = self._columns(path, table)
            tcol = 'startTimecode' if famille == 'situation' else 'timecode'
            if tcol not in cols:
                continue   # table sans colonne temporelle : hors périmètre du référentiel

            times = self._values(path, table, tcol, tcol)
            ts = timestampers.get(table) or timestampers.get(nom)
            if ts is not None:
                # Ré-horodatage À LA DEMANDE : on conserve tous les échantillons, on recalcule
                # seulement leurs étiquettes. Jamais appliqué d'office.
                times = [ts.timestamp(t, i, t) for i, t in enumerate(times)]

            d = declares.get(nom, {})
            meta = SignalMeta(
                name=nom,
                data_type=_TYPE_DE_FAMILLE.get(famille, ''),
                fs=self._frequence(d.get('frequency')),
                is_base=d.get('is_base', True),
                # Un événement ou un segment vaut jusqu'au suivant : PREVIOUS est la sémantique
                # juste. Un signal échantillonné admet le plus proche.
                default_lookup=NEAREST if famille == 'data' else PREVIOUS,
                comments=f"{famille} · {len(cols)} colonne(s)",
            )
            # Un segment porte DEUX bornes : sans la fin, on ne peut pas répondre à « quelle
            # situation contient cet instant ? » — la question même que posent des fenêtres
            # d'analyse emboîtées.
            ends = None
            if famille == 'situation' and 'endTimecode' in cols:
                ends = self._values(path, table, 'endTimecode', tcol)

            out.append(StreamSpec(
                meta=meta, times=times, ends=ends,
                rows=self._row_accessor(path, table, tcol),
                extent=self._extent_accessor(path, table, tcol),
                extents=self._extents_accessor(path, table, tcol),
                offset=offsets.get(nom, 0.0),
            ))
        return out

    # ── Accès bas niveau ──────────────────────────────────────────────────────────────────────
    def _declarations(self, path: Path) -> Dict[str, dict]:
        try:
            with self._open(path) as con:
                return {n: {'type': t, 'frequency': f, 'is_base': bool(b)}
                        for n, t, f, b in con.execute(
                            'SELECT name, type, frequency, isBase FROM "MetaDatas"')}
        except sqlite3.Error:
            return {}

    @staticmethod
    def _media_offsets(info: SourceInfo) -> Dict[str, float]:
        """Les médias externes ne sont pas ré-horodatés : ils portent un décalage propre."""
        return {Path(m['file']).stem: float(m.get('offset') or 0.0) for m in info.media}


register_reader(TripReader())

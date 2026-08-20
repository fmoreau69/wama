"""
Capacité d'import : bases `.trip` (SQLite).

Format d'un framework d'analyse de données expérimentales existant, dont des jeux réels sont
disponibles. Retenu comme PREMIER lecteur pour une raison pratique : c'est le seul format dont on
dispose d'un exemplaire réel (1,28 Go, 5,26 M lignes, 6 cadences natives), donc le seul qui permette
d'éprouver le contrat d'import sur autre chose que des données inventées.

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

from ..temporal import NEAREST, PREVIOUS, SignalMeta
from . import SourceInfo, SourceReader, StreamSpec, register_reader

#: Préfixes de table → famille. Les situations portent DEUX bornes, d'où un traitement distinct.
_PREFIXES = {'data_': 'data', 'event_': 'event', 'situation_': 'situation'}


class TripReader(SourceReader):
    format = 'trip'
    extensions = ('.trip',)
    description = "Base SQLite d'expérimentation (flux, événements, segments, médias liés)"

    # ── Reconnaissance ────────────────────────────────────────────────────────────────────────
    def can_read(self, path: Path) -> bool:
        if path.suffix.lower() not in self.extensions:
            return False
        # On renifle le contenu : un `.trip` est un SQLite portant le catalogue attendu. Sans ça,
        # un fichier mal nommé ferait échouer l'import loin de sa cause.
        try:
            with self._open(path) as con:
                noms = {r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            return 'MetaDatas' in noms
        except Exception:
            return False

    @staticmethod
    def _open(path: Path) -> sqlite3.Connection:
        """Connexion LECTURE SEULE — on n'écrit jamais dans une source importée."""
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)

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

            times = self._times(path, table, tcol)
            ts = timestampers.get(table) or timestampers.get(nom)
            if ts is not None:
                # Ré-horodatage À LA DEMANDE : on conserve tous les échantillons, on recalcule
                # seulement leurs étiquettes. Jamais appliqué d'office.
                times = [ts.timestamp(t, i, t) for i, t in enumerate(times)]

            d = declares.get(nom, {})
            freq = d.get('frequency')
            meta = SignalMeta(
                name=nom,
                # 0 et -1 signifient « non renseigné » dans ce format : mesuré sur une base réelle,
                # le champ valait 0 pour les 10 flux. On ne fabrique pas une cadence déclarée.
                fs=float(freq) if freq not in (None, 0, -1) else None,
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
                ends = self._ends(path, table, tcol)

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

    def _columns(self, path: Path, table: str) -> List[str]:
        with self._open(path) as con:
            return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]

    def _times(self, path: Path, table: str, tcol: str) -> List[float]:
        with self._open(path) as con:
            return [r[0] for r in con.execute(
                f'SELECT "{tcol}" FROM "{table}" ORDER BY "{tcol}"')]

    def _ends(self, path: Path, table: str, tcol: str) -> List[float]:
        """Bornes de fin, dans le MÊME ordre que les débuts (tri sur la colonne de début)."""
        with self._open(path) as con:
            return [r[0] for r in con.execute(
                f'SELECT "endTimecode" FROM "{table}" ORDER BY "{tcol}"')]

    def _extent_accessor(self, path: Path, table: str, tcol: str):
        """Rend `(t0, t1, colonne) -> (min, max)` calculé EN SQL, borné par le TEMPS.

        ⚠ Borné par le temps, PAS par l'index — leçon d'une première version mesurée inutilisable.
        Agréger par `LIMIT n OFFSET k` oblige SQLite à re-parcourir depuis le début à chaque appel :
        sur 2 M de lignes et 2000 tranches, le coût devient quadratique et la vue décimée ne rend
        jamais la main. Une borne temporelle, elle, exploite l'index sur la colonne de temps —
        c'est justement pour ça que ce format crée un index par colonne.

        La colonne est validée contre le schéma réel avant d'être interpolée dans la requête : un
        nom venant de l'appelant ne doit jamais atterrir tel quel dans du SQL.
        """
        colonnes = set(self._columns(path, table))

        def extent(t0: float, t1: float, column: str):
            if column not in colonnes or t1 <= t0:
                return (None, None)
            with self._open(path) as con:
                row = con.execute(
                    f'SELECT MIN("{column}"), MAX("{column}") FROM "{table}" '
                    f'WHERE "{tcol}" >= ? AND "{tcol}" < ?', (t0, t1)).fetchone()
            return (row[0], row[1]) if row else (None, None)

        return extent

    def _extents_accessor(self, path: Path, table: str, tcol: str):
        """Rend `(t0, t1, buckets, colonne) -> {n° de tranche: (min, max)}` — TOUTES les tranches
        en UNE requête groupée.

        Mesuré : 2000 tranches sur 2 M de lignes coûtaient 24,9 s en interrogeant tranche par
        tranche (une requête et une connexion chacune), contre ~1 s en une seule passe avec
        `GROUP BY`. Pour une vue d'interface la différence n'est pas un confort, c'est la
        viabilité. C'est aussi pourquoi le contrat prévoit cette capacité en OPTION : une source
        qui ne sait pas grouper retombe sur l'agrégation tranche par tranche, puis sur la lecture
        des lignes — trois niveaux, du plus efficace au plus universel.
        """
        colonnes = set(self._columns(path, table))

        def extents(t0: float, t1: float, buckets: int, column: str):
            if column not in colonnes or buckets <= 0 or t1 <= t0:
                return {}
            pas = (t1 - t0) / buckets
            with self._open(path) as con:
                rows = con.execute(
                    f'SELECT CAST(("{tcol}" - ?) / ? AS INTEGER) AS b, '
                    f'MIN("{column}"), MAX("{column}") FROM "{table}" '
                    f'WHERE "{tcol}" >= ? AND "{tcol}" < ? GROUP BY b',
                    (t0, pas, t0, t1)).fetchall()
            return {int(b): (lo, hi) for b, lo, hi in rows if b is not None}

        return extents

    def _row_accessor(self, path: Path, table: str, tcol: str):
        """Rend `(i0, i1) -> lignes`. Chaque appel rouvre en lecture seule : une connexion SQLite
        n'est pas sûre entre fils d'exécution, et un référentiel est destiné à être interrogé
        depuis plusieurs contextes."""
        def rows(i0: int, i1: int):
            if i1 <= i0:
                return []
            with self._open(path) as con:
                cur = con.execute(
                    f'SELECT * FROM "{table}" ORDER BY "{tcol}" LIMIT ? OFFSET ?',
                    (i1 - i0, i0))
                noms = [c[0] for c in cur.description]
                return [dict(zip(noms, r)) for r in cur.fetchall()]
        return rows


register_reader(TripReader())

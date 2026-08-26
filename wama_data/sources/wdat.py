"""
Capacité d'import : conteneurs `.wdat` — le format NATIF de WAMA Data (décision **D3**).

POURQUOI CE LECTEUR N'EST PAS OPTIONNEL
    Sans lui, `.wdat` serait **write-only**, donc inutilisable comme *fichier de travail* : on
    pourrait produire un conteneur et jamais le rouvrir. Or c'est précisément ce que le format est
    censé être — l'endroit où les traitements s'accumulent, régénérable depuis `raw_data + protocole`
    (`WAMA_DATA_WORLD §9quater.2`, §9undecies.1).

CE QU'IL LIT DE PLUS QU'UN `.trip`, ET POURQUOI ÇA COMPTE
    Le schéma natif porte comme DONNÉES quatre faits que le format de BIND connaît sans les dire :

        WamaStreams.data_type       la FAMILLE — plus besoin d'analyser un préfixe de table
        WamaStreams.losses          les pertes d'acquisition (`SignalMeta.pertes`)
        WamaStreams.offset          le décalage PAR FLUX (BIND n'a qu'un décalage par média)
        WamaVariables.unit          l'unité par colonne — le champ que `.trip` déclare, laisse
                                    vide partout, et **ne relit jamais**

    ⚠ Le quatrième est la raison d'être du reste. Un champ qu'on écrit sans jamais le relire est un
    champ absent qui ment : c'est le motif que ce dépôt a rencontré six fois en deux jours sous
    l'angle « le fait est connu et n'est pas porté ». Ici, il est écrit ET relu — un test l'exige.

L'ALLER-RETOUR EST LA SEULE PREUVE QUI VAILLE
    Un lecteur jugé sur des fixtures qu'il a lui-même inspirées ne prouve que sa cohérence interne.
    Celui-ci est éprouvé contre **ce que l'écrivain produit** : on écrit un référentiel, on le
    relit, et on compare flux par flux. C'est le garde-fou **G7** (« exercer, pas déclarer »)
    appliqué au format natif — et c'est ce qui rendra une évolution du schéma détectable au lieu
    d'être découverte à la réouverture d'un vieux fichier.

CE QU'IL NE FAIT PAS ENCORE
    ⏳ Il ne relit pas `WamaManifests` (la copie projetée du protocole) : rouvrir un conteneur ne
    doit PAS réinjecter son manifeste dans le magasin par effet de bord. Ce geste est un **ingest**,
    donc une décision d'utilisateur, et il porte un conflit possible (**D16**) qui n'a pas encore
    de garde. Les exposer sans les ingérer est le seul comportement défendable pour l'instant :
    `probe()` les COMPTE, pour qu'on sache qu'ils sont là.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..core.temporal import NEAREST, SignalMeta
from . import SourceInfo, StreamSpec, register_reader
from ._sqlite import SqliteSourceReader

#: Colonnes de temps par famille — la graphie tranchée par **D9** (`time`, `start`/`end`).
#: ⚠ Le schéma natif n'encode PAS la famille dans le nom de table : on décide donc des bornes en
#: regardant les COLONNES présentes, jamais un préfixe. C'est exactement ce que `.wdat` corrige.
DEBUT, FIN, INSTANT = 'start', 'end', 'time'


class WdatReader(SqliteSourceReader):
    format = 'wdat'
    extensions = ('.wdat',)
    table_temoin = 'WamaStreams'
    description = "Conteneur natif WAMA Data — catalogue complet, unités, pertes, protocole embarqué"

    # ── Inventaire ────────────────────────────────────────────────────────────────────────────
    def probe(self, path: Path) -> SourceInfo:
        with self._open(path) as con:
            flux = [r[0] for r in con.execute(
                'SELECT name FROM "WamaStreams" ORDER BY name')]
            attributs = dict(con.execute('SELECT key, value FROM "WamaMeta"'))
            medias = [{'file': f, 'offset': o, 'description': d} for f, o, d in con.execute(
                'SELECT file, offset, description FROM "WamaMedia"')]
            protocoles = [f'{k}:{c}' for k, c in con.execute(
                'SELECT manifest_kind, key FROM "WamaManifests" ORDER BY manifest_kind, key')]

        return SourceInfo(
            format=self.format, path=str(path), streams=flux,
            attributes=attributs, media=medias,
            notes=(f"{len(flux)} flux ; {len(medias)} média(s) lié(s) ; "
                   f"{len(protocoles)} protocole(s) embarqué(s)"
                   + (f" ({', '.join(protocoles[:3])})" if protocoles else '')
                   + f" ; schéma v{attributs.get('schema_version', '?')}"),
        )

    def protocoles(self, path: Path) -> List[Dict[str, Any]]:
        """Les COPIES PROJETÉES du conteneur — exposées, jamais ingérées d'office.

        ⚠ Rouvrir un fichier ne doit pas écrire dans le magasin de manifestes : ce serait un effet
        de bord invisible, et `ingest()` écrase `body` en silence sur `kind+key` existant (**D16**).
        L'appelant décide, avec le conflit sous les yeux.
        """
        import json
        with self._open(path) as con:
            return [{'manifest_kind': k, 'key': c, 'version': v, 'read_only': bool(ro),
                     'body': json.loads(b) if b else {}}
                    for k, c, v, ro, b in con.execute(
                        'SELECT manifest_kind, key, version, read_only, body '
                        'FROM "WamaManifests" ORDER BY manifest_kind, key')]

    # ── Lecture ───────────────────────────────────────────────────────────────────────────────
    def read(self, path: Path, streams: Optional[Iterable[str]] = None,
             timestampers: Optional[Dict[str, Any]] = None) -> List[StreamSpec]:
        timestampers = timestampers or {}
        declares = self._declarations(path)
        unites = self._unites(path)
        voulus = list(streams) if streams is not None else sorted(declares)
        out: List[StreamSpec] = []

        for name in voulus:
            d = declares.get(name)
            if d is None:
                raise ValueError(
                    f"'{name}' n'est pas un flux de cette source "
                    f"(déclarés : {', '.join(sorted(declares)) or '—'})")
            table = d['table']
            cols = self._columns(path, table)
            # La famille ne se lit PAS dans le nom : on décide sur les colonnes réellement là.
            segmente = DEBUT in cols and FIN in cols
            tcol = DEBUT if segmente else INSTANT
            if tcol not in cols:
                continue   # table sans axe temporel : hors périmètre du référentiel

            times = self._values(path, table, tcol, tcol)
            ts = timestampers.get(name) or timestampers.get(table)
            if ts is not None:
                # Ré-horodatage À LA DEMANDE — tous les échantillons conservés, seules leurs
                # étiquettes recalculées. Jamais appliqué d'office.
                times = [ts.timestamp(t, i, t) for i, t in enumerate(times)]

            meta = SignalMeta(
                name=name,
                data_type=d['data_type'],
                fs=self._frequence(d['fs']),
                pertes=int(d['losses'] or 0),
                units=unites.get(name, {}),
                is_base=d['is_base'],
                default_lookup=d['default_lookup'] or NEAREST,
                comments=d['comments'] or '',
            )
            out.append(StreamSpec(
                meta=meta, times=times,
                # ⚠ Une fin absente reste `None` — « fin NON OBSERVÉE » (D15). La refermer donnerait
                # une durée mesurée sur ce que personne n'a mesuré.
                ends=self._values(path, table, FIN, tcol) if segmente else None,
                rows=self._row_accessor(path, table, tcol),
                extent=self._extent_accessor(path, table, tcol),
                extents=self._extents_accessor(path, table, tcol),
                offset=float(d['offset'] or 0.0),
            ))
        return out

    # ── Catalogue ─────────────────────────────────────────────────────────────────────────────
    def _declarations(self, path: Path) -> Dict[str, dict]:
        with self._open(path) as con:
            return {r[0]: {'table': r[1], 'data_type': r[2] or '', 'fs': r[3],
                           'is_base': bool(r[4]), 'default_lookup': r[5], 'losses': r[6],
                           'offset': r[7], 'comments': r[9]}
                    for r in con.execute(
                        'SELECT name, table_name, data_type, fs, is_base, default_lookup, '
                        'losses, offset, rows_count, comments FROM "WamaStreams"')}

    def _unites(self, path: Path) -> Dict[str, Dict[str, str]]:
        """Unité par flux et par colonne. ⭐ C'est le fait que `.trip` porte sans jamais le relire.

        Les unités vides sont ÉCARTÉES : `SignalMeta.units` doit dire « on connaît l'unité de
        `value` », pas « on a une entrée pour chaque colonne dont la plupart ne disent rien ». Un
        dictionnaire plein de chaînes vides ne se distingue pas d'un dictionnaire renseigné.
        """
        out: Dict[str, Dict[str, str]] = {}
        with self._open(path) as con:
            for flux, column, unite in con.execute(
                    'SELECT stream, name, unit FROM "WamaVariables"'):
                if unite:
                    out.setdefault(flux, {})[column] = unite
        return out


register_reader(WdatReader())

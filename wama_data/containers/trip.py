"""
Schéma `.trip` — écriture au format de BIND, pour la COMPATIBILITÉ.

POURQUOI ON ÉCRIT LE FORMAT DE L'AUTRE
    « Pouvoir recréer des fichiers trip à partir de fichiers rec est important pour la compatibilité
    BIND » (Fabien, 2026-08-24). Le laboratoire a un outil MATLAB en service et des années de
    fichiers : produire un conteneur que cet outil sait ouvrir n'est pas une concession, c'est la
    condition pour que WAMA entre dans une chaîne existante au lieu de la remplacer d'un bloc.

    ⚠ Ce module N'EST PAS le conteneur natif — c'est `wdat.py` (**D3**). Ici on parle la langue de
    l'autre, et on **compte ce qu'elle ne sait pas dire**.

LE SCHÉMA EST RELEVÉ, PAS DEVINÉ (2026-08-24, sur la base réelle de 1,28 Go)
    Neuf tables de catalogue, dont la forme EXACTE a été mesurée avant d'écrire une ligne :

        MetaDatas            (name, type, frequency INT, comments, isBase BOOL)   ← flux `data_`
        MetaEvents           (name, comments, isBase)                             ← ⚠ PAS de frequency
        MetaSituations       (name, comments, isBase)                             ← ⚠ PAS de frequency
        MetaDataVariables      (data_name,      name, type, unit, comments)
        MetaEventVariables     (event_name,     name, type, unit, comments)
        MetaSituationVariables (situation_name, name, type, unit, comments)
        MetaTripDatas        (key, value)          MetaParticipantDatas (key, value)
        MetaTripVideos       (filename, offset DOUBLE, description)

    ⚠ Les trois tables `*Variables` comptent **la colonne de temps elle-même** parmi les variables
    (`timecode` / `startTimecode` / `endTimecode`, type `REAL`, unité vide). Reproduit tel quel :
    un outil qui itère les variables attendrait sinon une colonne de moins que la table n'en a.

    ⚠ Et le relevé a confirmé **D11** une fois de plus, sur la donnée : les 12 situations réelles se
    nomment `0_15`, `15_45`, `30_60`… — **les paramètres de fenêtre SONT le nom**. C'est ce que
    `.wdat` refuse de reconduire ; ici on l'écrit puisque c'est la langue de l'autre.

CE QUE CE SCHÉMA NE SAIT PAS PORTER — énuméré, jamais tu
    Un `.trip` produit depuis un référentiel WAMA **perd** des faits. `Rapport.pertes` les nomme un
    par un. Le pire cas n'est pas la perte, c'est la perte silencieuse : elle laisse croire à un
    aller-retour fidèle, et c'est en la découvrant six mois plus tard qu'on doute de tout le reste.
"""
from __future__ import annotations

import sqlite3
from typing import Dict, List, Sequence, Tuple

from wama.common.catalog.data_types import DataType

from ..core.naming import normalize
from ..core.temporal import Signal
from . import Context, Entry, ContainerSchema, register_schema, ident

#: Famille de la taxonomie partagée → préfixe de table. Inverse exact de `_TYPE_DE_FAMILLE`
#: (`sources/trip.py`) : le vocabulaire vient de `DataType`, il n'est recopié ni ici ni là-bas.
PREFIXES = {DataType.TIMESERIES: 'data_', DataType.EVENTS: 'event_',
            DataType.SEGMENTS: 'situation_'}

#: Préfixe → (table de déclaration, table de variables, colonne de rattachement).
CATALOGUE = {
    'data_': ('MetaDatas', 'MetaDataVariables', 'data_name'),
    'event_': ('MetaEvents', 'MetaEventVariables', 'event_name'),
    'situation_': ('MetaSituations', 'MetaSituationVariables', 'situation_name'),
}

COMMENTAIRE = "Exporté par WAMA Data"


def _prefixe(signal: Signal) -> Tuple[str, bool]:
    """Préfixe de table, et si la famille a dû être DEVINÉE.

    La famille déclarée (`SignalMeta.data_type`, §9nonies) prime toujours. On ne retombe sur la
    structure que si la source n'a rien dit — et dans ce cas on le SIGNALE : deviner la famille,
    c'est décider dans quelle table de catalogue le flux atterrit, donc comment BIND l'affichera.
    """
    prefixe = PREFIXES.get(signal.meta.data_type)
    if prefixe:
        return prefixe, False
    return ('situation_' if signal.is_segments else 'data_'), True


class TripSchema(ContainerSchema):
    format = 'trip'
    extension = '.trip'
    description = "Base SQLite au format BIND — compatibilité avec l'outil MATLAB du laboratoire"

    def table_name(self, signal: Signal) -> str:
        return _prefixe(signal)[0] + normalize(signal.meta.name)

    def colonnes_temps(self, signal: Signal) -> Tuple[str, ...]:
        return (('startTimecode', 'endTimecode') if _prefixe(signal)[0] == 'situation_'
                else ('timecode',))

    # ── Catalogue ─────────────────────────────────────────────────────────────────────────────
    def ecrire_catalogue(self, con: sqlite3.Connection,
                         entrees: Sequence[Entry], contexte: Context) -> None:
        con.execute('CREATE TABLE "MetaDatas" (name TEXT PRIMARY KEY, type TEXT, '
                    'frequency INT, comments TEXT, isBase BOOL)')
        con.execute('CREATE TABLE "MetaEvents" (name TEXT PRIMARY KEY, comments TEXT, isBase BOOL)')
        con.execute('CREATE TABLE "MetaSituations" (name TEXT PRIMARY KEY, comments TEXT, '
                    'isBase BOOL)')
        for _, (_, variables, rattachement) in CATALOGUE.items():
            con.execute(f'CREATE TABLE {ident(variables)} ({ident(rattachement)} TEXT, '
                        'name TEXT, type TEXT, unit TEXT, comments TEXT, '
                        f'PRIMARY KEY ({ident(rattachement)}, name))')
        con.execute('CREATE TABLE "MetaTripDatas" (key TEXT PRIMARY KEY, value TEXT)')
        con.execute('CREATE TABLE "MetaParticipantDatas" (key TEXT PRIMARY KEY, value TEXT)')
        con.execute('CREATE TABLE "MetaTripVideos" (filename TEXT PRIMARY KEY, offset DOUBLE, '
                    'description TEXT)')

        for e in entrees:
            prefixe = _prefixe(e.signal)[0]
            declaration, variables, rattachement = CATALOGUE[prefixe]
            base = 1 if e.meta.is_base else 0
            if declaration == 'MetaDatas':
                con.execute(
                    'INSERT OR REPLACE INTO "MetaDatas" VALUES (?, ?, ?, ?, ?)',
                    (e.meta.name, self._type_dominant(e), int(e.meta.fs or 0),
                     COMMENTAIRE, base))
            else:
                con.execute(
                    f'INSERT OR REPLACE INTO {ident(declaration)} VALUES (?, ?, ?)',
                    (e.meta.name, COMMENTAIRE, base))
            # ⚠ La colonne de temps figure parmi les variables — conforme au relevé.
            rows = [(e.meta.name, col, 'REAL', '', '') for col in e.colonnes_temps]
            rows += [(e.meta.name, col, e.types.get(col, 'TEXT'),
                        e.meta.units.get(col, ''), COMMENTAIRE) for col in e.columns]
            con.executemany(
                f'INSERT OR REPLACE INTO {ident(variables)} VALUES (?, ?, ?, ?, ?)', rows)

        entetes = [('export_time', contexte.date()), ('exported_by', contexte.auteur or 'WAMA')]
        entetes += [(str(k), '' if v is None else str(v)) for k, v in contexte.attributs.items()]
        con.executemany('INSERT OR REPLACE INTO "MetaTripDatas" VALUES (?, ?)', entetes)
        con.executemany(
            'INSERT OR REPLACE INTO "MetaTripVideos" VALUES (?, ?, ?)',
            [(str(m.get('file', '')), float(m.get('offset') or 0.0),
              str(m.get('description', ''))) for m in contexte.medias])

    @staticmethod
    def _type_dominant(entree: Entry) -> str:
        """Type déclaré du flux, au sens de `MetaDatas.type` — `REAL` dans toute la base relevée.

        On rend le type le plus fréquent parmi les colonnes plutôt qu'une constante : un flux
        entièrement textuel annoncé `REAL` induirait en erreur l'outil qui lit cette colonne.
        """
        if not entree.types:
            return 'REAL'
        comptes: Dict[str, int] = {}
        for t in entree.types.values():
            comptes[t] = comptes.get(t, 0) + 1
        return max(comptes.items(), key=lambda kv: kv[1])[0]

    # ── Ce que la langue de l'autre ne sait pas dire ──────────────────────────────────────────
    def losses(self, entrees: Sequence[Entry], contexte: Context) -> List[str]:
        out: List[str] = []
        devines = [e.meta.name for e in entrees if _prefixe(e.signal)[1]]
        if devines:
            out.append(
                f"famille DEVINÉE (aucun `data_type` déclaré) pour {len(devines)} flux : "
                f"{', '.join(devines[:5])} — la table de catalogue a été choisie sur la "
                f"structure, pas sur une déclaration")

        losses = [e.meta.name for e in entrees if e.meta.losses]
        if losses:
            out.append(f"pertes d'acquisition non portées ({', '.join(losses[:5])}) : le schéma "
                       f"BIND n'a aucun champ pour un compte d'échantillons manquants")

        lookups = [e.meta.name for e in entrees if e.meta.default_lookup]
        if lookups:
            out.append(f"politique de résolution (`default_lookup`) non portée pour "
                       f"{len(lookups)} flux — BIND la fixe par famille, elle n'est pas déclarable")

        decales = [e.meta.name for e in entrees if e.offset]
        if decales:
            out.append(f"décalage par flux non porté ({', '.join(decales[:5])}) : seul un décalage "
                       f"par MÉDIA existe (`MetaTripVideos.offset`)")

        fractions = [e.meta.name for e in entrees
                     if e.meta.fs and float(e.meta.fs) != int(e.meta.fs)]
        if fractions:
            out.append(f"cadence ARRONDIE pour {', '.join(fractions[:5])} : `MetaDatas.frequency` "
                       f"est un entier")

        sans_frequence = [e.meta.name for e in entrees
                          if e.meta.fs and _prefixe(e.signal)[0] != 'data_']
        if sans_frequence:
            out.append(f"cadence PERDUE pour {', '.join(sans_frequence[:5])} : `MetaEvents` et "
                       f"`MetaSituations` n'ont pas de colonne `frequency`")

        open_ones = self._segments_ouverts(entrees)
        if open_ones:
            out.append(
                f"{open_ones} segment(s) OUVERT(s) écrits avec une fin NULL : BIND n'a pas de "
                f"représentation pour « fin non observée » (D15) et lira une borne absente. "
                f"Mesuré sur la base réelle : 0 fin NULL sur 84 situations — le cas ne s'y "
                f"présente jamais, donc son traitement par l'outil n'est pas connu")

        if contexte.manifestes:
            out.append(
                f"{len(contexte.manifestes)} copie(s) projetée(s) du protocole NON embarquée(s) : "
                f"le schéma BIND n'a pas de table de manifestes. Le conteneur produit n'est donc "
                f"pas autoportant — il faut le protocole à côté")
        return out

    @staticmethod
    def _segments_ouverts(entrees: Sequence[Entry]) -> int:
        total = 0
        for e in entrees:
            if not e.a_des_fins:
                continue
            total += sum(1 for i in range(len(e.signal)) if e.signal.end_at(i) is None)
        return total


register_schema(TripSchema())

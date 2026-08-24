"""
Schéma `.wdat` — le conteneur NATIF de WAMA Data (**D3** puis **D17**, `WAMA_DATA_WORLD §9quater.2`).

POURQUOI `.wdat`, ET POURQUOI PAS LES QUATRE AUTRES CANDIDATS
    `.trip`     présuppose un **DÉPLACEMENT** — un laboratoire qui analyse des données temporelles
                sans aucun trajet n'a pas à manipuler des « trips ». C'est **D3**.
    `.rec`      pris par RTMaps.
    `.dataset`  pris — le kind de manifeste désigne une **EXPÉRIMENTATION** (un corpus de N
                fichiers), pas un essai.
    `.wrec`     ⚠ **le nom porté du 23 au 24/08, et abandonné le 24 — c'est D17.** « rec »
                présuppose une **session d'enregistrement live**, exactement le même défaut que
                `trip` un cran plus loin : le monde doit tenir des données temporelles sans aucune
                acquisition. Retenir le critère pour `trip` et l'écarter pour `rec` aurait été
                défendre un choix parce qu'il était le nôtre. Et `.wrec` était à **une lettre** de
                `.rec`, qu'on lit — dans un Converter qui manipule les deux, la confusion était
                garantie.
    `.wds`      « WAMA DataSet » — écarté : il **écrase deux étages** de la hiérarchie
                (projet → expérimentation → participant → **essai** → event/situation). Le kind
                `dataset` est l'expérimentation ; ce fichier est UN essai.
    `.wdb`      « WAMA DataBase » — écarté, et c'était le pire : il nomme **une chose qui existe
                déjà et qui est différente**, la base Postgres de WAMA. Un nom faux par COLLISION
                envoie au mauvais endroit ; un nom faux par connotation ne fait qu'être étroit.

    ⭐ `.wdat` ne présuppose rien — ce qui est exactement l'objet du renommage.
    ⚠ Le SCHÉMA, lui, n'a pas changé d'un octet : les tables du catalogue s'appelaient déjà
    `Wama*`, jamais `Wrec*`. On a renommé l'emballage, pas le format.

CE QU'IL GARDE DE `.trip`, ET POURQUOI CE N'EST PAS DE L'HÉRITAGE
    **Une table par flux.** C'est la conséquence directe de **D10** (aucune grille de temps
    commune) : six cadences natives coexistent dans une base réelle, les fondre exigerait de
    rééchantillonner. La structure est donc juste ; c'est le CATALOGUE qui était pauvre.

CE QU'IL CORRIGE — quatre faits que `.trip` connaît sans les porter
    1. **La famille n'est plus dans le NOM de la table.** `.trip` l'encode en préfixe
       (`data_`/`event_`/`situation_`), si bien que la lire oblige à analyser une chaîne. Ici
       toutes les tables portent le même préfixe `flux_` — **le nom ne dit rien**, le catalogue dit
       tout (`WamaStreams.data_type`, alimenté par la taxonomie partagée). C'est §9nonies appliqué
       à l'écriture : la famille est une DONNÉE.
    2. **Les unités sont écrites ET relues.** `.trip` a bien une table `MetaDataVariables` portant
       type et unité par colonne — mesuré : `unit` y vaut la chaîne vide **partout**, et son propre
       lecteur ne la lit jamais. Un champ présent que personne n'alimente ni ne relit est un champ
       absent qui ment.
    3. **Les pertes d'acquisition sont une colonne** (`SignalMeta.pertes`), pas un message de
       journal.
    4. **La copie projetée du protocole est dans le conteneur** (`WamaManifests`), estampillée —
       c'est ce qui rend le fichier de travail autoportant (`§9undecies.4`).

LA COPIE PROJETÉE EST ESTAMPILLÉE OU N'EST PAS
    Un manifeste embarqué sans `kind`/`key` est **refusé**, pas écrit dégradé. Sans estampille on ne
    peut ni le rapprocher du magasin, ni savoir laquelle des deux versions est la plus récente : la
    copie cesse d'être une projection et devient une **seconde source**, ce que « une source, N
    rendus » interdit. Le coût d'un refus est une exception ; le coût d'une copie anonyme est une
    divergence qu'on découvre des mois plus tard.
"""
from __future__ import annotations

import json
import sqlite3
from typing import List, Sequence, Tuple

from ..core.noms import normaliser
from ..core.temporal import Signal
from . import (Contexte, Entree, SchemaConteneur, enregistrer_schema, ident)

#: Version du schéma, écrite dans `WamaMeta`. Un lecteur futur doit pouvoir refuser ce qu'il ne sait
#: pas lire plutôt que d'en déduire n'importe quoi.
VERSION = '1'

#: Préfixe UNIQUE des tables de flux. ⚠ Il est le même pour toutes les familles À DESSEIN — il dit
#: « ceci est un flux », jamais « ceci est un segment ». La famille se lit dans le catalogue.
PREFIXE = 'flux_'


class SchemaWdat(SchemaConteneur):
    format = 'wdat'
    extension = '.wdat'
    description = "Conteneur natif WAMA Data — un flux par table, catalogue complet, protocole embarqué"

    def nom_table(self, signal: Signal) -> str:
        return PREFIXE + normaliser(signal.meta.name)

    def colonnes_temps(self, signal: Signal) -> Tuple[str, ...]:
        """`time`, ou `start`/`end` pour des segments — la graphie tranchée par **D9**.

        ⚠ Pas `timecode` : ce mot est **déjà pris dans WAMA** au sens AV positionnel (`mm:ss`, une
        chaîne — Transcriber), là où il désignerait ici un flottant en secondes. Ce n'était pas un
        arbitrage de goût mais une collision mesurée.
        """
        return ('start', 'end') if signal.is_segments else ('time',)

    # ── Catalogue ─────────────────────────────────────────────────────────────────────────────
    def ecrire_catalogue(self, con: sqlite3.Connection,
                         entrees: Sequence[Entree], contexte: Contexte) -> None:
        self._meta(con, entrees, contexte)
        self._flux(con, entrees)
        self._variables(con, entrees)
        self._medias(con, contexte)
        self._manifestes(con, contexte)

    @staticmethod
    def _meta(con, entrees: Sequence[Entree], contexte: Contexte) -> None:
        con.execute('CREATE TABLE "WamaMeta" (key TEXT PRIMARY KEY, value TEXT)')
        lignes = [
            ('format', 'wdat'),
            ('schema_version', VERSION),
            ('created_at', contexte.date()),
            ('created_by', contexte.auteur),
            ('streams', str(len(entrees))),
        ]
        lignes += [(str(k), '' if v is None else str(v))
                   for k, v in contexte.attributs.items()]
        con.executemany('INSERT OR REPLACE INTO "WamaMeta" (key, value) VALUES (?, ?)', lignes)

    @staticmethod
    def _flux(con, entrees: Sequence[Entree]) -> None:
        """Un flux = une ligne. Tout ce que `SignalMeta` porte est écrit, y compris ce que le
        schéma de BIND n'a jamais su dire (`data_type`, `pertes`, `offset`, `default_lookup`)."""
        con.execute(
            'CREATE TABLE "WamaStreams" ('
            'name TEXT PRIMARY KEY, table_name TEXT, data_type TEXT, fs REAL, '
            'is_base INTEGER, default_lookup TEXT, losses INTEGER, offset REAL, '
            'rows_count INTEGER, comments TEXT)')
        con.executemany(
            'INSERT INTO "WamaStreams" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [(e.meta.name, e.table, e.meta.data_type, e.meta.fs,
              1 if e.meta.is_base else 0, e.meta.default_lookup, int(e.meta.pertes),
              float(e.offset), e.lignes, e.meta.comments) for e in entrees])

    @staticmethod
    def _variables(con, entrees: Sequence[Entree]) -> None:
        """Une colonne = une ligne, avec son unité. ⚠ C'est le champ que `.trip` déclare et
        n'alimente jamais ; ici il vient de `SignalMeta.units`, donc il vaut ce que la source a su
        dire — vide quand elle n'a rien dit, et alors c'est un fait, pas un oubli."""
        con.execute(
            'CREATE TABLE "WamaVariables" ('
            'stream TEXT, name TEXT, unit TEXT, storage TEXT, PRIMARY KEY (stream, name))')
        lignes = [(e.meta.name, col, e.meta.units.get(col, ''), e.types.get(col, 'TEXT'))
                  for e in entrees for col in e.colonnes]
        con.executemany('INSERT OR REPLACE INTO "WamaVariables" VALUES (?, ?, ?, ?)', lignes)

    @staticmethod
    def _medias(con, contexte: Contexte) -> None:
        con.execute('CREATE TABLE "WamaMedia" (file TEXT, offset REAL, description TEXT)')
        con.executemany(
            'INSERT INTO "WamaMedia" VALUES (?, ?, ?)',
            [(str(m.get('file', '')), float(m.get('offset') or 0.0),
              str(m.get('description', ''))) for m in contexte.medias])

    @staticmethod
    def _manifestes(con, contexte: Contexte) -> None:
        """Les COPIES PROJETÉES — estampillées, et destinées à être relues en lecture seule.

        ⚠ Le refus d'une copie anonyme est délibéré : voir l'en-tête du module. `read_only` est
        écrit comme une donnée du conteneur pour qu'un outil tiers (ou un futur lecteur) n'ait pas
        à connaître la convention pour la respecter.
        """
        con.execute(
            'CREATE TABLE "WamaManifests" ('
            'manifest_kind TEXT, key TEXT, version TEXT, read_only INTEGER, body TEXT, '
            'PRIMARY KEY (manifest_kind, key))')
        lignes = []
        for m in contexte.manifestes:
            kind, cle = str(m.get('manifest_kind') or m.get('kind') or ''), str(m.get('key') or '')
            if not kind or not cle:
                raise ValueError(
                    "copie projetée sans estampille : un manifeste embarqué doit porter "
                    "`manifest_kind` et `key`. Sans eux il ne peut être ni rapproché du magasin ni "
                    "daté, donc il cesse d'être une projection pour devenir une seconde source.")
            lignes.append((kind, cle, str(m.get('schema_version') or m.get('version') or ''),
                           1, json.dumps(m, ensure_ascii=False, default=str)))
        con.executemany('INSERT OR REPLACE INTO "WamaManifests" VALUES (?, ?, ?, ?, ?)', lignes)

    def pertes(self, entrees: Sequence[Entree], contexte: Contexte) -> List[str]:
        """Le format natif porte tout ce que le référentiel sait dire — par construction."""
        return []


enregistrer_schema(SchemaWdat())

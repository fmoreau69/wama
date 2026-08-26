"""
ÉCRIVAIN DE CONTENEUR — un moteur, N schémas. Le pendant exact de `sources/` (un moteur, N lecteurs).

POURQUOI IL N'EXISTAIT PAS, ET POURQUOI C'EST UN MANQUE
    Vérifié le 2026-08-23 : **zéro écriture SQLite dans tout `wama_data`** (0 `INSERT`, 0 `to_sql`).
    Le monde Data savait donc LIRE trois formats et n'en savait écrire aucun — un importeur sans
    fichier de travail, c'est-à-dire une chaîne qui recommence à zéro à chaque ouverture.

UN MOTEUR, DEUX SCHÉMAS — et ce n'est pas une commodité
    `.wdat`  le conteneur NATIF (décision **D3**, `WAMA_DATA_WORLD §9quater.2`) ;
    `.trip`  le schéma de BIND, pour la **compatibilité** — « pouvoir recréer des fichiers trip à
             partir de fichiers rec est important » (Fabien, 2026-08-24).

    Les deux partagent **toute** la mécanique : une table par flux, un index temporel, une écriture
    transactionnelle par tranches. Ils ne diffèrent que par des **noms** et par la **richesse du
    catalogue**. Écrire deux écrivains aurait donc dupliqué la seule partie difficile pour ne varier
    que la partie triviale — exactement le geste que la règle de centralisation interdit.

    ⚠ **La structure « une table par flux » n'est PAS une bizarrerie de BIND qu'on hérite** : c'est
    la **conséquence de D10** (aucune grille de temps commune). Six cadences natives coexistent dans
    une base réelle ; les fondre en une table exigerait de rééchantillonner, ce qui est refusé. Le
    `.wdat` garde donc la structure et **enrichit le catalogue**, il ne la corrige pas.

CE QUE L'ÉCRITURE N'EST PAS AUTORISÉE À FAIRE
    Elle ne touche **jamais** une source. Elle crée un fichier NEUF, et le fichier de travail
    produit est **régénérable** depuis `raw_data + protocole` — c'est précisément ce qui autorise à
    y écrire (précision de Fabien, 2026-08-23 ; la phrase « on n'écrit jamais dans une source
    importée » interdit de **muter** une source, pas d'en **écrire une nouvelle**).

CE QUE LE SCHÉMA CIBLE NE SAIT PAS PORTER EST **COMPTÉ**, PAS TU
    Écrire un `.trip` depuis un référentiel WAMA **perd** de l'information : ni les pertes
    d'acquisition, ni les unités, ni la copie projetée du manifeste, ni un **segment ouvert** n'ont
    de place dans le schéma de BIND. `Rapport.pertes` les énumère. Une conversion qui appauvrit en
    silence est la façon la plus sûre de faire croire à un aller-retour fidèle — c'est le motif que
    ce dépôt a déjà rencontré six fois sous l'angle inverse (« le fait est connu et n'est pas porté »).

G1 S'APPLIQUE ICI À L'IDENTIQUE
    Aucun format n'est privilégié dans le moteur : les schémas sont **découverts** (`pkgutil`),
    jamais cités. Ajouter `.mat` ou un export Parquet = déposer un module, sans toucher ce fichier.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..core.noms import AXES_TEMPORELS
from ..core.temporal import Signal, SignalMeta, TemporalReferential
from ..core.valeurs import manquant

#: Lignes lues (et insérées) par tranche. Une base réelle dépasse le gigaoctet : ni la lecture ni
#: l'insertion ne peuvent tenir en mémoire d'un bloc.
TRANCHE = 5000


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Ce qu'on écrit AUTOUR des flux
# ──────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Contexte:
    """Ce qui accompagne les flux dans le conteneur — le catalogue non temporel.

    `manifestes` porte les **copies projetées** (`WAMA_DATA_WORLD §9undecies.4`) : le protocole
    embarqué qui rend le conteneur autoportant. ⚠ Elles sont **estampillées** (`kind`, `key`,
    `version`) et destinées à être relues en **lecture seule** — sans l'estampille, la copie
    deviendrait une seconde source, ce que « une source, N rendus » interdit.

    `auteur` et `horodatage` ne sont pas de la décoration : l'usage visé est **collaboratif**
    (plusieurs personnes sur le même dossier de dataset, voir ce que l'autre a traité). Sans eux,
    le suivi exigerait une base partagée que personne n'aura.
    """

    auteur: str = ''
    horodatage: str = ''
    attributs: Dict[str, Any] = field(default_factory=dict)
    medias: List[Dict[str, Any]] = field(default_factory=list)
    manifestes: List[Dict[str, Any]] = field(default_factory=list)

    def date(self) -> str:
        """Horodatage fourni, ou l'instant courant en ISO/UTC."""
        if self.horodatage:
            return self.horodatage
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat(timespec='seconds')


@dataclass
class Entree:
    """Un flux PRÊT à écrire : sa table, ses colonnes de temps, ses colonnes de données.

    Construite par le moteur, consommée par le schéma pour rédiger le catalogue. C'est la seule
    chose que les deux étages ont à se dire.
    """

    name: str
    signal: Signal
    table: str
    colonnes_temps: Tuple[str, ...]
    colonnes: List[str] = field(default_factory=list)
    types: Dict[str, str] = field(default_factory=dict)
    offset: float = 0.0
    lignes: int = 0

    @property
    def meta(self) -> SignalMeta:
        return self.signal.meta

    @property
    def a_des_fins(self) -> bool:
        return len(self.colonnes_temps) > 1


@dataclass
class Rapport:
    """Ce que l'écriture a produit — et ce qu'elle a **perdu**."""

    chemin: str
    format: str
    tables: Dict[str, int] = field(default_factory=dict)
    pertes: List[str] = field(default_factory=list)
    notes: str = ''

    @property
    def lignes(self) -> int:
        return sum(self.tables.values())

    @property
    def fidele(self) -> bool:
        """Vrai si le schéma cible a tout porté. Faux n'est pas une erreur — c'est un fait à lire."""
        return not self.pertes

    def __repr__(self) -> str:
        return (f"<Rapport {self.format} {Path(self.chemin).name} "
                f"{len(self.tables)} table(s) {self.lignes} ligne(s) "
                f"{len(self.pertes)} perte(s)>")


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Contrat d'un schéma
# ──────────────────────────────────────────────────────────────────────────────────────────────

class SchemaConteneur:
    """Un format de conteneur. À sous-classer, puis à enregistrer via `enregistrer_schema`.

    Un schéma décide **des noms et du catalogue**. Il ne décide ni de la transaction, ni du
    découpage en tranches, ni de l'indexation, ni de la conversion des valeurs : tout cela est du
    moteur, et c'est ce qui garantit que deux formats se comportent pareil là où ils le doivent.
    """

    #: Identifiant stable (« wdat », « trip »…).
    format = ''
    #: Extension produite, en minuscules, point compris.
    extension = ''
    description = ''

    def nom_table(self, signal: Signal) -> str:
        """Nom de la table portant ce flux.

        ⚠ Reçoit le SIGNAL, pas seulement sa `SignalMeta`. Un schéma peut avoir besoin de la
        structure — le schéma `.trip` encode la famille dans le préfixe de table et doit pouvoir
        retomber sur `is_segments` quand la famille n'est pas déclarée. Lui passer la seule méta
        l'obligerait à mémoriser ce qu'il a vu ailleurs, or **un schéma est un singleton de
        registre** : tout état retenu fuirait d'une écriture à la suivante et entre fils
        d'exécution. Le contrat est donc SANS ÉTAT, et la signature est ce qui le garantit.
        """
        raise NotImplementedError

    def colonnes_temps(self, signal: Signal) -> Tuple[str, ...]:
        """`(début,)` pour un flux ponctuel, `(début, fin)` pour une collection de segments."""
        raise NotImplementedError

    def pertes(self, entrees: Sequence[Entree], contexte: Contexte) -> List[str]:
        """Ce que ce schéma ne sait PAS porter, énoncé fait par fait. Vide = conversion fidèle."""
        return []

    def ecrire_catalogue(self, con: sqlite3.Connection,
                         entrees: Sequence[Entree], contexte: Contexte) -> None:
        """Écrit les tables de métadonnées. Appelé dans la transaction, après les flux."""
        raise NotImplementedError


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Registre — même geste que `sources.READERS`, même raison (G1)
# ──────────────────────────────────────────────────────────────────────────────────────────────

SCHEMAS: Dict[str, SchemaConteneur] = {}


def enregistrer_schema(schema: SchemaConteneur) -> SchemaConteneur:
    if not schema.format:
        raise ValueError("un schéma de conteneur doit déclarer un `format`")
    if not schema.extension.startswith('.'):
        raise ValueError(f"l'extension de '{schema.format}' doit commencer par un point")
    if schema.format in SCHEMAS:
        raise ValueError(f"format de conteneur '{schema.format}' déjà enregistré")
    SCHEMAS[schema.format] = schema
    return schema


def schemas_disponibles() -> List[str]:
    return sorted(SCHEMAS)


def extensions_ecrivables() -> List[str]:
    return sorted({s.extension for s in SCHEMAS.values()})


def schema_pour(cible) -> Optional[SchemaConteneur]:
    """Le schéma désigné par un nom de format **ou** par l'extension d'un chemin."""
    texte = str(cible)
    if texte in SCHEMAS:
        return SCHEMAS[texte]
    suffixe = Path(texte).suffix.lower()
    for s in SCHEMAS.values():
        if s.extension == suffixe:
            return s
    return None


def modules_schemas() -> List[str]:
    """Modules de schéma du paquet — **DÉCOUVERTS, jamais cités** (G1, cf. `sources.modules_lecteurs`)."""
    import pkgutil
    return sorted(m.name for m in pkgutil.iter_modules(__path__)
                  if not m.name.startswith(('_', 'test')))


def _enregistrer_livres():
    """Enregistre les schémas livrés, **chacun isolé des autres** — un schéma qui échoue à
    s'importer ne doit pas emporter les autres, ni le monde Data avec eux."""
    import importlib
    for name in modules_schemas():
        try:
            importlib.import_module(f'{__name__}.{name}')
        except Exception:
            logging.getLogger(__name__).warning(
                "schéma de conteneur '%s' non enregistré — les autres restent disponibles",
                name, exc_info=True)


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Utilitaires d'écriture — communs aux deux schémas, à dessein
# ──────────────────────────────────────────────────────────────────────────────────────────────

def ident(name: str) -> str:
    """Identifiant SQL cité. Un nom de colonne vient de la DONNÉE : il ne doit jamais atterrir tel
    quel dans une requête. Même précaution que `TripReader._extent_accessor`, côté écriture."""
    return '"' + str(name).replace('"', '""') + '"'


def _sqlite_type(valeur: Any) -> str:
    """Type déclaré d'une colonne, déduit de sa première valeur PRÉSENTE.

    ⚠ SQLite type par valeur, pas par colonne : la déclaration est une **indication**, pas une
    contrainte. On la pose quand même — elle est ce qu'un outil tiers (BIND, un tableur, un script
    MATLAB) lira pour décider comment interpréter la colonne.

    ⚠ `bool` est une sous-classe de `int` en Python : un booléen est donc stocké en `INTEGER` (0/1).
    C'est le comportement de SQLite lui-même, qui n'a pas de type booléen.
    """
    if isinstance(valeur, bool) or isinstance(valeur, int):
        return 'INTEGER'
    if isinstance(valeur, float):
        return 'REAL'
    if isinstance(valeur, (bytes, bytearray)):
        return 'BLOB'
    return 'TEXT'


def _sans_nan(v: Any) -> Any:
    """Remplace récursivement les absences par `None` DANS une structure, avant sérialisation."""
    if isinstance(v, dict):
        return {k: _sans_nan(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sans_nan(x) for x in v]
    return None if manquant(v) else v


def valeur_sql(v: Any) -> Any:
    """Valeur Python → valeur SQLite.

    ⚠ CE QUE LA MORSURE A CORRIGÉ DANS MON PROPRE RÉCIT (2026-08-24). J'avais écrit ici que
    `manquant()` protégeait du piège pandas au niveau scalaire. **Neutraliser l'appel n'a fait
    échouer aucun test**, et la mesure dit pourquoi : **SQLite coerce lui-même `NaN` en `NULL`**
    (`typeof` rend `'null'`). Le garde-fou n'était donc pas porteur, et mon test prouvait le
    RÉSULTAT sans rien prouver du mécanisme. L'appel reste — ne pas dépendre d'une coercion qu'on
    ne contrôle pas est juste — mais il ne faut pas lui prêter un rôle qu'il n'a pas.

    ⚠ LE VRAI TROU ÉTAIT À CÔTÉ, et la même mesure l'a montré : `json.dumps([nan])` produit le
    littéral `[NaN]`, que **la spécification JSON n'accepte pas** — donc une valeur composite
    contenant une absence était écrite dans le conteneur sous une forme qu'aucun analyseur
    standard ne relit. C'est le vrai 5ᵉ passage du piège pandas ici, et il n'était couvert ni par
    `manquant()` ni par SQLite. D'où `_sans_nan`, appliqué **récursivement** avant sérialisation.
    """
    if manquant(v):
        return None
    if isinstance(v, (int, float, str, bytes, bytearray)):
        return v
    return json.dumps(_sans_nan(v), ensure_ascii=False, default=str)


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Le moteur
# ──────────────────────────────────────────────────────────────────────────────────────────────

def ecrire(referentiel: TemporalReferential, chemin, *,
           format: str = '', contexte: Optional[Contexte] = None,
           flux: Optional[Iterable[str]] = None,
           tranche: int = TRANCHE, ecraser: bool = False) -> Rapport:
    """Écrit un référentiel dans un conteneur. Rend un `Rapport` — **y compris ce qui a été perdu**.

    `format` est facultatif : l'extension du chemin suffit à désigner le schéma.

    ⚠ **On écrit d'abord à côté, on renomme ensuite.** Une écriture interrompue (disque plein,
    ligne illisible, coupure) ne doit pas laisser un conteneur à moitié rempli qui s'ouvre
    normalement — c'est un fichier de TRAVAIL, quelqu'un le rouvrira en croyant y trouver son
    dataset. Le renommage final est atomique sur les deux systèmes de fichiers visés, et une
    version existante n'est remplacée qu'une fois la nouvelle complète.
    """
    contexte = contexte or Contexte()
    cible = Path(chemin)
    schema = schema_pour(format or cible)
    if schema is None:
        raise ValueError(
            f"aucun schéma de conteneur pour '{format or cible.name}' "
            f"(formats connus : {', '.join(schemas_disponibles()) or '—'})")

    if cible.exists() and not ecraser:
        raise FileExistsError(
            f"'{cible}' existe déjà — passer `ecraser=True` pour le remplacer. "
            "Un conteneur est un fichier de travail : l'écraser sans le dire perdrait "
            "les traitements qu'il porte.")

    noms = list(flux) if flux is not None else referentiel.names   # `names` est une PROPRIÉTÉ
    partiel = cible.with_name(cible.name + '.partiel')
    partiel.unlink(missing_ok=True)

    rapport = Rapport(chemin=str(cible), format=schema.format)
    entrees: List[Entree] = []
    con = sqlite3.connect(str(partiel))
    try:
        con.execute('PRAGMA journal_mode=MEMORY')
        with con:                                  # une seule transaction : tout ou rien
            for name in noms:
                signal = referentiel.get(name)
                entree = _preparer(signal, name, schema, referentiel.offset(name), tranche)
                _ecrire_flux(con, entree, tranche, rapport)
                entrees.append(entree)
                rapport.tables[entree.table] = entree.lignes
            schema.ecrire_catalogue(con, entrees, contexte)
    except BaseException:
        con.close()
        partiel.unlink(missing_ok=True)
        raise
    con.close()

    os.replace(partiel, cible)
    rapport.pertes.extend(schema.pertes(entrees, contexte))
    rapport.notes = (f"{len(entrees)} flux, {rapport.lignes} ligne(s), "
                     f"{'aucune perte' if rapport.fidele else str(len(rapport.pertes)) + ' perte(s)'}")
    return rapport


def _preparer(signal: Signal, name: str, schema: SchemaConteneur,
              offset: float, tranche: int) -> Entree:
    """Décide table, colonnes et types en lisant la PREMIÈRE tranche — jamais tout le flux."""
    entree = Entree(name=name, signal=signal, table=schema.nom_table(signal),
                    colonnes_temps=schema.colonnes_temps(signal), offset=offset)
    premieres = signal.rows(0, min(tranche, len(signal))) or []
    ordre: List[str] = []
    for ligne in premieres:
        for cle in ligne:
            if cle not in ordre and str(cle).lower() not in AXES_TEMPORELS:
                ordre.append(cle)
    entree.colonnes = ordre
    for col in ordre:
        echantillon = next((l[col] for l in premieres
                            if col in l and not manquant(l[col])), None)
        entree.types[col] = _sqlite_type(echantillon) if echantillon is not None else 'TEXT'
    return entree


def _ecrire_flux(con: sqlite3.Connection, entree: Entree, tranche: int, rapport: Rapport) -> None:
    """Crée la table du flux, y verse les lignes par tranches, puis indexe l'axe du temps."""
    temps = entree.colonnes_temps
    colonnes = [f'{ident(c)} REAL' for c in temps]
    colonnes += [f'{ident(c)} {entree.types[c]}' for c in entree.colonnes]
    con.execute(f'CREATE TABLE {ident(entree.table)} ({", ".join(colonnes)})')

    toutes = list(temps) + entree.colonnes
    insert = (f'INSERT INTO {ident(entree.table)} '
              f'({", ".join(ident(c) for c in toutes)}) '
              f'VALUES ({", ".join("?" * len(toutes))})')

    signal, n = entree.signal, len(entree.signal)
    inconnues: set = set()
    for i0 in range(0, n, tranche):
        i1 = min(i0 + tranche, n)
        lignes = signal.rows(i0, i1)
        paquet = []
        for k in range(i0, i1):
            valeurs: List[Any] = [signal.time_at(k)]
            if len(temps) > 1:
                # ⚠ `end_at` rend `None` sur un segment OUVERT, et c'est ce qu'on écrit : NULL dit
                # « fin non observée », là où recopier la fin du média donnerait une durée MESURÉE
                # sur ce que personne n'a mesuré (D15, tranchée le 2026-08-24).
                valeurs.append(signal.end_at(k))
            ligne = lignes[k - i0] if lignes and (k - i0) < len(lignes) else {}
            inconnues |= {c for c in ligne
                          if c not in entree.types and str(c).lower() not in AXES_TEMPORELS}
            valeurs += [valeur_sql(ligne.get(c)) for c in entree.colonnes]
            paquet.append(valeurs)
        if paquet:
            con.executemany(insert, paquet)
    entree.lignes = n

    if inconnues:
        # Une colonne apparue APRÈS la première tranche n'a pas de place dans la table : la taire
        # ferait disparaître une variable entière sans trace.
        rapport.pertes.append(
            f"flux '{entree.name}' : {len(inconnues)} colonne(s) apparue(s) au-delà de la première "
            f"tranche, absentes de la table ({', '.join(sorted(map(str, inconnues))[:5])})")

    con.execute(f'CREATE INDEX {ident("idx_" + entree.table)} '
                f'ON {ident(entree.table)} ({ident(temps[0])})')


_enregistrer_livres()

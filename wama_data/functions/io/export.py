"""
Déclaration au catalogue de l'Exporter (implémentation : `wama_data/core/export.py`).

Aucune logique ici — des adaptateurs de ports, comme pour le Segmenter et le Calculator : le
cœur manipule des listes de dicts, le catalogue fait circuler des `TypedFrame`.

POURQUOI `io/` ET NON `temporal/`. Le pivot ne suppose aucun temps : il regroupe des lignes par
identité et étale une colonne en colonnes. Ce qu'il fait est de la RESTITUTION — faire sortir un
corpus de WAMA — donc le même domaine que l'ingest, en sens inverse.

POURQUOI LA CATÉGORIE `aggregate`. Le pivot ne calcule aucune statistique, mais il fait bien
passer de N lignes à une ligne PAR GROUPE : c'est la définition de la catégorie (« agrège par
groupe »), et c'est ce qui importe au canvas — la granularité change, donc ce qui était
branchable en aval ne l'est plus. `transform` aurait menti sur ce point précis, puisqu'elle
promet le même type en sortie.

⚠ CE QUI SORT N'EST PLUS DES `segments`. Une ligne du livrable est une PASSATION, pas une
portion de temps : elle n'a ni `start` ni `end`. Le type de sortie est donc `table`, et c'est
volontairement un ALLER SANS RETOUR — aucune fonction de segmentation ne doit pouvoir se
brancher derrière, elle n'y retrouverait pas ses bornes.
"""
from __future__ import annotations

from wama.common.catalog.data_types import CANONICAL_FIELDS, DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionCategory, FunctionSpec, ParamSpec,
                                                  PortSpec, register)
from ...core.export import decimer, en_lignes, pivot_large


def _liste(valeur: str) -> list:
    """« a , b » → ['a', 'b']. Forme retenue partout dans WAMA Data : elle reste sérialisable
    dans un manifeste et éditable dans une modale générée, contrairement à une liste Python."""
    return [x.strip() for x in (valeur or '').split(',') if x.strip()]


def export_pivot(segments: TypedFrame, cle_ligne: str = 'trip_id', cle_colonne: str = 'name',
                 mesures: str = '', pas_de_decimation: int = 1) -> TypedFrame:
    """Pivot long → large : une ligne par passation, les segments côte à côte.

    `mesures` vide = TOUTES les colonnes qui ne servent ni d'identité ni de préfixe. C'est le
    défaut utile : après un `calcul_par_segment`, ce sont exactement les indicateurs produits,
    et les nommer un par un serait à refaire à chaque ajout de statistique.
    """
    import pandas as pd

    lignes = segments.df.to_dict('records')
    lignes = decimer(lignes, pas_de_decimation)

    identite = _liste(cle_ligne)
    demandees = _liste(mesures)
    if not demandees:
        # Tout ce qui n'est ni identité ni préfixe. `start`/`end` sont écartés : ce sont les
        # bornes du segment, pas des mesures — les étaler produirait `0_15.start`, une colonne
        # qui redit ce que le nom de la fenêtre porte déjà.
        exclues = set(identite) | {cle_colonne, 'start', 'end'}
        demandees = [c for c in segments.df.columns if c not in exclues]

    larges, colonnes = pivot_large(lignes, cle_ligne=identite, cle_colonne=cle_colonne,
                                   mesures=demandees)
    # `columns=colonnes` : l'ordre vient du cœur, jamais de l'ordre d'insertion des dicts —
    # un livrable dont les colonnes bougent d'un export à l'autre est incomparable.
    return TypedFrame(pd.DataFrame(larges, columns=colonnes), DataType.TABLE,
                      meta={**(segments.meta or {}), 'export': 'pivot_large',
                            'colonnes': colonnes})


def export_tableau(table: TypedFrame, absent: str = '') -> list:
    """Le cadre aplati en lignes de texte, en-tête compris — la forme qu'attend un écrivain de
    fichier (CSV/TSV/XLSX). Rendre le TABLEAU plutôt qu'écrire le fichier garde cette fonction
    pure et testable, et laisse le choix du format à la couche qui connaît la destination."""
    return en_lignes(table.df.to_dict('records'), list(table.df.columns), absent=absent)


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Déclaration
# ──────────────────────────────────────────────────────────────────────────────────────────────

register(FunctionSpec(
    key='export_pivot_large',
    name='Export — pivot long → large',
    description="Passe d'une ligne PAR SEGMENT à une ligne PAR PASSATION, segments côte à côte "
                "(colonnes « <segment>.<indicateur> »). C'est l'étape que les chercheurs font "
                "aujourd'hui À LA MAIN dans un tableur : les quatre chemins d'export de BIND_GUI "
                "produisent tous du long, et le livrable à 393 colonnes naît d'un remaniement "
                "manuel (WAMA_DATA_WORLD §6.7). Une combinaison absente reste ABSENTE — une "
                "fenêtre non observée et une fenêtre mesurée à zéro ne se corrigent pas de la "
                "même façon. Une seconde occurrence d'un même segment reçoit un rang "
                "(« freinage#2. ») au lieu d'écraser la première.",
    category=FunctionCategory.AGGREGATE,
    tags=['export', 'restitution', 'tableur'],
    inputs=[PortSpec('segments', DataType.SEGMENTS,
                     required_fields=CANONICAL_FIELDS[DataType.SEGMENTS],
                     description="Segments porteurs d'indicateurs (sortie de `calcul_par_segment`).")],
    outputs=[PortSpec('table', DataType.TABLE,
                      description="Une ligne par passation. ⚠ Ce ne sont plus des segments : "
                                  "la ligne n'a ni début ni fin, aucune segmentation ne se "
                                  "rebranche derrière.")],
    params=[
        ParamSpec('cle_ligne', 'str', 'trip_id',
                  description="Colonne(s) identifiant une ligne du livrable, séparées par des "
                              "virgules (BIND écrit participant ET scénario côte à côte)."),
        ParamSpec('cle_colonne', 'str', 'name',
                  description="Colonne dont les valeurs deviennent les préfixes de colonnes."),
        ParamSpec('mesures', 'str', '',
                  description="Indicateurs à étaler, séparés par des virgules. Vide = tous ceux "
                              "qui ne servent ni d'identité ni de préfixe (start/end exclus)."),
        ParamSpec('pas_de_decimation', 'int', 1, min=1,
                  description="Garde une ligne sur N. Le mécanisme vient de BIND (`sub_sampling`) "
                              "où il est vital — 88 Go pour une étude ; son défaut ici n'enlève "
                              "rien, contrairement au 1000 écrit en dur dans le batch d'origine."),
    ],
    cost={'cpu_bound': True},
    fn=export_pivot,
))

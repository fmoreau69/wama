"""
Déclaration au catalogue du Calculator (implémentation : `wama_data/core/calculation.py`).

Aucune logique ici — des adaptateurs de ports, comme pour le Segmenter : le cœur manipule des
listes de flottants, le catalogue fait circuler des `TypedFrame`. Mettre la conversion dans le
cœur le rendrait dépendant de pandas et intestable sans lui.

LES DEUX MODES, ET POURQUOI DEUX CATÉGORIES DIFFÉRENTES

  ① `calcul_glissant`, `calcul_derivee`, `calcul_cumul` → `FunctionCategory.ENRICHER`
     « ajoute des champs/colonnes à l'entrée » : le cadre sort avec les mêmes lignes, une colonne
     de plus. La catégorie n'est pas décorative — c'est elle qui dit au canvas que la sortie reste
     branchable là où l'entrée l'était.

  ② `calcul_par_segment` → `FunctionCategory.AGGREGATE`
     « agrège par groupe » : une ligne PAR SEGMENT, plus du tout par échantillon. Le cadre change
     de granularité, donc de type (`segments`).

⚠ CE QUI SÉPARE ① DE ② EST UNE RÈGLE GÉNÉRALE, ÉCRITE LE 2026-08-23 (`§9quater.4`) :

      « Une colonne calculée reste dans SA table tant que la CLÉ TEMPORELLE ne change pas.
        Elle en sort dès qu'elle change. »

Cette règle était DÉJÀ APPLIQUÉE ici, mais n'existait nulle part comme doctrine — elle n'était
qu'une propriété émergente de ces deux catégories, donc contredisible par le prochain module sans
que personne ne s'en aperçoive. Ses trois conséquences, pour qui écrit une fonction de calcul :

  • deux colonnes de la MÊME table  → `ENRICHER`, colonne adjointe, nom dérivé (`nom_produit()`) ;
  • deux colonnes à PAS DIFFÉRENTS  → surtout PAS d'interpolation (D6). Le défaut recommandé est
    l'AGRÉGATION du flux rapide sur les intervalles du lent — c'est `calcul_par_segment`, et elle
    n'invente aucune valeur. Le rééchantillonnage vers une table annexe reste possible, mais
    EXPLICITE et tracé (D10) : la grille change, donc c'est une nouvelle table ;
  • calcul sur une PORTION (`present_dans`) → la clé temporelle ne change pas : mêmes instants, en
    moins. La colonne revient donc dans la table d'origine AVEC DES TROUS (`None` hors contexte),
    ce qui est plus informatif qu'une table à part. ⚠ Calculer SUR la restriction, jamais masquer
    après : aux bords du contexte, masquer laisserait fuir des échantillons extérieurs dans la
    fenêtre glissante. Et le contexte se TRACE sur la colonne (D11) — sans quoi deux colonnes de
    même nom calculées sur deux contextes différents seraient indiscernables.

⚠ ET CE QU'ON PERSISTE EST LA DÉCLARATION, PAS LES VALEURS (`§9quater.5`). Une colonne matérialisée
devient périmée vis-à-vis de sa source sans que rien ne le signale, et l'enregistrement réel fait
déjà 1,28 Go. Les valeurs sont un CACHE keyé par la déclaration ; elles ne s'écrivent en dur qu'à
l'export, où elles sont le produit demandé.

⚠ UN `None` DU CŒUR RESSORT EN `NaN` DANS LE CADRE — et c'est VOULU, ne pas le « corriger ».
`_segments()` force le type `object` sur la colonne `end`, parce que le Segmenter y teste
`end is None` : c'est un marqueur STRUCTUREL. `duree` et les colonnes d'indicateurs, elles, sont
NUMÉRIQUES — on en calcule des moyennes en aval. Y forcer `object` pour préserver `None` casserait
toute arithmétique, et `NaN` est justement la marque d'absence des flottants. La distinction qui
compte (« pas de durée observée » ≠ « durée nulle ») survit intacte, puisque `NaN` n'est pas `0`.
La relecture se fait avec `manquant()`, comme partout ailleurs à cette frontière.

⚠ `n` ET la statistique `nombre` font double emploi au mode ② — assumé. `nombre` existe pour le
mode ①, où une fenêtre glissante n'a pas de champ de service pour dire combien de points elle a
vus. La retirer du vocabulaire commun pour éviter une redondance dans un seul des deux modes
coûterait plus qu'elle ne rapporte.

⚠ POURQUOI `produced_fields` EST VIDE ICI, alors que le Segmenter le renseigne. Le nom de la
colonne produite se DÉDUIT des paramètres (`vitesse` + `moyenne` → `vitesse_moyenne`) : aucune
liste statique ne peut le dire. Deux mauvaises réponses étaient possibles — déclarer le nom par
défaut (qui devient faux dès qu'on change un paramètre, et fait valider une chaîne qui casse à
l'exécution), ou inventer un paramètre de renommage (un nom de plus à tenir juste). On déclare
donc la RÈGLE de nommage dans la description du port, et rien qu'elle : un chaînage refusé se
rattrape, un chaînage validé à tort ne se rattrape qu'en production.
"""
from __future__ import annotations

from wama.common.catalog.data_types import CANONICAL_FIELDS, DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionCategory, FunctionSpec, ParamSpec,
                                                  PortSpec, register)
from ...core.calculation import (CHAMPS_DE_SERVICE, DEFAUT, STATISTIQUES, cumul, derivee,
                                 glissant, par_segment)
from .segmentation import _colonne, _fin, _segments


#: ⚠ `nom_produit` VIVAIT ICI, dans l'adaptateur, alors que `nom_jonction`/`nom_chaine` vivaient
#: dans le cœur — même famille de règle, deux étages (audit A, §9sexies). Elle a rejoint la brique
#: unique `core/noms.py` ; on la garde importable d'ici, les appelants n'ont pas à savoir.
from ...core.noms import nom_produit  # noqa: F401


def _avec_colonne(signal: TypedFrame, name: str, valeurs: list) -> TypedFrame:
    """Le cadre d'entrée, augmenté d'une colonne. L'entrée n'est jamais modifiée en place —
    une fonction de chaîne qui mute son entrée casse tout rejeu de la chaîne."""
    df = signal.df.copy()
    df[name] = valeurs
    return TypedFrame(df, signal.data_type, meta=signal.meta)


# ── ① COLONNES DÉRIVÉES ───────────────────────────────────────────────────────────────────────

def calc_rolling(signal: TypedFrame, window_s: float = 5.0, statistic: str = DEFAUT,
                    column: str = 'value', centered: bool = True,
                    min_points: int = 1) -> TypedFrame:
    """Statistique sur fenêtre glissante (en SECONDES) → nouvelle colonne."""
    valeurs = glissant(_colonne(signal, 'time'), _colonne(signal, column), window_s,
                       statistic, centered=centered, min_points=min_points)
    return _avec_colonne(signal, nom_produit(column, statistic), valeurs)


def calc_derivative(signal: TypedFrame, column: str = 'value') -> TypedFrame:
    """Taux de variation instantané (unité/seconde) → nouvelle colonne."""
    return _avec_colonne(signal, nom_produit(column, 'derivative'),
                         derivee(_colonne(signal, 'time'), _colonne(signal, column)))


def calc_cumulative(signal: TypedFrame, column: str = 'value') -> TypedFrame:
    """Intégrale cumulée (unité × seconde) → nouvelle colonne."""
    return _avec_colonne(signal, nom_produit(column, 'cumulative'),
                         cumul(_colonne(signal, 'time'), _colonne(signal, column)))


# ── ② INDICATEURS PAR SEGMENT ─────────────────────────────────────────────────────────────────

def calc_per_segment(segments: TypedFrame, signal: TypedFrame, statistics: str = DEFAUT,
                       column: str = 'value') -> TypedFrame:
    """Indicateurs par segment, ADJOINTS aux segments reçus (une ligne par segment).

    `statistiques` est une liste séparée par des virgules — la forme qui reste sérialisable dans
    un manifeste et éditable dans une modale générée, contrairement à une liste Python.
    """
    noms = [s.strip() for s in statistics.split(',') if s.strip()] or [DEFAUT]
    lignes = [dict(r, end=_fin(r.get('end'))) for r in segments.df.to_dict('records')]
    jeux = par_segment(lignes, _colonne(signal, 'time'), _colonne(signal, column), noms)
    # Les indicateurs sont PRÉFIXÉS du nom de la colonne mesurée : sans cela, calculer sur deux
    # signaux successifs écraserait la première série par la seconde, en silence.
    fusion = []
    for ligne, jeu in zip(lignes, jeux):
        indicateurs = {(k if k in CHAMPS_DE_SERVICE else nom_produit(column, k)): v
                       for k, v in jeu.items()}
        fusion.append({**ligne, **indicateurs})
    return _segments(fusion, meta=segments.meta)


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Déclarations
# ──────────────────────────────────────────────────────────────────────────────────────────────

_CHOIX_STATS = sorted(STATISTIQUES)

#: Entrée commune aux trois fonctions du mode ①. `timeseries` et non `signal` : un `signal` EST
#: une `timeseries` (sous-typage), donc le port accepte les deux — l'inverse serait faux.
_ENTREE_SIGNAL = PortSpec('signal', DataType.TIMESERIES,
                          required_fields=CANONICAL_FIELDS[DataType.TIMESERIES],
                          description="Flux échantillonné à enrichir. La colonne mesurée est "
                                      "choisie par le paramètre `colonne`.")

_PARAM_COLONNE = ParamSpec('column', 'str', 'value',
                           description="Colonne du signal sur laquelle porte le calcul.")

register(FunctionSpec(
    key='calc_rolling',
    name='Moyenne (ou autre statistique) glissante',
    description="Statistique calculée sur une fenêtre glissante déclarée EN SECONDES — jamais en "
                "nombre d'échantillons : WAMA Data aligne des flux à cadences incommensurables, "
                "et « 50 points » n'y désigne pas la même durée d'un flux à l'autre. La fenêtre "
                "centrée lisse sans déphaser ; la fenêtre causale ne lit pas l'avenir, et c'est "
                "la seule licite si le résultat doit déclencher quelque chose.",
    category=FunctionCategory.ENRICHER,
    tags=['temporel', 'calcul', 'lissage'],
    inputs=[_ENTREE_SIGNAL],
    outputs=[PortSpec('signal', DataType.TIMESERIES,
                      description="Le signal, augmenté de la colonne « <colonne>_<statistique> ».")],
    params=[
        ParamSpec('window_s', 'float', 5.0, min=0.0, unit='s',
                  description="Largeur de la fenêtre, en secondes."),
        ParamSpec('statistic', 'enum', DEFAUT, choices=_CHOIX_STATS,
                  description="Statistique appliquée dans la fenêtre."),
        _PARAM_COLONNE,
        ParamSpec('centered', 'bool', True,
                  description="Fenêtre centrée (analyse) plutôt que causale (temps réel)."),
        ParamSpec('min_points', 'int', 1, min=1,
                  description="Minimum d'échantillons présents, sinon la sortie vaut « absent » — "
                              "évite une valeur calculée sur un seul point au milieu d'un trou."),
    ],
    cost={'cpu_bound': True},
    fn=calc_rolling,
))

register(FunctionSpec(
    key='calc_derivative',
    name='Dérivée temporelle',
    description="Taux de variation instantané (unité/seconde), par différence centrée à "
                "l'intérieur et décentrée aux bords. Rend « absent » là où le calcul n'a pas de "
                "sens — voisin manquant, ou deux échantillons au même instant : un signal à "
                "cadence irrégulière en contient, et les taire produirait des infinis qui "
                "contaminent toute statistique en aval.",
    category=FunctionCategory.ENRICHER,
    tags=['temporel', 'calcul'],
    inputs=[_ENTREE_SIGNAL],
    outputs=[PortSpec('signal', DataType.TIMESERIES,
                      description="Le signal, augmenté de la colonne « <colonne>_derivee ».")],
    params=[_PARAM_COLONNE],
    cost={'cpu_bound': True},
    fn=calc_derivative,
))

register(FunctionSpec(
    key='calc_cumulative',
    name='Intégrale cumulée',
    description="Aire sous le signal (unité × seconde) par la méthode des trapèzes. Un intervalle "
                "dont une borne manque n'apporte rien et le cumul se maintient : interpoler "
                "par-dessus le trou inventerait de l'aire sans que la sortie le signale.",
    category=FunctionCategory.ENRICHER,
    tags=['temporel', 'calcul'],
    inputs=[_ENTREE_SIGNAL],
    outputs=[PortSpec('signal', DataType.TIMESERIES,
                      description="Le signal, augmenté de la colonne « <colonne>_cumul ».")],
    params=[_PARAM_COLONNE],
    cost={'cpu_bound': True},
    fn=calc_cumulative,
))

register(FunctionSpec(
    key='calc_per_segment',
    name='Indicateurs par segment',
    description="Agrège un signal sur chaque segment et adjoint les indicateurs à celui-ci — une "
                "ligne par segment. Trois champs de service accompagnent toujours le résultat : "
                "`n` (échantillons présents), `duree` et `tronque`. Sans eux un indicateur absent "
                "serait indéchiffrable — aucune mesure dans la fenêtre, ou fenêtre jamais "
                "refermée ? Un segment OUVERT n'a d'ailleurs pas de durée observée (`duree` vaut "
                "« absent ») : une durée refermée par la fin de l'enregistrement n'est pas une "
                "durée mesurée, et les confondre fausse toute statistique de durée.",
    category=FunctionCategory.AGGREGATE,
    tags=['temporel', 'calcul', 'indicateurs'],
    inputs=[
        PortSpec('segments', DataType.SEGMENTS,
                 required_fields=CANONICAL_FIELDS[DataType.SEGMENTS],
                 description="Segments sur lesquels agréger (Segmenter, codage, transcription…)."),
        PortSpec('signal', DataType.TIMESERIES,
                 required_fields=CANONICAL_FIELDS[DataType.TIMESERIES],
                 description="Flux mesuré, échantillonné."),
    ],
    outputs=[PortSpec('segments', DataType.SEGMENTS, produced_fields=list(CHAMPS_DE_SERVICE),
                      description="Les segments reçus, augmentés d'une colonne "
                                  "« <colonne>_<statistique> » par statistique demandée.")],
    params=[
        ParamSpec('statistics', 'str', DEFAUT,
                  description="Statistiques à calculer, séparées par des virgules "
                              f"(disponibles : {', '.join(_CHOIX_STATS)})."),
        _PARAM_COLONNE,
    ],
    cost={'cpu_bound': True},
    fn=calc_per_segment,
))

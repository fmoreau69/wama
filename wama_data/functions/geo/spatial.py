"""
Déclaration au catalogue des prédicats SPATIAUX (implémentation : `wama_data/core/geo.py`).

⚠ POURQUOI IL N'Y A PAS DE « MODE DE SEGMENTATION SPATIALE » (question de Fabien, 2026-08-23,
tranchée par la mesure — `WAMA_DATA_WORLD.md §9septies`).

L'intuition de départ était un mode de plus au Segmenter, voire un « domaine spatial » face au
« domaine temporel ». La mesure de `cam_analyzer::find_intersection_windows` — qui fait déjà
exactement ça — montre que ce n'est ni l'un ni l'autre :

    dist = haversine(gps, carrefour)      →  une VALEUR, calculée par échantillon
    dist <= radius                        →  un MASQUE
    fusion des trous / rejet des courtes  →  `conditionnelle()`, déjà écrite

**La segmentation spatiale n'est donc pas un mode : c'est une COLONNE DÉRIVÉE suivie de la chaîne
conditionnelle existante.** La distance a la même clé temporelle que la trace dont elle vient —
donc `ENRICHER`, donc elle reste dans la table (§9quater.4), donc la chaîne la voit comme
n'importe quelle autre colonne numérique.

Le gain n'est pas d'écrire moins : c'est que **`distance_carrefour <= 40 ET vitesse > 30` devient
exprimable sans une ligne de code neuve**. Un « mode spatial » séparé, lui, n'aurait jamais pu se
mêler à un prédicat temporel — il aurait fallu un troisième mode pour ça, puis un quatrième.

⚠ CE QUI N'EST DÉLIBÉRÉMENT PAS ICI : une fonction `segment_dans_rayon()`. Elle ne demanderait
aucune brique neuve (distance + `segment_chaine_conditionnelle`) et dupliquerait le seuil et
l'hystérésis. Même arbitrage, mot pour mot, que le « temps passé au-dessus d'un seuil » écarté de
`core/calculation.py`.
"""
from __future__ import annotations

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionCategory, FunctionSpec, ParamSpec,
                                                  PortSpec, register)
from ...core.geo import distances_a_point
from ...core.noms import normaliser
from ..temporal.segmentation import _colonne


def distance_a_point(track: TypedFrame, lat: float = 0.0, lon: float = 0.0,
                     nom: str = '', champ_lat: str = 'lat',
                     champ_lon: str = 'lon') -> TypedFrame:
    """Distance de chaque position à un point de référence → colonne `distance_<nom>` (mètres).

    `nom` désigne le POINT (« carrefour_nord »), pas la colonne : le nom de colonne s'en dérive,
    comme partout ailleurs (`core/noms.py`). Sans lui, deux distances à deux points différents
    écraseraient la même colonne — et rien ne le signalerait.
    """
    if not nom:
        raise ValueError("nommer le point de référence : la colonne produite s'en dérive, et "
                         "deux points sans nom écraseraient la même colonne")
    valeurs = distances_a_point(_colonne(track, champ_lat), _colonne(track, champ_lon), lat, lon)
    df = track.df.copy()
    df[f"distance_{normaliser(nom)}"] = valeurs
    return TypedFrame(df, track.data_type, meta=track.meta)


register(FunctionSpec(
    key='distance_a_point',
    name='Distance à un point de référence',
    description="Adjoint à une trace la distance (mètres, haversine) de chaque position à un "
                "point géographique — carrefour, arrêt, borne. C'est la brique qui rend la "
                "segmentation SPATIALE exprimable : une fois la distance en colonne, « Segments "
                "par chaîne de conditions » la traite comme n'importe quel seuil, hystérésis "
                "comprise, ET peut la combiner à un prédicat temporel. Une position absente rend "
                "une distance absente, jamais une distance calculée sur zéro.",
    category=FunctionCategory.ENRICHER,
    tags=['geo', 'spatial', 'segmentation'],
    inputs=[PortSpec('track', DataType.GEO_TRACK, required_fields=['time', 'lat', 'lon'],
                     description='Trace géolocalisée.')],
    # `produced_fields` vide À DESSEIN : le nom se DÉDUIT du paramètre `nom`, aucune liste
    # statique ne peut le dire. Même arbitrage et mêmes motifs que le Calculator.
    outputs=[PortSpec('track', DataType.GEO_TRACK,
                      description="La trace, augmentée de `distance_<nom>` en mètres.")],
    params=[
        ParamSpec('nom', 'str', '', description="Nom du point de référence — la colonne produite "
                                                "s'en dérive (`distance_carrefour_nord`)."),
        ParamSpec('lat', 'float', 0.0, description='Latitude du point (degrés).'),
        ParamSpec('lon', 'float', 0.0, description='Longitude du point (degrés).'),
        ParamSpec('champ_lat', 'str', 'lat'),
        ParamSpec('champ_lon', 'str', 'lon'),
    ],
    cost={'cpu_bound': True},
    fn=distance_a_point,
))

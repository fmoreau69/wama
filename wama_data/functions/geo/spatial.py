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
from ...core.geo import abscisse_curviligne, distances_a_point
from ...core.noms import normaliser
from ...core.segmentation import marges_spatiales
from ..temporal.segmentation import _colonne, _fin, _segments


def distance_a_point(track: TypedFrame, lat: float = 0.0, lon: float = 0.0,
                     name: str = '', champ_lat: str = 'lat',
                     champ_lon: str = 'lon') -> TypedFrame:
    """Distance de chaque position à un point de référence → colonne `distance_<nom>` (mètres).

    `nom` désigne le POINT (« carrefour_nord »), pas la colonne : le nom de colonne s'en dérive,
    comme partout ailleurs (`core/noms.py`). Sans lui, deux distances à deux points différents
    écraseraient la même colonne — et rien ne le signalerait.
    """
    if not name:
        raise ValueError("nommer le point de référence : la colonne produite s'en dérive, et "
                         "deux points sans nom écraseraient la même colonne")
    valeurs = distances_a_point(_colonne(track, champ_lat), _colonne(track, champ_lon), lat, lon)
    df = track.df.copy()
    df[f"distance_{normaliser(name)}"] = valeurs
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
        ParamSpec('name', 'str', '', description="Nom du point de référence — la colonne produite "
                                                "s'en dérive (`distance_carrefour_nord`)."),
        ParamSpec('lat', 'float', 0.0, description='Latitude du point (degrés).'),
        ParamSpec('lon', 'float', 0.0, description='Longitude du point (degrés).'),
        ParamSpec('champ_lat', 'str', 'lat'),
        ParamSpec('champ_lon', 'str', 'lon'),
    ],
    cost={'cpu_bound': True},
    fn=distance_a_point,
))


def segments_spatial_margins(segments: TypedFrame, track: TypedFrame,
                              before_m: float = 0.0, after_m: float = 0.0,
                              champ_lat: str = 'lat', champ_lon: str = 'lon') -> TypedFrame:
    """Marges en MÈTRES le long de la trace — l'abscisse curviligne convertit la distance en bornes.

    Même généralisation que la segmentation spatiale ci-dessus : la marge spatiale n'est pas un
    mode, c'est une marge exprimée sur une COLONNE monotone (la distance parcourue) au lieu de
    `time`. Les bornes rendues sont des échantillons EXISTANTS de la trace.
    """
    abscisses = abscisse_curviligne(_colonne(track, champ_lat), _colonne(track, champ_lon))
    rows = [dict(r, end=_fin(r.get('end'))) for r in segments.df.to_dict('records')]
    return _segments(marges_spatiales(rows, _colonne(track, 'time'), abscisses,
                                      before_m=before_m, after_m=after_m),
                     meta=segments.meta)


register(FunctionSpec(
    key='segment_spatial_margins',
    name="Marges spatiales autour de segments (mètres le long de la trace)",
    description="Décale les bornes d'une DISTANCE PARCOURUE (« 50 m avant l'entrée de zone »), "
                "convertie en instants par l'abscisse curviligne de la trace. Les bornes rendues "
                "sont des échantillons EXISTANTS (aucune valeur inventée) : la marge rendue vaut "
                "AU MOINS la marge demandée, et s'arrête où la donnée s'arrête. Un trou GPS ne "
                "fabrique pas de distance ; une fin ouverte reste ouverte ; un segment qui "
                "s'inverse est écarté.",
    category=FunctionCategory.TRANSFORM,
    tags=['geo', 'spatial', 'segmentation'],
    inputs=[
        PortSpec('segments', DataType.SEGMENTS, required_fields=['start', 'end']),
        PortSpec('track', DataType.GEO_TRACK, required_fields=['time', 'lat', 'lon'],
                 description="Trace géolocalisée qui porte la distance parcourue."),
    ],
    outputs=[PortSpec('segments', DataType.SEGMENTS,
                      description="Segments aux bornes décalées — origine tracée, "
                                  "`source` garde l'origine d'avant la marge.")],
    params=[
        ParamSpec('before_m', 'float', 0.0, unit='m',
                  description="Marge AVANT chaque segment, en mètres parcourus."),
        ParamSpec('after_m', 'float', 0.0, unit='m',
                  description="Marge APRÈS chaque segment, en mètres parcourus."),
        ParamSpec('champ_lat', 'str', 'lat'),
        ParamSpec('champ_lon', 'str', 'lon'),
    ],
    cost={'cpu_bound': True},
    fn=segments_spatial_margins,
))

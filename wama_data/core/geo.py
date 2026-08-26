"""
Primitives GÉODÉSIQUES — le domicile unique des distances lat/lon du monde Data.

⚠ POURQUOI CE FICHIER (mesuré le 2026-08-23). La distance géodésique était implémentée **quatre
fois** dans le dépôt, toutes hors du monde Data :

    wama_lab/cam_analyzer/utils/intersection_analyzer.py::haversine
    wama_lab/cam_analyzer/utils/ego_pose.py::_haversine_m
    wama_lab/cam_analyzer/…::make_local_frame
    wama_data/functions/driving/gps_map_match.py::_local_frame   (privé, et son commentaire dit
                                                                  déjà « cohérent avec … cam_analyzer »)

Quatre implémentations d'une constante de la nature. Une cinquième était exclue : ce module est le
domicile, et les copies du Lab sont des **candidates à l'adoption** — pas touchées ici (périmètre
d'un autre monde), mais nommées pour que le portage soit un geste et non une redécouverte.

⚠ CE MODULE EST PUR — `math` seulement. Ni pandas, ni Django, ni `TypedFrame`, comme tout `core/`.
"""
from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence

#: Rayon moyen de la Terre (m), valeur usuelle WGS-84 sphérique.
RAYON_TERRE_M = 6371000.0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance grand-cercle entre deux points géographiques, en MÈTRES.

    Formule de haversine — stable pour les courtes distances, contrairement à la loi des cosinus
    sphériques qui perd sa précision sous quelques dizaines de mètres. C'est exactement l'échelle
    qui nous intéresse (rayon d'analyse autour d'un carrefour : 40 m).
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2)
    return 2 * RAYON_TERRE_M * math.asin(math.sqrt(a))


def _invalide(a: Any, b: Any) -> bool:
    """Position inexploitable : absente, non numérique, booléenne ou NaN (`x != x`)."""
    return (isinstance(a, bool) or isinstance(b, bool)
            or not isinstance(a, (int, float)) or not isinstance(b, (int, float))
            or a != a or b != b)


def distances_a_point(lats: Sequence[Any], lons: Sequence[Any],
                      lat: float, lon: float) -> List[Optional[float]]:
    """Distance de chaque position à un point de référence, en mètres.

    ⚠ Une position ABSENTE ou non numérique rend `None`, jamais une distance. Un trou GPS est un
    cas ordinaire (tunnel, perte de fix) et le remplacer par une valeur calculée sur `0.0`
    placerait le sujet au large de l'Afrique — une distance énorme, plausible, et fausse.
    """
    if len(lats) != len(lons):
        raise ValueError(f"lats et lons de longueurs différentes ({len(lats)} ≠ {len(lons)})")
    out: List[Optional[float]] = []
    for a, b in zip(lats, lons):
        if _invalide(a, b):
            out.append(None)
            continue
        out.append(haversine(a, b, lat, lon))
    return out


def abscisse_curviligne(lats: Sequence[Any], lons: Sequence[Any]) -> List[Optional[float]]:
    """Distance CUMULÉE le long de la trace, en mètres — l'abscisse curviligne de chaque position.

    C'est la colonne qui rend les MARGES SPATIALES exprimables (« 50 m avant l'entrée de zone ») :
    une distance parcourue se lit dessus par soustraction, comme un temps sur `time`.

    ⚠ Une position invalide rend `None` (mêmes règles que `distances_a_point`) et ne fait PAS
    avancer l'abscisse ; la position valide suivante cumule la distance depuis la DERNIÈRE valide.
    Le trou ne fabrique pas de distance — il la reporte d'un bloc, et l'abscisse reste MONOTONE.
    """
    if len(lats) != len(lons):
        raise ValueError(f"lats et lons de longueurs différentes ({len(lats)} ≠ {len(lons)})")
    out: List[Optional[float]] = []
    cumul = 0.0
    derniere: Optional[tuple] = None
    for a, b in zip(lats, lons):
        if _invalide(a, b):
            out.append(None)
            continue
        if derniere is not None:
            cumul += haversine(derniere[0], derniere[1], a, b)
        out.append(cumul)
        derniere = (a, b)
    return out

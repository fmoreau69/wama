"""
Zones ROUTIÈRES : l'emprise de la chaussée, tirée des axes BD TOPO et de leur largeur.

Demande de Fabien (2026-09-29) : *« tracer les contours de la voie comme pour la voie de la
navette pour faire apparaître les intersections correctement et connaître les zones routières
pour être sûr de ne pas exclure les véhicules aux intersections »*. La vue de dessus dessinait
jusque-là, à chaque intersection, une bande violette (branche apprise du trafic, ou bande
symétrique « aveugle » à défaut) : elle disait qu'il y avait une route croisante, pas OÙ était
la chaussée.

Chaque axe est élargi de sa demi-largeur de chaussée (`largeur_m`, sinon nombre de voies × 3 m
— la même règle que le recalage voie + carte, `driving.lane_map_matching.carriageway_width`),
puis les emprises sont UNIES : le contour de l'union suit les bords de chaussée et s'ouvre de
lui-même aux carrefours, là où deux emprises se rejoignent — ce qu'une bande par axe ne peut pas
faire (ses bords traverseraient le carrefour).

La même union sert à tester qu'une position est SUR la chaussée (`on_road`) : c'est le socle
de la seconde moitié de la demande (ne pas écarter un véhicule arrêté à un carrefour).

⚠ Le référentiel est l'IGN, pas l'orthophoto : un axe BD TOPO peut être décalé de quelques
mètres de la chaussée photographiée, et `largeur_de_chaussee` sous-estime parfois un boulevard.
Ce sont des zones de RÉFÉRENCE, pas une segmentation de l'image.
"""
from __future__ import annotations

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                                  FunctionCategory, register)
from wama_data.functions.driving.gps_map_match import local_frame
from wama_data.functions.driving.lane_map_matching import NOT_DRIVABLE, carriageway_width


def _clean(v):
    """None pour une valeur manquante — NaN d'un DataFrame compris."""
    return None if v is None or (isinstance(v, float) and v != v) else v


def road_zone_union(roads, to_xy, *, default_lane_width_m=3.0, excluded_types=NOT_DRIVABLE,
                    margin_m=0.0):
    """Union des emprises de chaussée, en mètres dans le repère `to_xy(lat, lon) → (x, y)`.

    `roads` : [{'geometry': [(lat, lon), …], 'largeur_m', 'nb_voies', 'sens', 'type'}] (forme du
    port `road_map`). `margin_m` élargit chaque emprise (tolérance d'un test d'appartenance).
    Rend une géométrie shapely (Polygon / MultiPolygon, vide si aucun tronçon roulable)."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    parts = []
    for r in roads:
        if r.get('type') in excluded_types:
            continue
        pts = [to_xy(la, lo) for la, lo in (r.get('geometry') or [])]
        if len(pts) < 2:
            continue
        W, _n = carriageway_width({'largeur': _clean(r.get('largeur_m')),
                                   'nb_voies': _clean(r.get('nb_voies')),
                                   'sens': _clean(r.get('sens'))}, default_lane_width_m)
        # extrémités PLATES : un bout de tronçon arrondi déborderait de la chaussée voisine
        parts.append(LineString(pts).buffer(W / 2.0 + margin_m, cap_style='flat', join_style='round'))
    return unary_union(parts)


def road_zones(road_map: TypedFrame, *, default_lane_width_m=3.0, excluded_types=NOT_DRIVABLE,
               simplify_m=0.3) -> TypedFrame:
    """Axes routiers (`road_map`) → emprises de chaussée UNIES, une ligne par polygone :
    `rings` = [contour extérieur, trous…], chacun en [(lat, lon), …] ; `area_m2`.
    `simplify_m` allège les contours (tolérance Douglas-Peucker, m) sans les déformer."""
    rows = road_map.df.to_dict('records')
    all_pts = [p for r in rows for p in (r.get('geometry') or [])]
    if not all_pts:
        return TypedFrame(road_map.df.iloc[0:0].assign(rings=[], area_m2=[]), DataType.TABLE)
    lat0 = sum(p[0] for p in all_pts) / len(all_pts)
    lon0 = sum(p[1] for p in all_pts) / len(all_pts)
    to_xy, to_ll = local_frame(lat0, lon0)
    union = road_zone_union(rows, to_xy, default_lane_width_m=default_lane_width_m,
                            excluded_types=excluded_types)
    if simplify_m:
        union = union.simplify(simplify_m, preserve_topology=True)
    polys = list(getattr(union, 'geoms', [union])) if not union.is_empty else []
    import pandas as pd

    def ring_ll(ring):
        return [tuple(round(v, 7) for v in to_ll(x, y)) for x, y in ring.coords]
    out = [{'rings': [ring_ll(p.exterior)] + [ring_ll(h) for h in p.interiors],
            'area_m2': round(p.area, 1)} for p in polys if p.geom_type == 'Polygon']
    return TypedFrame(pd.DataFrame(out, columns=['rings', 'area_m2']), DataType.TABLE,
                      meta={'road_zones': {'polygons': len(out), 'roads': len(rows),
                                           'origin': (lat0, lon0)}})


def on_road(union, x, y, margin_m=0.0):
    """La position (x, y) — même repère que l'union — est-elle sur la chaussée (± `margin_m`) ?"""
    from shapely.geometry import Point
    return (not union.is_empty) and union.distance(Point(x, y)) <= margin_m


SPEC = register(FunctionSpec(
    key='road_zones',
    name='Zones routières (emprise de chaussée)',
    description="Emprise de la CHAUSSÉE tirée des axes routiers de référence : chaque axe élargi "
                "de sa demi-largeur (largeur déclarée, sinon nombre de voies × 3 m), puis les "
                "emprises UNIES — le contour suit les bords de chaussée et s'ouvre aux carrefours. "
                "Sert l'affichage (bords de voie en vue de dessus) et le test « sur la chaussée ».",
    category=FunctionCategory.TRANSFORM,
    tags=['geo', 'reference', 'requires-road-map'],
    inputs=[PortSpec('road_map', DataType.ROAD_MAP, required_fields=['geometry'],
                     description='Axes routiers ((lat, lon), largeur_m, nb_voies, sens, type — '
                                 'les natures non roulables sont écartées).')],
    outputs=[PortSpec('zones', DataType.TABLE, produced_fields=['rings', 'area_m2'],
                      cardinality='many',
                      description='Polygones de chaussée : contour extérieur puis trous, en (lat, lon).')],
    params=[
        ParamSpec('default_lane_width_m', 'float', 3.0, 2.0, 5.0, 'm',
                  'Largeur de voie supposée quand la chaussée n\'a pas de largeur déclarée.'),
        ParamSpec('simplify_m', 'float', 0.3, 0.0, 5.0, 'm', 'Tolérance de simplification des contours.'),
    ],
    fn=road_zones,
))

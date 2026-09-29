"""Zones routières (2026-09-29) : emprise de chaussée = axes élargis de leur largeur, puis UNIS."""
import math
import unittest

import pandas as pd

from wama.common.catalog.data_types import DataType, TypedFrame
from wama_data.functions.driving.gps_map_match import local_frame
from wama_data.functions.driving.lane_map_matching import carriageway_width, expected_lane_offset
from wama_data.functions.geo.road_zones import on_road, road_zone_union, road_zones

LAT0, LON0 = 43.62, 7.07
M_LON = 111320.0 * math.cos(math.radians(LAT0))


def _ll(x, y):
    return (LAT0 + y / 111320.0, LON0 + x / M_LON)


def _road(pts, **kw):
    return {'geometry': [_ll(x, y) for x, y in pts], 'largeur_m': kw.get('w'), 'nb_voies': kw.get('n'),
            'sens': kw.get('sens', 'Double sens'), 'type': kw.get('type', 'Route à 1 chaussée')}


CROSS = [_road([(-50, 0), (50, 0)], w=8.0), _road([(0, -50), (0, 50)], w=6.0)]


class RoadZoneUnionTest(unittest.TestCase):

    def setUp(self):
        self.to_xy, _ = local_frame(LAT0, LON0)
        self.union = road_zone_union(CROSS, self.to_xy)

    def test_a_crossroads_is_ONE_polygon_open_at_the_junction(self):
        """Deux bandes séparées auraient des bords qui traversent le carrefour ; l'union non."""
        self.assertEqual(self.union.geom_type, 'Polygon')
        self.assertAlmostEqual(self.union.area, 100 * 8 + 100 * 6 - 8 * 6, delta=5.0)

    def test_on_road_follows_the_declared_width(self):
        x, y = self.to_xy(*_ll(20, 3.9))
        self.assertTrue(on_road(self.union, x, y))                   # demi-largeur 4 m
        x, y = self.to_xy(*_ll(20, 4.5))
        self.assertFalse(on_road(self.union, x, y))
        self.assertTrue(on_road(self.union, x, y, margin_m=1.0))

    def test_non_drivable_natures_are_left_out(self):
        path = _road([(-50, 20), (50, 20)], w=3.0, type='Sentier')
        union = road_zone_union(CROSS + [path], self.to_xy)
        x, y = self.to_xy(*_ll(20, 20))
        self.assertFalse(on_road(union, x, y))

    def test_missing_width_falls_back_to_lanes_times_three_metres(self):
        union = road_zone_union([_road([(-50, 0), (50, 0)], w=float('nan'), n=2)], self.to_xy)
        self.assertAlmostEqual(union.area, 100 * 6.0, delta=1.0)


class RoadZonesFrameTest(unittest.TestCase):

    def test_rings_come_back_in_lat_lon_and_close(self):
        out = road_zones(TypedFrame(pd.DataFrame(CROSS), DataType.ROAD_MAP))
        self.assertEqual(len(out.df), 1)
        outer = out.df.iloc[0]['rings'][0]
        self.assertEqual(outer[0], outer[-1])
        self.assertTrue(all(abs(la - LAT0) < 0.001 and abs(lo - LON0) < 0.001 for la, lo in outer))

    def test_an_empty_road_map_gives_no_zone(self):
        out = road_zones(TypedFrame(pd.DataFrame(columns=['geometry']), DataType.ROAD_MAP))
        self.assertTrue(out.df.empty)


class CarriagewayWidthKeepsTheLaneRecalageBehaviourTest(unittest.TestCase):
    """`carriageway_width` a été extrait de `expected_lane_offset` : le recalage voie + carte ne
    doit pas changer, NaN compris (une largeur NaN SE PROPAGE — l'ancre tombe à la porte
    `correction_too_big`, comportement historique ; `road_zones` passe None pour le défaut)."""

    def test_declared_unknown_and_nan_widths(self):
        self.assertEqual(carriageway_width({'largeur': 7.0, 'nb_voies': 2}), (7.0, 2))
        self.assertEqual(carriageway_width({'sens': 'Double sens'}), (6.0, 2))
        self.assertEqual(carriageway_width({'sens': 'Sens direct'}), (3.0, 1))
        w, n = carriageway_width({'largeur': float('nan'), 'nb_voies': 2})
        self.assertTrue(math.isnan(w))
        self.assertEqual(expected_lane_offset({'largeur': 7.0, 'nb_voies': 2}), (1.75, 3.5))


if __name__ == '__main__':
    unittest.main(verbosity=2)

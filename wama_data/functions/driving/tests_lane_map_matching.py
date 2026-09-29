"""Recalage latéral voie + carte — briques pures, sur une scène SYNTHÉTIQUE aux pièges VÉCUS.

Scène (repère local, m) : l'axe parcouru x = 0 (nord-sud, double sens, 2 voies, 6 m → centre de
la voie de droite à +1,5 m), une route PARALLÈLE à x = +15 et une PERPENDICULAIRE en y = 50. La
navette roule vers le nord, centrée dans sa voie (x = +1,5) ; le GPS la place 2 m trop à droite.
Les deux pièges sont ceux mesurés le 2026-09-28 sur la session ENA : le plus-proche-segment
sautait sur une route parallèle, puis sur une perpendiculaire (Δcap −78°).
"""
import math
import random

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from wama.common.catalog.data_types import DataType, TypedFrame
from wama_data.functions.driving.gps_map_match import local_frame, map_match, match_track, road_segments
from wama_data.functions.driving.lane_map_matching import (
    expected_lane_offset, lane_map_recalage, lane_observation, lateral_corrections)

LAT0, LON0 = 43.6188, 7.0751
TO_XY, TO_LL = local_frame(LAT0, LON0)


def _road(x0, y0, x1, y1, **attrs):
    (la0, lo0), (la1, lo1) = TO_LL(x0, y0), TO_LL(x1, y1)
    return {'coords': [(lo0, la0), (lo1, la1)], **attrs}


ROADS = [
    _road(0, -200, 0, 200, nb_voies=2, largeur=6.0, sens='Double sens'),     # parcourue
    _road(15, -200, 15, 200, nb_voies=2, largeur=6.0, sens='Double sens'),   # parallèle
    _road(-100, 50, 100, 50, nb_voies=2, largeur=6.0, sens='Double sens'),   # perpendiculaire
]


class RoadMatchingTest(SimpleTestCase):
    def setUp(self):
        self.segs = road_segments(ROADS, TO_XY)

    def _naive(self, x, y):
        best = None
        for s in self.segs:
            dx, dy = s['bx'] - s['ax'], s['by'] - s['ay']
            t = max(0.0, min(1.0, ((x - s['ax']) * dx + (y - s['ay']) * dy) / (dx * dx + dy * dy)))
            d = math.hypot(x - s['ax'] - t * dx, y - s['ay'] - t * dy)
            if best is None or d < best[0]:
                best = (d, s['road'])
        return best[1]

    def test_a_brief_drift_towards_a_parallel_road_does_not_switch_roads(self):
        pts = [(1.5, y, 0.0, True) for y in range(-100, 0, 3)]
        pts[10:13] = [(8.5, pts[k][1], 0.0, True) for k in range(10, 13)]
        self.assertEqual(self._naive(8.5, pts[11][1]), 1)            # le piège existe
        roads = {m['road'] for m in match_track(pts, self.segs)}
        self.assertEqual(roads, {0})

    def test_crossing_an_intersection_keeps_the_driven_road(self):
        pts = [(1.5, y, 0.0, True) for y in np.arange(30.0, 70.0, 1.0)]
        pts.append((3.5, 50.5, 0.0, True))
        self.assertEqual(self._naive(3.5, 50.5), 2)                  # le piège existe
        roads = {m['road'] for m in match_track(sorted(pts, key=lambda p: p[1]), self.segs)}
        self.assertEqual(roads, {0})

    def test_without_history_the_heading_decides_near_a_crossing(self):
        # Un point isolé (reprise après un trou) : la continuité ne peut rien, seul le cap tranche.
        self.assertEqual(match_track([(3.5, 50.5, 0.0, True)], self.segs)[0]['road'], 0)
        self.assertEqual(match_track([(3.5, 50.5, 90.0, True)], self.segs)[0]['road'], 2)

    def test_a_real_turn_onto_the_crossing_road_is_followed(self):
        # Contre-épreuve de la continuité : elle ne doit pas bloquer un VRAI virage.
        pts = [(1.5, y, 0.0, True) for y in np.arange(20.0, 48.0, 2.0)]
        pts += [(x, 48.5, 90.0, True) for x in np.arange(6.0, 60.0, 2.0)]
        m = match_track(pts, self.segs)
        self.assertEqual(m[0]['road'], 0)
        self.assertEqual(m[-1]['road'], 2)

    def test_map_match_continuous_mode_does_not_jump_where_nearest_mode_does(self):
        # La même brique catalogue, deux modes : 'nearest' (portage d'origine) saute sur la
        # parallèle pendant l'excursion, 'continuous' reste sur la route parcourue.
        rows = []
        for k, y in enumerate(range(-100, 0, 3)):
            x = 8.5 if 10 <= k < 13 else 1.5
            la, lo = TO_LL(x, float(y))
            rows.append({'ts': float(k), 'lat': la, 'lon': lo, 'heading': 0.0, 'speed_kmh': 10.0})
        rm = pd.DataFrame([{'id': f'r{i}', 'geometry': [(p[1], p[0]) for p in r['coords']]}
                           for i, r in enumerate(ROADS)])
        tr = TypedFrame(pd.DataFrame(rows), DataType.GEO_TRACK)
        nearest = map_match(tr, TypedFrame(rm, DataType.ROAD_MAP))
        continuous = map_match(tr, TypedFrame(rm, DataType.ROAD_MAP), method='continuous')
        self.assertIn('r1', set(nearest.df['section_id']))
        self.assertEqual(set(continuous.df['section_id']), {'r0'})

    def test_lateral_is_signed_to_the_right_of_travel_in_both_directions(self):
        north = match_track([(2.0, 0.0, 0.0, True)], self.segs)[0]
        south = match_track([(2.0, 0.0, 180.0, True)], self.segs)[0]
        self.assertAlmostEqual(north['lateral_m'], 2.0, places=2)    # à l'est en allant au nord = droite
        self.assertAlmostEqual(south['lateral_m'], -2.0, places=2)
        self.assertAlmostEqual(south['bearing_deg'], 180.0, places=1)


class ProjectionOvershootTest(SimpleTestCase):
    def test_beyond_the_end_of_a_road_the_offset_is_not_lateral(self):
        from wama_data.functions.driving.gps_map_match import _project
        seg = {'ax': 0.0, 'ay': 0.0, 'bx': 0.0, 'by': 10.0}
        self.assertEqual(_project(1.0, 5.0, seg), (1.0, 1.0, 0.0))
        d, lat, over = _project(1.0, 15.0, seg)
        self.assertAlmostEqual(over, 5.0)

    def test_an_observation_past_a_dead_end_is_not_an_anchor(self):
        stub = [_road(0, -200, 0, 0, nb_voies=2, largeur=6.0, sens='Double sens')]
        rows, lanes = [], []
        for k, y in enumerate(np.arange(10.0, 20.0, 1.0)):        # 10-20 m APRÈS le bout
            la, lo = TO_LL(3.5, y)
            rows.append({'ts': float(k), 'lat': la, 'lon': lo, 'heading': 0.0})
            lanes.append({'ts': float(k), 'offset_m': 0.0, 'width_m': 3.0, 'rel_heading_deg': 0.0})
        rm = pd.DataFrame([{'geometry': [(p[1], p[0]) for p in r['coords']], 'nb_voies': 2,
                            'largeur_m': 6.0, 'sens': 'Double sens'} for r in stub])
        out = lane_map_recalage(TypedFrame(pd.DataFrame(rows), DataType.GEO_TRACK),
                                TypedFrame(rm, DataType.ROAD_MAP), TypedFrame(pd.DataFrame(lanes), DataType.TABLE))
        self.assertEqual(out.meta['lane_map']['anchors'], 0)
        self.assertEqual(out.meta['lane_map']['rejected']['beyond_road_end'], 10)


class LaneGeometryTest(SimpleTestCase):
    def test_the_right_lane_centre_follows_width_lanes_and_direction(self):
        self.assertEqual(expected_lane_offset({'nb_voies': 2, 'largeur': 6.0, 'sens': 'Double sens'}), (1.5, 3.0))
        self.assertEqual(expected_lane_offset({'nb_voies': 1, 'largeur': 4.0, 'sens': 'Sens direct'})[0], 0.0)
        self.assertEqual(expected_lane_offset({'nb_voies': 3, 'largeur': None, 'sens': 'Sens direct'}), (3.0, 3.0))

    def test_the_camera_offset_and_width_come_from_the_nearest_lines(self):
        lines = [[(-1.3, y) for y in np.arange(3, 12, 0.5)], [(1.7, y) for y in np.arange(3, 12, 0.5)],
                 [(5.0, y) for y in np.arange(3, 12, 0.5)]]
        obs = lane_observation(lines)
        self.assertAlmostEqual(obs['width_m'], 3.0, places=2)
        self.assertAlmostEqual(obs['offset_m'], -0.2, places=2)      # caméra 0,2 m à GAUCHE du centre
        self.assertAlmostEqual(obs['rel_heading_deg'], 0.0, places=2)

    def test_lines_leaning_right_mean_the_vehicle_is_turned_left(self):
        t = math.tan(math.radians(5.0))
        lines = [[(-1.5 + t * y, y) for y in np.arange(3, 12, 0.5)], [(1.5 + t * y, y) for y in np.arange(3, 12, 0.5)]]
        self.assertAlmostEqual(lane_observation(lines)['rel_heading_deg'], -5.0, places=1)

    def test_a_sparse_mask_contour_is_densified_before_the_fit(self):
        # contour d'un masque de ligne : 4 sommets, AUCUN dans la bande 5-10 m
        def thin(x):
            return [(x - 0.1, 3.0), (x - 0.1, 12.0), (x + 0.1, 12.0), (x + 0.1, 3.0)]
        obs = lane_observation([thin(-1.5), thin(1.5)])
        self.assertIsNotNone(obs)
        self.assertAlmostEqual(obs['width_m'], 3.0, places=2)

    def test_a_diagonal_blob_is_not_a_lane_line(self):
        straight = [[(-1.5, y) for y in np.arange(3, 12, 0.5)], [(3.0, y) for y in np.arange(3, 12, 0.5)]]
        diagonal = [(-0.5 + 0.6 * (y - 5.0), y) for y in np.arange(5, 10.5, 0.5)]   # 31°
        self.assertAlmostEqual(lane_observation(straight + [diagonal])['width_m'], 4.5, places=2)
        # contre-épreuve : sans la borne de pente, la diagonale devient la ligne de droite
        self.assertAlmostEqual(lane_observation(straight + [diagonal], max_slope_deg=45)['width_m'], 2.5, places=2)

    def test_an_implausible_width_is_not_an_observation(self):
        lines = [[(-1.3, y) for y in np.arange(3, 12, 0.5)], [(9.0, y) for y in np.arange(3, 12, 0.5)]]
        self.assertIsNone(lane_observation(lines))


class MovingTest(SimpleTestCase):
    def test_repeated_fixes_do_not_make_a_driving_vehicle_stopped(self):
        from wama_data.functions.driving.lane_map_matching import _moving
        # 6 m/s, un fix par seconde RÉPÉTÉ deux fois (vitesse fixe-à-fixe nulle 2 fois sur 3)
        ts, xy = [], []
        for s in range(10):
            for dt in (0.0, 0.1, 0.4):
                ts.append(s + dt); xy.append((0.0, 6.0 * s))
        self.assertTrue(_moving(np.array(ts), np.array(xy)).all())

    def test_a_stopped_vehicle_is_not_moving(self):
        from wama_data.functions.driving.lane_map_matching import _moving
        ts = np.arange(0.0, 10.0, 0.5)
        self.assertFalse(_moving(ts, np.zeros((len(ts), 2))).any())


class CorrectionSeriesTest(SimpleTestCase):
    def test_interpolation_between_anchors_and_ramp_far_from_them(self):
        cl, ch, anc = lateral_corrections([0, 5, 10], [-2, -2, -2], [0, 0, 0], [2.5, 7.0, 60.0])
        self.assertAlmostEqual(cl[0], -2.0); self.assertAlmostEqual(cl[1], -2.0)
        self.assertEqual(cl[2], 0.0); self.assertFalse(anc[2])

    def test_a_single_outlier_anchor_is_smoothed_away(self):
        cl, _, _ = lateral_corrections([0, 1, 2, 3, 4], [-2, -2, 3, -2, -2], [0] * 5, [2.0])
        self.assertAlmostEqual(cl[0], -2.0)


class EndToEndTest(SimpleTestCase):
    def test_the_gps_bias_is_recovered_on_the_driven_road(self):
        rng = random.Random(20260928)
        rows, lanes = [], []
        for k, y in enumerate(np.arange(-150.0, 150.0, 3.0)):
            t = float(k)
            gx = 1.5 + 2.0 + rng.gauss(0, 0.3)                          # GPS : 2 m trop à droite
            la, lo = TO_LL(gx, y + rng.gauss(0, 0.3))
            rows.append({'ts': t, 'lat': la, 'lon': lo, 'heading': 0.0, 'speed_kmh': 10.8})
            lanes.append({'ts': t, 'offset_m': 0.0, 'rel_heading_deg': 0.0})
        rm = pd.DataFrame([{'geometry': [(p[1], p[0]) for p in r['coords']], 'nb_voies': r['nb_voies'],
                            'largeur_m': r['largeur'], 'sens': r['sens']} for r in ROADS])
        out = lane_map_recalage(TypedFrame(pd.DataFrame(rows), DataType.GEO_TRACK),
                                TypedFrame(rm, DataType.ROAD_MAP),
                                TypedFrame(pd.DataFrame(lanes), DataType.TABLE))
        de = out.df['corr_de_m'].to_numpy()
        self.assertAlmostEqual(float(np.median(de)), -2.0, delta=0.2)
        self.assertLess(float(np.median(np.abs(out.df['corr_dn_m']))), 0.05)   # latéral seulement
        self.assertGreater(out.meta['lane_map']['anchored_share'], 0.95)

    def _run(self, lane_offset, lane_width, **kw):
        rows, lanes = [], []
        for k, y in enumerate(np.arange(-150.0, 150.0, 3.0)):
            la, lo = TO_LL(1.5 + 2.0, y)                                  # GPS : 2 m trop à droite
            rows.append({'ts': float(k), 'lat': la, 'lon': lo, 'heading': 0.0, 'speed_kmh': 10.8})
            lanes.append({'ts': float(k), 'offset_m': lane_offset, 'width_m': lane_width,
                          'rel_heading_deg': 0.0})
        rm = pd.DataFrame([{'geometry': [(p[1], p[0]) for p in r['coords']], 'nb_voies': r['nb_voies'],
                            'largeur_m': r['largeur'], 'sens': r['sens']} for r in ROADS])
        return lane_map_recalage(TypedFrame(pd.DataFrame(rows), DataType.GEO_TRACK),
                                 TypedFrame(rm, DataType.ROAD_MAP),
                                 TypedFrame(pd.DataFrame(lanes), DataType.TABLE), **kw)

    def test_an_inflated_lateral_scale_is_measured_against_the_map_and_removed(self):
        # navette VRAIMENT 0,4 m à droite du centre de voie ; projection qui gonfle les X ×1,8
        out = self._run(0.4 * 1.8, 3.0 * 1.8)
        rep = out.meta['lane_map']
        self.assertAlmostEqual(rep['lateral_scale'], 1.8, places=2)
        self.assertEqual(rep['lateral_scale_source'], 'measured')
        self.assertAlmostEqual(float(np.median(out.df['corr_de_m'])), -1.6, delta=0.05)
        # contre-épreuve : en croyant la projection, la voie « de 5,4 m » est rejetée partout
        self.assertEqual(self._run(0.4 * 1.8, 3.0 * 1.8, lateral_scale=1.0).meta['lane_map']['anchors'], 0)

    def test_a_held_correction_keeps_its_direction_through_a_turn(self):
        # nord le long de x = 0 avec observations, puis virage à droite sur la perpendiculaire
        # SANS observation (maintien) : la correction reste le vecteur mesuré (−2 m vers l'ouest)
        rows, lanes = [], []
        for k, y in enumerate(np.arange(-30.0, 48.0, 3.0)):
            la, lo = TO_LL(3.5, y)
            rows.append({'ts': float(k), 'lat': la, 'lon': lo, 'heading': 0.0, 'speed_kmh': 10.8})
            lanes.append({'ts': float(k), 'offset_m': 0.0, 'width_m': 3.0, 'rel_heading_deg': 0.0})
        t0 = len(rows)
        for j in range(5):
            la, lo = TO_LL(6.5 + 3.0 * j, 46.5)
            rows.append({'ts': float(t0 + j), 'lat': la, 'lon': lo, 'heading': 90.0, 'speed_kmh': 10.8})
        rm = pd.DataFrame([{'geometry': [(p[1], p[0]) for p in r['coords']], 'nb_voies': r['nb_voies'],
                            'largeur_m': r['largeur'], 'sens': r['sens']} for r in ROADS])
        out = lane_map_recalage(TypedFrame(pd.DataFrame(rows), DataType.GEO_TRACK),
                                TypedFrame(rm, DataType.ROAD_MAP),
                                TypedFrame(pd.DataFrame(lanes), DataType.TABLE))
        after = out.df.iloc[t0 + 1:]
        self.assertTrue(after['lane_anchored'].all())
        self.assertAlmostEqual(float(after['corr_de_m'].median()), -2.0, delta=0.1)
        self.assertLess(float(after['corr_dn_m'].abs().max()), 0.1)

    def test_a_footpath_is_never_the_road_of_a_vehicle(self):
        # un sentier SOUS la trace GPS ; la route réelle 2 m plus loin
        roads = ROADS + [_road(3.5, -200, 3.5, 200, nb_voies=None, largeur=None, sens='Sans objet',
                               type='Sentier')]
        rm = pd.DataFrame([{'geometry': [(p[1], p[0]) for p in r['coords']], 'nb_voies': r['nb_voies'],
                            'largeur_m': r['largeur'], 'sens': r['sens'], 'type': r.get('type')}
                           for r in roads])
        rows, lanes = [], []
        for k, y in enumerate(np.arange(-30.0, 30.0, 3.0)):
            la, lo = TO_LL(3.5, y)
            rows.append({'ts': float(k), 'lat': la, 'lon': lo, 'heading': 0.0})
            lanes.append({'ts': float(k), 'offset_m': 0.0, 'width_m': 3.0, 'rel_heading_deg': 0.0})
        run = lambda **kw: lane_map_recalage(TypedFrame(pd.DataFrame(rows), DataType.GEO_TRACK),
                                             TypedFrame(rm, DataType.ROAD_MAP),
                                             TypedFrame(pd.DataFrame(lanes), DataType.TABLE), **kw)
        self.assertAlmostEqual(float(run().df['corr_de_m'].median()), -2.0, delta=0.05)
        # contre-épreuve : sentier admis, la trace s'y rattache et rien n'est corrigé à -2 m
        self.assertNotAlmostEqual(float(run(excluded_types=()).df['corr_de_m'].median()), -2.0, delta=0.5)

    def test_the_kalman_bias_carries_the_correction_through_a_long_gap(self):
        # ancres sur 60 m, puis 45 s sans aucune observation (boucle, carrefour) : l'interpolation
        # retombe à zéro loin des ancres, le biais lissé reste appliqué
        rows, lanes = [], []
        for k, y in enumerate(np.arange(-150.0, 150.0, 3.0)):
            la, lo = TO_LL(1.5 + 2.0, y)                          # GPS : 2 m trop à droite
            rows.append({'ts': float(k), 'lat': la, 'lon': lo, 'heading': 0.0})
            if k < 20 or k > 65:
                lanes.append({'ts': float(k), 'offset_m': 0.0, 'width_m': 3.0, 'rel_heading_deg': 0.0})
        rm = pd.DataFrame([{'geometry': [(p[1], p[0]) for p in r['coords']], 'nb_voies': r['nb_voies'],
                            'largeur_m': r['largeur'], 'sens': r['sens']} for r in ROADS])
        run = lambda model: lane_map_recalage(TypedFrame(pd.DataFrame(rows), DataType.GEO_TRACK),
                                              TypedFrame(rm, DataType.ROAD_MAP),
                                              TypedFrame(pd.DataFrame(lanes), DataType.TABLE),
                                              bias_model=model).df
        k = 43                                                    # au milieu du trou
        self.assertAlmostEqual(float(run('kalman')['corr_de_m'].iloc[k]), -2.0, delta=0.3)
        self.assertEqual(float(run('interpolate')['corr_de_m'].iloc[k]), 0.0)

    def test_without_lane_observations_nothing_is_corrected(self):
        la, lo = TO_LL(3.5, 0.0)
        tr = TypedFrame(pd.DataFrame([{'ts': 0.0, 'lat': la, 'lon': lo, 'heading': 0.0, 'speed_kmh': 10.0}]),
                        DataType.GEO_TRACK)
        rm = pd.DataFrame([{'geometry': [(p[1], p[0]) for p in ROADS[0]['coords']], 'nb_voies': 2,
                            'largeur_m': 6.0, 'sens': 'Double sens'}])
        out = lane_map_recalage(tr, TypedFrame(rm, DataType.ROAD_MAP),
                                TypedFrame(pd.DataFrame(columns=['ts', 'offset_m', 'rel_heading_deg']),
                                           DataType.TABLE))
        self.assertEqual(float(out.df['corr_de_m'].iloc[0]), 0.0)

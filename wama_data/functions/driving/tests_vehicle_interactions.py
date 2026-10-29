"""Interactions navette ↔ véhicules (`vehicle_interactions`, 2026-10-29) : insertions et dépassements.

Scène de référence : la navette roule plein nord sur e = 0, de n = −50 à n = 50 à 5 m/s (t de 0 à 20 s),
voie de 3,5 m. Les valeurs attendues se calculent à la main (cf. chaque test)."""
import math

from django.test import SimpleTestCase

from wama_data.functions.driving.vehicle_interactions import (PathFrame, ShuttleTrack, insertion_rows,
                                                              observed_ttc, overtaking_rows, _first_movement)

STEP = 0.1


def shuttle_rows():
    return [(k * STEP, 0.0, -50.0 + 5.0 * k * STEP, 0.0) for k in range(int(20 / STEP) + 1)]


def track(with_path=True):
    rows = shuttle_rows()
    return ShuttleTrack(rows, PathFrame([(r[1], r[2]) for r in rows]) if with_path else None)


def side_vehicle():
    """Arrêté à droite (e = 15, n = 30) jusqu'à t = 4, puis roule vers l'ouest à 5 m/s."""
    out = []
    for k in range(int(10 / STEP) + 1):
        t = k * STEP
        moving = t > 4.0
        e = 15.0 - 5.0 * (t - 4.0) if moving else 15.0
        out.append((t, e, 30.0, -5.0 if moving else 0.0, 0.0, 'car', None, None))
    return out


def through_vehicle():
    """Trafic de passage dans la voie opposée, vers le sud, sans jamais en sortir."""
    return [(k * STEP, -3.5, 60.0 - 8.0 * k * STEP, 0.0, -8.0, 'car', None, None) for k in range(101)]


WINDOW = {'name': 'X', 'idx': 0, 't_enter': 0.0, 't_exit': 20.0, 'center': (0.0, 25.0), 'radius_m': 30.0}


class GeometryTest(SimpleTestCase):

    def test_the_path_frame_gives_the_abscissa_and_a_right_positive_offset(self):
        path = PathFrame([(0.0, 0.0), (0.0, 10.0), (0.0, 20.0)])
        s, lat, (ue, un) = path.project(2.0, 5.0)
        self.assertAlmostEqual(s, 5.0, places=6)
        self.assertAlmostEqual(lat, 2.0, places=6, msg='à l\'est d\'un chemin vers le nord : à droite')
        self.assertEqual((ue, un), (0.0, 1.0))
        self.assertAlmostEqual(path.project(-1.0, 30.0)[0], 30.0, places=6, msg='au-delà du bout : prolongé')

    def test_the_observed_ttc_is_the_footprint_collision_at_constant_speed(self):
        """Face à face, navette 5,5 m et voiture 4,5 m, centres à 20 m, rapprochement 10 m/s : les
        pare-chocs se touchent à (20 − 5) / 10 = 1,5 s, au pas de 0,2 s près (`TTC_STEP_S`)."""
        shuttle = (0.0, 0.0, 0.0, 5.0, 5.5, 2.1)
        self.assertAlmostEqual(observed_ttc(0.0, shuttle, (0.0, 20.0, 0.0, -5.0, 4.5, 1.8)), 1.5, delta=0.21)
        self.assertIsNone(observed_ttc(0.0, shuttle, (0.0, 20.0, 0.0, 10.0, 4.5, 1.8)), 'il s\'éloigne')
        self.assertEqual(observed_ttc(0.0, shuttle, (0.0, 3.0, 0.0, 5.0, 4.5, 1.8)), 0.0, 'ils se touchent')
        self.assertIsNone(observed_ttc(0.0, shuttle, (0.0, 200.0, 0.0, -5.0, 4.5, 1.8)),
                          'au-delà de l\'horizon')
        self.assertIsNone(observed_ttc(0.0, shuttle, (3.5, 20.0, 0.0, -5.0, 4.5, 1.8)),
                          'il croise dans la voie voisine sans toucher')

    def test_the_first_movement_after_a_stop(self):
        times = [k * STEP for k in range(100)]
        speeds = [0.0 if t < 3.0 else 2.0 for t in times]
        t0, from_stop, waited = _first_movement(times, speeds)
        self.assertAlmostEqual(t0, 3.0, places=6)
        self.assertTrue(from_stop)
        self.assertGreater(waited, 2.5)
        t0, from_stop, _w = _first_movement(times, [2.0] * 100)
        self.assertEqual((t0, from_stop), (0.0, False), 'roulait déjà')


class InsertionRowsTest(SimpleTestCase):

    def rows(self, vehicles, parked=()):
        return insertion_rows(WINDOW, track(), vehicles, parked=parked, lane_w=3.5)

    def test_a_vehicle_waiting_on_the_right_then_crossing_ahead_of_the_shuttle(self):
        (row,) = self.rows({'7': side_vehicle()})
        self.assertTrue(row['inserted'])
        self.assertTrue(row['shuttle_lane'] and row['opposite_lane'])
        self.assertTrue(row['started_from_stop'])
        self.assertAlmostEqual(row['t0_s'], 4.1, delta=0.15)
        # entre dans la voie de la navette à e = 1,75 : t = 4 + 13,25 / 5 = 6,65 ; en sort à e = −1,75 : 7,35
        self.assertAlmostEqual(row['t1_s'], 6.65, delta=0.15)
        self.assertAlmostEqual(row['t2_s'], 7.35, delta=0.15)
        self.assertEqual(row['t2_kind'], 'sortie')
        self.assertTrue(row['before_shuttle'])
        # la navette (avant à s = 80) n'arrive qu'à 14,9 s : PET = 14,9 − 7,35, le véhicule d'abord
        self.assertAlmostEqual(row['pet_s'], 7.55, delta=0.2)
        self.assertEqual(row['pet_first'], 'vehicle_first')
        self.assertGreater(row['d1_m'], 0)

    def test_through_traffic_and_parked_cars_are_not_listed(self):
        self.assertEqual(self.rows({'8': through_vehicle()}), [])
        self.assertEqual(self.rows({'7': side_vehicle()}, parked={'7'}), [])

    def test_a_vehicle_behind_the_shuttle_in_its_lane_is_its_rear_vehicle(self):
        behind = [(k * STEP, 0.0, -50.0 + 5.0 * k * STEP - 15.0, 0.0, 6.0, 'car', None, None) for k in range(201)]
        (row,) = self.rows({'7': side_vehicle(), '9': behind})
        self.assertTrue(row['rear_present'])
        # 15 m derrière le centre arrière, demi-longueur 2,25 : 12,75 m de pare-chocs à pare-chocs
        self.assertAlmostEqual(row['rear_min_gap_m'], 12.75, delta=0.3)
        self.assertEqual(row['rear_span'], 'traversée')


class OvertakingRowsTest(SimpleTestCase):

    def test_a_car_overtaking_on_the_left_then_cutting_in(self):
        car = []
        for k in range(int(14 / STEP) + 1):
            t = k * STEP
            e = -3.5 if t < 9.0 else 0.0
            car.append((t, e, -80.0 + 10.0 * t, 0.0, 10.0, 'car', None, None))
        (row,) = overtaking_rows(track(with_path=False), {'4': car}, lane_w=3.5)
        self.assertEqual((row['direction'], row['side']), ('vehicle_overtakes_shuttle', 'left'))
        # à hauteur quand −80 + 10 t = −47,25 + 5 t : t = 6,55
        self.assertAlmostEqual(row['t_alongside_s'], 6.55, delta=0.15)
        self.assertAlmostEqual(row['lateral_gap_min_m'], 3.5 - 1.05 - 0.9, delta=0.05)
        self.assertTrue(row['cut_in'])
        # à t = 9 : 12,25 m devant le centre − 2,75 − 2,25 = 7,25 m
        self.assertAlmostEqual(row['cut_in_gap_m'], 7.25, delta=0.6)
        self.assertAlmostEqual(row['relative_speed_kmh'], 18.0, delta=1.0)

    def test_a_car_on_a_parallel_road_is_not_an_overtake(self):
        far = [(k * STEP, -40.0, -80.0 + 10.0 * k * STEP, 0.0, 10.0, 'car', None, None) for k in range(141)]
        self.assertEqual(overtaking_rows(track(with_path=False), {'5': far}, lane_w=3.5), [])

    def test_oncoming_traffic_is_not_an_overtake(self):
        self.assertEqual(overtaking_rows(track(with_path=False), {'8': through_vehicle()}, lane_w=3.5), [])

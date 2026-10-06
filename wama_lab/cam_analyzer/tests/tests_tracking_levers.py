"""Leviers de CONTINUITÉ du tracking 360° (2026-10-01, demande de Fabien : « ne pas dupliquer les
objets, ni les perdre » — sans pansement). Mesurés sur ENA_CASA avec la métrique #3
(`placement_metrics.tracking_continuity`) : chaînes éclatées 867 → 597, doublons 28 → 25, relais ratés
39 → 38. ⚠ Ce paragraphe disait aussi « aucune fusion abusive » : FAUX, corrigé le 2026-10-03 — la
métrique ne savait pas les voir. Le recollement fusionnait en chaîne des dizaines de véhicules
(46 478 allers-retours entre objets séparés) ; compteur `switchbacks` et ⚑ stitch_one_to_one ci-dessous.
"""
import inspect

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils import multicam_tracker as mt
from wama_lab.cam_analyzer.utils.features import FEATURES


class TrackingLeversTest(SimpleTestCase):
    def setUp(self):
        self.src = inspect.getsource(mt.annotate_global_tracks)

    def test_locked_chains_are_served_before_new_ones(self):
        loop = self.src.index('for f, d, e, n, pos, relaxed in dets_here:')
        self.assertLess(self.src.index('dets_here.sort(key=_locked_first)'), loop,
                        "l'ordre doit être posé AVANT l'association de l'image")

    def test_the_birth_guard_lets_a_detector_renumbering_through(self):
        """Une boîte qui recouvre la dernière de l'autre chaîne = même objet renuméroté : permise.
        Sans cette clause, la garde fabriquait des pertes (+789 identifiants mesurés)."""
        guard = self.src[self.src.index('if _birth_guard:'):self.src.index('pe = tr[\'e\'] + tr[\'ve\'] * dt')]
        self.assertIn('box_iou(_lv[2], d.get(\'bbox\')) < DUPLICATE_BOX_IOU', guard)
        self.assertIn('t - _lv[1] <= 0.5', guard)

    def test_both_levers_are_declared_and_on(self):
        by_key = {f.key: f for f in FEATURES}
        for k in ('chain_lock_priority', 'birth_same_camera_guard'):
            self.assertTrue(by_key[k].default, k)
            self.assertEqual(by_key[k].scope, 'compute', k)

    def test_the_continuity_metric_is_reported(self):
        self.assertIn('tracking_continuity(_continuity_obs, root=_root)', self.src)
        self.assertIn("'continuity': continuity", self.src)


class StitchOneToOneTest(SimpleTestCase):
    """⚑ stitch_one_to_one (2026-10-03) : le recollement prolongeait une même fin par PLUSIEURS débuts
    et fondait des groupes présents en même temps — G2788 : 1584 observations sur 48 m."""

    def test_two_starts_competing_for_one_end_go_to_the_best_fit(self):
        spans = {'A': (0, 10), 'B': (11, 20), 'C': (11.5, 25)}
        links, _ = mt.one_to_one_stitches([(0.6, 'B', 'A'), (0.2, 'C', 'A')], spans)
        self.assertEqual(links, [('C', 'A')])

    def test_the_order_of_appearance_does_not_decide(self):
        """Le mauvais candidat apparu le PREMIER ne prend plus la fin au bon (1342 refus mesurés)."""
        spans = {'A': (0, 10), 'early': (10.5, 12), 'right': (11, 30)}
        links, _ = mt.one_to_one_stitches([(0.9, 'early', 'A'), (0.1, 'right', 'A')], spans)
        self.assertEqual(links, [('right', 'A')])

    def test_each_end_and_each_start_is_used_once(self):
        spans = {'A': (0, 10), 'D': (0, 9), 'B': (11, 20), 'C': (10, 20)}
        links, _ = mt.one_to_one_stitches([(0.1, 'B', 'A'), (0.2, 'C', 'A'), (0.3, 'C', 'D'),
                                           (0.4, 'B', 'D')], spans)
        self.assertEqual(sorted(links), [('B', 'A'), ('C', 'D')])

    def test_a_group_present_at_the_same_time_is_never_joined(self):
        spans = {'E': (0, 19), 'F': (24, 45), 'S': (20, 30)}
        links, refused = mt.one_to_one_stitches([(0.1, 'F', 'E'), (0.2, 'S', 'F')], spans)
        self.assertEqual(links, [('F', 'E')])
        self.assertEqual(refused, 1)

    def test_a_short_overlap_within_tolerance_is_allowed(self):
        """Une fin et un début qui se chevauchent de quelques images : même objet relayé."""
        spans = {'A': (0, 10.1), 'B': (10.0, 20)}
        self.assertEqual(mt.one_to_one_stitches([(0.3, 'B', 'A')], spans)[0], [('B', 'A')])

    def test_the_switch_is_declared_and_on(self):
        f = {x.key: x for x in FEATURES}['stitch_one_to_one']
        self.assertTrue(f.default, "correction d'un défaut mesuré (46 478 → 581 allers-retours)")
        self.assertEqual(f.scope, 'compute')
        self.assertIn('one_to_one_stitches(_pairs, _span)', inspect.getsource(mt.annotate_global_tracks))


class DuplicateChainMergeTest(SimpleTestCase):
    """⚑ duplicate_chain_merge (2026-10-04) : G459 à 525,1 s — deux images d'une seconde chaîne sur la
    voiture G449, recollées 5,7 s plus tard à une autre voiture, d'où un fantôme. Observations :
    (image, caméra, chaîne, identifiant, e, n, boîte)."""
    CAR = [100, 80, 150, 115]
    SAME_CAR = [102, 82, 152, 113]          # recouvrement ≈ 0,86 : le même véhicule vu deux fois
    OTHER = [200, 80, 250, 115]             # séparée : un autre véhicule

    def test_a_short_twin_chain_is_merged_into_the_long_one(self):
        obs = [(f, 'front', 569, 449, 0.0, -float(f), self.CAR) for f in range(10)]
        obs += [(f, 'front', 577, 459, 0.8, -float(f), self.SAME_CAR) for f in (4, 5)]
        self.assertEqual(mt.duplicate_chain_merges(obs), {459: 449})

    def test_only_a_short_duplicate_is_merged(self):
        """A/B du 2026-10-04 : fondre aussi des doublons LONGS réunissait une voiture et le passager
        d'une moto suivis par une même chaîne instable (G3174) — le levier vise la chaîne de
        quelques images."""
        obs = [(f, 'front', 1, 1, 0.0, -float(f), self.CAR) for f in range(40)]
        obs += [(f, 'front', 2, 2, 0.5, -float(f), self.SAME_CAR) for f in range(20)]
        self.assertEqual(mt.duplicate_chain_merges(obs), {}, '20 observations : pas un doublon court')
        self.assertEqual(mt.duplicate_chain_merges(obs, max_obs=20), {2: 1})

    def test_overlapping_boxes_of_two_cars_two_metres_apart_stay_two(self):
        """Une voiture masquée par une autre recouvre sa boîte, mais elle est À DISTANCE."""
        obs = [(0, 'front', 1, 1, 0.0, 0.0, self.CAR), (0, 'front', 2, 2, 0.0, -5.0, self.SAME_CAR)]
        self.assertEqual(mt.duplicate_chain_merges(obs), {})

    def test_two_ids_ever_seen_apart_in_one_image_are_never_merged(self):
        obs = [(0, 'front', 1, 1, 0.0, 0.0, self.CAR), (0, 'front', 2, 2, 0.5, 0.0, self.SAME_CAR),
               (3, 'front', 1, 1, 0.0, 0.0, self.CAR), (3, 'front', 2, 2, 3.0, 0.0, self.OTHER)]
        self.assertEqual(mt.duplicate_chain_merges(obs), {})

    def test_the_guard_holds_for_groups_not_only_pairs(self):
        """A doublon de B, C doublon de B, mais A et C vus séparés : on ne réunit pas A et C."""
        obs = [(f, 'front', 9, 'B', 0.0, 0.0, self.CAR) for f in range(20)]
        obs += [(1, 'front', 1, 'A', 0.3, 0.0, self.SAME_CAR), (2, 'front', 1, 'A', 0.3, 0.0, self.SAME_CAR),
                (1, 'left', 3, 'C', 0.2, 0.0, self.CAR), (1, 'left', 1, 'A', 0.1, 0.0, self.OTHER)]
        obs += [(5, 'front', 3, 'C', 0.4, 0.0, self.SAME_CAR)]
        merges = mt.duplicate_chain_merges(obs)
        self.assertEqual(merges.get('A'), 'B')
        self.assertNotIn('C', merges, "C a été vu séparé de A, déjà fondu dans B")

    def test_different_cameras_are_not_duplicates_of_a_detector(self):
        """La règle est celle d'un doublon de DÉTECTEUR : une même image d'une même caméra."""
        obs = [(0, 'front', 1, 1, 0.0, 0.0, self.CAR), (0, 'left', 7, 2, 0.5, 0.0, self.SAME_CAR)]
        self.assertEqual(mt.duplicate_chain_merges(obs), {})

    def test_the_switch_is_declared_off_and_wired_before_the_stitch(self):
        f = {x.key: x for x in FEATURES}['duplicate_chain_merge']
        self.assertFalse(f.default, 'défaut OFF tant que l’A/B sur données réelles ne l’a pas tranché')
        self.assertEqual(f.scope, 'compute')
        src = inspect.getsource(mt.annotate_global_tracks)
        self.assertLess(src.index('duplicate_chain_merges(_continuity_obs)'), src.index('_endfit = {}'),
                        "fondre AVANT le recollement : la fin du doublon ne doit plus être un morceau")


class StitchBidirectionalTest(SimpleTestCase):
    """⚑ stitch_bidirectional (2026-10-05) — chiffres RÉELS de la Twingo G1588 (rejeu, 1779-1782 s) :
    elle accélère pour doubler — fin arrière ajustée à 3,7 m/s, tête avant à ~11 m/s."""
    END_A = (1779.00, 1778.50, 56.65, -221.20, -0.79, 3.66)      # fin de G1545 (arrière)
    START_B = (1780.17, 53.29, -205.88)                           # 1ʳᵉ observation de G1588 (gauche)
    HEAD_B = (1780.17, 1780.75, 54.06, -197.87, 0.86, 11.0)        # tête de G1588 (avant)

    def test_forward_only_misses_the_twingo(self):
        ratio, refused, back = mt.stitch_link_ratio(self.END_A, self.START_B, self.HEAD_B, 3.5)
        self.assertGreater(ratio, 1.0)
        self.assertFalse(refused or back)

    def test_both_ways_link_the_twingo(self):
        ratio, refused, back = mt.stitch_link_ratio(self.END_A, self.START_B, self.HEAD_B, 3.5,
                                                    bidirectional=True)
        self.assertLess(ratio, 1.0)
        self.assertTrue(back)
        self.assertFalse(refused)

    def test_two_moving_pieces_in_opposite_directions_are_refused(self):
        end = (522.83, 522.80, 53.95, -233.2, 0.0, -10.0)        # vers le sud, 10 m/s
        head = (528.50, 529.00, 54.33, -253.3, 0.3, 5.0)         # vers le nord, 5 m/s
        self.assertTrue(mt.stitch_link_ratio(end, (528.5, 54.29, -254.72), head, 3.5,
                                             bidirectional=True)[1])

    def test_g459_itself_is_left_to_the_duplicate_merge(self):
        """Le morceau arrière de G459 roule à 2,8 m/s, sous le seuil des morceaux qui « roulent » : la
        direction d'un morceau lent n'est que du bruit de placement (A/B : refuser dès 1 m/s coûtait
        162 recollements). G459 relève de ⚑ duplicate_chain_merge."""
        end = (522.83, 522.80, 53.95, -233.2, 0.0, -10.0)
        head = (528.50, 529.00, 54.33, -253.3, 0.3, 2.8)
        self.assertFalse(mt.stitch_link_ratio(end, (528.5, 54.29, -254.72), head, 3.5,
                                              bidirectional=True)[1])

    def test_slow_pieces_keep_the_forward_only_rule(self):
        """Un garé vu à l'avant puis « roulant » à 1-2 m/s à l'arrière (placement qui dérive) : pas de
        raccord par l'arrière — sans cette borne, 85 garés perdus à l'A/B du 2026-10-05."""
        end = (100.0, 99.5, 0.0, 0.0, 0.0, 0.8)
        head = (101.0, 101.5, 0.0, 6.0, 0.0, 1.5)
        fwd = mt.stitch_link_ratio(end, (101.0, 0.0, 6.0), head, 3.5)
        both = mt.stitch_link_ratio(end, (101.0, 0.0, 6.0), head, 3.5, bidirectional=True)
        self.assertEqual(fwd[0], both[0])
        self.assertFalse(both[2])

    def test_the_head_fit_skips_the_first_half_second(self):
        hist = [(i, 10.0 + i / 12, 0.0, 2.0 * (i / 12), 'car') for i in range(36)]
        hist[0] = (0, 10.0, 0.0, 30.0, 'car')            # entrée de champ corrompue
        t0, tb, e, n, ve, vn = mt.track_head_fit(hist)
        self.assertEqual(t0, 10.0)
        self.assertAlmostEqual(vn, 2.0, places=6)
        self.assertAlmostEqual(n, 2.0 * (tb - 10.0), places=6)


class GhostHermiteTest(SimpleTestCase):
    """⚑ ghost_hermite (2026-10-05) : la courbe du trou respecte les vitesses à ses deux bords."""

    def test_the_curve_leaves_and_arrives_along_the_velocities(self):
        p0, v0, p1, v1, T = (0.0, 0.0), (0.0, 10.0), (4.0, 20.0), (4.0, 10.0), 2.0
        self.assertEqual(mt.hermite_ghost(p0, v0, p1, v1, T, 0.0), p0)
        self.assertEqual(mt.hermite_ghost(p0, v0, p1, v1, T, 1.0), p1)
        e, n = mt.hermite_ghost(p0, v0, p1, v1, T, 0.05)
        self.assertLess(abs(e / n), 0.1, 'au départ, la courbe suit la vitesse (vers le nord)')

    def test_straight_and_steady_is_the_straight_line(self):
        p = mt.hermite_ghost((0.0, 0.0), (0.0, 5.0), (0.0, 10.0), (0.0, 5.0), 2.0, 0.3)
        self.assertAlmostEqual(p[0], 0.0)
        self.assertAlmostEqual(p[1], 3.0)

    def test_incoherent_velocities_fall_back_to_the_line(self):
        """Des vitesses opposées sur une corde courte inventeraient un détour : la droite reste."""
        p = mt.hermite_ghost((0.0, 0.0), (10.0, 0.0), (2.0, 0.0), (-10.0, 0.0), 3.0, 0.5)
        self.assertEqual(p, (1.0, 0.0))

    def test_switches_declared_off_and_wired(self):
        by_key = {f.key: f for f in FEATURES}
        for k in ('stitch_bidirectional', 'ghost_hermite'):
            self.assertFalse(by_key[k].default, k)
            self.assertEqual(by_key[k].scope, 'compute', k)
        src = inspect.getsource(mt.annotate_global_tracks)
        self.assertIn("bidirectional=_bidir", src)
        self.assertIn("use_hermite=_feat.get('ghost_hermite', False)", src)


class RangeCorrectionWiringTest(SimpleTestCase):
    """⚑ range_correction (2026-10-05) : courbe de biais de distance mesurée AUTOMATIQUEMENT à chaque
    tracking (garés), persistée, appliquée au calcul suivant — universel, rien à saisir par caméra."""
    CURVE = [{'lo': 4.0, 'hi': 10.0, 'ratio': 1.0}, {'lo': 10.0, 'hi': 15.0, 'ratio': 0.95},
             {'lo': 30.0, 'hi': 40.0, 'ratio': 0.6}]

    def test_the_fix_stretches_the_distance_and_keeps_the_direction(self):
        lat, lon = mt.range_fix((3.0, 20.0), self.CURVE)
        self.assertGreater(lon, 20.0)
        self.assertAlmostEqual(lat / lon, 3.0 / 20.0, places=9)
        self.assertEqual(mt.range_fix((3.0, 20.0), None), (3.0, 20.0))

    def test_declared_off_measured_every_run_and_persisted_by_the_task(self):
        f = {x.key: x for x in FEATURES}['range_correction']
        self.assertFalse(f.default)
        self.assertEqual(f.scope, 'compute')
        src = inspect.getsource(mt.annotate_global_tracks)
        self.assertIn('measure_range_bias(', src)
        self.assertIn("'range_bias': range_bias", src)
        self.assertIn("range_fix(ego, _rb_applied.get((pos, 'ground')))", src)
        self.assertIn("range_fix(ego, _rb_applied.get((pos, 'box')))", src)
        from wama_lab.cam_analyzer import tasks
        task_src = inspect.getsource(tasks._run_global_tracking)
        self.assertIn("_cfg['range_bias']", task_src)
        self.assertIn("'config'] if _config_changed", task_src)


class ServerHeadingTest(SimpleTestCase):
    """Le cap d'un véhicule qui roule vient de la vitesse LISSÉE du serveur (2026-10-02) : la trace
    de la page, vidée à chaque saut, faisait dessiner un véhicule qui traverse dans l'axe de la route."""

    def test_the_smoothed_velocity_travels_with_the_smoothed_position(self):
        src = inspect.getsource(mt.annotate_global_tracks)
        block = src[src.index("d['world_en'] = [round(w[0], 2), round(w[1], 2)]"):]
        self.assertIn("d['world_vel'] = [round(wv[0], 2), round(wv[1], 2)]", block[:400])

    def test_the_velocity_is_purged_like_every_tracker_field(self):
        self.assertIn('world_vel', mt.TRACKER_FIELDS)

    def test_the_page_uses_it_under_its_switch(self):
        from pathlib import Path
        js = (Path(mt.__file__).resolve().parents[1] / 'static/cam_analyzer/js/index.js').read_text(encoding='utf-8')
        self.assertIn("camFeat.server_heading !== false && Array.isArray(det.world_vel)", js)
        self.assertIn("let _vEst = _srvSpeed;", js)
        self.assertTrue({f.key: f for f in FEATURES}['server_heading'].default)


class OffsetPitchCalibTest(SimpleTestCase):
    """⚑ offset_pitch_calib (2026-10-05) : le tangage d'une caméra qui annule l'écart d'écartement de ses
    garés avec l'ancre — un garé ne bouge pas, sa distance à la route ne dépend pas de la caméra. Rig : la
    navette roule plein nord à 4 m/s ; caméra droite en (1 ; 3,4) regardant à l'est ; garés à 6 m à l'est.
    Projecteur simulé : distance × (1 + 0,05 × (18 − tangage)) — juste à 18°, trop loin en dessous."""
    GEO = {'right': {'yaw': 90.0, 'mount': (1.0, 3.4)}}

    class _Frame:
        def __init__(self, dets):
            self.detections = dets

    class _Proj:
        def __init__(self, pitch):
            self.k = 1.0 + 0.05 * (18.0 - pitch)

    def _scene(self, n=24):
        import numpy as np
        frames, anchor = {}, []
        for k in range(n):
            y = 20.0 + 15.0 * k
            for fn in range(0, 12 * 120):
                t = fn / 12.0
                sn = 4.0 * t
                if 3.0 <= y - sn - 4.5 <= 12.0 and fn % 3 == 0:     # l'avant le voit de près : juste
                    anchor.append((t, 'front', k, 6.0, y, 0.0, sn + 4.5))
                dy = y - sn - 3.4
                if -5.0 <= dy <= 5.0 and fn % 3 == 0:                # la droite le voit par le travers
                    # repère caméra (latéral, longitudinal) vrai de ce garé : longitudinal 5 m, latéral −dy
                    frames.setdefault(fn, self._Frame([]))
                    frames[fn].detections.append({'global_track_id': k, 'class_name': 'car',
                                                  'bbox': [-dy, 5.0, 0, 0]})
        path = np.asarray([(t / 2.0, 0.0, 2.0 * t) for t in range(400)])
        return {'right': (384, 248, frames)}, anchor, path

    def _search(self, p0):
        from unittest import mock
        per_cam, anchor, path = self._scene()
        with mock.patch.object(mt, 'ground_projector_for', lambda s, pos, g, pitch_deg=None: self._Proj(pitch_deg)), \
                mock.patch.object(mt, 'ground_ego', lambda gp, bb: (bb[0], bb[1] * gp.k)):
            return mt.offset_pitch_search(None, per_cam, set(range(24)), self.GEO, 'front', anchor, path,
                                          lambda fn: (0.0, 4.0 * fn / 12.0, 0.0), lambda fn: fn / 12.0,
                                          {'right': p0})

    def test_the_search_finds_the_pitch_that_puts_the_parked_cars_where_the_anchor_sees_them(self):
        res = self._search(15.0)['right']
        self.assertAlmostEqual(res['gap_before_m'], 0.75, places=1)   # 5 m × 0,15 : trop loin de 0,75 m
        self.assertEqual(res['pitch_deg'], 18.0)
        self.assertAlmostEqual(res['gap_after_m'], 0.0, places=2)
        self.assertEqual(res['from_deg'], 15.0)
        self.assertEqual(res['objects'], 24)

    def test_a_camera_already_right_keeps_its_pitch(self):
        """Contre-épreuve : au bon tangage, rien ne bouge."""
        res = self._search(18.0)['right']
        self.assertEqual(res['pitch_deg'], 18.0)
        self.assertAlmostEqual(res['gap_before_m'], 0.0, places=2)

    def test_the_anchor_is_never_searched(self):
        self.assertEqual(mt.offset_pitch_search(None, {}, set(), {}, 'front', [], [], None, None,
                                                {'front': 13.0}), {})

    def test_a_proposal_applies_only_if_it_reduces_the_gap_on_enough_cars(self):
        ok = {'from_deg': 15.5, 'pitch_deg': 19.0, 'gap_before_m': 0.95, 'gap_after_m': 0.0, 'objects': 178}
        self.assertEqual(mt.offset_pitch_is_usable(ok), 19.0)
        self.assertIsNone(mt.offset_pitch_is_usable(dict(ok, objects=12)))
        self.assertIsNone(mt.offset_pitch_is_usable(dict(ok, gap_after_m=1.2)))
        self.assertIsNone(mt.offset_pitch_is_usable(dict(ok, pitch_deg=21.0)))
        self.assertIsNone(mt.offset_pitch_is_usable(None))
        self.assertIsNone(mt.offset_pitch_is_usable({'objects': 30}))
        # une caméra qui a CONVERGÉ garde son tangage (rejeu : la gauche retombait de 19° à 15,5°)
        converged = {'from_deg': 19.0, 'pitch_deg': 19.0, 'gap_before_m': 0.01, 'gap_after_m': 0.01, 'objects': 189}
        self.assertEqual(mt.offset_pitch_is_usable(converged), 19.0)

    def test_the_imposed_pitch_reaches_the_ground_projector(self):
        """Le tangage imposé change la projection ; sans lui, le tangage persisté sert."""
        from types import SimpleNamespace
        from wama_lab.cam_analyzer.utils.prediction_adapter import ground_projector_for
        cam = SimpleNamespace(width=384, height=248)
        session = SimpleNamespace(
            config={'ground_calib': {'left': {'pitch_deg': 15.5, 'height_m': 2.3}}},
            cameras=SimpleNamespace(filter=lambda **kw: SimpleNamespace(first=lambda: cam)))
        geo = {'fov_h': 79.6, 'fov_v': 55.0}
        stored = ground_projector_for(session, 'left', geo).project(192, 200)
        steeper = ground_projector_for(session, 'left', geo, pitch_deg=19.0).project(192, 200)
        same = ground_projector_for(session, 'left', geo, pitch_deg=15.5).project(192, 200)
        self.assertLess(steeper[1], stored[1])        # plus incliné : le même pixel touche le sol plus près
        self.assertAlmostEqual(same[1], stored[1], places=9)

    def test_declared_off_measured_every_run_and_persisted_by_the_task(self):
        f = {x.key: x for x in FEATURES}['offset_pitch_calib']
        self.assertFalse(f.default)
        self.assertEqual(f.scope, 'compute')
        src = inspect.getsource(mt.annotate_global_tracks)
        self.assertIn('offset_pitch_search(', src)
        self.assertIn("'offset_pitch': offset_pitch", src)
        self.assertIn('pitch_deg=_op_p', src)
        from wama_lab.cam_analyzer import tasks
        self.assertIn("_cfg['offset_pitch']", inspect.getsource(tasks._run_global_tracking))


class ParkedLongExposureTest(SimpleTestCase):
    """⚑ parked_long_exposure (2026-10-06) : les fragments d'un garé, hors voies et immobiles, réunis avant
    de juger — la position fixe et le cap se prennent sur toutes ses observations. Emprise simulée : une
    chaussée de 7 m le long de l'axe est (y ∈ [−3,5 ; 3,5])."""

    def _road(self):
        from shapely.geometry import box
        fp = box(-100, -3.5, 300, 3.5)
        return fp, fp.boundary

    @staticmethod
    def _hist(e, n, t0, k=12, step=0.0):
        return [(i, t0 + i / 12.0, e + step * i, n, 'car') for i in range(k)]

    def test_only_still_fragments_off_the_road_are_candidates(self):
        fp, edge = self._road()
        hist = {1: self._hist(10, 6.0, 0), 2: self._hist(10, 0.0, 0),          # garé ; arrêté SUR la voie
                3: self._hist(10, 6.0, 0, k=40, step=0.5),                     # roule hors voie (20 m)
                4: self._hist(30, 6.0, 0)}                                     # un vélo garé
        votes = {1: {'car': 3.0}, 2: {'car': 3.0}, 3: {'car': 3.0}, 4: {'bicycle': 1.0}}
        cands = mt.long_exposure_candidates(hist, votes, fp, edge)
        self.assertEqual(sorted(c[0] for c in cands), [1, 4])
        self.assertEqual(dict((c[0], c[4]) for c in cands)[4], 'two_wheel')

    def test_two_boxes_of_one_image_are_two_objects(self):
        obs = [(5, 'left', 1, 11, 0, 0, [0, 0, 40, 30]), (5, 'left', 2, 12, 0, 0, [100, 0, 140, 30]),
               (6, 'left', 1, 11, 0, 0, [0, 0, 40, 30]), (6, 'front', 3, 13, 0, 0, [0, 0, 40, 30])]
        conf = mt.distinct_box_conflicts(obs, {11, 12, 13}, lambda g: g)
        self.assertEqual(conf, {frozenset((11, 12))})          # 13 vu par une AUTRE caméra : pas un conflit

    def test_declared_off_measured_and_wired_before_the_parked_decision(self):
        f = {x.key: x for x in FEATURES}['parked_long_exposure']
        self.assertFalse(f.default)
        self.assertEqual(f.scope, 'compute')
        src = inspect.getsource(mt.annotate_global_tracks)
        self.assertIn("if _feat.get('parked_long_exposure', False) and _footprint is not None:", src)
        self.assertLess(src.index('long_exposure_groups(_frag'), src.index('stationary_gids = []'))
        self.assertIn("'parked_twins': parked_twins", src)


class TrajectoryTwinMergeTest(SimpleTestCase):
    """⚑ trajectory_twin_merge (2026-10-06) : le geste de la métrique « doublons »."""

    def test_declared_off_and_wired_after_the_stitch_never_across_families(self):
        f = {x.key: x for x in FEATURES}['trajectory_twin_merge']
        self.assertFalse(f.default)
        self.assertEqual(f.scope, 'compute')
        src = inspect.getsource(mt.annotate_global_tracks)
        self.assertIn("if _feat.get('trajectory_twin_merge', False):", src)
        self.assertLess(src.index('trajectory_twins(['), src.index('stationary_gids = []'))
        self.assertIn('if not families_conflict(_fam_tw.get(g), _fam_tw.get(r))', src)
        self.assertIn("'trajectory_twins': _twins", src)

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

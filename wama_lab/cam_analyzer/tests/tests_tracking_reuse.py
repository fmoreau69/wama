"""Les Indicateurs RÉUTILISENT le tracking 360° quand il est à jour (2026-09-30).

Ils le refaisaient à chaque fois : lancer « Tracking 360° » puis « Indicateurs » jouait deux fois le
même calcul de ~4 min (mesuré dans le journal du worker le jour même).
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from wama.common.models import JOB_FAILURE, JOB_STALE, JOB_SUCCESS
from wama_lab.cam_analyzer.utils import pass_tracking as pt

T0 = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
FEATURES = {'lane_map_recalage': True, 'measured_camera_fov': True}


def row(pass_type, status=JOB_SUCCESS, at=T0, summary=None):
    """Une LIGNE COMMUNE (`ProcessRun`) — l'état d'une passe depuis le 2026-10-04."""
    return SimpleNamespace(node_id=pass_type, instance_key='', status=status,
                           finished_at=at, output_summary=summary)


def tracking(**kw):
    return row('global_tracking', summary={'tracks': 6910, 'features': dict(FEATURES)}, **kw)


class TrackingIsCurrentTest(SimpleTestCase):
    def _check(self, rows, features=FEATURES):
        runs = SimpleNamespace(lines=lambda session: rows)
        with mock.patch.object(pt, '_common_runs', return_value=runs):
            return pt.tracking_is_current(SimpleNamespace(id='s'), features)

    def test_a_fresh_tracking_with_the_same_switches_is_reused(self):
        ok, why, summary = self._check([tracking(), row('lane_map_recalage', at=T0 - timedelta(hours=1))])
        self.assertTrue(ok, why)
        self.assertEqual(summary['tracks'], 6910)

    def test_no_tracking_or_a_stale_one_is_recomputed(self):
        self.assertFalse(self._check([])[0])
        self.assertFalse(self._check([tracking(status=JOB_STALE)])[0])
        self.assertFalse(self._check([tracking(status=JOB_FAILURE)])[0])

    def test_a_tracking_without_a_switch_snapshot_is_recomputed(self):
        ok, why, _ = self._check([row('global_tracking', summary={'tracks': 1})])
        self.assertFalse(ok)
        self.assertIn('instantané', why)

    def test_a_changed_compute_switch_is_named(self):
        ok, why, _ = self._check([tracking()], {**FEATURES, 'measured_camera_fov': False})
        self.assertFalse(ok)
        self.assertIn('measured_camera_fov', why)

    def test_a_side_input_recomputed_after_the_tracking_invalidates_it(self):
        """Le recalage voie change la pose navette sans être un amont déclaré du tracking."""
        ok, why, _ = self._check([tracking(), row('lane_map_recalage', at=T0 + timedelta(minutes=5))])
        self.assertFalse(ok)
        self.assertIn('lane_map_recalage', why)


class ComputeSnapshotTest(SimpleTestCase):
    def test_every_switch_a_computation_reads_enters_the_snapshot(self):
        from wama_lab.cam_analyzer.utils.features import FEATURES as REG, compute_snapshot
        snap = compute_snapshot(SimpleNamespace(config={}))
        self.assertEqual(set(snap), {f.key for f in REG if f.scope in ('compute', 'hybrid')})
        self.assertNotIn('display_ema', snap)     # une bascule d'affichage n'invalide aucun calcul
        # lue par le tracking ET appliquée en partie par la page : elle périme le tracking (2026-10-13)
        self.assertIn('fov_dist_correction', snap)


class SwitchChangeStalesThePanelTest(SimpleTestCase):
    """Changer une bascule de calcul PÉRIME le tracking AU PANNEAU, et l'aval par cascade
    (2026-10-13) : avant, seuls les Indicateurs le voyaient, et « Compléter les passes » ne
    relançait rien — mesuré sur `_seg`, cinq bascules changées, aucune passe périmée."""

    def _stale(self, seen, config_features, indicators_before=False):
        from wama_lab.cam_analyzer.utils.features import compute_snapshot
        photo = compute_snapshot(SimpleNamespace(config={}))
        for k in seen.get('drop', ()):
            photo.pop(k)
        photo.update(seen.get('set', {}))
        # toutes les passes du registre terminées : seule la photo des bascules peut périmer
        rows = [row(key, summary={'features': photo} if key == 'global_tracking' else {},
                    at=T0 - timedelta(hours=1) if key == 'indicators' and indicators_before else T0)
                for key in pt.ORDER]
        for r in rows:
            r.settings_snapshot = {}
        runs = SimpleNamespace(lines=lambda session: rows)
        session = SimpleNamespace(profile=None, config={'features': config_features})
        with mock.patch.object(pt, '_common_runs', return_value=runs), \
                mock.patch.object(pt, '_stale_common_lines') as staled:
            pt.recompute_stale(session)
        return {node for node, _ in (staled.call_args.args[1] if staled.called else [])}

    def test_a_changed_switch_stales_the_tracking_and_the_indicators(self):
        # … et les tableaux par véhicule (2026-10-29), en aval des Indicateurs : la cascade
        self.assertEqual(self._stale({}, {'class_family_gate': False}),
                         {'global_tracking', 'indicators', 'vehicle_tables'})

    def test_the_same_switches_stale_nothing(self):
        self.assertEqual(self._stale({}, {}), set())

    def test_a_switch_missing_from_the_photo_is_not_a_change(self):
        """Une bascule passée « lue par un calcul » après le tracking : la surveillance a changé,
        pas le réglage — même règle que `process_runs._watched_changed`."""
        self.assertEqual(self._stale({'drop': ('fov_dist_correction',)}, {}), set())

    def test_a_display_switch_stales_nothing(self):
        self.assertEqual(self._stale({}, {'display_ema': False}), set())

    def test_a_ttc_switch_stales_the_indicators_but_no_longer_the_tracking(self):
        """Le tracking ne lit pas les bascules du TTC/PET (`Feature.processes`) : changer l'une
        d'elles le refaisait (~4 min) pour rien. Les Indicateurs terminés APRÈS le tracking ont vu
        sa photo (ils l'avaient vérifiée pour le réutiliser) : elle leur sert de repli."""
        self.assertEqual(self._stale({}, {'prediction_ground': True}), {'indicators', 'vehicle_tables'})

    def test_indicators_older_than_the_tracking_keep_the_old_rule(self):
        self.assertEqual(self._stale({}, {'prediction_ground': True}, indicators_before=True), set())


class SwitchPhotoPerPassTest(SimpleTestCase):
    """Chaque passe range à son lancement la photo des bascules qu'ELLE lit (2026-10-13) : en
    changer une périme ses lecteurs, et seulement eux (l'aval suit par la cascade)."""

    def _stale(self, config_features, photo_for=None):
        from wama_lab.cam_analyzer.utils.features import read_by
        defaults = SimpleNamespace(config={})
        photo_for = set(pt.ORDER) if photo_for is None else photo_for
        rows = []
        for key in pt.ORDER:
            r = row(key, summary={})
            r.settings_snapshot = pt._switch_photo(read_by(defaults, key)) if key in photo_for else {}
            rows.append(r)
        runs = SimpleNamespace(lines=lambda session: rows)
        session = SimpleNamespace(profile=None, config={'features': config_features})
        with mock.patch.object(pt, '_common_runs', return_value=runs), \
                mock.patch.object(pt, '_stale_common_lines') as staled:
            pt.recompute_stale(session)
        return {node for node, _ in (staled.call_args.args[1] if staled.called else [])}

    def test_a_ttc_switch_stales_the_indicators_only(self):
        # (et leur aval par la cascade : les tableaux par véhicule, 2026-10-29 — pas le tracking)
        self.assertEqual(self._stale({'prediction_kalman': True}), {'indicators', 'vehicle_tables'})

    def test_the_sam3_arbitration_stales_the_sam3_pass_and_its_downstream(self):
        stale = self._stale({'sam3_label_arbitration': False})
        self.assertIn('sam3_markings', stale)
        self.assertNotIn('global_tracking', stale, "le tracking ne dépend pas de SAM3 (registre)")

    def test_the_lane_map_bias_stales_the_lane_map_pass(self):
        self.assertEqual(self._stale({'gps_bias_kalman': False}), {'lane_map_recalage'})

    def test_a_pass_launched_before_the_photo_is_not_staled_by_a_switch(self):
        """Sinon toutes les passes qui lisent une bascule seraient périmées d'un coup à la mise à
        jour — recalage ortho (GPU) compris."""
        self.assertEqual(self._stale({'gps_bias_kalman': False}, photo_for=set()), set())


class ParkedRadiusTest(SimpleTestCase):
    """Rayon « jamais garé » réglable par intersection (2026-10-13, demande de Fabien)."""

    def _profile(self, **extra):
        return SimpleNamespace(intersections=[{'name': 'A', 'lat': 43.6, 'lon': 7.07, 'radius_m': 30,
                                               **extra}])

    def test_absent_it_falls_back_on_the_analysis_radius(self):
        from wama_lab.cam_analyzer.utils.intersection_analyzer import parked_radius_m
        self.assertEqual(parked_radius_m({'radius_m': 30}), 30)
        self.assertEqual(parked_radius_m({'radius_m': 30, 'parked_radius_m': 10}), 10)
        self.assertEqual(parked_radius_m({}), 30.0)

    def test_it_stales_the_tracking_but_not_the_windows(self):
        """Les fenêtres l'ignorent : sinon SAM3 et le recalage ortho (GPU) suivaient par cascade."""
        before, after = self._profile(), self._profile(parked_radius_m=10)
        snap = lambda p, key: pt._profile_snapshot(p, pt._WATCHED[key])
        self.assertEqual(snap(before, 'intersection_windows'), snap(after, 'intersection_windows'))
        self.assertNotEqual(snap(before, 'global_tracking'), snap(after, 'global_tracking'))

    def _stale_old_tracking(self, profile):
        """Un tracking lancé AVANT que le rayon soit surveillé : sa photo (les bascules vues, rangées
        à son résumé) ne le porte pas ; les autres passes ont la photo de leurs réglages du jour."""
        from wama_lab.cam_analyzer.utils.features import compute_snapshot
        rows = []
        for key in pt.ORDER:
            tracked = key == 'global_tracking'
            r = row(key, summary={'features': compute_snapshot(SimpleNamespace(config={}))} if tracked else {})
            r.settings_snapshot = {} if tracked else pt._profile_snapshot(profile, pt._WATCHED.get(key) or [])
            rows.append(r)
        runs = SimpleNamespace(lines=lambda session: rows)
        with mock.patch.object(pt, '_common_runs', return_value=runs), \
                mock.patch.object(pt, '_stale_common_lines') as staled:
            pt.recompute_stale(SimpleNamespace(profile=profile, config={}))
        return {node for node, _ in (staled.call_args.args[1] if staled.called else [])}

    def test_a_radius_set_after_an_old_tracking_stales_it(self):
        """Vécu le 2026-10-13 : rayon posé à 15 m sur `_seg`, tracking du matin resté « terminé » —
        « Compléter les passes » ne l'aurait pas refait. Il avait tourné au rayon d'analyse."""
        self.assertIn('global_tracking', self._stale_old_tracking(self._profile(parked_radius_m=15)))

    def test_an_old_tracking_without_a_parked_radius_stays_current(self):
        self.assertEqual(self._stale_old_tracking(self._profile()), set())


class SwitchBornSinceTheTrackingTest(SimpleTestCase):
    """Une bascule née ON qui change le calcul déclare comment calculait un tracking d'avant
    (`Feature.legacy`) : ⚑ parked_speed_floor, sans quoi le plancher de 2 m/s n'atteignait jamais un
    tracking déjà fait (2026-10-13)."""

    def _old_tracking_photo(self):
        from wama_lab.cam_analyzer.utils.features import compute_snapshot
        photo = compute_snapshot(SimpleNamespace(config={}))
        photo.pop('parked_speed_floor')
        return photo

    def test_the_old_tracking_is_staled_at_the_panel(self):
        rows = [row(key, summary={'features': self._old_tracking_photo()} if key == 'global_tracking' else {})
                for key in pt.ORDER]
        for r in rows:
            r.settings_snapshot = {}
        runs = SimpleNamespace(lines=lambda session: rows)
        with mock.patch.object(pt, '_common_runs', return_value=runs), \
                mock.patch.object(pt, '_stale_common_lines') as staled:
            pt.recompute_stale(SimpleNamespace(profile=None, config={}))
        self.assertIn('global_tracking', {node for node, _ in staled.call_args.args[1]})

    def test_the_indicators_do_not_reuse_it(self):
        from wama_lab.cam_analyzer.utils.features import compute_snapshot
        runs = SimpleNamespace(lines=lambda session: [
            row('global_tracking', summary={'features': self._old_tracking_photo()})])
        with mock.patch.object(pt, '_common_runs', return_value=runs):
            ok, why, _ = pt.tracking_is_current(SimpleNamespace(id='s'),
                                                compute_snapshot(SimpleNamespace(config={})))
        self.assertFalse(ok)
        self.assertIn('parked_speed_floor', why)

    def test_switched_off_it_matches_the_old_tracking(self):
        from wama_lab.cam_analyzer.utils.features import compute_snapshot
        runs = SimpleNamespace(lines=lambda session: [
            row('global_tracking', summary={'features': self._old_tracking_photo()})])
        with mock.patch.object(pt, '_common_runs', return_value=runs):
            ok, why, _ = pt.tracking_is_current(SimpleNamespace(id='s'), compute_snapshot(
                SimpleNamespace(config={'features': {'parked_speed_floor': False}})))
        self.assertTrue(ok, why)


class FailedSideInputTest(TrackingIsCurrentTest):
    def test_a_side_input_that_failed_after_the_tracking_does_not_invalidate_it(self):
        """Une correction ortho ÉCHOUÉE n'a rien changé à ce que lit le tracking (2026-10-01)."""
        ok, why, _ = self._check([tracking(), row('ortho_correction', status=JOB_FAILURE,
                                                  at=T0 + timedelta(minutes=5))])
        self.assertTrue(ok, why)

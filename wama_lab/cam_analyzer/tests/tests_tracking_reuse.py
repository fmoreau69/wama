"""Les Indicateurs RÉUTILISENT le tracking 360° quand il est à jour (2026-09-30).

Ils le refaisaient à chaque fois : lancer « Tracking 360° » puis « Indicateurs » jouait deux fois le
même calcul de ~4 min (mesuré dans le journal du worker le jour même).
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils import pass_tracking as pt

T0 = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
FEATURES = {'lane_map_recalage': True, 'measured_camera_fov': True}


def row(pass_type, status='completed', at=T0, summary=None):
    """Une LIGNE COMMUNE (`ProcessRun`) — lue depuis le 2026-10-04 ; l'état s'écrit dans le
    vocabulaire du Lab pour rester lisible, traduit par `common_status`."""
    return SimpleNamespace(node_id=pass_type, instance_key='', status=pt.common_status(status),
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
        self.assertFalse(self._check([tracking(status='stale')])[0])
        self.assertFalse(self._check([tracking(status='failed')])[0])

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
    def test_only_compute_switches_enter_the_snapshot(self):
        from wama_lab.cam_analyzer.utils.features import FEATURES as REG, compute_snapshot
        snap = compute_snapshot(SimpleNamespace(config={}))
        self.assertEqual(set(snap), {f.key for f in REG if f.scope == 'compute'})
        self.assertNotIn('display_ema', snap)     # une bascule d'affichage n'invalide aucun calcul


class FailedSideInputTest(TrackingIsCurrentTest):
    def test_a_side_input_that_failed_after_the_tracking_does_not_invalidate_it(self):
        """Une correction ortho ÉCHOUÉE n'a rien changé à ce que lit le tracking (2026-10-01)."""
        ok, why, _ = self._check([tracking(), row('ortho_correction', status='failed',
                                                  at=T0 + timedelta(minutes=5))])
        self.assertTrue(ok, why)

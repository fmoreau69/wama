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

    def _stale(self, seen, config_features):
        from wama_lab.cam_analyzer.utils.features import compute_snapshot
        photo = compute_snapshot(SimpleNamespace(config={}))
        for k in seen.get('drop', ()):
            photo.pop(k)
        photo.update(seen.get('set', {}))
        # toutes les passes du registre terminées : seule la photo des bascules peut périmer
        rows = [row(key, summary={'features': photo} if key == 'global_tracking' else {})
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
        self.assertEqual(self._stale({}, {'class_family_gate': False}), {'global_tracking', 'indicators'})

    def test_the_same_switches_stale_nothing(self):
        self.assertEqual(self._stale({}, {}), set())

    def test_a_switch_missing_from_the_photo_is_not_a_change(self):
        """Une bascule passée « lue par un calcul » après le tracking : la surveillance a changé,
        pas le réglage — même règle que `process_runs._watched_changed`."""
        self.assertEqual(self._stale({'drop': ('fov_dist_correction',)}, {}), set())

    def test_a_display_switch_stales_nothing(self):
        self.assertEqual(self._stale({}, {'display_ema': False}), set())


class FailedSideInputTest(TrackingIsCurrentTest):
    def test_a_side_input_that_failed_after_the_tracking_does_not_invalidate_it(self):
        """Une correction ortho ÉCHOUÉE n'a rien changé à ce que lit le tracking (2026-10-01)."""
        ok, why, _ = self._check([tracking(), row('ortho_correction', status=JOB_FAILURE,
                                                  at=T0 + timedelta(minutes=5))])
        self.assertTrue(ok, why)

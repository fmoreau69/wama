"""▶ Calculs ne lance pas une seconde chaîne tant que la première est en file ou en cours.

Mesuré le 2026-09-29 : deux clics à 19 s d'intervalle, la 1re chaîne attendant derrière une autre
tâche du worker GPU — aucune passe « running », donc aucun refus, et deux chaînes entrelacées
(chaque passe jouée deux fois). Verrou : `pass_tracking.calc_chain_key`, posé par `run_passes`,
levé par `release_calc_chain_task` (dernier maillon ET errback).
"""
import json
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, RequestFactory, override_settings

from wama_lab.cam_analyzer import views
from wama_lab.cam_analyzer.utils.pass_tracking import calc_chain_key

SID = '00000000-0000-0000-0000-0000000000ca'


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class CalcChainLockTest(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def _post(self):
        req = RequestFactory().post(f'/x/{SID}/passes/run/', data=json.dumps({'types': ['distance']}),
                                    content_type='application/json')
        req.user = SimpleNamespace(is_authenticated=True, id=1)
        session = SimpleNamespace(id=SID, profile=object())
        chain = mock.MagicMock()
        chain.return_value.apply_async.return_value.id = 'chain-result-id'
        with mock.patch.object(views, 'get_object_or_404', return_value=session), \
                mock.patch('wama_lab.cam_analyzer.utils.pass_tracking.recompute_stale'), \
                mock.patch('wama_lab.cam_analyzer.utils.pass_tracking.reconcile_interrupted_calc_passes'), \
                mock.patch('wama_lab.cam_analyzer.utils.pass_tracking.get_passes_status', return_value=[]), \
                mock.patch.object(views.DetectionFrame.objects, 'filter') as flt, \
                mock.patch('celery.chain', chain):
            flt.return_value.exists.return_value = True
            resp = views.run_passes(req, SID)
        return resp, chain

    def test_a_queued_chain_rejects_a_second_launch(self):
        cache.set(calc_chain_key(SID), ['compute_distance_task'], 60)
        resp, chain = self._post()
        self.assertEqual(resp.status_code, 409)
        chain.assert_not_called()

    def test_a_launch_sets_the_lock_and_ends_the_chain_with_its_release(self):
        resp, chain = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(cache.get(calc_chain_key(SID)))
        sigs = chain.call_args.args
        self.assertEqual(sigs[-1].task, 'wama_lab.cam_analyzer.tasks.release_calc_chain_task')
        kwargs = chain.return_value.apply_async.call_args.kwargs
        self.assertEqual(kwargs['link_error'].task, 'wama_lab.cam_analyzer.tasks.release_calc_chain_task')

    def test_the_release_task_lifts_the_lock(self):
        from wama_lab.cam_analyzer.tasks import release_calc_chain_task
        cache.set(calc_chain_key(SID), ['x'], 60)
        release_calc_chain_task(SID)
        self.assertIsNone(cache.get(calc_chain_key(SID)))


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class InterruptedCalcPassTest(SimpleTestCase):
    """Une passe de calcul RUNNING sans chaîne en cours est INTERROMPUE (2026-09-30) : worker
    `default` arrêté pendant les Indicateurs, verrou libéré par le lien d'échec, passe RUNNING à
    vie — son bouton restait ⏳ et la relance était impossible depuis le panneau."""

    def setUp(self):
        cache.clear()

    def _reconcile(self):
        from wama_lab.cam_analyzer.utils import pass_tracking as pt
        with mock.patch('wama_lab.cam_analyzer.models.AnalysisPass.objects.filter') as flt:
            flt.return_value.update.return_value = 1
            n = pt.reconcile_interrupted_calc_passes(SimpleNamespace(id=SID))
        return n, flt

    def test_while_a_chain_runs_nothing_is_touched(self):
        cache.set(calc_chain_key(SID), ['compute_indicators_task'], 60)
        n, flt = self._reconcile()
        self.assertEqual(n, 0)
        flt.assert_not_called()

    def test_without_a_chain_running_calc_passes_become_relaunchable(self):
        from wama_lab.cam_analyzer.models import AnalysisPass
        from wama_lab.cam_analyzer.utils.pass_tracking import PASSES, INTERRUPTED_MESSAGE
        n, flt = self._reconcile()
        self.assertEqual(n, 1)
        kw = flt.call_args.kwargs
        self.assertEqual(kw['status'], AnalysisPass.Status.RUNNING)
        self.assertEqual(set(kw['pass_type__in']), {p.key for p in PASSES if p.stage == 'calcul'})
        self.assertNotIn('sam3_markings', kw['pass_type__in'])      # ANALYSE : pas de preuve
        upd = flt.return_value.update.call_args.kwargs
        self.assertEqual(upd['status'], AnalysisPass.Status.FAILED)
        self.assertEqual(upd['error_message'], INTERRUPTED_MESSAGE)

    def test_every_calc_entry_point_takes_the_chain_lock(self):
        """La preuve ne vaut que si AUCUN calcul ne tourne hors verrou."""
        import inspect
        src = inspect.getsource(views)
        self.assertNotIn('compute_indicators_task.delay(', src)
        self.assertNotIn('compute_ortho_correction_task.delay(', src)
        self.assertEqual(src.count('chain(*'), 1, "un seul lancement de chaîne : _launch_calc_chain")
        self.assertIn('if _launch_calc_chain(session, [compute_indicators_task]) is None:', src)
        self.assertIn('if _launch_calc_chain(session, [compute_ortho_correction_task]) is None:', src)

"""Les passes d'une session (calculs PUIS analyses, 2026-09-30) s'EMPILENT et se DÉPILENT : une seule chaîne à la fois, jamais de refus.

Mesuré le 2026-09-29 : deux clics à 19 s d'intervalle, deux chaînes entrelacées (chaque passe jouée
deux fois). Verrou : `pass_tracking.calc_chain_key`. Du 29 au 30/09 une seconde demande était
REFUSÉE (409) ; depuis le 2026-09-30 (demande de Fabien : « que les tâches s'empilent et se
dépilent comme c'est normalement le cas partout dans WAMA ») elle rejoint la file de la session,
que `release_calc_chain_task` (dernier maillon ET errback) dépile en lançant la chaîne suivante.
"""
import json
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, RequestFactory, override_settings

from wama_lab.cam_analyzer import views
from wama_lab.cam_analyzer.utils.pass_tracking import calc_chain_key

SID = '00000000-0000-0000-0000-0000000000ca'
MARK_PENDING = 'wama_lab.cam_analyzer.utils.pass_tracking._mark_detection_pending'


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class CalcChainLockTest(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def _post(self, types=('distance',)):
        req = RequestFactory().post(f'/x/{SID}/passes/run/', data=json.dumps({'types': list(types)}),
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
                mock.patch(MARK_PENDING) as pending,                 mock.patch('celery.chain', chain):
            flt.return_value.exists.return_value = True
            resp = views.run_passes(req, SID)
        self.pending = pending
        return resp, chain

    def test_a_launch_during_a_chain_is_queued_not_refused(self):
        from wama_lab.cam_analyzer.utils.pass_tracking import queued_session_passes
        cache.set(calc_chain_key(SID), ['compute_distance_task'], 60)
        resp, chain = self._post(types=('lane_map_recalage',))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.content)['queued'], ['lane_map_recalage'])
        chain.assert_not_called()                      # une seule chaîne à la fois
        self.assertEqual(queued_session_passes(SID), ['lane_map_recalage'])

    def test_asking_twice_for_the_same_pass_queues_it_once(self):
        from wama_lab.cam_analyzer.utils.pass_tracking import queued_session_passes
        cache.set(calc_chain_key(SID), ['compute_distance_task'], 60)
        self._post(types=('indicators',))
        self._post(types=('indicators', 'lane_map_recalage'))
        self.assertEqual(sorted(queued_session_passes(SID)), ['indicators', 'lane_map_recalage'])

    def test_several_passes_launched_together_run_in_dependency_order(self):
        resp, chain = self._post(types=('indicators', 'depth_calc', 'lane_map_recalage'))
        names = [s.task.rsplit('.', 1)[-1] for s in chain.call_args.args]
        self.assertEqual(names, ['compute_depth_calc_task', 'compute_lane_map_recalage_task',
                                 'compute_indicators_task', 'release_calc_chain_task'])

    def test_a_launch_sets_the_lock_and_ends_the_chain_with_its_release(self):
        resp, chain = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(cache.get(calc_chain_key(SID)))
        sigs = chain.call_args.args
        self.assertEqual(sigs[-1].task, 'wama_lab.cam_analyzer.tasks.release_calc_chain_task')
        kwargs = chain.return_value.apply_async.call_args.kwargs
        self.assertEqual(kwargs['link_error'].task, 'wama_lab.cam_analyzer.tasks.release_calc_chain_task')

    def test_the_release_task_lifts_the_lock_when_nothing_is_queued(self):
        from wama_lab.cam_analyzer.tasks import release_calc_chain_task
        cache.set(calc_chain_key(SID), ['x'], 60)
        release_calc_chain_task(SID)
        self.assertIsNone(cache.get(calc_chain_key(SID)))

    def test_the_release_task_unstacks_the_queue_into_the_next_chain(self):
        from wama_lab.cam_analyzer.tasks import release_calc_chain_task
        from wama_lab.cam_analyzer.utils.pass_tracking import session_queue_key, queued_session_passes
        cache.set(calc_chain_key(SID), ['compute_depth_calc_task'], 60)
        cache.set(session_queue_key(SID), {'keys': ['indicators', 'lane_map_recalage']}, 60)
        chain = mock.MagicMock()
        chain.return_value.apply_async.return_value.id = 'next-chain'
        with mock.patch('celery.chain', chain):
            out = release_calc_chain_task(SID)
        names = [s.task.rsplit('.', 1)[-1] for s in chain.call_args.args]
        self.assertEqual(names, ['compute_lane_map_recalage_task', 'compute_indicators_task',
                                 'release_calc_chain_task'])
        self.assertTrue(cache.get(calc_chain_key(SID)), "le verrou tient entre deux chaînes")
        self.assertEqual(queued_session_passes(SID), [])
        self.assertFalse(out['released'])

    # ── ANALYSES dans la même file (2026-09-30) ───────────────────────────────────────────
    def _names(self, chain):
        return [s.task.rsplit('.', 1)[-1] for s in chain.call_args.args]

    def test_detection_and_other_analyses_run_in_one_ordered_chain(self):
        """Avant : « détection + profondeur + recalage ortho » ne lançait que la détection."""
        resp, chain = self._post(types=('yolo_detect', 'ortho_recalage', 'depth', 'sam3_markings'))
        names = self._names(chain)
        self.assertEqual(names[0], 'process_session_task')
        self.assertEqual(names[-1], 'release_calc_chain_task')
        self.assertEqual(set(names[1:-1]), {'analyze_sam3_only_task', 'compute_depth_task',
                                            'compute_ortho_recalage_task'})
        self.assertLess(names.index('analyze_sam3_only_task'),
                        names.index('compute_ortho_recalage_task'))   # dépendance
        detect = chain.call_args.args[0]
        self.assertFalse(detect.kwargs['chain_sam3'], "SAM3 est un maillon, pas une suite async")
        self.assertTrue(detect.kwargs['force_rerun'], "relance explicite = forcée")
        self.pending.assert_called_once_with(SID)

    def test_a_calc_only_chain_leaves_the_session_status_alone(self):
        self._post(types=('indicators',))
        self.pending.assert_not_called()

    def test_yolo_and_yolopv2_together_are_one_detection_link(self):
        resp, chain = self._post(types=('yolo_detect', 'yolopv2_lanes', 'lane_events', 'distance'))
        self.assertEqual(self._names(chain), ['process_session_task', 'release_calc_chain_task'])

    def test_cancel_revokes_the_detection_task_not_the_release(self):
        resp, chain = self._post(types=('yolo_detect',))
        detect = chain.call_args.args[0]
        self.assertEqual(cache.get(f'cam_analyzer_task_{SID}'), detect.options['task_id'])

    def test_a_detection_asked_during_a_chain_is_queued_with_its_force(self):
        from wama_lab.cam_analyzer.tasks import release_calc_chain_task
        cache.set(calc_chain_key(SID), ['compute_distance_task'], 60)
        resp, chain = self._post(types=('yolopv2_lanes', 'depth'))
        chain.assert_not_called()
        self.assertEqual(sorted(json.loads(resp.content)['queued']), ['depth', 'yolopv2_lanes'])
        nxt = mock.MagicMock()
        nxt.return_value.apply_async.return_value.id = 'next'
        with mock.patch('celery.chain', nxt), mock.patch(MARK_PENDING) as pending:
            release_calc_chain_task(SID)
        self.assertEqual(self._names(nxt), ['process_session_task', 'compute_depth_task',
                                            'release_calc_chain_task'])
        self.assertTrue(nxt.call_args.args[0].kwargs['force_rerun'])
        pending.assert_called_once_with(SID)      # la session passe en attente AU DÉPILEMENT

    def test_cancelling_stops_the_chain_and_drops_the_queue(self):
        from wama_lab.cam_analyzer.utils.pass_tracking import (abort_session_chain,
                                                               session_queue_key)
        cache.set(calc_chain_key(SID), ['process_session_task'], 60)
        cache.set(session_queue_key(SID), {'keys': ['indicators']}, 60)
        task = SimpleNamespace(request=SimpleNamespace(chain=[{'task': 'compute_depth_task'}]))
        abort_session_chain(SID, task=task)
        self.assertIsNone(task.request.chain, "la suite de la chaîne est coupée")
        self.assertIsNone(cache.get(calc_chain_key(SID)))
        self.assertIsNone(cache.get(session_queue_key(SID)))


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class InterruptedCalcPassTest(SimpleTestCase):
    """Une passe de calcul RUNNING sans chaîne en cours est INTERROMPUE (2026-09-30) : worker
    `default` arrêté pendant les Indicateurs, verrou libéré par le lien d'échec, passe RUNNING à
    vie — son bouton restait ⏳ et la relance était impossible depuis le panneau."""

    def setUp(self):
        cache.clear()

    def _reconcile(self):
        """Lignes COMMUNES (lues depuis le 2026-10-04) : un calcul en cours, une analyse GPU en
        cours, un calcul terminé — seul le premier a la preuve qu'il a perdu son exécutant."""
        from wama.common.models import JOB_RUNNING, JOB_SUCCESS
        from wama_lab.cam_analyzer.utils import pass_tracking as pt
        lines = [SimpleNamespace(node_id='distance', instance_key='', status=JOB_RUNNING),
                 SimpleNamespace(node_id='sam3_markings', instance_key='front', status=JOB_RUNNING),
                 SimpleNamespace(node_id='conflicts', instance_key='', status=JOB_SUCCESS)]
        runs = mock.MagicMock()
        runs.lines.return_value = lines
        with mock.patch.object(pt, '_common_runs', return_value=runs), \
                mock.patch.object(pt, '_lab_rows') as lab:
            n = pt.reconcile_interrupted_calc_passes(SimpleNamespace(id=SID))
        return n, runs, lab

    def test_while_a_chain_runs_nothing_is_touched(self):
        cache.set(calc_chain_key(SID), ['compute_indicators_task'], 60)
        n, runs, lab = self._reconcile()
        self.assertEqual(n, 0)
        runs.lines.assert_not_called()
        lab.assert_not_called()

    def test_without_a_chain_running_calc_passes_become_relaunchable(self):
        from wama_lab.cam_analyzer.utils.pass_tracking import INTERRUPTED_MESSAGE
        n, runs, lab = self._reconcile()
        self.assertEqual(n, 1)
        runs.fail.assert_called_once()
        args, kw = runs.fail.call_args
        self.assertEqual((args[1], args[2], kw['instance_key']), ('distance', INTERRUPTED_MESSAGE, ''))
        lab.assert_called_once()                                    # sam3 (ANALYSE) : pas de preuve
        self.assertEqual(lab.call_args.args[1:], ('distance', ''))
        upd = lab.return_value.filter.return_value.update.call_args.kwargs
        self.assertEqual((upd['status'], upd['error_message']), ('failed', INTERRUPTED_MESSAGE))

    def test_every_calc_entry_point_takes_the_chain_lock(self):
        """La preuve ne vaut que si AUCUN calcul ne tourne hors verrou."""
        import inspect
        from wama_lab.cam_analyzer.utils import pass_tracking as pt
        src = inspect.getsource(views)
        self.assertNotIn('compute_indicators_task.delay(', src)
        self.assertNotIn('compute_ortho_correction_task.delay(', src)
        self.assertNotRegex(src, r'(?<![\w.])chain\(', "les vues ne lancent aucune chaîne elles-mêmes")
        self.assertEqual(inspect.getsource(pt).count('chain(*'), 1,
                         "un seul lancement de chaîne : pass_tracking._start_session_chain")
        self.assertNotIn('.delay(', inspect.getsource(views.run_passes),
                         "le panneau des passes ne lance rien hors de la file de la session")
        self.assertIn("launch_session_passes(session.id, ['indicators'])", src)
        self.assertIn("launch_session_passes(session.id, ['ortho_correction'])", src)
        self.assertIn('res = launch_session_passes(session.id, needs_run, detect_force=', src)

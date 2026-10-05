"""The PROGRESS views factory (`progress_views.make_progress_views`, ROUTE §11 #37, 2026-10-03).

Ten apps wrote their own `progress` and `global_progress` : three formulas for the queue bar,
four vocabularies of keys. The factory renders ONE formula — the contract of the common bar
(`wama-global-progress.js` : `done / total` when not given, « done » and « failed » counted
apart) — and the hooks carry what each app reads on top. The generic contract over the ten
apps lives in `tests_item_lifecycle_contract`.
"""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from wama.common.utils.progress_views import make_progress_views, queue_progress


class QueueFormulaTest(SimpleTestCase):

    def test_a_failure_is_failed_not_done(self):
        """Fabien, 2026-10-03 : « un élément échoué est échoué, pas terminé ». The describer
        formula, which the bar's own fallback (`done / total`) already says."""
        out = queue_progress([('SUCCESS', 0), ('FAILURE', 0), ('RUNNING', 50), ('PENDING', 0)])
        self.assertEqual((4, 1, 1, 1, 1), (out['total'], out['success'], out['failure'],
                                           out['running'], out['pending']))
        self.assertEqual(int((100 + 0 + 50 + 0) / 4), out['overall_progress'])

    def test_a_queue_with_only_failures_does_not_reach_100(self):
        self.assertEqual(0, queue_progress([('FAILURE', 0), ('FAILURE', 0)])['overall_progress'])

    def test_both_spellings_of_the_contract_are_emitted(self):
        out = queue_progress([('SUCCESS', 0), ('FAILURE', 0)])
        self.assertEqual((out['success'], out['failure']), (out['done'], out['failed']))

    def test_an_empty_queue_is_zero_everywhere(self):
        out = queue_progress([])
        self.assertEqual(0, out['overall_progress'])
        self.assertEqual(0, out['total'])


class OneEtaPlacePerAppTest(SimpleTestCase):
    """The ETA triplet an app's progress view estimates with is the one its task LEARNS — declared
    ONCE, in the task module, and read by the view (ROUTE §11 #37). Written twice, it diverged :
    the avatarizer view estimated a 3D avatar under a key the task never fed (2026-10-03)."""

    APPS = ('anonymizer', 'avatarizer', 'composer', 'converter', 'describer', 'enhancer',
            'imager', 'reader', 'synthesizer', 'transcriber')

    def test_every_eta_hook_of_a_view_delegates_to_the_task_module(self):
        """An app whose PROCESSES declare their ETA (`ProcessSpec.eta`, 2026-10-05) has no view
        hook any more — `tests_process_eta.EveryAppProcessNamesItsEtaTest` holds it."""
        import ast
        from pathlib import Path
        from django.conf import settings
        from wama.common.catalog import function_catalog
        from wama.common.services.process_pipeline import APP_PIPELINES
        function_catalog.load_all()
        by_processes = {app for app, pipeline in APP_PIPELINES.items()
                        if any(spec.eta for spec in pipeline.specs)}
        self.assertTrue(by_processes, 'no app estimates by its processes : the guard is blind')
        for app in self.APPS:
            if app in by_processes:
                continue
            with self.subTest(app=app):
                src = (Path(settings.BASE_DIR) / 'wama' / app / 'views.py').read_text(
                    encoding='utf-8')
                tree = ast.parse(src)
                hooks = {kw.value.id for node in ast.walk(tree) if isinstance(node, ast.Call)
                         and getattr(node.func, 'id', '') == 'make_progress_views'
                         for kw in node.keywords
                         if kw.arg == 'eta_for' and isinstance(kw.value, ast.Name)}
                self.assertTrue(hooks, f'{app} : aucun `eta_for` déclaré à la fabrique')
                for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef)
                           and n.name in hooks):
                    body = ast.get_source_segment(src, fn)
                    self.assertRegex(body, r'from \.(tasks|workers|eta) import',
                                     f'{app}.{fn.name} recalcule le triplet au lieu de le lire')
                    self.assertNotIn('make_key(', body, f'{app}.{fn.name} écrit sa propre clé')


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                       'LOCATION': 'progress-views-tests'}})
class FactoryViewsTest(TestCase):
    """On a real queue model (the describer's), the hooks do what the apps declare."""

    def setUp(self):
        from wama.describer.models import Description
        cache.clear()
        self.model = Description
        self.user = get_user_model().objects.create_user('progress-views', password='x')
        self.item = Description.objects.create(user=self.user, status='RUNNING', progress=10,
                                               error_message='an old failure')

    def _views(self, **kw):
        return make_progress_views(work_model=self.model, get_user=lambda r: r.user,
                                   app_id='progress_test', **kw)

    def _get(self, view, *args):
        request = RequestFactory().get('/x/')
        request.user = self.user
        return json.loads(view(request, *args).content)

    def test_the_live_progress_is_read_from_the_cache_the_skeleton_publishes(self):
        cache.set(f'progress_test_progress_{self.item.pk}', 64)
        data = self._get(self._views()['progress'], self.item.pk)
        self.assertEqual((64, 'RUNNING'), (data['progress'], data['status']))

    def test_an_app_reads_its_own_live_progress_through_progress_of(self):
        """The reader keeps a dict `{'pct': …}` in its cache — same hook as `make_batch_views`."""
        data = self._get(self._views(progress_of=lambda item: 77)['progress'], self.item.pk)
        self.assertEqual(77, data['progress'])

    def test_a_past_error_is_not_shown_on_a_relaunched_card(self):
        data = self._get(self._views()['progress'], self.item.pk)
        self.assertEqual(('', ''), (data['error'], data['error_message']))
        self.model.objects.filter(pk=self.item.pk).update(status='FAILURE')
        data = self._get(self._views()['progress'], self.item.pk)
        self.assertEqual(('an old failure', 'an old failure'), (data['error'], data['error_message']))

    def test_the_eta_triplet_is_estimated_while_in_flight_only(self):
        views = self._views(eta_for=lambda item: ('progress_test:key', 2, 'item'))
        with mock.patch('wama.model_manager.services.eta_estimator.estimate',
                        return_value=12.5) as estimate:
            data = self._get(views['progress'], self.item.pk)
        self.assertEqual(12.5, data['estimated_seconds'])
        estimate.assert_called_once_with('progress_test:key', size=2, unit='item',
                                         model_loaded=True)
        self.model.objects.filter(pk=self.item.pk).update(status='SUCCESS')
        self.assertNotIn('estimated_seconds', self._get(views['progress'], self.item.pk))

    def test_the_declared_prior_answers_when_nothing_is_learned(self):
        views = self._views(eta_for=lambda item: ('k', 1, 'item'), eta_fallback=lambda item: 30)
        with mock.patch('wama.model_manager.services.eta_estimator.estimate', return_value=0):
            self.assertEqual(30, self._get(views['progress'], self.item.pk)['estimated_seconds'])

    def test_a_card_whose_processes_name_their_eta_is_estimated_at_their_sum(self):
        """`process_runs.launch_eta` prevails over the app triplet : one triplet per app gave the
        render alone of the composer the time of a score + a render (2026-10-05)."""
        views = self._views(eta_for=lambda item: ('k', 1, 'item'))
        with mock.patch('wama.common.services.process_runs.launch_eta', return_value=42.0), \
                mock.patch('wama.model_manager.services.eta_estimator.estimate',
                           return_value=7.0) as estimate:
            self.assertEqual(42.0, self._get(views['progress'], self.item.pk)['estimated_seconds'])
        estimate.assert_not_called()

    def test_extra_keys_complete_the_common_payload(self):
        data = self._get(self._views(extra=lambda item: {'partial_text': 'abc'})['progress'],
                         self.item.pk)
        self.assertEqual('abc', data['partial_text'])

    def test_an_app_without_pipeline_shows_no_process_band(self):
        data = self._get(self._views()['progress'], self.item.pk)
        self.assertNotIn('processes', data)

    def test_the_queue_bar_counts_the_users_elements_with_the_live_progress(self):
        cache.set(f'progress_test_progress_{self.item.pk}', 50)
        self.model.objects.create(user=self.user, status='FAILURE')
        other = get_user_model().objects.create_user('someone-else', password='x')
        self.model.objects.create(user=other, status='SUCCESS')
        data = self._get(self._views()['global_progress'])
        self.assertEqual((2, 1, 1), (data['total'], data['running'], data['failed']))
        self.assertEqual(25, data['overall_progress'])

    def test_a_bar_per_domain_carries_the_contract_in_each(self):
        views = self._views(domains={'image': lambda qs: qs.filter(status='RUNNING'),
                                     'video': lambda qs: qs.exclude(status='RUNNING')})
        data = self._get(views['global_progress'])
        self.assertEqual(1, data['image']['total'])
        self.assertEqual(0, data['video']['total'])
        self.assertEqual(data['image']['total'], data['total'])   # the first one, flat

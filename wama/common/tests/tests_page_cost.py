"""Le coût commun de chaque page, réduit le 2026-10-02 — et ce que ces réductions ne doivent PAS changer.

CE QUE CES GARDES TIENNENT :
- les droits du menu se lisent EN UNE FOIS (`accessible_apps`) : la décision doit rester
  IDENTIQUE, app par app, à `accessible()` — c'est une décision d'accès, une divergence serait
  une faille ou un refus injustifié, et elle ne se verrait pas à l'usage ;
- `static_v` garde le chemin résolu et ne relit la date d'un statique qu'au-delà de son délai —
  mais il VOIT une modification ensuite (sinon un JS corrigé n'arriverait pas au navigateur) ;
- le registre des bacs à sable n'est relu que s'il a changé — mais il EST relu quand il change,
  et un appelant ne peut pas altérer la copie gardée ;
- (2026-10-14) la page de FILE de chaque app à pipeline lit l'état des étapes de toutes ses cards
  en une fois (`decorate_cards`) : autant de lectures pour une card que pour quatre, réparties
  en deux lots — contrat générique, aucune app nommée ;
- (2026-10-15, `/audit-lenteurs`) la grille fonctionnelle de `/common/apps/` ne relit ses
  rapports nocturnes que si l'un s'ajoute ou si le dernier est réécrit — et le résultat est celui
  du calcul direct.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from wama.accounts.models import AppAccessPolicy
from wama.accounts.permissions import GROUP_PREFIX, accessible, accessible_apps


class GroupedAccessDecisionTest(TestCase):

    APPS = ['transcriber', 'imager', 'model_manager', 'converter', 'converter_42', 'unknown_app']

    def setUp(self):
        research = Group.objects.create(name=GROUP_PREFIX + 'recherche')
        communication = Group.objects.create(name=GROUP_PREFIX + 'communication')
        AppAccessPolicy.objects.create(app_id='transcriber').roles.add(research)
        AppAccessPolicy.objects.create(app_id='imager').roles.add(communication)
        AppAccessPolicy.objects.create(app_id='model_manager', min_tier='developpeur')
        AppAccessPolicy.objects.create(app_id='converter')             # app commune
        # Jumelle RESTREINTE : seul son créateur (non développeur) y entre, par la dérogation du
        # créateur — sans restriction, une lecture groupée qui oublierait le créateur passerait.
        AppAccessPolicy.objects.create(app_id='converter_42', min_tier='developpeur')
        User = get_user_model()
        self.researcher = User.objects.create_user('grouped_research', password='x')
        self.researcher.groups.add(research)
        self.nobody = User.objects.create_user('grouped_nobody', password='x')
        self.admin = User.objects.create_superuser('grouped_admin', password='x')
        # Une jumelle de bac à sable dont `grouped_nobody` est le CRÉATEUR.
        registry = mock.patch('wama.common.sandbox.load_registry',
                              return_value=[{'label': 'converter_42', 'created_by': 'grouped_nobody'}])
        registry.start()
        self.addCleanup(registry.stop)

    def test_the_grouped_reading_decides_exactly_like_the_unit_decision(self):
        for user in (self.researcher, self.nobody, self.admin):
            with self.subTest(user=user.username):
                self.assertEqual([a for a in self.APPS if accessible(user, 'app', a)],
                                 accessible_apps(user, self.APPS))

    def test_the_policies_are_read_once_for_the_whole_list(self):
        with CaptureQueriesContext(connection) as queries:
            accessible_apps(self.researcher, self.APPS * 5)
        on_policies = [q for q in queries.captured_queries
                       if 'accounts_appaccesspolicy' in q['sql']]
        self.assertLessEqual(len(on_policies), 2, on_policies)


class ReaderGlobalProgressTest(TestCase):
    """La progression globale est interrogée en continu par la page : UNE requête sur `status` et
    `progress`, même calcul qu'avant (2026-10-03 ; même correctif au transcriber, gardé par
    `transcriber/tests/tests_queue_load`)."""

    def test_the_figures_are_unchanged_and_come_from_one_light_query(self):
        from django.urls import reverse
        from wama.reader.models import ReadingItem
        user = get_user_model().objects.create_superuser('reader_progress', password='x')
        for status, progress in (('SUCCESS', 100), ('RUNNING', 40), ('PENDING', 0)):
            ReadingItem.objects.create(user=user, original_filename=f'{status}.pdf',
                                       status=status, progress=progress)
        self.client.force_login(user)
        with CaptureQueriesContext(connection) as queries:
            data = self.client.get(reverse('wama.reader:global_progress')).json()
        # `failed` : le vocabulaire COMPLET de la fabrique commune (ROUTE §11 #37, 2026-10-03) —
        # le reader nommait ses échecs `error`, une des quatre graphies que le JS commun absorbait.
        self.assertEqual((3, 1, 1, 1, 0, 46),
                         (data['total'], data['done'], data['running'], data['pending'],
                          data['failed'], data['overall_progress']))
        on_items = [q['sql'] for q in queries.captured_queries if 'FROM "reader_readingitem"' in q['sql']]
        self.assertEqual(1, len(on_items), on_items)


class StaticVersionCacheTest(SimpleTestCase):

    def setUp(self):
        from wama.common.templatetags import wama_static
        self.module = wama_static
        self.folder = tempfile.mkdtemp()
        self.file = Path(self.folder) / 'probe.js'
        self.file.write_text('// v1', encoding='utf-8')
        os.utime(self.file, (1_000_000, 1_000_000))
        wama_static._PATH_CACHE.clear()
        wama_static._MTIME_CACHE.clear()
        self.addCleanup(wama_static._PATH_CACHE.clear)
        self.addCleanup(wama_static._MTIME_CACHE.clear)

    @override_settings(DEBUG=True)
    def test_the_finder_runs_once_and_a_change_shows_after_the_delay(self):
        clock = [100.0]
        with mock.patch('django.contrib.staticfiles.finders.find',
                        return_value=str(self.file)) as find, \
                mock.patch.object(self.module.time, 'monotonic', side_effect=lambda: clock[0]):
            first = [self.module.static_v('probe/probe.js') for _ in range(3)]
            os.utime(self.file, (2_000_000, 2_000_000))
            within = self.module.static_v('probe/probe.js')
            clock[0] += self.module.DEBUG_RECHECK_SECONDS + 1
            after = self.module.static_v('probe/probe.js')
        find.assert_called_once()
        self.assertTrue(all(u.endswith('v=1000000') for u in first + [within]), first)
        self.assertTrue(after.endswith('v=2000000'), after)


class SandboxRegistryCacheTest(SimpleTestCase):

    def setUp(self):
        from wama.common import sandbox
        self.sandbox = sandbox
        self.path = Path(tempfile.mkdtemp()) / 'sandbox_apps.json'
        patcher = mock.patch.object(sandbox, 'REGISTRY_PATH', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        sandbox._REGISTRY_CACHE.update(stamp=None, data=[])
        self.addCleanup(sandbox._REGISTRY_CACHE.update, stamp=None, data=[])

    def _write(self, entries, mtime):
        self.path.write_text(json.dumps(entries), encoding='utf-8')
        os.utime(self.path, (mtime, mtime))

    def test_a_changed_registry_is_read_again(self):
        self._write([{'label': 'converter_01'}], 1_000_000)
        self.assertEqual(['converter_01'], [e['label'] for e in self.sandbox.load_registry()])
        self._write([{'label': 'converter_01'}, {'label': 'imager_02'}], 2_000_000)
        self.assertEqual(['converter_01', 'imager_02'],
                         [e['label'] for e in self.sandbox.load_registry()])

    def test_a_caller_cannot_alter_the_kept_copy(self):
        self._write([{'label': 'converter_01', 'created_by': 'alice'}], 1_000_000)
        self.sandbox.load_registry()[0]['created_by'] = 'mallory'
        self.assertEqual('alice', self.sandbox.load_registry()[0]['created_by'])


class OutputDigestCacheTest(SimpleTestCase):
    """2026-10-13 — the process strip re-hashed every card's outputs on each display (1,2 s on the
    anonymizer and composer pages). An unchanged file is not read again ; a rewritten one is — a
    process output rewritten must still make its downstream stale."""

    def test_an_unchanged_file_is_hashed_once_and_a_rewritten_one_again(self):
        import hashlib
        from wama.common.utils import provenance
        path = Path(tempfile.mkdtemp()) / 'out.txt'
        path.write_text('first', encoding='utf-8')
        os.utime(path, (1_000_000, 1_000_000))
        with mock.patch.object(provenance, '_digest', wraps=provenance._digest) as read:
            first = [provenance.sha256_of(path) for _ in range(3)]
            path.write_text('second', encoding='utf-8')
            os.utime(path, (2_000_000, 2_000_000))
            second = provenance.sha256_of(path)
        self.assertEqual(2, read.call_count, 'an unchanged file was read again')
        self.assertEqual(hashlib.sha256(b'first').hexdigest(), first[0])
        self.assertEqual(hashlib.sha256(b'second').hexdigest(), second)


class SurfaceDeclarationsLoadedOnceTest(SimpleTestCase):
    """2026-10-13 — `surface_button` (once per card) re-ran the import of every app's `surfaces`
    module: a FAILED import per app without one, i.e. a search of `sys.path` over /mnt/d —
    4,5 s for the anonymizer page. The declarations load once per process."""

    def test_the_declarations_are_imported_once(self):
        from wama.common import surfaces
        surfaces.load_all()
        with mock.patch('importlib.import_module') as imported:
            surfaces.surface('anonymizer', 'review')
            surfaces.surfaces_of('anonymizer')
        imported.assert_not_called()


class QueuePageReadsStepStatesOnceTest(TestCase):
    """Every app's QUEUE page reads the step states (`ProcessRun` lines) of all its cards at once
    — `process_pipeline.decorate_cards` — never once per card.

    Measured on 2026-10-03: the process strip cost six queries PER CARD. The brick that reads a
    page in one query is guarded on its own (`tests_process_pipeline`), but nothing checked that
    an APP's page goes through it: the enhancer kept decorating card by card until 2026-10-14
    (`b04b78d9`, measured by hand on the live base). One generic contract, every app that
    declares a pipeline: the lines are read the same number of times for one card and for four.
    """

    TABLE = 'common_processrun'

    def _apps(self):
        from django.urls import NoReverseMatch, reverse
        from wama.common.app_registry import APP_CATALOG
        from wama.common.sandbox import twins_with_copied_views
        from wama.common.services.process_pipeline import pipeline_of
        from wama.common.utils.preview_registry import PreviewRegistry
        copied, out = twins_with_copied_views(), []
        for app, spec in APP_CATALOG.items():
            if app in copied or (spec or {}).get('sandbox'):
                continue
            model = PreviewRegistry.get_model(app)
            try:
                url = reverse(f'{app}:index')
            except NoReverseMatch:
                continue
            if model is not None and pipeline_of(model()) is not None:
                out.append((app, model, url))
        return out

    def _step_reads(self, url):
        with CaptureQueriesContext(connection) as page:
            response = self.client.get(url)
        self.assertEqual(200, response.status_code)
        return sum(self.TABLE in q['sql'] for q in page)

    def test_the_step_states_are_read_once_per_page_not_once_per_card(self):
        from wama.common.tests.tests_endpoints import EveryEndpointAnswersTest
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        apps = self._apps()
        self.assertGreaterEqual(len(apps), 10, [a for a, _, _ in apps])
        for app, model, url in apps:
            with self.subTest(app=app):
                account = EveryEndpointAnswersTest._account_for(self, app)
                self.client.force_login(account)
                _lot_de(model, account, 1)
                one = self._step_reads(url)
                # Non-vacuity: a page that shows no strip would pass with zero reads.
                self.assertGreaterEqual(one, 1, f'{app}: the card was not decorated')
                _lot_de(model, account, 3)
                self.assertEqual(one, self._step_reads(url),
                                 f'{app}: the step states are read again for each card')


class FunctionalGridReadsReportsOnceTest(SimpleTestCase):
    """`/common/apps/` relisait les 749 rapports nocturnes à chaque visite (1,4 s mesurées le
    2026-10-15). La grille est mémorisée : relue quand un rapport s'AJOUTE ou quand le DERNIER
    est réécrit (une campagne en cours), jamais sinon — et toujours égale au calcul direct."""

    def setUp(self):
        from wama.common.services import nightly_tests
        self.nightly = nightly_tests
        self.scenario = next(sc for sc in nightly_tests.REGISTRY if sc.enabled)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.reports = Path(self._tmp.name) / 'logs' / 'nightly_tests'
        self.reports.mkdir(parents=True)
        settings_override = override_settings(BASE_DIR=Path(self._tmp.name))
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        nightly_tests._functional_grid_cache.clear()
        self.addCleanup(nightly_tests._functional_grid_cache.clear)

    def _write(self, stamp, ok):
        (self.reports / f'nightly_{stamp}.json').write_text(json.dumps({
            'generated_at': stamp, 'results': [{'scenario_id': self.scenario.id, 'ok': ok}]}),
            encoding='utf-8')

    def _line(self, grid):
        return next(s for s in grid[self.scenario.app]['scenarios'] if s['id'] == self.scenario.id)

    def test_reports_are_read_again_only_when_one_is_added_or_the_latest_rewritten(self):
        self._write('20261001_010000', ok=False)
        self._write('20261002_010000', ok=True)
        direct = self.nightly._compute_functional_grid(self.reports)
        compute = mock.Mock(wraps=self.nightly._compute_functional_grid)
        with mock.patch.object(self.nightly, '_compute_functional_grid', compute):
            first = self.nightly.functional_grid()
            self.assertEqual(direct, first)
            self.assertEqual(first, self.nightly.functional_grid())
            self.assertEqual(1, compute.call_count, 'unchanged reports were read again')

            self._write('20261003_010000', ok=False)           # a new report
            self.assertFalse(self._line(self.nightly.functional_grid())['ok'])
            self.assertEqual(2, compute.call_count)

            self._write('20261003_010000', ok=True)            # the latest, rewritten
            self.assertTrue(self._line(self.nightly.functional_grid())['ok'])
            self.assertEqual(3, compute.call_count)

    def test_without_any_report_every_scenario_is_never_run(self):
        self.assertTrue(self._line(self.nightly.functional_grid())['never_run'])

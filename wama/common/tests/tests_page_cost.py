"""Le coût commun de chaque page, réduit le 2026-10-02 — et ce que ces réductions ne doivent PAS changer.

CE QUE CES GARDES TIENNENT :
- les droits du menu se lisent EN UNE FOIS (`accessible_apps`) : la décision doit rester
  IDENTIQUE, app par app, à `accessible()` — c'est une décision d'accès, une divergence serait
  une faille ou un refus injustifié, et elle ne se verrait pas à l'usage ;
- `static_v` garde le chemin résolu et ne relit la date d'un statique qu'au-delà de son délai —
  mais il VOIT une modification ensuite (sinon un JS corrigé n'arriverait pas au navigateur) ;
- le registre des bacs à sable n'est relu que s'il a changé — mais il EST relu quand il change,
  et un appelant ne peut pas altérer la copie gardée.
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
    `transcriber/tests_queue_load`)."""

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

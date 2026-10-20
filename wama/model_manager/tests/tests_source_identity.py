"""Le NOM d'une source de modèle — `models.source_identity` (2026-10-20, filtre « Source » du model
manager, `WAMA_APP_GENERATION_ROUTE §10.6 P1`).

La clé `AIModel.source` a trois natures, et chacune est déjà nommée ailleurs : une app
(`app_registry.app_identity`), un fournisseur distant ou une plateforme (`external_sources`). La
barre de filtres, le badge de card et l'inspecteur affichaient la clé brute ; les libellés de
`ModelSource` recopiaient ces noms et avaient déjà divergé.
"""
import importlib.util
import json
import re
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama.common import external_sources
from wama.common.app_registry import app_identity
from wama.model_manager.models import AIModel, ModelSource, SOURCE_NATURES, source_identity

INDEX = (Path(settings.BASE_DIR) / 'wama' / 'model_manager' / 'templates' / 'model_manager'
         / 'index.html')
HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None


class SourceIdentityTest(SimpleTestCase):

    def test_an_app_source_is_named_by_its_app_identity(self):
        apps = [s for s in ModelSource.values if app_identity(s)['declared']]
        self.assertGreaterEqual(len(apps), 10, 'nothing measured')
        for source in apps:
            with self.subTest(source=source):
                self.assertEqual({'key': source, 'nature': 'app',
                                  'label': app_identity(source)['label']},
                                 source_identity(source))

    def test_a_remote_provider_is_named_by_the_registry_and_the_subscription_stays_apart(self):
        remote = [s for s in ModelSource.values
                  if getattr(external_sources.by_key().get(s), 'kind', '') == 'llm']
        self.assertGreaterEqual(len(remote), 5, 'nothing measured')
        for source in remote:
            with self.subTest(source=source):
                self.assertEqual(('remote', external_sources.get(source).label),
                                 (source_identity(source)['nature'], source_identity(source)['label']))
        # Fabien: the Claude Code subscription and the Anthropic API are two different channels.
        self.assertNotEqual(source_identity('claude_code')['label'],
                            source_identity('anthropic')['label'])

    def test_a_platform_is_named_by_the_registry(self):
        for source in ('huggingface', 'ollama', 'github'):
            with self.subTest(source=source):
                self.assertEqual({'key': source, 'nature': 'platform',
                                  'label': external_sources.get(source).label},
                                 source_identity(source))

    def test_a_key_nothing_else_names_keeps_the_label_of_its_enumeration(self):
        self.assertEqual({'key': 'custom', 'nature': 'platform', 'label': ModelSource.CUSTOM.label},
                         source_identity('custom'))
        self.assertEqual('nowhere', source_identity('nowhere')['label'])

    def test_every_source_falls_in_a_group_of_the_filter_and_is_named(self):
        natures = {key for key, _label in SOURCE_NATURES}
        for source in ModelSource.values:
            identity = source_identity(source)
            with self.subTest(source=source):
                self.assertIn(identity['nature'], natures)
                self.assertNotEqual(source, identity['label'], 'the raw key is shown')


class SourceOnTheCatalogueTest(TestCase):

    def test_the_catalogue_api_carries_the_name_and_the_nature(self):
        for key, execution in (('face_analyzer:x', 'local'), ('claude_code:opus', 'cloud'),
                               ('huggingface:org/m', 'local')):
            AIModel.objects.create(model_key=key, name=key, model_type='llm',
                                   source=key.split(':')[0], execution=execution,
                                   is_available=True)
        user = get_user_model().objects.create_user('source_filter_reader', password='x')
        self.client.force_login(user)
        rows = {r['model_key']: (r['source_label'], r['source_nature'])
                for r in self.client.get('/model-manager/api/models/db/').json()['models']}
        for key, (label, nature) in rows.items():
            with self.subTest(key=key):
                identity = source_identity(key.split(':')[0])
                self.assertEqual((identity['label'], identity['nature']), (label, nature))
        self.assertEqual('app', rows['face_analyzer:x'][1])

    def test_the_page_hands_the_groups_to_the_filter(self):
        admin = get_user_model().objects.create_superuser('source_filter_admin', password='x')
        self.client.force_login(admin)
        html = self.client.get('/model-manager/').content.decode()
        found = re.search(r'<script id="mm-source-natures" type="application/json">(.*?)</script>',
                          html, re.S)
        self.assertIsNotNone(found, 'the groups are not served')
        self.assertEqual([{'key': k, 'label': label} for k, label in SOURCE_NATURES],
                         json.loads(found.group(1)))
        self.assertIn('for="filter-source">Source :</label>', html)


class SourceFilterScriptTest(SimpleTestCase):
    """The options of the filter, built by the page script — run under V8."""

    def setUp(self):
        self.html = INDEX.read_text(encoding='utf-8')

    def test_the_card_and_the_inspector_show_the_name(self):
        self.assertIn('${WamaApp.escapeHtml(model.source_label || model.source)}', self.html)
        self.assertIn("{ k: 'Source', get: function (m) { return m.source_label", self.html)
        self.assertNotIn("<span class=\"source-badge\">${model.source}</span>", self.html)

    @skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
    def test_the_options_are_grouped_by_nature_and_named(self):
        from py_mini_racer import MiniRacer
        body = re.search(r'\n    function sourceOptions\(models\) \{.*?\n    \}\n', self.html, re.S)
        self.assertIsNotNone(body, 'sourceOptions was not found')
        natures = json.dumps([{'key': k, 'label': label} for k, label in SOURCE_NATURES])
        ctx = MiniRacer()
        ctx.eval("var WamaApp = {escapeHtml: function (s) { return String(s).replace(/&/g, '&amp;')"
                 ".replace(/</g, '&lt;').replace(/\"/g, '&quot;'); }};"
                 "var document = {getElementById: function () { return {textContent: %s}; }};"
                 % json.dumps(natures) + body.group(0))
        models = [{'source': key, 'source_label': source_identity(key)['label'],
                   'source_nature': source_identity(key)['nature']}
                  for key in ('openrouter', 'imager', 'huggingface', 'claude_code', 'imager')]
        html = ctx.eval('sourceOptions(%s)' % json.dumps(models))
        groups = re.findall(r'<optgroup label="([^"]+)">(.*?)</optgroup>', html)
        self.assertEqual(['Apps WAMA', 'Fournisseurs distants', 'Plateformes'],
                         [label for label, _ in groups])
        options = [re.findall(r'<option value="([^"]+)">([^<]+)</option>', inner)
                   for _, inner in groups]
        self.assertEqual([[('imager', app_identity('imager')['label'])],
                          sorted([('claude_code', source_identity('claude_code')['label']),
                                  ('openrouter', source_identity('openrouter')['label'])],
                                 key=lambda o: o[1]),
                          [('huggingface', source_identity('huggingface')['label'])]], options)
        # Counter-check: a nature that no model carries opens no empty group.
        self.assertNotIn('optgroup', ctx.eval("sourceOptions([])"))

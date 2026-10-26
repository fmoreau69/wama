"""Le NOM d'une source de modèle — `models.source_identity` (filtre « Source » du model manager,
`WAMA_APP_GENERATION_ROUTE §10.6 P1`).

La clé `AIModel.source` a trois natures, et chacune est déjà nommée ailleurs : une app
(`app_registry.app_identity`), un fournisseur distant (`external_sources.remote_origin_label` : son
hébergement et son COÛT, la phrase des sélecteurs) ou une plateforme (`external_sources`). Les
groupes du filtre sont les mondes des apps et les familles du registre des sources : rien n'est
écrit pour eux.

2026-10-22 : la première version (20/10) nommait un fournisseur par son seul nom au registre, et
le test l'exigeait — « Claude Code » ne disait plus l'abonnement (relevé de Fabien). Les tests
ci-dessous exigent le coût.
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
from wama.common.app_registry import WORLD_SECTIONS, app_identity
from wama.model_manager.models import AIModel, ModelSource, source_groups, source_identity

INDEX = (Path(settings.BASE_DIR) / 'wama' / 'model_manager' / 'templates' / 'model_manager'
         / 'index.html')
HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None


def _remote_sources():
    return [s for s in ModelSource.values
            if getattr(external_sources.by_key().get(s), 'kind', '') == 'llm']


class SourceIdentityTest(SimpleTestCase):

    def test_an_app_source_is_named_by_its_app_identity_in_its_world(self):
        apps = [s for s in ModelSource.values if app_identity(s)['declared']]
        self.assertGreaterEqual(len(apps), 10, 'nothing measured')
        for source in apps:
            with self.subTest(source=source):
                self.assertEqual({'key': source, 'group': f"world:{app_identity(source)['world']}",
                                  'label': app_identity(source)['label']},
                                 source_identity(source))

    def test_a_remote_provider_says_where_it_runs_and_what_it_costs(self):
        remote = _remote_sources()
        self.assertGreaterEqual(len(remote), 5, 'nothing measured')
        for source in remote:
            with self.subTest(source=source):
                self.assertEqual({'key': source, 'group': 'kind:llm',
                                  'label': external_sources.remote_origin_label(source)},
                                 source_identity(source))

    def test_the_claude_subscription_and_the_claude_api_are_told_apart_by_their_cost(self):
        # Fabien: « savoir si c'est Claude API ou Claude abonnement ». Claude Code alone does not
        # say it — the CLI also runs on API billing.
        subscription = source_identity('claude_code')['label']
        api = source_identity('anthropic')['label']
        self.assertIn(external_sources.cost_label('subscription'), subscription)
        self.assertIn(external_sources.cost_label('metered'), api)
        self.assertNotIn(external_sources.cost_label('subscription'), api)

    def test_a_platform_is_named_by_the_registry_in_its_family(self):
        for source in ('huggingface', 'ollama', 'github'):
            declared = external_sources.get(source)
            with self.subTest(source=source):
                self.assertEqual({'key': source, 'group': f'kind:{declared.kind}',
                                  'label': declared.label},
                                 source_identity(source))

    def test_a_key_nothing_else_names_keeps_its_enumeration_label_outside_any_group(self):
        self.assertEqual({'key': 'custom', 'group': '', 'label': ModelSource.CUSTOM.label},
                         source_identity('custom'))
        self.assertEqual('nowhere', source_identity('nowhere')['label'])

    def test_every_source_is_named_and_falls_in_a_declared_group(self):
        groups = {g['key'] for g in source_groups()}
        for source in ModelSource.values:
            identity = source_identity(source)
            with self.subTest(source=source):
                self.assertNotEqual(source, identity['label'], 'the raw key is shown')
                if source != 'custom':
                    self.assertIn(identity['group'], groups)

    def test_the_groups_are_the_worlds_then_the_source_families_and_nothing_written_here(self):
        worlds = sorted(WORLD_SECTIONS.values(), key=lambda s: s.get('order', 0))
        self.assertEqual([s['label'] for s in worlds] + list(external_sources.KINDS.values()),
                         [g['label'] for g in source_groups()])


class SourceVocabularyTest(SimpleTestCase):
    """`ModelSource` is a VOCABULARY of key prefixes, not a list of names (2026-10-22)."""

    def test_the_source_field_carries_no_choices_so_a_new_source_needs_no_migration(self):
        self.assertFalse(AIModel._meta.get_field('source').choices)

    def test_the_enumeration_writes_no_label_by_hand(self):
        for member in ModelSource:
            with self.subTest(member=member.name):
                self.assertEqual(member.name.replace('_', ' ').title(), member.label)

    def test_every_value_but_custom_is_the_key_of_an_existing_declaration(self):
        for source in ModelSource.values:
            if source == ModelSource.CUSTOM:
                continue
            with self.subTest(source=source):
                self.assertTrue(app_identity(source)['declared']
                                or source in external_sources.by_key(),
                                f'{source!r} is declared nowhere')

    def test_the_admin_cannot_change_a_source_apart_from_its_key(self):
        from django.contrib import admin
        model_admin = admin.site._registry[AIModel]
        self.assertTrue({'model_key', 'source'} <= set(model_admin.readonly_fields))


class SourceOnTheCatalogueTest(TestCase):

    def test_the_catalogue_api_carries_the_name_and_the_group(self):
        for key, execution in (('face_analyzer:x', 'local'), ('claude_code:opus', 'cloud'),
                               ('huggingface:org/m', 'local')):
            AIModel.objects.create(model_key=key, name=key, model_type='llm',
                                   source=key.split(':')[0], execution=execution,
                                   is_available=True)
        user = get_user_model().objects.create_user('source_filter_reader', password='x')
        self.client.force_login(user)
        rows = {r['model_key']: r
                for r in self.client.get('/model-manager/api/models/db/').json()['models']}
        for key, row in rows.items():
            with self.subTest(key=key):
                identity = source_identity(key.split(':')[0])
                self.assertEqual((identity['label'], identity['group']),
                                 (row['source_label'], row['source_group']))
        self.assertEqual('world:lab', rows['face_analyzer:x']['source_group'])
        self.assertIn('abonnement', rows['claude_code:opus']['source_label'])

    def test_the_page_hands_the_declared_groups_to_the_filter(self):
        admin = get_user_model().objects.create_superuser('source_filter_admin', password='x')
        self.client.force_login(admin)
        html = self.client.get('/model-manager/').content.decode()
        found = re.search(r'<script id="mm-source-groups" type="application/json">(.*?)</script>',
                          html, re.S)
        self.assertIsNotNone(found, 'the groups are not served')
        self.assertEqual(source_groups(), json.loads(found.group(1)))
        self.assertIn('for="filter-source">Source :</label>', html)

    def test_the_admin_filter_names_the_sources_like_the_page(self):
        for key in ('claude_code:opus', 'anthropic:claude-x'):
            AIModel.objects.create(model_key=key, name=key, model_type='llm',
                                   source=key.split(':')[0], execution='cloud')
        admin = get_user_model().objects.create_superuser('source_admin_filter', password='x')
        self.client.force_login(admin)
        html = self.client.get('/admin/model_manager/aimodel/').content.decode()
        for source in ('claude_code', 'anthropic'):
            with self.subTest(source=source):
                self.assertIn(source_identity(source)['label'].replace("'", '&#x27;'), html)
        self.assertEqual(1, len(self.client.get('/admin/model_manager/aimodel/',
                                                {'source': 'claude_code'})
                                .context['cl'].result_list))


class SourceForTheAssistantTest(TestCase):
    """The two catalogue tools say the source under its own name, and the ORIGIN."""

    def test_the_tools_return_the_source_and_the_origin_never_an_app_key(self):
        from wama.tool_api import get_ai_model, list_ai_models
        AIModel.objects.create(model_key='claude_code:opus', name='Opus', model_type='llm',
                               source='claude_code', execution='cloud',
                               cost_tier='subscription', capabilities={'task': 'source-test'})
        user = get_user_model().objects.create_user('source_tool_reader', password='x')
        listed = [m for m in list_ai_models(user, task='source-test')['models']
                  if m['key'] == 'claude_code:opus']
        self.assertEqual(1, len(listed))
        one = get_ai_model(user, 'claude_code:opus')
        for row in (listed[0], one):
            with self.subTest(tool='list' if row is listed[0] else 'get'):
                self.assertNotIn('app', row)
                self.assertEqual('claude_code', row['source'])
                self.assertEqual(AIModel.objects.get(model_key='claude_code:opus').origin_label,
                                 row['origin'])
                self.assertIn('abonnement', row['origin'])


class SourceFilterScriptTest(SimpleTestCase):
    """The options of the filter and the card badge, built by the page script — run under V8."""

    def setUp(self):
        self.html = INDEX.read_text(encoding='utf-8')

    def _function(self, name):
        body = re.search(r'\n    function %s\(model[s]?\) \{.*?\n    \}\n' % name, self.html, re.S)
        self.assertIsNotNone(body, f'{name} was not found')
        return body.group(0)

    def test_the_inspector_says_the_origin_the_platform_the_author_and_the_licence(self):
        self.assertIn("{ k: 'Source', get: function (m) { return m.source_label", self.html)
        for row in ("{ k: 'Origine', field: 'origin' }", "{ k: 'Plateforme', get:",
                    "{ k: 'Auteur', field: 'author' }", "{ k: 'Licence', field: 'license' }"):
            with self.subTest(row=row):
                self.assertIn(row, self.html)
        self.assertIn('${WamaApp.escapeHtml(sourceBadge(model))}', self.html)
        self.assertNotIn("<span class=\"source-badge\">${model.source}</span>", self.html)

    @skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
    def test_a_remote_card_shows_the_origin_of_the_model_a_local_one_its_source(self):
        from py_mini_racer import MiniRacer
        ctx = MiniRacer()
        ctx.eval(self._function('sourceBadge'))
        free = {'execution': 'cloud', 'source_label': 'Cloud commercial · OpenRouter · facturé',
                'origin': 'Cloud commercial · OpenRouter · gratuit (quota)'}
        local = {'execution': 'local', 'source_label': 'Anonymizer', 'origin': 'WAMA local'}
        self.assertEqual(free['origin'], ctx.eval('sourceBadge(%s)' % json.dumps(free)))
        self.assertEqual('Anonymizer', ctx.eval('sourceBadge(%s)' % json.dumps(local)))

    @skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
    def test_the_options_are_grouped_by_declared_group_and_named(self):
        from py_mini_racer import MiniRacer
        ctx = MiniRacer()
        ctx.eval("var WamaApp = {escapeHtml: function (s) { return String(s).replace(/&/g, '&amp;')"
                 ".replace(/</g, '&lt;').replace(/\"/g, '&quot;'); }};"
                 "var document = {getElementById: function () { return {textContent: %s}; }};"
                 % json.dumps(json.dumps(source_groups())) + self._function('sourceOptions'))
        keys = ('openrouter', 'imager', 'huggingface', 'claude_code', 'imager', 'custom')
        models = [{'source': key, 'source_label': source_identity(key)['label'],
                   'source_group': source_identity(key)['group']} for key in keys]
        html = ctx.eval('sourceOptions(%s)' % json.dumps(models))
        groups = re.findall(r'<optgroup label="([^"]+)">(.*?)</optgroup>', html)
        labels = {g['key']: g['label'] for g in source_groups()}
        self.assertEqual([labels['world:media'], labels['kind:llm'], labels['kind:catalogue']],
                         [label for label, _ in groups])
        options = [re.findall(r'<option value="([^"]+)">([^<]+)</option>', inner)
                   for _, inner in groups]
        self.assertEqual([('imager', app_identity('imager')['label'])], options[0])
        self.assertEqual(['claude_code', 'openrouter'],
                         sorted(key for key, _ in options[1]))
        self.assertEqual([('huggingface', source_identity('huggingface')['label'])], options[2])
        # A source no declaration ranges stays choosable, outside the groups.
        self.assertTrue(html.endswith(f'<option value="custom">{ModelSource.CUSTOM.label}</option>'))
        # Counter-check: a group no model carries opens no empty group.
        self.assertNotIn('optgroup', ctx.eval("sourceOptions([])"))

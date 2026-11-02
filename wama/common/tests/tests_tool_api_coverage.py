"""THE ASSISTANT'S API FOLLOWS EVERY FUNCTIONAL ADDITION (2026-11-02, Fabien's decision : « l'API doit
être complétée systématiquement à chaque ajout fonctionnel »).

The tool registry (`tool_api.TOOL_REGISTRY`) is THE API : the assistant, the REST API v1, the MCP
server and the Studio runner all derive from it. Until now the guards that held it named the ten
apps by hand (`EveryTriadIsDeclaredTest`, `tests_tool_api_twins`) : an app added afterwards — the
Translator, born from a manifest without its `tool_api` facet — had no tool, and no test said so.
Measured the same day : the Translator had none, and two gestures of EVERY card (⏹ stop, ⚙
settings) had none either.

What is held, DERIVED from what WAMA declares, never from a list of names :
  1. every app of the catalogue (real, twin, born from a manifest) has its triad ;
  2. every gesture the common view factories give a card (`make_item_views`) or a batch
     (`make_batch_views`) maps to the tool that does it — a NEW gesture fails until it is mapped ;
     a gesture without a tool is a declared budget that can only shrink ;
  3. ⏹ and ⚙ through their tools, by the app's own view, under the app guard ;
  4. the tools decide a sandbox app as its page does — one rule (2026-11-02, Fabien's decision).
The recipe to complete the API is the skill `/api-outils`.
"""
import ast
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama import tool_api as T

#: Apps of the catalogue that have NO tool, each with its reason. Can only SHRINK : an app added to
#: the catalogue never enters it — it gets its triad (`/api-outils`). EMPTY since 2026-11-02.
APPS_WITHOUT_TOOLS = {}

#: Each gesture of the common view factories → the tool that does it (`{app}` : the app's triad),
#: or None when no tool does it yet. Read against the factories themselves (AST) : a gesture they
#: gain without a line here fails `test_every_gesture_of_the_factories_is_mapped`.
GESTURE_TOOLS = {
    'item': {
        'start': 'start_{app}', 'start_all': 'start_{app}', 'clear_all': 'clear_my_queue',
        'stop': 'stop_item', 'delete': 'delete_item', 'duplicate': 'duplicate_item',
        'download': 'get_item_result', 'update_settings': 'update_item_settings',
    },
    # A BATCH has no tool yet : the assistant reaches its elements one by one (the item gestures
    # above). ⏳ consigned at ROUTE §11 #44 — the budget below can only go down.
    'batch': {
        'batch_start': None, 'batch_update': None, 'batch_delete': None, 'batch_duplicate': None,
        'batch_download': None, 'batch_status': None, 'batch_promote': None, 'batch_realign': None,
    },
}
#: Gestures without a tool. The value of the measure ; LOWER it in the commit that adds a tool.
GESTURES_WITHOUT_TOOL_BUDGET = 8

FACTORIES = {'item': ('wama/common/utils/item_views.py', 'make_item_views'),
             'batch': ('wama/common/utils/batch_views.py', 'make_batch_views')}


def factory_gestures(path: str, function: str) -> set:
    """The keys of the dict a view factory RETURNS — its gestures, read in its source."""
    tree = ast.parse((Path(settings.BASE_DIR) / path).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            returned = [n.value for n in node.body if isinstance(n, ast.Return)]
            if returned and isinstance(returned[-1], ast.Dict):
                return {k.value for k in returned[-1].keys if isinstance(k, ast.Constant)}
    raise AssertionError(f'{path} : {function} ne rend plus un dict de vues')


class EveryAppHasItsToolsTest(SimpleTestCase):

    def test_every_app_of_the_catalogue_has_its_triad(self):
        from wama.common.app_registry import APP_CATALOG
        missing = {}
        for app in APP_CATALOG:
            if app in APPS_WITHOUT_TOOLS:
                continue
            absent = [name for name in (f'add_to_{app}', f'start_{app}', f'get_{app}_status')
                      if name not in T.TOOL_REGISTRY]
            if absent:
                missing[app] = absent
        self.assertEqual({}, missing, "une app sans ses outils : la compléter (skill /api-outils)")

    def test_an_exemption_is_still_needed(self):
        for app in APPS_WITHOUT_TOOLS:
            with self.subTest(app=app):
                self.assertNotIn(f'add_to_{app}', T.TOOL_REGISTRY,
                                 f'{app} a ses outils : la retirer de APPS_WITHOUT_TOOLS')


class EveryGestureHasItsToolTest(SimpleTestCase):

    def test_every_gesture_of_the_factories_is_mapped(self):
        for kind, (path, function) in FACTORIES.items():
            with self.subTest(factory=function):
                self.assertEqual(factory_gestures(path, function), set(GESTURE_TOOLS[kind]),
                                 'un geste neuf de la fabrique : lui donner son outil (/api-outils)')

    def test_every_mapped_tool_exists(self):
        for kind, gestures in GESTURE_TOOLS.items():
            for gesture, tool in gestures.items():
                if tool is None:
                    continue
                with self.subTest(gesture=gesture):
                    self.assertIn(tool.format(app='reader'), T.TOOL_REGISTRY)

    def test_the_budget_of_gestures_without_tool_is_exact(self):
        """It FAILS when it keeps a margin too : a margin is a permission to add a gesture
        without its tool."""
        without = [g for gestures in GESTURE_TOOLS.values() for g, t in gestures.items() if t is None]
        self.assertEqual(GESTURES_WITHOUT_TOOL_BUDGET, len(without), without)

    def test_the_new_card_tools_are_cross_app_and_state_their_effect(self):
        for name in ('stop_item', 'update_item_settings'):
            with self.subTest(tool=name):
                self.assertIsNone(T.app_id_for_tool(name), 'transverse : gardé dans son corps')
                self.assertEqual('write', T.effect_of(name)['effect'])


def _account(username, tier='utilisateur', role=''):
    """An account that PASSES the app guard, never bypasses it : the imager asks for the
    `communication` role (same reason as `tests_tool_api_lectures._utilisateur`)."""
    from django.contrib.auth.models import Group

    from wama.accounts.models import UserProfile
    from wama.accounts.permissions import GROUP_PREFIX
    user = get_user_model().objects.create_user(username, password='x')
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.account_tier = tier
    profile.save()
    if role:
        user.groups.add(Group.objects.get_or_create(name=GROUP_PREFIX + role)[0])
    return get_user_model().objects.get(pk=user.pk)


class StopAndSettingsToolsTest(TestCase):
    """⏹ and ⚙ by the app's own view — the imager's, as the factory serves it to the ten apps."""

    def setUp(self):
        from wama.imager.models import ImageGeneration
        self.me = _account('coverage_me', role='communication')
        self.other = _account('coverage_other', role='communication')
        self.mine = ImageGeneration.objects.create(user=self.me, prompt='a cat')
        self.theirs = ImageGeneration.objects.create(user=self.other, prompt='a dog')

    def test_stop_marks_a_waiting_item_stopped_and_keeps_it(self):
        out = T.execute_tool('stop_item', {'app': 'imager', 'pk': self.mine.pk}, self.me)
        self.assertNotIn('error', out, out)
        self.mine.refresh_from_db()
        self.assertEqual((True, self.mine.status), (out['stopped'], out['status']))
        self.assertNotEqual('PENDING', self.mine.status)

    def test_settings_are_written_through_the_form_and_only_what_changes(self):
        out = T.execute_tool('update_item_settings',
                             {'app': 'imager', 'pk': self.mine.pk, 'settings': {'steps': '12'}},
                             self.me)
        self.assertNotIn('error', out, out)
        self.mine.refresh_from_db()
        self.assertEqual((12, ['steps']), (self.mine.steps, out['updated']))

    def test_a_json_text_is_read_as_the_settings_object(self):
        out = T.update_item_settings(self.me, 'imager', self.mine.pk, settings='{"steps": 9}')
        self.assertNotIn('error', out, out)
        self.mine.refresh_from_db()
        self.assertEqual(9, self.mine.steps)

    def test_another_users_item_is_neither_stopped_nor_changed(self):
        T.stop_item(self.me, 'imager', self.theirs.pk)
        T.update_item_settings(self.me, 'imager', self.theirs.pk, settings={'steps': 3})
        self.theirs.refresh_from_db()
        self.assertEqual(('PENDING', 30), (self.theirs.status, self.theirs.steps))

    def test_no_settings_and_an_anonymous_caller_are_refused(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertIn('error', T.update_item_settings(self.me, 'imager', self.mine.pk))
        self.assertIn('error', T.stop_item(AnonymousUser(), 'imager', self.mine.pk))


class SandboxAppsThroughTheToolsTest(TestCase):
    """ONE rule everywhere (Fabien, 2026-11-02 : « une seule règle partout, un dev ne voit que ses
    propres apps, admin toutes ») : the tools decide as the pages do (`accessible`) — the opening of
    an app to a developer (`AccessGrant`) is held by `accounts.tests.tests_app_access`."""

    REGISTRY = [{'label': 'writer_01', 'generated_from': '', 'created_by': 'coverage_dev'},
                {'label': 'reader_01', 'generated_from': 'reader', 'created_by': ''}]

    def setUp(self):
        from wama.accounts.permissions import DEFAULT_APP_ACCESS
        policy = {'roles': ['ingenierie'], 'min_tier': 'developpeur'}
        # The sandbox registry is GITIGNORED : posed here, so HEAD measures the rule, not the tree.
        for patch in (mock.patch.dict(DEFAULT_APP_ACCESS, {'writer_01': policy, 'reader_01': policy}),
                      mock.patch('wama.common.sandbox.load_registry', return_value=self.REGISTRY)):
            patch.start()
            self.addCleanup(patch.stop)
        self.admin = _account('coverage_admin', 'admin')
        self.dev = _account('coverage_dev', 'developpeur')
        self.other_dev = _account('coverage_other_dev', 'developpeur')

    def test_the_tool_gate_decides_as_the_page(self):
        from wama.accounts.permissions import accessible, tool_accessible
        with mock.patch.dict(T.TOOL_APP_OVERRIDE, {'add_to_writer_01': 'writer_01'}):
            for user, opened in ((self.admin, True), (self.dev, True), (self.other_dev, False)):
                with self.subTest(user=user.username):
                    self.assertEqual(opened, tool_accessible(user, 'add_to_writer_01'))
                    self.assertEqual(opened, accessible(user, 'app', 'writer_01'))
        self.assertFalse(accessible(self.dev, 'app', 'reader_01'), 'created by the command line')
        self.assertTrue(accessible(self.admin, 'app', 'reader_01'))

    def test_the_cycle_verbs_apply_it(self):
        self.assertEqual('forbidden', T.delete_item(self.other_dev, 'writer_01', 1).get('error'))
        self.assertEqual('forbidden', T.stop_item(self.other_dev, 'writer_01', 1).get('error'))

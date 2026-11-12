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
  4. the tools decide a sandbox app as its page does — one rule (2026-11-02, Fabien's decision) ;
  5. every ACTION ROUTE of WAMA (a path with an `api/` segment) maps to the tool that does it — a
     route without a tool is a declared budget that can only shrink (2026-11-08, Fabien : « si les
     API existent, l'assistant doit pouvoir les utiliser ». Measured that day : 252 such routes,
     the guards above saw none of them ; the format routes of the model manager had no tool) ;
  6. each tool of the model manager posts THE view of its button, with the method it accepts, and
     asks the user's agreement where the page does (2026-11-09 : the whole page, 46 routes) ;
  7. what the model reads of every tool is a whole sentence (2026-11-09 : 44 of 144 were cut).
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
    # A BATCH : the gestures of its mother card (2026-11-02) — the three ways of setting a whole
    # batch (write, promote one item, realign on the reference) are one tool with one mode each.
    'batch': {
        'batch_start': 'launch_batch', 'batch_update': 'update_batch_settings',
        'batch_promote': 'update_batch_settings', 'batch_realign': 'update_batch_settings',
        'batch_duplicate': 'duplicate_batch', 'batch_delete': 'delete_batch',
        'batch_download': 'get_batch_result', 'batch_status': 'get_batch_state',
    },
}
#: Gestures without a tool. The value of the measure ; LOWER it in the commit that adds a tool.
#: 8 → 0 on 2026-11-02 : the batch tools.
GESTURES_WITHOUT_TOOL_BUDGET = 0

FACTORIES = {'item': ('wama/common/utils/item_views.py', 'make_item_views'),
             'batch': ('wama/common/utils/batch_views.py', 'make_batch_views')}

#: Routes that ARE a surface of the API, not a gesture to give it : the derived REST API, the
#: tools' own HTTP views, and the assistant's channel (its chat, its voice) — each with its reason.
API_SURFACE_NAMESPACES = {'api_v1'}            # derived from TOOL_REGISTRY (`wama/api/v1/views.py`)
API_SURFACE_MODULES = {'wama.tool_api'}        # the HTTP views of the tools themselves
ASSISTANT_CHANNEL_ROUTES = {                   # the conversation with the assistant itself
    'ai_chat', 'ai_chat_clear', 'ai_chat_settings', 'ai_chat_follow_ups', 'ai_chat_jobs',
    'ai_chat_thread', 'ai_chat_stream', 'kokoro_tts', 'speech_to_text', 'end_of_turn',
}

#: Each action route → the tool that does it, read against the URL resolver itself : a route that
#: maps nowhere counts in the budget below. One tool may serve several routes (a page's poller of a
#: gesture is that gesture's tool, called again).
ROUTE_TOOLS = {
    # The domain of an app page (2026-11-12) : `open_page(page, domain=…)` keeps it for the account.
    'common:api_page_domain': 'open_page',
    'model_manager:api_models_db': 'list_ai_models',
    'model_manager:api_prospect_ollama': 'prospect_models',
    'model_manager:api_prospect_install': 'install_model',
    'model_manager:api_prospect_install_progress': 'install_model',
    'model_manager:api_prospect_install_options': 'get_install_options',
    'model_manager:api_library_action': 'install_library',
    'model_manager:api_library_action_state': 'get_library_action',
    'model_manager:api_format_stats': 'get_model_formats',
    'model_manager:api_conversion_suggestions': 'get_model_formats',
    'model_manager:api_conversion_options': 'get_model_formats',
    'model_manager:api_convert_model': 'convert_model_format',
    'model_manager:api_batch_convert': 'convert_model_format',
    'model_manager:api_convert_and_backup': 'convert_model_format',
    # Every other gesture of the model manager page (2026-11-09) — each tool posts the button's view.
    'model_manager:api_memory_stats': 'get_memory_state',
    'model_manager:api_memory_detailed': 'get_memory_state',
    'model_manager:api_tracked_models': 'get_memory_state',
    'model_manager:api_idle_models': 'get_memory_state',
    'model_manager:api_large_objects': 'get_memory_state',
    'model_manager:api_memory_snapshot': 'get_memory_state',
    'model_manager:api_debug_stats': 'get_memory_state',
    'model_manager:api_cleaner_status': 'get_memory_state',
    'model_manager:api_services': 'get_memory_state',
    'model_manager:api_service_control': 'control_service',
    'model_manager:api_disk_space': 'get_disk_space',
    'model_manager:api_check_disk_space': 'get_disk_space',
    'model_manager:api_catalog_stats': 'get_model_catalog_state',
    'model_manager:api_sync_logs': 'get_model_catalog_state',
    'model_manager:api_diagnose_models': 'get_model_catalog_state',
    'model_manager:api_models_list': 'get_model_catalog_state',
    'model_manager:api_watcher_status': 'get_model_catalog_state',
    'model_manager:api_backup_status': 'get_backup_state',
    'model_manager:api_backup_list': 'get_backup_state',
    'model_manager:api_backup_models_progress': 'get_backup_state',
    'model_manager:api_backup_media_progress': 'get_backup_state',
    'model_manager:api_prospect_assess_progress': 'get_model_evaluation_progress',
    'model_manager:api_sync_benchmarks_progress': 'get_model_evaluation_progress',
    'model_manager:api_manifest_proposals': 'list_model_proposals',
    'model_manager:api_model_options': 'list_model_choices',
    'model_manager:api_unload_model': 'free_memory',
    'model_manager:api_unload_model_by_id': 'free_memory',
    'model_manager:api_cleanup_idle': 'free_memory',
    'model_manager:api_aggressive_cleanup': 'free_memory',
    'model_manager:api_clear_gpu': 'free_memory',
    'model_manager:api_clear_gpu_cache': 'free_memory',
    'model_manager:api_force_gc': 'free_memory',
    'model_manager:api_vram_grant': 'free_gpu_for_item',
    'model_manager:api_cleaner_start': 'control_memory_cleaner',
    'model_manager:api_cleaner_stop': 'control_memory_cleaner',
    'model_manager:api_cleaner_configure': 'control_memory_cleaner',
    'model_manager:api_watcher_control': 'control_model_watcher',
    'model_manager:api_backup_db': 'start_backup',
    'model_manager:api_backup_models_start': 'start_backup',
    'model_manager:api_backup_media_start': 'start_backup',
    'model_manager:api_backup_model': 'start_backup',
    'model_manager:api_sync_models': 'sync_model_catalog',
    'model_manager:api_prospect_assess': 'assess_proposed_models',
    'model_manager:api_sync_benchmarks': 'sync_model_benchmarks',
    'model_manager:api_prospect_reject': 'reject_proposed_model',
    'model_manager:api_model_uninstall': 'uninstall_model',
    'model_manager:api_model_task_limit': 'set_model_task_limit',
    'model_manager:api_manifest_proposal_decide': 'decide_model_proposal',
}
#: Action routes without a tool. The value of the measure ; LOWER it in the commit that adds a tool.
#: Measured on 2026-11-08 when this guard was written : 208 (221 action routes, 13 mapped ; the
#: twins' routes folded onto their source's). Some of them are already done by an existing tool and
#: only lack their line here — map them first. 208 → 162 on 2026-11-09 : the whole model manager.
ROUTES_WITHOUT_TOOL_BUDGET = 162


def action_routes() -> dict:
    """`{route key: view}` of every action route — a path with an `api/` segment — outside the API's
    own surfaces. The key is `<namespace>:<name>` (the name alone, or the path, without them).

    A TWIN's routes fold onto its source's (`generated_from`) : its tools derive from the source's
    (`_register_twin_creators`), and the sandbox is not versioned — counted apart, the budget would
    depend on the installation (measured on 2026-11-08 : 212 in the tree, 208 on HEAD)."""
    from django.urls import URLPattern, URLResolver, get_resolver

    from wama.common.app_registry import APP_CATALOG

    def source_of(namespace):
        head, _, rest = namespace.partition(':')
        head = (APP_CATALOG.get(head) or {}).get('generated_from') or head
        return ':'.join(filter(None, (head, rest)))

    def walk(resolver, prefix, namespace):
        for p in resolver.url_patterns:
            if isinstance(p, URLResolver):
                yield from walk(p, prefix + str(p.pattern),
                                ':'.join(filter(None, (namespace, p.namespace))))
            elif isinstance(p, URLPattern):
                yield namespace, prefix + str(p.pattern), p.name, p.callback

    routes = {}
    for namespace, path, name, view in walk(get_resolver(), '', ''):
        if '/api/' not in '/' + path or namespace.split(':')[0] in API_SURFACE_NAMESPACES:
            continue
        if view.__module__ in API_SURFACE_MODULES or (not namespace and name in ASSISTANT_CHANNEL_ROUTES):
            continue
        routes[':'.join(filter(None, (source_of(namespace), name))) or path] = view
    return routes


def factory_gestures(path: str, function: str) -> set:
    """The keys of the dict a view factory RETURNS — its gestures, read in its source."""
    tree = ast.parse((Path(settings.BASE_DIR) / path).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            returned = [n.value for n in node.body if isinstance(n, ast.Return)]
            value = returned[-1] if returned else None
            if isinstance(value, ast.Name):      # `views = {...}` … `return views`
                value = next((n.value for n in node.body if isinstance(n, ast.Assign)
                              and any(getattr(t, 'id', None) == value.id for t in n.targets)), None)
            if isinstance(value, ast.Dict):
                return {k.value for k in value.keys if isinstance(k, ast.Constant)}
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

    def test_the_new_card_and_batch_tools_are_cross_app_and_state_their_effect(self):
        effects = {'stop_item': 'write', 'update_item_settings': 'write', 'launch_batch': 'write',
                   'update_batch_settings': 'write', 'duplicate_batch': 'write',
                   'delete_batch': 'destroy', 'get_batch_state': 'read', 'get_batch_result': 'read'}
        for name, effect in effects.items():
            with self.subTest(tool=name):
                self.assertIsNone(T.app_id_for_tool(name), 'transverse : gardé dans son corps')
                self.assertIsNone(T.tool_role(name), 'never taken for a triad tool')
                self.assertEqual(effect, T.effect_of(name)['effect'])


class EveryActionRouteHasItsToolTest(SimpleTestCase):

    def test_every_mapped_route_exists_and_so_does_its_tool(self):
        routes = action_routes()
        for route, tool in ROUTE_TOOLS.items():
            with self.subTest(route=route):
                self.assertIn(route, routes, 'route renommée ou retirée : corriger ROUTE_TOOLS')
                self.assertIn(tool, T.TOOL_REGISTRY)

    def test_the_budget_of_routes_without_tool_is_exact(self):
        """It FAILS when it keeps a margin too : a margin is a permission to add a route without
        its tool. A new route gets its tool (`/api-outils`) and its line in ROUTE_TOOLS."""
        without = sorted(set(action_routes()) - set(ROUTE_TOOLS))
        self.assertEqual(ROUTES_WITHOUT_TOOL_BUDGET, len(without), without)

    def test_the_format_tools_share_the_page_bodies_and_stay_with_developers(self):
        """The routes and the tools read ONE body each (`format_converter`), and a simple user is
        refused by the tools as by the routes (`is_admin_or_dev`)."""
        from wama.model_manager.services import format_converter as F
        with mock.patch.object(F, 'convert_and_backup', return_value={'success': True}) as body, \
                mock.patch.object(T, '_unknown_model_key', return_value=None):
            dev = mock.Mock()
            with mock.patch('wama.accounts.permissions.can_manage_registries', return_value=True):
                self.assertEqual({'success': True}, T.convert_model_format(dev, 'reader:x', 'onnx'))
            body.assert_called_once_with('reader:x', 'onnx', backup_after=True,
                                         delete_source_after_backup=False)
        with mock.patch('wama.accounts.permissions.can_manage_registries', return_value=False):
            for call in (lambda u: T.get_model_formats(u), lambda u: T.convert_model_format(u, 'k')):
                self.assertEqual('forbidden', call(mock.Mock())['error'])
        for name, effect in (('get_model_formats', 'read'), ('convert_model_format', 'write')):
            self.assertEqual(effect, T.effect_of(name)['effect'])


class FormatToolsRefuseAnUnknownKeyTest(TestCase):

    def test_an_unknown_key_is_refused_before_any_disk_discovery(self):
        """A key the catalogue does not carry is refused at once : the resolution's fallback is the
        full disk discovery (2.5 min measured on 2026-11-08 for a mistyped key)."""
        from wama.model_manager.services import format_converter as F
        with mock.patch('wama.accounts.permissions.can_manage_registries', return_value=True), \
                mock.patch.object(F, 'resolve_weight_file') as resolve:
            for call in (lambda: T.get_model_formats(mock.Mock(), 'nope:none'),
                         lambda: T.convert_model_format(mock.Mock(), 'nope:none', 'onnx')):
                self.assertIn('Aucun modèle', call()['error'])
            resolve.assert_not_called()


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


class BatchToolsTest(TestCase):
    """The gestures of a batch through their tools — by the view the button posts, on a real app
    (the transcriber : its batch is linked by a row model), and on another user's batch : nothing."""

    def setUp(self):
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.common.utils.preview_registry import PreviewRegistry
        self.me = _account('batch_me', role='recherche')
        self.other = _account('batch_other', role='recherche')
        self.model = PreviewRegistry.get_model('transcriber')
        self.batch, self.items = _lot_de(self.model, self.me, 2)
        self.theirs, _ = _lot_de(self.model, self.other, 1)

    def test_state_and_result_read_the_batch(self):
        state = T.execute_tool('get_batch_state', {'app': 'transcriber', 'batch_id': self.batch.pk},
                               self.me)
        self.assertEqual((2, sorted(i.pk for i in self.items)),
                         (state['total'], sorted(r['id'] for r in state['items'])))
        result = T.get_batch_result(self.me, 'transcriber', self.batch.pk)
        self.assertEqual(('', "Aucun résultat à télécharger pour l'instant."),
                         (result['download_url'], result.get('message')))

    def test_realign_without_reference_says_so_and_one_gesture_at_a_time(self):
        out = T.update_batch_settings(self.me, 'transcriber', self.batch.pk, realign=True)
        self.assertIn('référence', out['error'])
        self.assertIn('error', T.update_batch_settings(self.me, 'transcriber', self.batch.pk))
        self.assertIn('error', T.update_batch_settings(self.me, 'transcriber', self.batch.pk,
                                                       realign=True, promote_from=self.items[0].pk))

    def test_duplicate_then_delete_with_confirmation(self):
        batch_model = type(self.batch)
        copy = T.execute_tool('duplicate_batch', {'app': 'transcriber', 'batch_id': self.batch.pk},
                              self.me)
        self.assertTrue(copy.get('duplicated'), copy)
        self.assertIn('error', T.delete_batch(self.me, 'transcriber', copy['new_id']))
        self.assertTrue(batch_model.objects.filter(pk=copy['new_id']).exists(), 'not confirmed')
        self.assertTrue(T.delete_batch(self.me, 'transcriber', copy['new_id'], confirm=True)['deleted'])
        self.assertFalse(batch_model.objects.filter(pk=copy['new_id']).exists())

    @mock.patch('celery.app.task.Task.apply_async', return_value=mock.Mock(id='no-task'))
    def test_launch_starts_its_items(self, _no_task):
        out = T.launch_batch(self.me, 'transcriber', self.batch.pk)
        self.assertTrue(out.get('started'), out)

    def test_another_users_batch_is_out_of_reach(self):
        for out in (T.get_batch_state(self.me, 'transcriber', self.theirs.pk),
                    T.delete_batch(self.me, 'transcriber', self.theirs.pk, confirm=True),
                    T.launch_batch(self.me, 'transcriber', self.theirs.pk)):
            self.assertIn('error', out)
        self.assertTrue(type(self.theirs).objects.filter(pk=self.theirs.pk).exists())

    def test_an_app_closed_to_the_account_rejects_its_batch_writes(self):
        """The app guard of a batch WRITE (`_batch_write_refusal`) : the view alone would let the
        owner act, whatever the app's policy — a cycle verb is gated in its body."""
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        closed = _account('batch_closed')                        # no role : the transcriber is closed
        batch, _ = _lot_de(self.model, closed, 1)
        self.assertEqual('forbidden', T.delete_batch(closed, 'transcriber', batch.pk,
                                                     confirm=True).get('error'))
        self.assertTrue(type(batch).objects.filter(pk=batch.pk).exists())

    def test_an_app_without_batches_says_so(self):
        self.assertIn('error', T.get_batch_state(self.me, 'nosuchapp', 1))


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


# ── The model manager's gestures (2026-11-09) ────────────────────────────────────────────────────

#: Each route of the model manager's page → the tool call that must reach its view. Read against
#: ROUTE_TOOLS both ways : a route mapped to one of these tools without a call here fails.
VIEW_CALLS = {
    'model_manager:api_memory_stats': ('get_memory_state', {}),
    'model_manager:api_memory_detailed': ('get_memory_state', {'view': 'detailed'}),
    'model_manager:api_tracked_models': ('get_memory_state', {'view': 'resident'}),
    'model_manager:api_idle_models': ('get_memory_state', {'view': 'idle'}),
    'model_manager:api_large_objects': ('get_memory_state', {'view': 'large_objects'}),
    'model_manager:api_memory_snapshot': ('get_memory_state', {'view': 'snapshot'}),
    'model_manager:api_debug_stats': ('get_memory_state', {'view': 'raw'}),
    'model_manager:api_cleaner_status': ('get_memory_state', {'view': 'cleaner'}),
    'model_manager:api_services': ('get_memory_state', {'view': 'services'}),
    'model_manager:api_service_control': ('control_service', {'service': 'tts_service', 'action': 'start'}),
    'model_manager:api_disk_space': ('get_disk_space', {}),
    'model_manager:api_check_disk_space': ('get_disk_space', {'required_gb': 12}),
    'model_manager:api_catalog_stats': ('get_model_catalog_state', {}),
    'model_manager:api_sync_logs': ('get_model_catalog_state', {'view': 'sync_logs'}),
    'model_manager:api_diagnose_models': ('get_model_catalog_state', {'view': 'diagnose'}),
    'model_manager:api_models_list': ('get_model_catalog_state', {'view': 'discovered'}),
    'model_manager:api_watcher_status': ('get_model_catalog_state', {'view': 'watcher'}),
    'model_manager:api_backup_status': ('get_backup_state', {}),
    'model_manager:api_backup_list': ('get_backup_state', {'view': 'list'}),
    'model_manager:api_backup_models_progress': ('get_backup_state', {'view': 'models_mirror'}),
    'model_manager:api_backup_media_progress': ('get_backup_state', {'view': 'media_mirror'}),
    'model_manager:api_prospect_assess_progress': ('get_model_evaluation_progress', {}),
    'model_manager:api_sync_benchmarks_progress': ('get_model_evaluation_progress',
                                                   {'kind': 'benchmarks'}),
    'model_manager:api_manifest_proposals': ('list_model_proposals', {}),
    'model_manager:api_model_options': ('list_model_choices', {'task': 'text-to-speech'}),
    'model_manager:api_unload_model': ('free_memory', {'action': 'unload', 'model_key': 'a:b',
                                                       'confirm': True}),
    'model_manager:api_cleanup_idle': ('free_memory', {'action': 'idle'}),
    'model_manager:api_aggressive_cleanup': ('free_memory', {'action': 'all', 'confirm': True}),
    'model_manager:api_clear_gpu': ('free_memory', {'action': 'gpu', 'confirm': True}),
    'model_manager:api_clear_gpu_cache': ('free_memory', {'action': 'gpu_cache'}),
    'model_manager:api_force_gc': ('free_memory', {'action': 'gc'}),
    'model_manager:api_vram_grant': ('free_gpu_for_item', {'app': 'imager', 'item_id': 1,
                                                           'confirm': True}),
    'model_manager:api_cleaner_start': ('control_memory_cleaner', {'action': 'start'}),
    'model_manager:api_cleaner_stop': ('control_memory_cleaner', {'action': 'stop'}),
    'model_manager:api_cleaner_configure': ('control_memory_cleaner',
                                            {'action': 'configure', 'idle_threshold_s': 600}),
    'model_manager:api_watcher_control': ('control_model_watcher', {'action': 'stop'}),
    'model_manager:api_backup_db': ('start_backup', {'target': 'database', 'confirm': True}),
    'model_manager:api_backup_models_start': ('start_backup', {'target': 'models', 'confirm': True}),
    'model_manager:api_backup_media_start': ('start_backup', {'target': 'media', 'confirm': True}),
    'model_manager:api_backup_model': ('start_backup', {'target': 'model', 'model_key': 'a:b',
                                                        'confirm': True}),
    'model_manager:api_sync_models': ('sync_model_catalog', {}),
    'model_manager:api_prospect_assess': ('assess_proposed_models', {'confirm': True}),
    'model_manager:api_sync_benchmarks': ('sync_model_benchmarks', {}),
    'model_manager:api_prospect_reject': ('reject_proposed_model', {'model_key': 'a:b',
                                                                    'confirm': True}),
    'model_manager:api_model_uninstall': ('uninstall_model', {'model_key': 'a:b', 'confirm': True}),
    'model_manager:api_model_task_limit': ('set_model_task_limit', {'model_key': 'a:b',
                                                                    'minutes': 90}),
    'model_manager:api_manifest_proposal_decide': ('decide_model_proposal',
                                                   {'decision': 'reject', 'file': 'backend_x.json',
                                                    'confirm': True}),
}
#: The tools that post a view of the page. The route `api_unload_model_by_id` shares the unload
#: body : the tool posts `api_unload_model`, the page's « Décharger ».
MODEL_MANAGER_VIEW_TOOLS = {tool for tool, _args in VIEW_CALLS.values()}
VIEW_ROUTE_ALIASES = {'model_manager:api_unload_model_by_id': 'model_manager:api_unload_model'}


def allowed_methods(view) -> set:
    """The HTTP methods a view accepts, read from its `require_http_methods` wrapper — the list it
    closes over, reached through the `__wrapped__` chain of the decorators."""
    while view is not None:
        for cell in (getattr(view, '__closure__', None) or ()):
            value = cell.cell_contents
            if isinstance(value, (list, tuple)) and value and all(
                    isinstance(m, str) and m.isupper() for m in value):
                return set(value)
        view = getattr(view, '__wrapped__', None)
    return set()


class EveryToolDescriptionIsAWholeSentenceTest(SimpleTestCase):
    """What the model reads of a tool (the prompt's list, the MCP server) is its docstring's first
    PARAGRAPH (`_doc_summary`). It was the first physical LINE until 2026-11-09 : docstrings wrap at
    100 columns, and 44 tools of 144 showed the model a sentence cut in the middle."""

    def test_each_description_ends_as_a_sentence_and_holds_no_section(self):
        for name, meta in T.tool_descriptions().items():
            text = meta['description']
            with self.subTest(tool=name):
                self.assertTrue(text and text[-1] in '.!?)»`"\'', text[-80:])
                self.assertNotRegex(text, r'\b(Args|Returns):')

    def test_the_summary_stops_at_the_first_blank_line_or_section(self):
        def tool():
            """First line of a sentence
            that goes on.

            Second paragraph.
            """
        def packed():
            """One sentence.
            Args:
                x: y.
            """
        self.assertEqual('First line of a sentence that goes on.', T._doc_summary(tool))
        self.assertEqual('One sentence.', T._doc_summary(packed))


class ModelManagerToolsReachTheirViewTest(SimpleTestCase):
    """Each tool posts THE view of the page's button — the route ROUTE_TOOLS names, with the method
    that view accepts, a JSON body for a POST (the views read `request.body`)."""

    def _reached(self, tool, args):
        calls = []

        def fake_call_view(user, view, args_=(), kwargs=None, **kw):
            calls.append((view, kw))
            return 200, {'success': True}
        with mock.patch.object(T, '_call_view', side_effect=fake_call_view), \
                mock.patch.object(T, '_unknown_model_key', return_value=None), \
                mock.patch.object(T, '_refus_app', return_value=None), \
                mock.patch('wama.accounts.permissions.can_manage_registries', return_value=True), \
                mock.patch('wama.accounts.permissions.is_admin_tier', return_value=True):
            out = getattr(T, tool)(mock.Mock(is_authenticated=True), **args)
        return out, calls

    def test_every_call_reaches_its_route_with_the_method_the_view_accepts(self):
        from django.urls import resolve, reverse
        for route, (tool, args) in VIEW_CALLS.items():
            with self.subTest(route=route):
                self.assertEqual(tool, ROUTE_TOOLS.get(route), 'VIEW_CALLS and ROUTE_TOOLS disagree')
                out, calls = self._reached(tool, args)
                self.assertNotIn('error', out, out)
                self.assertEqual(1, len(calls), calls)
                view, kw = calls[0]
                self.assertIs(resolve(reverse(route)).func, view)
                method = kw.get('method', 'post').upper()
                self.assertIn(method, allowed_methods(view))
                self.assertEqual(method == 'POST', kw.get('json_body'))

    def test_every_route_of_these_tools_has_its_call(self):
        for route, tool in ROUTE_TOOLS.items():
            if tool in MODEL_MANAGER_VIEW_TOOLS:
                with self.subTest(route=route):
                    self.assertIn(VIEW_ROUTE_ALIASES.get(route, route), VIEW_CALLS)

    def test_a_simple_user_is_refused_every_management_tool(self):
        with mock.patch('wama.accounts.permissions.can_manage_registries', return_value=False), \
                mock.patch.object(T, '_call_view') as reached:
            for route, (tool, args) in VIEW_CALLS.items():
                if T.TOOL_APP_OVERRIDE.get(tool) != 'registries':
                    continue
                with self.subTest(tool=tool):
                    self.assertEqual('forbidden', getattr(T, tool)(mock.Mock(), **args).get('error'))
            reached.assert_not_called()

    def test_a_gesture_the_page_confirms_is_refused_without_the_agreement(self):
        for route, (tool, args) in VIEW_CALLS.items():
            if not args.get('confirm'):
                continue
            with self.subTest(route=route):
                out, calls = self._reached(tool, {**args, 'confirm': False})
                self.assertIn('confirm=true', out.get('error', ''))
                self.assertEqual([], calls)

    def test_the_effects_are_declared(self):
        reads = {'get_memory_state', 'get_disk_space', 'get_model_catalog_state', 'get_backup_state',
                 'get_model_evaluation_progress', 'list_model_proposals', 'list_model_choices'}
        destroys = {'reject_proposed_model', 'uninstall_model'}
        for tool in MODEL_MANAGER_VIEW_TOOLS:
            with self.subTest(tool=tool):
                expected = 'read' if tool in reads else 'destroy' if tool in destroys else 'write'
                self.assertEqual(expected, T.effect_of(tool)['effect'])


class ModelManagerToolsOnTheRealViewsTest(TestCase):
    """The tools through the REAL views, their bodies stubbed at the service seam."""

    def setUp(self):
        self.admin = _account('mm_tools_admin', 'admin')
        self.dev = _account('mm_tools_dev', 'developpeur')
        self.user = _account('mm_tools_user')

    def test_a_proposal_is_decided_by_an_administrator_only_and_said_before_the_agreement(self):
        import wama.common.services.backend_proposals as B
        with mock.patch.object(B, 'reject', return_value=True) as reject:
            refused = T.decide_model_proposal(self.dev, 'reject', file='backend_x.json')
            self.assertEqual('forbidden', refused.get('error'), 'a developer proposes, never decides')
            asked = T.decide_model_proposal(self.admin, 'reject', file='backend_x.json')
            self.assertIn('confirm=true', asked['error'])
            reject.assert_not_called()
            done = T.decide_model_proposal(self.admin, 'reject', file='backend_x.json', confirm=True)
        self.assertEqual({'success': True}, done)
        reject.assert_called_once_with('backend_x.json', self.admin)

    def test_shared_weights_ask_a_second_agreement_with_what_they_carry(self):
        from wama.model_manager.services import model_installer
        sharing = {'ok': False, 'needs_confirmation': True, 'error': 'poids partagés',
                   'sharing': ['reader:x'], 'dependents': []}
        with mock.patch.object(T, '_unknown_model_key', return_value=None), \
                mock.patch.object(model_installer, 'uninstall_model', return_value=sharing) as body:
            out = T.uninstall_model(self.dev, 'reader:y', confirm=True)
        self.assertEqual((True, ['reader:x']), (out['needs_confirmation'], out['sharing']))
        body.assert_called_once_with('reader:y', include_shared=False, via='model_manager',
                                     withdraw=True)

    def test_free_gpu_for_an_item_of_someone_else_is_refused(self):
        from wama.common.services import resource_governor
        from wama.imager.models import ImageGeneration
        owner = _account('mm_tools_owner', role='communication')
        stranger = _account('mm_tools_stranger', role='communication')
        item = ImageGeneration.objects.create(user=owner, prompt='a cat')
        with mock.patch.object(resource_governor, 'grant_release', return_value=True) as grant:
            self.assertIn('error', T.free_gpu_for_item(stranger, 'imager', item.pk, confirm=True))
            grant.assert_not_called()
            out = T.free_gpu_for_item(owner, 'imager', item.pk, confirm=True)
        self.assertTrue(out.get('success'), out)
        grant.assert_called_once_with('imager', item.pk, user_id=owner.pk)

    def test_the_model_choices_are_open_to_any_account_but_not_to_a_visitor(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertIn('error', T.list_model_choices(AnonymousUser(), task='text-to-speech'))
        with mock.patch('wama.model_manager.services.get_registry_models',
                        return_value=([('m', 'M')], [])):
            out = T.list_model_choices(self.user, task='text-to-speech')
        self.assertNotIn('error', out, out)

    def test_the_cleanup_buttons_unload_in_every_process(self):
        """« Clean Idle », « Aggressive » and « Clear GPU » — human gestures — reach the models of
        the workers through the tenants' channel ; from gunicorn they unloaded none (2026-11-09)."""
        from wama.common.services import resource_governor as gov
        idle = [{'model_key': 'reader:ocr', 'vram_gb': 2.0, 'idle_seconds': 900,
                 'idle_minutes': 15, 'jamais_utilise': False, 'owner': 'x'}]
        stats = {'cpu_info': None, 'gpu_info': None, 'system_info': None}
        # The test process never touches the card : CUDA is said absent, the monitor stubbed.
        with mock.patch('torch.cuda.is_available', return_value=False), \
                mock.patch('wama.model_manager.views.SystemMonitor.get_model_manager_stats',
                           return_value=stats), \
                mock.patch.object(gov, 'idle_models', return_value=idle), \
                mock.patch.object(gov, 'resident_models', return_value={'reader:ocr': 2.0}), \
                mock.patch.object(gov, 'unload_resident', return_value=(True, 'ok')) as channel:
            for args in ({'action': 'idle'}, {'action': 'all', 'confirm': True},
                         {'action': 'gpu', 'confirm': True}):
                with self.subTest(**args):
                    channel.reset_mock()
                    self.assertNotIn('error', T.free_memory(self.dev, **args))
                    channel.assert_called_with('reader:ocr')

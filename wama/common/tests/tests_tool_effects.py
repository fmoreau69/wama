"""
Chaque outil de l'assistant DÉCLARE son effet sur sa fonction (`tool_api.tool_effect`,
`WAMA_HARNESS §9` chantier 2 — sa moitié déclarative, 2026-10-28).

POURQUOI. Les sous-agents de l'assistant seront en LECTURE SEULE (décision de Fabien du 28/10) :
il faut donc savoir, pour chaque outil, s'il lit, écrit ou détruit. Le dire dans une table à côté
du registre recréerait la coexistence de l'écart 5 ; le dire sur la fonction fait qu'un outil ne
peut pas exister sans dire sa nature — À CONDITION qu'un contrôle refuse l'outil muet. C'est ce
fichier. *Une règle qui demande de s'en souvenir n'est pas un contrôle.*

CE QUE CETTE GARDE TIENT :
  1. tout outil du registre — triade générée et jumelles du bac à sable comprises — porte un effet ;
  2. un outil déclaré LECTURE n'écrit pas dans son propre corps ni dans les fonctions du même
     fichier qu'il appelle (filet par AST : il ne voit pas une écriture faite dans un autre
     module, d'où le 1) ; et tout outil qui POSTe la vue d'une app est une écriture ;
  3. les outils d'un sous-agent DÉRIVENT des marques : les lectures, moins les exclusions
     déclarées avec leur raison ;
  4. le serveur MCP publie l'effet en annotations (`readOnlyHint` / `destructiveHint`).
"""
import ast
import inspect

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from wama import tool_api
from wama.tool_api import (
    DESTROY, READ, TOOL_REGISTRY, WRITE, effect_of, sub_agent_tools, tool_effect,
)

#: Ce qui, appelé dans un corps, ÉCRIT : la base, une tâche, la vue d'une app, la mémoire, une
#: installation. `update` n'y est pas — c'est aussi le verbe d'un dict.
WRITE_CALLS = {'save', 'delete', 'create', 'bulk_create', 'get_or_create', 'update_or_create',
               'delay', 'apply_async', 'send_task', '_poster_vue', '_refus_app', 'remember',
               'request_install', 'install_from_spec'}
#: Le passage OBLIGÉ des écritures dans les apps (`tool_api`, bloc « VERBES DE CYCLE »).
APP_WRITE_GATES = {'_poster_vue', '_refus_app'}


def _effect(name):
    """L'effet d'un outil, None s'il n'en déclare pas — le test dédié le nomme."""
    return (effect_of(name) or {}).get('effect')


def _module_functions():
    tree = ast.parse(inspect.getsource(tool_api))
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _calls(node):
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', None)
            if name:
                names.add(name)
    return names


def _reached_calls(name, functions, seen=None):
    """Les appels d'une fonction et des fonctions du MÊME fichier qu'elle appelle."""
    seen = seen if seen is not None else set()
    if name in seen or name not in functions:
        return set()
    seen.add(name)
    calls = _calls(functions[name])
    for callee in calls & functions.keys():
        calls |= _reached_calls(callee, functions, seen)
    return calls


class ToolEffectMarkTest(SimpleTestCase):

    def test_every_registered_tool_names_its_effect(self):
        silent = sorted(name for name in TOOL_REGISTRY if effect_of(name) is None)
        self.assertEqual([], silent, "outil sans effet déclaré : poser @tool_effect(...) "
                                     "sur sa fonction (tool_api, bloc « EFFET d'un outil »)")

    def test_the_generated_triad_names_its_effect_too(self):
        self.assertEqual(WRITE, effect_of('start_transcriber')['effect'])
        self.assertEqual(READ, effect_of('get_transcriber_status')['effect'])

    def test_a_tool_declared_read_writes_nothing_it_can_be_seen_to(self):
        functions = _module_functions()
        offenders = {}
        for name, fn in TOOL_REGISTRY.items():
            if _effect(name) != READ or fn.__name__ not in functions:
                continue            # la triade est construite par fabrique, marquée là
            found = _reached_calls(fn.__name__, functions) & WRITE_CALLS
            if found:
                offenders[name] = sorted(found)
        self.assertEqual({}, offenders)

    def test_a_tool_that_posts_to_an_app_is_a_write(self):
        functions = _module_functions()
        wrong = sorted(name for name, fn in TOOL_REGISTRY.items()
                       if fn.__name__ in functions
                       and _reached_calls(fn.__name__, functions) & APP_WRITE_GATES
                       and _effect(name) == READ)
        self.assertEqual([], wrong)

    def test_the_mark_rejects_an_unknown_effect_and_an_unexplained_exclusion(self):
        with self.assertRaises(ValueError):
            tool_effect('maybe')
        with self.assertRaises(ValueError):
            tool_effect(READ, sub_agent=False)


class SubAgentToolsTest(SimpleTestCase):

    def test_only_reads_and_never_a_write(self):
        tools = sub_agent_tools()
        self.assertTrue(tools)
        self.assertEqual({READ}, {_effect(name) for name in tools})
        for name in ('delete_item', 'clear_my_queue', 'add_to_transcriber', 'start_transcriber',
                     'install_model', 'remember_fact'):
            self.assertNotIn(name, tools)

    def test_the_declared_exclusions_are_out_and_say_why(self):
        tools = sub_agent_tools()
        excluded = {name: effect_of(name) for name in TOOL_REGISTRY
                    if _effect(name) == READ and not effect_of(name)['sub_agent']}
        self.assertTrue({'ask_claude_code', 'open_page', 'fold_side_panels'} <= excluded.keys())
        for name, effect in excluded.items():
            self.assertNotIn(name, tools)
            self.assertTrue(effect['reason'], name)

    def test_a_plain_read_is_in(self):
        for name in ('list_my_items', 'get_item_detail', 'search_docs', 'get_transcriber_status'):
            self.assertIn(name, sub_agent_tools())


class McpAnnotationsTest(TestCase):

    def test_the_mcp_listing_carries_the_effect(self):
        from wama.common.services.mcp_server import tools_for
        admin = User.objects.create_superuser('effects_admin', 'effects@example.org', 'x')
        annotations = {t.name: t.annotations for t in tools_for(admin)}
        self.assertTrue(annotations['list_my_items'].readOnlyHint)
        self.assertFalse(annotations['list_my_items'].destructiveHint)
        self.assertFalse(annotations['add_to_transcriber'].readOnlyHint)
        self.assertFalse(annotations['add_to_transcriber'].destructiveHint)
        self.assertTrue(annotations['delete_item'].destructiveHint)
        self.assertEqual(DESTROY, effect_of('clear_my_queue')['effect'])

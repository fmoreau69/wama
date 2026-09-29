"""
L'assistant, CLIENT MCP de la surface de développement (2026-09-22, ROADMAP §8d Phase 3 étape 5,
moitié dev — demande de Fabien : améliorer WAMA depuis l'assistant, admins et devs seulement).

⚠ CE QUE CES GARDES PROTÈGENT :
  1. un non-développeur ne se voit annoncer AUCUN outil de dev, et aucune connexion n'est ouverte
     pour lui ;
  2. un développeur les voit dans son prompt, et un appel `dev_*` est RELAYÉ à la surface dev par
     le protocole réel (session en mémoire sur le vrai serveur), jamais exécuté en local ;
  3. une surface dev injoignable laisse l'assistant répondre ;
  4. §16 : le moteur de l'assistant n'importe toujours pas `dev_tools` (process neuf).
"""
import subprocess
import sys
from unittest import mock

import anyio
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase

from wama.common.services import assistant_engine, mcp_client, mcp_server


def _in_memory_run(user, action):
    """Remplace `mcp_client._run` : session client réelle, sur le VRAI serveur de la surface dev,
    en mémoire (même idiome que `tests_mcp_server`)."""
    async def main():
        from mcp.shared.memory import create_connected_server_and_client_session
        server = mcp_server.build_server(fixed_user=user, surface=mcp_server.SURFACE_DEV)
        async with create_connected_server_and_client_session(server) as session:
            return await action(session)
    return anyio.run(main)


async def _inline(fn):
    return fn()


class DevToolsThroughTheAssistantTest(TestCase):

    def setUp(self):
        import os
        self.ordinary = get_user_model().objects.create_user('mcp_client_ordinary', password='x')
        self.dev = get_user_model().objects.create_user('mcp_client_dev', password='x')
        self.dev.groups.add(Group.objects.get_or_create(name='dev')[0])
        mcp_client._list_cache.clear()
        # ⚠ L'ORM sous `anyio.run` ouvre une AUTRE connexion, qui ne voit pas la transaction du
        # test (mesuré : les groupes du compte y sont vides — piège déjà consigné le 15/09 sur
        # `tests_mcp_server`). Le prédicat est donc remplacé par une comparaison PURE, aux deux
        # bouts (client et serveur, qui l'importent tous deux à l'appel) : c'est le RELAIS qui est
        # gardé ici, le prédicat lui-même l'est par `tests_mcp_dev_tools.PredicatDeveloppeurTest`.
        dev_pk = self.dev.pk
        for patcher in (mock.patch.object(mcp_server, '_run_sync', _inline),
                        mock.patch.dict(os.environ, {'DJANGO_ALLOW_ASYNC_UNSAFE': 'true'}),
                        mock.patch('wama.accounts.permissions.is_developer',
                                   side_effect=lambda u: getattr(u, 'pk', None) == dev_pk)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _turn(self, user, llm):
        with mock.patch.object(assistant_engine, '_llm_call', side_effect=llm):
            return assistant_engine.run_assistant_turn(user, 'liste les jumelles',
                                                       provider='wama-dev-ai', model='x')

    def test_a_non_developer_is_offered_no_dev_tool_and_no_connection_is_opened(self):
        with mock.patch.object(mcp_client, '_run') as connection:
            self.assertEqual([], mcp_client.dev_tools_for(self.ordinary))
            seen = []

            def llm(messages, *a, **k):
                seen.append(messages[0]['content'])
                return 'ok', {'input_tokens': 0, 'output_tokens': 0}
            self._turn(self.ordinary, llm)
        connection.assert_not_called()
        self.assertNotIn('dev_sandbox', seen[0])

    def test_a_developer_sees_the_dev_tools_in_the_prompt(self):
        with mock.patch.object(mcp_client, '_run', side_effect=_in_memory_run):
            tools = mcp_client.dev_tools_for(self.dev)
            seen = []

            def llm(messages, *a, **k):
                seen.append(messages[0]['content'])
                return 'ok', {'input_tokens': 0, 'output_tokens': 0}
            self._turn(self.dev, llm)
        self.assertIn('dev_sandbox', {t['name'] for t in tools})
        self.assertIn('dev_sandbox(action, app, target)', seen[0])
        self.assertIn('never applies it', seen[0])

    def test_a_dev_tool_call_is_relayed_to_the_dev_surface_not_to_the_local_gate(self):
        def llm(messages, *a, **k):
            if len(messages) == 2:
                return ('{"tool": "dev_sandbox", "args": {"action": "list"}}',
                        {'input_tokens': 0, 'output_tokens': 0})
            return 'fait', {'input_tokens': 0, 'output_tokens': 0}
        from wama.common.services import dev_tools
        with mock.patch.object(mcp_client, '_run', side_effect=_in_memory_run), \
             mock.patch.object(dev_tools, 'start_job', return_value={'job_id': 'j-1'}) as launch, \
             mock.patch('wama.tool_api.execute_tool') as gate:
            result = self._turn(self.dev, llm)
        launch.assert_called_once()
        self.assertEqual('sandbox:list', launch.call_args.args[1])
        gate.assert_not_called()
        step, = result['tool_steps']
        self.assertEqual(('dev_sandbox', 'j-1'), (step['tool'], step['result']['job_id']))
        # Un outil de dev fait entrer le tour dans le travail sur le code ; sans modèle de niveau
        # développement au catalogue (cas de ce test), le résultat porte la raison — jamais un
        # repli silencieux (`development_models`).
        self.assertIn('niveau développement', step['result']['warning'])
        self.assertEqual('fait', result['response'])

    def test_a_dev_tool_name_nobody_announced_goes_to_the_gate_which_rejects_it(self):
        """Contre-épreuve : un non-développeur dont le modèle émettrait `dev_sandbox` quand même
        n'atteint jamais la surface dev — le nom part à la porte commune, qui ne le connaît pas."""
        def llm(messages, *a, **k):
            if len(messages) == 2:
                return ('{"tool": "dev_sandbox", "args": {"action": "list"}}',
                        {'input_tokens': 0, 'output_tokens': 0})
            return 'fin', {'input_tokens': 0, 'output_tokens': 0}
        with mock.patch.object(mcp_client, '_run') as connection:
            result = self._turn(self.ordinary, llm)
        connection.assert_not_called()
        self.assertIn('error', result['tool_steps'][0]['result'])

    def test_an_unreachable_dev_surface_leaves_the_assistant_answering(self):
        with mock.patch.object(mcp_client, '_run', side_effect=ConnectionError('refusée')):
            seen = []

            def llm(messages, *a, **k):
                seen.append(messages[0]['content'])
                return 'toujours là', {'input_tokens': 0, 'output_tokens': 0}
            result = self._turn(self.dev, llm)
        self.assertEqual('toujours là', result['response'])
        self.assertNotIn('dev_sandbox', seen[0])
        self.assertIn('injoignable', mcp_client.call_dev_tool(self.dev, 'dev_sandbox', {})['error'])

    def test_the_tool_list_is_cached_per_account(self):
        with mock.patch.object(mcp_client, '_run', side_effect=_in_memory_run) as connection:
            mcp_client.dev_tools_for(self.dev)
            mcp_client.dev_tools_for(self.dev)
        self.assertEqual(1, connection.call_count)


class ProdProcessStaysCleanTest(SimpleTestCase):

    def test_the_engine_and_its_client_never_import_the_dev_tools(self):
        """§16 dans un process NEUF : importer le moteur et le client ne charge pas `dev_tools`."""
        code = ("import django, os, sys; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings'); "
                "django.setup(); import wama.common.services.mcp_client, wama.common.services.assistant_engine; "
                "print('wama.common.services.dev_tools' in sys.modules)")
        out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                             cwd=str(settings.BASE_DIR), timeout=180)
        self.assertEqual(0, out.returncode, out.stderr[-800:])
        self.assertEqual('False', out.stdout.strip().splitlines()[-1])

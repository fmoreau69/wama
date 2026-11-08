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
        from wama.accounts.permissions import set_account_tier
        set_account_tier(self.dev, 'developpeur')
        mcp_client._list_cache.clear()
        mcp_client._unreachable.clear()
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

    def _turn(self, user, llm, **kwargs):
        with mock.patch.object(assistant_engine, '_llm_call', side_effect=llm):
            return assistant_engine.run_assistant_turn(user, 'liste les jumelles',
                                                       provider='wama-dev-ai', model='x', **kwargs)

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
        # `manifest` (2026-10-15) : une app NOUVELLE naît d'un manifeste au bac à sable.
        self.assertIn('dev_sandbox(action, app, target, manifest)', seen[0])
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
             mock.patch('wama.tool_api.execute_tool', return_value={'consigne': 'dev'}) as gate:
            result = self._turn(self.dev, llm)
        launch.assert_called_once()
        self.assertEqual('sandbox:list', launch.call_args.args[1])
        # La porte commune ne voit PAS l'outil de dev — seulement la compétence que la boucle
        # charge après lui (2026-10-30, `_load_dev_competence`).
        self.assertEqual(['charger_competence'], [c.args[0] for c in gate.call_args_list])
        step, loaded = result['tool_steps']
        self.assertEqual(('dev_sandbox', 'j-1'), (step['tool'], step['result']['job_id']))
        self.assertEqual(('charger_competence', 'dev', True),
                         (loaded['tool'], loaded['args']['domaine'], loaded['automatic']))
        # Un outil de dev ne fait plus BASCULER le tour vers un modèle de niveau dev (bridage
        # levé le 2026-10-12) : aucun avertissement n'est greffé au résultat, le tour continue
        # sur son modèle.
        self.assertNotIn('warning', step['result'])
        self.assertEqual('fait', result['response'])

    def test_the_dev_competence_is_loaded_once_and_not_when_already_in_effect(self):
        """Deux outils de dev dans un tour : la compétence n'est chargée qu'une fois. Contre-épreuve :
        un tour déjà dans le domaine de développement ne la recharge pas."""
        calls = iter(['{"tool": "dev_sandbox", "args": {"action": "list"}}',
                      '{"tool": "dev_sandbox", "args": {"action": "list"}}', 'fait'])

        def llm(messages, *a, **k):
            return next(calls), {'input_tokens': 0, 'output_tokens': 0}
        from wama.common.services import dev_tools
        with mock.patch.object(mcp_client, '_run', side_effect=_in_memory_run), \
             mock.patch.object(dev_tools, 'start_job', return_value={'job_id': 'j-1'}), \
             mock.patch('wama.tool_api.execute_tool', return_value={'consigne': 'dev'}):
            result = self._turn(self.dev, llm)
            tools = [s['tool'] for s in result['tool_steps']]
            self.assertEqual(['dev_sandbox', 'charger_competence', 'dev_sandbox'], tools)
            calls = iter(['{"tool": "dev_sandbox", "args": {"action": "list"}}', 'fait'])
            already = self._turn(self.dev, llm, domain='dev')
        self.assertEqual(['dev_sandbox'], [s['tool'] for s in already['tool_steps']])

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

    def test_an_unreachable_dev_surface_is_said_not_taken_for_an_unknown_tool(self):
        """2026-11-07 (fil d'intégration d'ACE-Step) : la surface démarrait avec WAMA, le tour
        perdait ses outils de dev en silence, et le `dev_run_role` du modèle revenait « Outil
        inconnu » de la porte commune. Contre-épreuve : un non-développeur ne reçoit ni la
        ligne ni ce refus — son `dev_*` reste un inconnu de la porte."""
        def llm(messages, *a, **k):
            if len(messages) == 2:
                return ('{"tool": "dev_run_role", "args": {"role": "model"}}',
                        {'input_tokens': 0, 'output_tokens': 0})
            return 'dit', {'input_tokens': 0, 'output_tokens': 0}
        seen = []

        def watching(messages, *a, **k):
            seen.append(messages[0]['content'])
            return llm(messages, *a, **k)
        with mock.patch.object(mcp_client, '_run', side_effect=ConnectionError('refusée')), \
             mock.patch('wama.tool_api.execute_tool', return_value={'error': 'Outil inconnu'}) as gate:
            result = self._turn(self.dev, watching)
            self.assertIn(mcp_client.UNREACHABLE_NOTICE, seen[0])
            self.assertEqual({'error': mcp_client.UNREACHABLE_REFUSAL},
                             result['tool_steps'][0]['result'])
            self.assertNotIn('dev_run_role', [c.args[0] for c in gate.call_args_list])
            seen.clear()
            ordinary = self._turn(self.ordinary, watching)
        self.assertNotIn(mcp_client.UNREACHABLE_NOTICE, seen[0])
        self.assertEqual({'error': 'Outil inconnu'}, ordinary['tool_steps'][0]['result'])

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

"""Every brain reaches WAMA's tools — and the measure that says so (2026-10-23).

Fabien: « Claude Code appelé PAR WAMA : pas de MCP » — the subscription ran its own loop with its
own tools (the repository) and never saw WAMA's. What is held here:
  • the subscription's CLI receives the `wama` surface of the MCP server (`--mcp-config`, the only
    MCP config it reads), for the account, by the same gate (`execute_tool`), its API token carried
    by the environment — never on the command line — and named in `WSLENV` when the CLI is the
    Windows binary (measured: without it the interop drops the variable, the personal subscription
    token included, which silently fell back to the machine's credentials);
  • the profile's exposure choice is judged FIRST (`cloud_refusal`): no surface for a refused account;
  • one rule for a model's catalogue id (`ExternalSource.catalogue_model_id`), read by the native
    tools declaration and by the measure;
  • the measure (`llm_gateway_check --tools`) has three outcomes, and only measured ones conclude;
  • a WAMA relaunch restarts the MCP servers (they survived every relaunch with stale code).
No CLI, no network: `subprocess.run` and the provider calls are stand-ins.
"""
import json
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from wama.common import external_sources
from wama.common.services import claude_code
from wama.common.services.mcp_server import SURFACE_WAMA, TOKEN_ENV

WINDOWS_CLI = '/mnt/c/Users/someone/.local/bin/claude.exe'


def _developer(name='subscriber', policy='cloud_allowed'):
    from wama.accounts.models import UserApiKey
    user = User.objects.create_user(name, password='x', is_superuser=True)
    user.profile.cloud_policy = policy
    user.profile.cloud_hosting_max = 'third_party'   # the subscription is a third-party host
    user.profile.save()
    UserApiKey.objects.create(user=user, source='claude_code', api_key='sk-ant-oat01-personal-token')
    return user


class TheSubscriptionSeesWamaToolsTest(TestCase):

    def _prepare(self, user, cli='claude', **kwargs):
        with mock.patch.object(claude_code, 'chemin_cli', return_value=cli):
            return claude_code.prepare('question', user=user, **kwargs)

    def test_the_cli_receives_the_wama_surface_for_the_account(self):
        from rest_framework.authtoken.models import Token

        from wama.common.services.mcp_client import surface_url
        user = _developer()
        prepared = self._prepare(user)
        argv, env = prepared['argv'], prepared['env']
        self.assertIn('--strict-mcp-config', argv, 'the only MCP config the CLI reads')
        server = json.loads(argv[argv.index('--mcp-config') + 1])['mcpServers']['wama']
        self.assertEqual(('http', surface_url(SURFACE_WAMA)), (server['type'], server['url']))
        self.assertEqual('Bearer ${' + TOKEN_ENV + '}', server['headers']['Authorization'],
                         'the header NAMES the variable')
        self.assertEqual(Token.objects.get(user=user).key, env[TOKEN_ENV], "the account's own token")
        self.assertTrue(all(env[TOKEN_ENV] not in a for a in argv), 'never on the command line')
        allowed = argv[argv.index('--allowedTools') + 1:]
        self.assertEqual(['Read', 'Grep', 'Glob', 'mcp__wama'], allowed)

    def test_writing_adds_the_wama_tools_without_restricting_the_rest(self):
        argv = self._prepare(_developer(), ecriture=True)['argv']
        self.assertEqual(['mcp__wama'], argv[argv.index('--allowedTools') + 1:])

    def test_without_an_account_there_is_no_surface(self):
        prepared = self._prepare(None)
        self.assertNotIn('--mcp-config', prepared['argv'])
        self.assertNotIn(TOKEN_ENV, prepared['env'])

    def test_the_profile_is_judged_before_anything_is_handed_out(self):
        """A « 100 % local » profile is refused — and no API token is even created for it."""
        from rest_framework.authtoken.models import Token
        user = _developer('local-only', policy='local_only')
        self.assertIn('100 % local', self._prepare(user)['error'])
        self.assertFalse(Token.objects.filter(user=user).exists())

    def test_the_windows_cli_gets_its_secrets_through_wslenv(self):
        env = self._prepare(_developer(), cli=WINDOWS_CLI)['env']
        self.assertEqual({'CLAUDE_CODE_OAUTH_TOKEN', TOKEN_ENV}, set(env['WSLENV'].split(':')))
        self.assertEqual('sk-ant-oat01-personal-token', env['CLAUDE_CODE_OAUTH_TOKEN'])
        # Counter-check: a native CLI inherits nothing more, and needs no WSLENV.
        self.assertNotIn('WSLENV', self._prepare(_developer('native'), cli='claude')['env'])
        self.assertNotIn('ANTHROPIC_API_KEY', env, 'never the API key (it would bill the API)')

    def test_a_refused_token_says_what_to_do(self):
        message = claude_code._failure_message(
            1, json.dumps({'result': 'Failed to authenticate. API Error: 401 Invalid bearer token'}), '')
        self.assertIn('claude setup-token', message)
        self.assertNotIn('setup-token', claude_code._failure_message(1, '{"result": "boom"}', ''))


class OneRuleForACatalogueModelIdTest(SimpleTestCase):

    def test_only_the_protocol_prefix_is_removed(self):
        albert = external_sources.get('albert')
        self.assertEqual('gpt-oss-120b', albert.catalogue_model_id('openai/gpt-oss-120b'))
        openrouter = external_sources.get('openrouter')
        self.assertEqual('qwen/qwen3-coder', openrouter.catalogue_model_id('qwen/qwen3-coder'),
                         'part of an OpenRouter id, never cut')

    def test_a_declared_openrouter_model_is_recognised(self):
        """The cut at the last « / » recognised none of them (2026-10-23)."""
        from dataclasses import replace

        from wama.common.services.assistant_engine import _accepts_native_tools
        source = replace(external_sources.get('openrouter'), native_tools=('qwen/qwen3-coder',))
        self.assertTrue(_accepts_native_tools(source, 'qwen/qwen3-coder'))
        self.assertTrue(_accepts_native_tools(external_sources.get('albert'), None),
                        'the default model, written in its LiteLLM form')

    def test_only_the_ilaas_models_measured_three_out_of_three_are_declared(self):
        """Measured on 2026-10-26, once out of maintenance: five models named the tool 3/3 and
        are declared (Fabien's decision). `mistral-medium-latest` answered 503 « busy » 6 times
        out of 7: not measured, so not declared — it keeps the prompt's list."""
        from wama.common.services.assistant_engine import _accepts_native_tools
        ilaas = external_sources.get('ilaas')
        self.assertEqual({'gemma-4-31b', 'llama-3.1-8b', 'mistral-small-4-119b',
                          'qwen-3.6-35b-instruct', 'qwen-3.8-27b'}, set(ilaas.native_tools))
        self.assertTrue(_accepts_native_tools(ilaas, 'openai/qwen-3.8-27b'),
                        'recognised in its LiteLLM form')
        self.assertFalse(_accepts_native_tools(ilaas, 'mistral-medium-latest'))


class TheMeasureConcludesOnlyOnWhatItMeasuredTest(SimpleTestCase):

    def test_three_outcomes(self):
        from wama.common.utils.llm_utils import EMPTY_RESPONSE_ERROR, tool_call_text
        from wama.model_manager.management.commands.llm_gateway_check import probe_outcome
        self.assertEqual('named', probe_outcome(tool_call_text('list_ai_models', '{"limit": 1}'), None)[0])
        self.assertEqual('silent', probe_outcome('Voici les modèles…', None)[0])
        self.assertEqual('silent', probe_outcome(None, EMPTY_RESPONSE_ERROR)[0],
                         'an empty answer is the model speaking, not a failure')
        self.assertEqual('error', probe_outcome(None, 'credit balance is too low')[0])

    def test_errors_never_conclude(self):
        from django.core.management.color import no_style

        from wama.model_manager.management.commands.llm_gateway_check import verdict
        style = no_style()
        self.assertIn('Mesure impossible', verdict(0, 2, 2, style)[0])
        self.assertIn('déclarable', verdict(3, 0, 3, style)[0])
        self.assertIn('refaire la série', verdict(1, 1, 2, style)[0])
        self.assertIn('ne PAS déclarer', verdict(1, 0, 3, style)[0])

    def test_the_probe_answer_is_what_the_tool_returns(self):
        from wama.model_manager.management.commands.llm_gateway_check import probe_answer
        with mock.patch('wama.tool_api.execute_tool',
                        return_value={'models': [{'key': 'albert:bge-m3'}], 'count': 1}):
            self.assertEqual('albert:bge-m3', probe_answer(None))


class TheMeasuredToolListIsTheAssistantsTest(TestCase):

    def test_the_measure_sends_the_list_the_assistant_sends(self):
        from wama.common.services.assistant_engine import _native_tool_specs, native_tool_list
        user = _developer('measurer')
        self.assertEqual(native_tool_list(user), _native_tool_specs(user, 'albert', [], 'gpt-oss-120b'))
        self.assertIsNone(_native_tool_specs(user, 'albert', [], 'deepseek-v4-flash-0731'),
                          'measured mute: not declared')


class ARelaunchRestartsTheMcpServersTest(SimpleTestCase):

    def test_they_are_stopped_with_the_other_services(self):
        script = (Path(settings.BASE_DIR) / 'start_wama_prod.sh').read_text(encoding='utf-8')
        stop = script.index('STOP DES PROCESS EXISTANTS')
        start = script.index('supervise_mcp wama')
        self.assertLess(stop, script.index('pkill -f "manage.py run_[m]cp_server"'), start)

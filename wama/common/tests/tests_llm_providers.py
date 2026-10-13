"""
Fournisseurs compatibles OpenAI dans `llm_chat` — Albert API (DINUM), branchée le 2026-09-15.

⚠ POURQUOI CES GARDES : aucun de ces défauts ne se voit en local. Ils ne se révèlent qu'au
moment où quelqu'un choisit Albert, et alors ils se manifestent comme une erreur DISTANTE
(« modèle inconnu », 401) qui accuse le fournisseur au lieu du code :

  1. **le préfixe `openai/` doit être TOUJOURS posé.** Les identifiants d'Albert portent eux-mêmes
     un « / » (`mistralai/Mistral-Small-…`) ; la règle générale `'/' in model` les prendrait
     pour un préfixe de fournisseur LiteLLM ;
  2. **l'adresse et la clé viennent du registre `external_sources`**, jamais de
     `OPENAI_API_BASE` : global au processus, il détournerait aussi les appels à OpenAI ;
  3. **sans clé, l'appel ne part pas** — et le message nomme la variable à poser.

`litellm` est remplacé par un module factice : on mesure ce qui PART, pas le réseau.
"""
import os
import sys
import types
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from .. import external_sources
from ..utils import llm_utils

MESSAGES = [{'role': 'user', 'content': 'bonjour'}]


def _fake_litellm(text='OK'):
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=text))]
    module = types.ModuleType('litellm')
    module.completion = MagicMock(return_value=response)
    return module


class AlbertRoutageTest(SimpleTestCase):

    def _call(self, env=None, **kwargs):
        """Appelle `llm_chat` avec un `litellm` factice ; rend (résultat, module factice)."""
        fake = _fake_litellm()
        with patch.dict(sys.modules, {'litellm': fake}), patch.dict(os.environ):
            os.environ.pop('ALBERT_API_KEY', None)
            os.environ.pop('ALBERT_API_BASE', None)
            os.environ.update(env or {})
            result = llm_utils.llm_chat(MESSAGES, **kwargs)
        return result, fake

    def test_un_identifiant_a_slash_part_en_openai_avec_l_adresse_et_la_cle_du_registre(self):
        (text, err), fake = self._call(
            env={'ALBERT_API_KEY': 'sk-test'}, provider='albert',
            model='mistralai/Mistral-Small-3.2-24B-Instruct-2506')
        self.assertEqual(('OK', None), (text, err))
        sent = fake.completion.call_args.kwargs
        self.assertEqual('openai/mistralai/Mistral-Small-3.2-24B-Instruct-2506', sent['model'],
                         "sans le préfixe forcé, LiteLLM lirait « mistralai » comme fournisseur")
        self.assertEqual(external_sources.base_url('albert'), sent['api_base'])
        self.assertEqual('sk-test', sent['api_key'])

    def test_sans_cle_l_appel_ne_part_pas_et_nomme_la_variable(self):
        (text, err), fake = self._call(provider='albert', model='x')
        self.assertIsNone(text)
        self.assertIn('ALBERT_API_KEY', err)
        self.assertFalse(fake.completion.called, "un appel sans clé partirait en 401 distant")

    def test_l_adresse_se_surcharge_par_l_environnement(self):
        (_, _), fake = self._call(
            env={'ALBERT_API_KEY': 'k', 'ALBERT_API_BASE': 'https://albert.exemple/v1/'},
            provider='albert', model='x')
        self.assertEqual('https://albert.exemple/v1', fake.completion.call_args.kwargs['api_base'])

    def test_aucune_variable_OPENAI_n_est_posee_dans_l_environnement(self):
        self._call(env={'ALBERT_API_KEY': 'k'}, provider='albert', model='x')
        self.assertNotIn('OPENAI_API_BASE', os.environ)

    @override_settings(ALBERT_MODEL='openai/gpt-oss-120b-test')
    def test_le_modele_par_defaut_vient_du_reglage(self):
        (_, _), fake = self._call(env={'ALBERT_API_KEY': 'k'}, provider='albert')
        self.assertEqual('openai/openai/gpt-oss-120b-test', fake.completion.call_args.kwargs['model'])

    @override_settings(ALBERT_MODEL='')
    def test_without_setting_the_default_model_comes_from_the_registry(self):
        # 2026-10-07 (chantier 5 de WAMA_HARNESS.md) : un fournisseur DÉCLARÉ porte son modèle
        # par défaut au registre ; la table ne garde que les fournisseurs sans source.
        self.assertEqual(external_sources.get('albert').default_model,
                         llm_utils.default_cloud_model('albert'))

    def test_num_predict_None_ne_plafonne_pas_et_la_temperature_est_transmise(self):
        (_, _), fake = self._call(env={'ALBERT_API_KEY': 'k'}, provider='albert', model='x',
                                  num_predict=None, temperature=0.2)
        sent = fake.completion.call_args.kwargs
        self.assertNotIn('max_tokens', sent)
        self.assertEqual(0.2, sent['temperature'])


class AutresFournisseursInchangesTest(SimpleTestCase):
    """Contre-épreuve : la branche OpenAI-compatible ne doit rien changer aux autres."""

    def test_anthropic_garde_son_prefixe_et_ne_recoit_ni_adresse_ni_cle(self):
        fake = _fake_litellm()
        with patch.dict(sys.modules, {'litellm': fake}), patch.dict(os.environ), \
                patch.object(external_sources, 'stored_instance_key', return_value=''):
            os.environ.pop('ANTHROPIC_API_KEY', None)
            llm_utils.llm_chat(MESSAGES, provider='anthropic', model='claude-x')
        sent = fake.completion.call_args.kwargs
        self.assertEqual('anthropic/claude-x', sent['model'])
        self.assertNotIn('api_base', sent)
        self.assertNotIn('api_key', sent)
        self.assertEqual(2048, sent['max_tokens'], "le plafond par défaut d'avant est conservé")
        self.assertNotIn('temperature', sent)


class OpenAICompatibleProvidersAreDerivedTest(SimpleTestCase):
    """2026-10-07 (chantier 5 of WAMA_HARNESS.md, ILaaS): an `llm` source of protocol `openai`
    is routed with its own address and key WITHOUT any table to complete — the hand-written
    `OPENAI_COMPATIBLE_PROVIDERS` made a declared provider missing from it go to OpenAI."""

    def test_every_declared_openai_source_is_routed_and_no_other(self):
        for source in external_sources.SOURCES:
            expected = source.key if (source.kind == 'llm' and source.protocol == 'openai') else ''
            self.assertEqual(expected, llm_utils.openai_compatible_source(source.key), source.key)
        self.assertEqual('', llm_utils.openai_compatible_source('openai'))

    def test_ilaas_leaves_with_its_address_and_its_instance_key(self):
        fake = _fake_litellm()
        with patch.dict(sys.modules, {'litellm': fake}), \
                patch.dict(os.environ, {'ILAAS_API_KEY': 'ilaas-key'}), \
                patch.object(external_sources, 'stored_instance_key', return_value=''):
            text, err = llm_utils.llm_chat(MESSAGES, provider='ilaas')
        self.assertEqual(('OK', None), (text, err))
        sent = fake.completion.call_args.kwargs
        self.assertEqual('openai/' + external_sources.get('ilaas').default_model, sent['model'])
        self.assertEqual(external_sources.base_url('ilaas'), sent['api_base'])
        self.assertEqual('ilaas-key', sent['api_key'])

    def test_a_catalogue_key_of_every_llm_source_routes_to_that_provider_not_local(self):
        from ..services.assistant_engine import SOURCE_PROVIDERS
        for source in external_sources.SOURCES:
            if source.kind == 'llm':
                self.assertNotEqual('wama-dev-ai', SOURCE_PROVIDERS.get(source.key, 'wama-dev-ai'),
                                    f"un modèle `{source.key}:*` partirait sur le moteur LOCAL")


class ProvidersMustBeDeclaredTest(SimpleTestCase):
    """2026-10-11 (chantier 5 of WAMA_HARNESS.md): a remote provider EXISTS if it is in the
    registry, full stop. The six names `llm_chat` used to accept without a source (`openai`,
    `mistral`…) had no « 100 % local » guard, no personal key and no key on the Sources page."""

    def _call(self, provider, env=None, stored='', **kwargs):
        fake = _fake_litellm()
        with patch.dict(sys.modules, {'litellm': fake}), patch.dict(os.environ, env or {}), \
                patch.object(external_sources, 'stored_instance_key', return_value=stored):
            result = llm_utils.llm_chat(MESSAGES, provider=provider, **kwargs)
        return result, fake

    def test_a_provider_without_a_source_is_refused_before_any_call(self):
        for name in ('openai', 'mistral', 'groq', 'gemini', 'grok', 'xai', 'deepseek'):
            (text, err), fake = self._call(name, env={'OPENAI_API_KEY': 'k'}, model='m')
            self.assertIsNone(text, name)
            self.assertIn('non déclaré', err)
            self.assertFalse(fake.completion.called, name)

    def test_every_declared_provider_but_the_subscription_is_accepted(self):
        for source in external_sources.SOURCES:
            if source.kind != 'llm':
                continue
            expected = source.protocol != 'claude_cli'
            self.assertEqual(expected, llm_utils.declared_llm_source(source.key) is not None,
                             source.key)

    def test_the_gateway_check_offers_the_declared_providers_and_no_other(self):
        from wama.model_manager.management.commands.llm_gateway_check import _cloud_providers
        self.assertEqual([s.key for s in external_sources.SOURCES
                          if llm_utils.declared_llm_source(s.key)], _cloud_providers())
        self.assertNotIn('openai', _cloud_providers())

    def test_no_model_and_none_declared_is_refused_instead_of_sending_a_bare_prefix(self):
        with patch.object(llm_utils, 'default_cloud_model', return_value=''):
            (text, err), fake = self._call('albert', env={'ALBERT_API_KEY': 'k'})
        self.assertIsNone(text)
        self.assertFalse(fake.completion.called, "LiteLLM would have received `openai/` alone")

    def test_the_instance_key_set_on_the_sources_page_serves_every_declared_protocol(self):
        # Until 2026-10-11 only the OpenAI-compatible branch read it: the Anthropic API
        # ignored a key set on the page.
        (_, _), fake = self._call('anthropic', stored='page-key', model='claude-x')
        self.assertEqual('page-key', fake.completion.call_args.kwargs['api_key'])


class DeclaredRateLimitWaitTest(SimpleTestCase):
    """2026-10-11 (chantier 5 ③): the wait after a 429 WITHOUT `Retry-After` is the one the
    source MEASURED (`rate_limit_wait_s`, Albert: a whole window), otherwise the common one."""

    class RateLimitError(Exception):
        status_code = 429

    def _wait(self, provider, env):
        outcomes = iter([self.RateLimitError(), 'OK'])

        def completion(**kwargs):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return MagicMock(choices=[MagicMock(message=MagicMock(content=outcome))])
        with patch.dict(sys.modules, {'litellm': MagicMock(completion=completion)}), \
                patch.dict(os.environ, env), patch('time.sleep') as sleep, \
                patch.object(llm_utils, 'RATE_LIMIT_WAIT_S', 5.0), \
                patch.object(external_sources, 'stored_instance_key', return_value=''):
            self.assertEqual(('OK', None), llm_utils.llm_chat(MESSAGES, provider=provider,
                                                              model='m'))
        return sleep.call_args.args[0]

    def test_albert_waits_its_measured_window_and_another_provider_the_common_wait(self):
        self.assertEqual(external_sources.get('albert').rate_limit_wait_s,
                         self._wait('albert', {'ALBERT_API_KEY': 'k'}))
        self.assertEqual(5.0, self._wait('anthropic', {'ANTHROPIC_API_KEY': 'k'}))


class DeclaredRequestBodyTest(SimpleTestCase):
    """2026-10-10 (Fabien's decision): OpenRouter routes a request only to providers that
    neither keep nor train on the data — a rule DECLARED by the source (`no_reuse_request_body`).
    2026-10-12: the rule follows the user's hosting ceiling — not sent once they accept reuse."""

    def _sent(self, provider, env, **kwargs):
        fake = _fake_litellm()
        with patch.dict(sys.modules, {'litellm': fake}), patch.dict(os.environ, env), \
                patch.object(external_sources, 'stored_instance_key', return_value=''):
            text, err = llm_utils.llm_chat(MESSAGES, provider=provider, **kwargs)
        self.assertEqual(('OK', None), (text, err))
        return fake.completion.call_args.kwargs

    def test_openrouter_requests_deny_data_collection_by_default(self):
        sent = self._sent('openrouter', {'OPENROUTER_API_KEY': 'or-key'})
        self.assertEqual({'provider': {'data_collection': 'deny'}}, sent['extra_body'])
        self.assertEqual('openai/openrouter/auto', sent['model'])

    def test_accepted_data_reuse_sends_no_rule(self):
        sent = self._sent('openrouter', {'OPENROUTER_API_KEY': 'or-key'}, data_reuse_ok=True)
        self.assertNotIn('extra_body', sent)

    def test_a_source_without_a_rule_sends_nothing_more(self):
        # Counter-check: Albert's requests are unchanged.
        self.assertNotIn('extra_body', self._sent('albert', {'ALBERT_API_KEY': 'k'}))

    def test_chat_with_source_reads_the_users_ceiling(self):
        """The wiring: a signed-in user's ceiling decides; no user (instance key) stays strict."""
        user = MagicMock(is_authenticated=True)
        for accepted in (True, False):
            with patch('wama.model_manager.services.cloud_models.cloud_access', return_value='k'), \
                    patch('wama.model_manager.services.cloud_models.data_reuse_accepted',
                          return_value=accepted), \
                    patch.object(llm_utils, 'llm_chat', return_value=('OK', None)) as chat:
                llm_utils.chat_with_source('openrouter', 'm', MESSAGES, user=user)
            self.assertIs(accepted, chat.call_args.kwargs['data_reuse_ok'])
        with patch.object(llm_utils, 'llm_chat', return_value=('OK', None)) as chat:
            llm_utils.chat_with_source('openrouter', 'm', MESSAGES)
        self.assertIs(False, chat.call_args.kwargs['data_reuse_ok'])


class ProviderSaturationNoteTest(SimpleTestCase):
    """2026-10-13 (ROADMAP §8d step 2): a call refused because the PROVIDER is saturated NOTES it
    — the automatic draw then leaves it out while the note lasts — and a caller that has another
    provider at hand can skip the minute's wait. A fault of the request notes nothing."""

    class RateLimitError(Exception):
        status_code = 429

        def __init__(self):
            super().__init__('limit')
            self.response = MagicMock(headers={'retry-after': '7'})

    class ServiceUnavailableError(Exception):
        status_code = 503

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def tearDown(self):
        from django.core.cache import cache
        cache.clear()

    def _fail(self, error, **kwargs):
        def completion(**_kwargs):
            raise error
        with patch.dict(sys.modules, {'litellm': MagicMock(completion=completion)}), \
                patch('time.sleep') as sleep:
            result = llm_utils.llm_chat(MESSAGES, provider='albert', model='m', api_key='k',
                                        **kwargs)
        return result, sleep

    def _noted(self, scope):
        from wama.model_manager.services.cloud_models import saturated_sources
        return saturated_sources({'albert': scope}).get('albert', '')

    def test_a_rate_limit_without_waiting_fails_at_once_and_notes_the_key(self):
        (text, _error), sleep = self._fail(self.RateLimitError(), rate_limit_wait=False,
                                           saturation_scope='user:7')
        self.assertIsNone(text)
        sleep.assert_not_called()
        self.assertEqual(llm_utils.RATE_LIMITED, self._noted('user:7'))
        # The limit belongs to THAT key: another key is not concerned.
        self.assertEqual('', self._noted('instance'))

    def test_the_scope_is_computed_only_when_a_failure_is_noted(self):
        scope = MagicMock(return_value='user:8')
        with patch.dict(sys.modules, {'litellm': _fake_litellm()}):
            llm_utils.llm_chat(MESSAGES, provider='albert', model='m', api_key='k',
                               saturation_scope=scope)
        scope.assert_not_called()
        self._fail(self.RateLimitError(), rate_limit_wait=False, saturation_scope=scope)
        self.assertEqual(llm_utils.RATE_LIMITED, self._noted('user:8'))

    def test_an_outage_is_noted_for_every_key(self):
        self._fail(self.ServiceUnavailableError('down'))
        self.assertEqual(llm_utils.UNAVAILABLE, self._noted('user:9'))

    def test_a_fault_of_the_request_notes_nothing(self):
        """Counter-check: a refused key or an unknown model is not fixed by another provider."""
        for error in (ValueError('clé refusée'), type('AuthenticationError', (Exception,),
                                                      {'status_code': 401})('401')):
            with self.subTest(error=type(error).__name__):
                self._fail(error)
                self.assertEqual('', self._noted('instance'))

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
        self.assertNotIn('albert', llm_utils.CLOUD_DEFAULT_MODELS)

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
        with patch.dict(sys.modules, {'litellm': fake}):
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


class DeclaredRequestBodyTest(SimpleTestCase):
    """2026-10-10 (Fabien's decision): OpenRouter routes every request only to providers that
    neither keep nor train on the data — a rule DECLARED by the source (`request_body`)."""

    def _sent(self, provider, env):
        fake = _fake_litellm()
        with patch.dict(sys.modules, {'litellm': fake}), patch.dict(os.environ, env), \
                patch.object(external_sources, 'stored_instance_key', return_value=''):
            text, err = llm_utils.llm_chat(MESSAGES, provider=provider)
        self.assertEqual(('OK', None), (text, err))
        return fake.completion.call_args.kwargs

    def test_openrouter_requests_deny_data_collection(self):
        sent = self._sent('openrouter', {'OPENROUTER_API_KEY': 'or-key'})
        self.assertEqual({'provider': {'data_collection': 'deny'}}, sent['extra_body'])
        self.assertEqual('openai/openrouter/auto', sent['model'])

    def test_a_source_that_declares_nothing_sends_nothing_more(self):
        # Counter-check: Albert's requests are unchanged.
        self.assertNotIn('extra_body', self._sent('albert', {'ALBERT_API_KEY': 'k'}))

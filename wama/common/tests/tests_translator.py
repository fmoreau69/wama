"""La brique de traduction (`common/utils/translator.py`) — moteur de l'app Translator (2026-10-16).

Elle n'avait AUCUN test alors que le pipeline de prompts de toutes les apps et l'assistant
l'appellent. Ce qui est tenu : le passthrough, le modèle désigné par une CLÉ DE CATALOGUE (voie
locale gouvernée pour `ollama:*`, `chat_with_catalog_model` sinon, avec la clé de l'utilisateur),
l'ancien nom nu accepté, l'aperçu au fil des morceaux, et un cache qui distingue les modèles.
"""
from unittest import mock

from django.test import SimpleTestCase

from wama.common.utils import llm_utils, translator


class TranslatorServiceTest(SimpleTestCase):

    def _service(self, **kw):
        return translator.TranslatorService(use_cache=False, **kw)

    def test_same_language_or_empty_text_calls_no_model(self):
        with mock.patch.object(llm_utils, 'llm_chat') as local, \
                mock.patch.object(llm_utils, 'chat_with_catalog_model') as remote:
            self.assertEqual('Bonjour', self._service().translate('Bonjour', 'fr', 'fr')['text'])
            self.assertTrue(self._service().translate('  ', 'fr', 'en')['ok'])
        local.assert_not_called()
        remote.assert_not_called()

    def test_a_local_key_takes_the_governed_ollama_path(self):
        with mock.patch.object(llm_utils, 'llm_chat', return_value=('Hello', None)) as local:
            out = self._service().translate('Bonjour', 'fr', 'en')
        self.assertEqual('Hello', out['text'])
        self.assertEqual(('ollama', 'translategemma:12b'),
                         (local.call_args.kwargs['provider'], local.call_args.kwargs['model']))

    def test_a_remote_key_goes_through_the_catalog_call_with_the_user(self):
        user = object()
        with mock.patch.object(llm_utils, 'chat_with_catalog_model',
                               return_value=('Hello', None)) as remote, \
                mock.patch.object(llm_utils, 'llm_chat') as local:
            out = self._service(model='ilaas:qwen-3.8-27b', user=user).translate(
                'Bonjour', 'fr', 'en')
        self.assertEqual('Hello', out['text'])
        self.assertEqual('ilaas:qwen-3.8-27b', remote.call_args.args[0])
        self.assertIs(user, remote.call_args.kwargs['user'])
        local.assert_not_called()

    def test_the_former_bare_ollama_name_is_still_accepted(self):
        self.assertEqual('ollama:translategemma:12b',
                         self._service(model='translategemma:12b').model)

    def test_each_translated_chunk_is_reported_as_it_comes(self):
        text = 'a' * 3000 + '\n\n' + 'b' * 3000          # deux morceaux (> _CHUNK_CHARS)
        seen = []
        with mock.patch.object(llm_utils, 'llm_chat', side_effect=[('A', None), ('B', None)]):
            out = self._service().translate(text, 'fr', 'en', on_chunk=seen.append)
        self.assertEqual(['A', 'A\n\nB'], seen)
        self.assertEqual('A\n\nB', out['text'])

    def test_an_unknown_source_is_left_to_the_model_and_never_named_auto(self):
        """Mesuré le 2026-10-16 sur translategemma : « de « auto » vers « en » » rendait le texte
        INCHANGÉ. La consigne nomme les langues par code ISO et fait détecter la source."""
        with mock.patch.object(llm_utils, 'llm_chat', return_value=('Hello', None)) as local:
            self._service().translate('Bonjour', 'auto', 'en')
            unknown = local.call_args.kwargs['messages'][0]['content']
            self._service().translate('Bonjour', 'fr', 'en')
            known = local.call_args.kwargs['messages'][0]['content']
        self.assertNotIn('« auto »', unknown)
        self.assertIn('détecte', unknown)
        self.assertIn('ISO 639-1 « en »', unknown)
        self.assertIn('« fr »', known)                    # contre-épreuve : la source connue se dit

    def test_a_rewritten_prompt_does_not_serve_the_old_cached_translations(self):
        key = translator.TranslatorService._cache_key
        before = key('Bonjour', 'auto', 'en', [], 'ollama:translategemma:12b')
        with mock.patch.object(translator, 'PROMPT_VERSION', translator.PROMPT_VERSION + 1):
            self.assertNotEqual(before, key('Bonjour', 'auto', 'en', [], 'ollama:translategemma:12b'))

    def test_two_models_never_share_a_cached_translation(self):
        key = translator.TranslatorService._cache_key
        self.assertNotEqual(key('Bonjour', 'fr', 'en', [], 'ollama:translategemma:12b'),
                            key('Bonjour', 'fr', 'en', [], 'ilaas:qwen-3.8-27b'))

"""An LLM call designated by a CATALOG KEY — `llm_utils.chat_with_catalog_model` (2026-09-30).

The gesture « catalog key → provider + model + the user's key » only lived privately in the
assistant; an app whose « Model » setting is catalog-driven (route F4b) needs it too. What is
held here: the routing, and that a remote call always goes through the common guard.
"""
from unittest import mock

from django.test import SimpleTestCase

from wama.common.utils import llm_utils

MESSAGES = [{'role': 'user', 'content': 'bonjour'}]


class CatalogKeyRoutingTest(SimpleTestCase):

    def _call(self, key, **kw):
        with mock.patch.object(llm_utils, 'llm_chat', return_value=('ok', None)) as chat:
            result = llm_utils.chat_with_catalog_model(key, MESSAGES, **kw)
        return result, chat

    def test_auto_goes_to_the_local_catalog_funnel(self):
        (text, err), chat = self._call('auto', num_predict=10)
        self.assertEqual(('ok', None), (text, err))
        _args, kwargs = chat.call_args
        self.assertEqual('ollama', kwargs['provider'])
        self.assertIsNone(kwargs['model'], 'auto must leave the choice to the funnel')
        self.assertEqual(10, kwargs['num_predict'])

    def test_an_ollama_key_keeps_its_full_model_name(self):
        _result, chat = self._call('ollama:qwen3.8:latest')
        _args, kwargs = chat.call_args
        self.assertEqual(('ollama', 'qwen3.8:latest'), (kwargs['provider'], kwargs['model']))

    def test_a_remote_key_goes_through_the_common_guard_with_the_users_key(self):
        user = object()
        with mock.patch('wama.model_manager.services.cloud_models.cloud_access',
                        return_value='user-key') as guard:
            _result, chat = self._call('albert:gpt-oss-120b', user=user)
        guard.assert_called_once_with(user, 'albert', 'gpt-oss-120b')
        _args, kwargs = chat.call_args
        self.assertEqual(('albert', 'gpt-oss-120b', 'user-key'),
                         (kwargs['provider'], kwargs['model'], kwargs['api_key']))

    def test_a_refusal_of_the_guard_is_returned_not_raised(self):
        from wama.model_manager.services.cloud_models import CloudAccessRefused
        with mock.patch('wama.model_manager.services.cloud_models.cloud_access',
                        side_effect=CloudAccessRefused('profil 100 % local', 403)):
            (text, err), chat = self._call('albert:gpt-oss-120b', user=object())
        self.assertIsNone(text)
        self.assertIn('100 % local', err)
        chat.assert_not_called()

    def test_undeclared_sources_and_the_subscription_are_refused(self):
        for key in ('openai:gpt-4o', 'claude_code:default', 'no-colon'):
            with self.subTest(key=key):
                (text, err), chat = self._call(key)
                self.assertIsNone(text)
                self.assertTrue(err)
                chat.assert_not_called()

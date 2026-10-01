"""An LLM call designated by a CATALOG KEY — `llm_utils.chat_with_catalog_model` (2026-09-30).

The gesture « catalog key → provider + model + the user's key » only lived privately in the
assistant; an app whose « Model » setting is catalog-driven (route F4b) needs it too. What is
held here: the routing, and that a remote call always goes through the common guard.
"""
from unittest import mock

from django.test import SimpleTestCase

from wama.common.utils import llm_utils

MESSAGES = [{'role': 'user', 'content': 'bonjour'}]


class _User:
    """A signed-in user: the common guard only applies to one (as in the assistant)."""
    is_authenticated = True


class CatalogKeyRoutingTest(SimpleTestCase):

    def _call(self, key, **kw):
        with mock.patch.object(llm_utils, 'llm_chat', return_value=('ok', None)) as chat:
            result = llm_utils.chat_with_catalog_model(key, MESSAGES, **kw)
        return result, chat

    def test_auto_is_refused_with_the_gesture_to_make(self):
        """ONE « auto » path (2026-10-01): an app draws with `resolve_model_choice` — the path of
        the preview under its select. This branch used to fall back on its own to a second
        funnel (`modele_par_defaut`): an app that forgot to draw announced one model and launched
        another. Refused, the omission is visible; nothing is called."""
        for key in ('auto', '', 'auto:text-generation'):
            with self.subTest(key=key):
                (text, err), chat = self._call(key)
                self.assertIsNone(text)
                self.assertIn('resolve_model_choice', err)
                chat.assert_not_called()

    def test_an_ollama_key_keeps_its_full_model_name(self):
        _result, chat = self._call('ollama:qwen3.8:latest')
        _args, kwargs = chat.call_args
        self.assertEqual(('ollama', 'qwen3.8:latest'), (kwargs['provider'], kwargs['model']))

    def test_a_remote_key_goes_through_the_common_guard_with_the_users_key(self):
        user = _User()
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
            (text, err), chat = self._call('albert:gpt-oss-120b', user=_User())
        self.assertIsNone(text)
        self.assertIn('100 % local', err)
        chat.assert_not_called()

    def test_without_a_user_the_instance_key_serves_and_no_guard_runs(self):
        """Command-line roles have no user: `llm_chat` takes the instance key, as before."""
        with mock.patch('wama.model_manager.services.cloud_models.cloud_access') as guard:
            _result, chat = self._call('albert:gpt-oss-120b')
        guard.assert_not_called()
        self.assertIsNone(chat.call_args[1]['api_key'])

    def test_the_signature_is_explicit_so_a_guessed_argument_fails_at_once(self):
        """No `**kwargs` relay: the codegen role had passed `max_tokens` / `max_new_tokens`
        through one — invisible to its checks, `TypeError` at the first launch."""
        import inspect
        params = inspect.signature(llm_utils.chat_with_catalog_model).parameters
        self.assertFalse(any(p.kind == p.VAR_KEYWORD for p in params.values()))
        with self.assertRaises(TypeError):
            llm_utils.chat_with_catalog_model('auto', MESSAGES, max_tokens=10)

    def test_no_call_timeout_by_default_the_task_max_duration_bounds_it(self):
        """The 1st real Editor run fell on a 300 s the glue had COPIED from this default."""
        _result, chat = self._call('ollama:qwen3.8:latest')
        self.assertIsNone(chat.call_args[1]['timeout'])

    def test_undeclared_sources_and_the_subscription_are_refused(self):
        for key in ('openai:gpt-4o', 'claude_code:default', 'no-colon'):
            with self.subTest(key=key):
                (text, err), chat = self._call(key)
                self.assertIsNone(text)
                self.assertTrue(err)
                chat.assert_not_called()

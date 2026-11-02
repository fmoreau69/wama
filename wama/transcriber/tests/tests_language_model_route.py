"""The transcriber asks the ROUTE for the model its language probe listens with (2026-11-02) —
Whisper tiny, a catalogue row of its own (`spoken_language.MODEL_KEY`), which NeMo also hears
passage by passage. It used to be fetched by name at first use, with no row. And the first-draft
utilities of `utils/model_config.py` are gone (no caller — REMOVAL_LEDGER).

⚠ Identifiants en anglais ; commentaires et docstrings en français. Aucun modèle chargé.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from wama.common.utils import spoken_language
from wama.transcriber import workers


class LanguageProbeAsksTheRouteTest(SimpleTestCase):

    def _plan(self, mode='auto', cap=30, ensure=None):
        steps = []
        card = SimpleNamespace(language_mode=mode, user_id=None, duration_seconds=60)
        backend = SimpleNamespace(max_audio_seconds=cap)

        def probe(path, duration):
            steps.append('probe')
            return [('fr', 0.9), ('fr', 0.9)]
        with mock.patch.object(spoken_language, 'probe_languages', side_effect=probe), \
                mock.patch.object(workers, '_console'):
            plan = workers._language_plan(card, 'x.wav', backend,
                                          ensure_model=ensure or steps.append)
        return plan, steps

    def test_the_language_model_is_asked_before_the_probe_listens(self):
        plan, steps = self._plan()
        self.assertEqual([spoken_language.MODEL_KEY, 'probe'], steps)
        self.assertEqual(('single', 'fr', 'fr'), plan)

    def test_a_refused_installation_is_a_failed_probe_not_a_failed_card(self):
        from wama.common.utils.model_readiness import ModelInstallRefused

        def refuse(key):
            raise ModelInstallRefused('espace disque insuffisant')
        plan, steps = self._plan(ensure=refuse)
        self.assertEqual([], steps, 'nothing listens without its model')
        self.assertEqual(('single', None, None), plan)

    def test_waiting_for_the_installation_is_never_swallowed_by_the_probe(self):
        """`ServiceNotReady` (the task waits, its worker freed) must reach the skeleton."""
        from wama.common.utils.task_skeleton import ServiceNotReady

        def wait(key):
            raise ServiceNotReady('installation en cours')
        with self.assertRaises(ServiceNotReady):
            self._plan(ensure=wait)

    def test_counter_proof_no_probe_no_ask(self):
        """Whisper in « multi » decides alone, window by window: nothing to ask."""
        plan, steps = self._plan(mode='multi', cap=None)
        self.assertEqual([], steps)
        self.assertEqual(('multi', None, None), plan)


class FirstDraftUtilitiesAreGoneTest(SimpleTestCase):

    def test_the_uncalled_utilities_and_their_environment_variable_are_gone(self):
        from wama.transcriber.utils import model_config
        for name in ('load_whisper_model', 'setup_model_environment', 'get_model_info',
                     'list_available_models', 'get_whisper_download_root', 'DEFAULT_MODEL',
                     'WHISPER_DIR'):
            with self.subTest(name=name):
                self.assertFalse(hasattr(model_config, name))
        self.assertIn('whisper', model_config.TRANSCRIBER_MODELS, 'the declarations stay')

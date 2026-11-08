"""Smart Turn au contrat commun (`end-of-turn`) — le juge de la fin de tour de l'écoute.

Jusqu'au 2026-11-08, le service vocal le chargeait lui-même (`_turn_session`, un dict de sessions
ONNX par chemin) d'après un chemin que Django lui passait (`loaded_by`). La recette (fenêtre, silence
au début) est gardée par `tests_assistant_listen.EndOfTurnServiceRecipeTest`.

⚠ Identifiants en anglais ; commentaires et docstrings en français. Aucun modèle chargé.
"""
from pathlib import Path
from unittest import mock

import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, TestCase

from wama.common.tts.end_of_turn import MODEL_KEY


class EndOfTurnThroughTheCommonContractTest(TestCase):
    """La ligne du catalogue désigne le backend du contrat `end-of-turn` ; le service le tient."""

    def setUp(self):
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key=MODEL_KEY, name='smart turn', model_type='speech',
                               source='huggingface', is_downloaded=True,
                               capabilities={'task': 'end-of-turn'},
                               composition={'runtime': {'engine': 'onnxruntime'}})

    def test_the_line_resolves_its_backend_of_the_contract(self):
        """`onnxruntime` est partagé : c'est le contrat LIANT qui désigne le juge."""
        from wama.common.backends.manager import _work_method, backend_for_key
        from wama.common.backends.smart_turn_backend import SmartTurnBackend
        self.assertIs(SmartTurnBackend, backend_for_key(MODEL_KEY))
        self.assertEqual('turn_end_probability', _work_method(SmartTurnBackend))

    def test_the_task_has_its_binding_contract_and_the_backend_implements_it(self):
        """La liste du backend suffit à le désigner ; le CONTRAT dit ce qu'un juge proposé par le
        rôle `backend` doit implémenter, et borne le moteur partagé à sa tâche."""
        from wama.common.backends.end_of_turn_base import EndOfTurnBackend
        from wama.common.backends.smart_turn_backend import SmartTurnBackend
        from wama.common.services.backend_inventory import TASK_CONTRACTS
        module, name, binding = TASK_CONTRACTS['end-of-turn']
        self.assertEqual(('end_of_turn_base', 'EndOfTurnBackend', True), (module, name, binding))
        self.assertTrue(issubclass(SmartTurnBackend, EndOfTurnBackend))

    def test_the_manifest_requires_the_libraries_of_its_backend(self):
        from wama.common.manifests.builtin.model import _requires_librairies
        body = {'composition': {'runtime': {'engine': 'onnxruntime'}},
                'capabilities': {'task': 'end-of-turn'}}
        keys = [r['key'] for r in _requires_librairies(body, MODEL_KEY)]
        self.assertIn('transformers', keys)
        self.assertTrue(any(k.startswith('onnxruntime') for k in keys), keys)

    def test_the_discovery_retracts_the_loader_it_used_to_name(self):
        from wama.model_manager.services.model_sync import merged_composition
        from wama.model_manager.tests.tests_model_loaded_by import _registry
        registry = _registry()
        registry._discover_turn_end_models()
        prior = {'runtime': {'engine': 'onnxruntime', 'loaded_by': 'wama.common.tts.service'}}
        self.assertEqual({'runtime': {'engine': 'onnxruntime'}},
                         merged_composition(prior, registry._models[MODEL_KEY].composition))

    def test_the_voice_service_keeps_one_instance_of_the_backend(self):
        from wama.common.backends.smart_turn_backend import SmartTurnBackend
        from wama.common.tts import service
        first, second = service._turn_backend(), service._turn_backend()
        self.assertIsInstance(first, SmartTurnBackend)
        self.assertIs(first, second)


class TheDeclarationsAgreeTest(SimpleTestCase):
    """Le littéral du backend et le dossier qu'il lit redisent les déclarations de l'écoute."""

    def test_the_literal_list_is_the_key_its_module_names(self):
        from wama.common.backends.smart_turn_backend import SmartTurnBackend
        from wama.common.utils.model_keys import backend_model_id
        self.assertEqual({backend_model_id(MODEL_KEY): {'model_key': MODEL_KEY}},
                         SmartTurnBackend.SUPPORTED_MODELS)

    def test_django_and_the_voice_service_read_the_same_folder(self):
        """Le service n'a pas Django : la lecture commune y retombe sur le même dossier."""
        from wama.common.backends import tts_base
        from wama.common.tts.end_of_turn import model_folder
        declared = Path(settings.MODEL_PATHS['speech']['smart_turn'])
        self.assertEqual(declared, model_folder())
        with self.settings(MODEL_PATHS={}):
            outside = model_folder()
        self.assertEqual(tts_base.ai_models_dir() / 'models' / 'speech' / declared.name, outside)
        self.assertEqual(declared, outside)

    def test_an_absent_model_is_said_never_fetched(self):
        from wama.common.backends.smart_turn_backend import SmartTurnBackend
        with mock.patch('wama.common.tts.end_of_turn.model_folder',
                        return_value=Path('/nowhere/smart-turn')), \
                mock.patch('onnxruntime.InferenceSession') as session:
            with self.assertRaisesMessage(RuntimeError, MODEL_KEY):
                SmartTurnBackend().load()
        session.assert_not_called()


FAKE_JUDGE = '''
from .end_of_turn_base import EndOfTurnBackend


class FakeJudge(EndOfTurnBackend):
    def load(self, model=None):
        self._loaded = True
        return True

    def unload(self):
        self._loaded = False

    def turn_end_probability(self, audio):
        return __ANSWER__
'''


class EndOfTurnSmokeTest(SimpleTestCase):
    """L'essai du contrat (`backend_proposals.SMOKES`) : un juge que propose le rôle `backend`
    rend une probabilité sur l'extrait de parole réelle du smoke de PAROLE."""

    def _smoke(self, answer: str):
        """`answer` : l'EXPRESSION que rend le faux juge (source du module proposé)."""
        from types import SimpleNamespace
        from wama.common.services import backend_proposals
        clip = SimpleNamespace(attributes={}, file=SimpleNamespace(path='x.wav'))
        with mock.patch.object(backend_proposals, 'smoke_speech_clip', return_value=(clip, None)), \
                mock.patch('wama.common.utils.audio_decode.decode_window',
                           return_value=(np.zeros(16000, dtype=np.float32), 16000)):
            return backend_proposals.SMOKES['EndOfTurnBackend'](
                FAKE_JUDGE.replace('__ANSWER__', answer),
                module='fake_turn_backend', model_key='huggingface:org/fake-turn', out_dir=None)

    def test_a_probability_passes(self):
        out = self._smoke('0.42')
        self.assertTrue(out['ok'], out)

    def test_an_answer_outside_the_contract_fails(self):
        for answer in ('1.5', '-0.1', "'yes'", "float('nan')"):
            with self.subTest(answer=answer):
                self.assertIn('hors contrat', self._smoke(answer)['error'])

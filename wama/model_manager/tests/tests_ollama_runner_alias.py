"""An Ollama runner manifest is not a model (2026-10-12).

Ollama 0.40 writes, next to a pulled model, an engine-specific manifest
`library/llamacpp/<sha256>` whose layers come `"from": "qwen3.5:4b"`. On 2026-10-07
`ollama list` showed it, WAMA catalogued `ollama:llamacpp:96f38c…` — a duplicate of qwen3.5:4b
that the selector then picked — and no later sync ever realigned it.
"""
from unittest import mock

from django.test import SimpleTestCase, TestCase

from wama.model_manager.models import AIModel

DIGEST = '96f38c742e0a10e194b237d2ffb8b55925ebfeed9d27df72688f565e773569e7'


class RunnerAliasNameTest(SimpleTestCase):

    def test_a_full_digest_tag_is_a_runner_alias(self):
        from wama.model_manager.services.model_registry import is_ollama_runner_alias
        self.assertTrue(is_ollama_runner_alias(f'llamacpp:{DIGEST}'))
        self.assertTrue(is_ollama_runner_alias(f'ggml:{DIGEST}'), "the engine name is not read")

    def test_real_model_names_are_not(self):
        from wama.model_manager.services.model_registry import is_ollama_runner_alias
        for name in ('qwen3.5:4b', 'glm-ocr:latest', 'bge-m3',
                     'hf.co/SandLogicTechnologies/chandra-ocr-2-GGUF:Q6_K',
                     f'llamacpp:{DIGEST[:-1]}', f'llamacpp:{DIGEST.upper()}', DIGEST):
            with self.subTest(name=name):
                self.assertFalse(is_ollama_runner_alias(name))


class DiscoverySkipsRunnerAliasTest(SimpleTestCase):

    LISTING = ("NAME                ID              SIZE      MODIFIED\n"
               "qwen3.5:4b          96f38c742e0a    3.4 GB    4 days ago\n"
               f"llamacpp:{DIGEST}  96f38c742e0a    3.4 GB    4 days ago\n")

    def test_ollama_list_keeps_the_model_and_drops_its_runner_manifest(self):
        from wama.model_manager.services import model_registry as mr
        registry = mr.ModelRegistry()
        saved = dict(registry._models)
        registry._models.clear()
        done = mock.Mock(returncode=0, stdout=self.LISTING)
        try:
            with mock.patch.object(mr.subprocess, 'run', return_value=done), \
                    mock.patch.object(mr.ModelRegistry, '_ollama_charges', return_value={}), \
                    mock.patch.object(mr.ModelRegistry, '_ollama_capacites', return_value={}), \
                    mock.patch.object(mr.ModelRegistry, '_ollama_fiche', return_value={}):
                registry._discover_ollama_models()
            keys = set(registry._models)
        finally:
            registry._models.clear()
            registry._models.update(saved)
        self.assertIn('ollama:qwen3.5:4b', keys)
        self.assertNotIn(f'ollama:llamacpp:{DIGEST}', keys)


class SyncDropsCataloguedRunnerAliasTest(TestCase):

    def test_the_ghost_row_goes_and_real_rows_stay(self):
        from wama.model_manager.services.model_sync import ModelSyncService
        for key in (f'ollama:llamacpp:{DIGEST}', 'ollama:qwen3.5:4b'):
            AIModel.objects.create(model_key=key, name=key.partition(':')[2], model_type='llm',
                                   source='ollama', is_downloaded=True)
        AIModel.objects.create(model_key='proposed:ollama:other:latest', name='other',
                               model_type='llm', source='ollama', is_proposed=True)
        self.assertEqual(1, ModelSyncService._drop_ollama_runner_aliases())
        self.assertEqual({'ollama:qwen3.5:4b', 'proposed:ollama:other:latest'},
                         set(AIModel.objects.filter(source='ollama')
                             .values_list('model_key', flat=True)))

"""A silent Ollama daemon does not change the nature of a model (2026-10-16).

When the WSL network fell at 00:45:58, the discovery got no capabilities from the daemon and
assumed a COMPLETION model for every row: bge-m3 and qwen3-embedding were rewritten
`text-generation` + `completion=True`, and the assistant drew bge-m3 as its chat model
(« does not support chat »). The discovery now recomputes from the LAST measured capabilities
(`abilities`, the raw set it keeps on the row) instead of assuming.
"""
from unittest import mock

from django.test import TestCase

from wama.model_manager.models import AIModel


class SilentDaemonKeepsTheMeasuredNatureTest(TestCase):

    LISTING = ("NAME            ID              SIZE      MODIFIED\n"
               "bge-m3:latest   790764642607    1.2 GB    2 months ago\n"
               "brand-new:7b    123456789abc    4.1 GB    1 minute ago\n")

    def setUp(self):
        AIModel.objects.create(
            model_key='ollama:bge-m3:latest', name='bge-m3:latest', model_type='embedding',
            source='ollama', is_downloaded=True,
            capabilities={'task': 'feature-extraction', 'completion': False, 'embedding': True,
                          'abilities': ['embedding']})

    def _discover(self):
        from wama.model_manager.services import model_registry as mr
        registry = mr.ModelRegistry()
        saved = dict(registry._models)
        registry._models.clear()
        done = mock.Mock(returncode=0, stdout=self.LISTING)
        try:
            # The daemon's API is SILENT: no capabilities from /api/tags nor /api/show.
            with mock.patch.object(mr.subprocess, 'run', return_value=done), \
                    mock.patch.object(mr.ModelRegistry, '_ollama_charges', return_value={}), \
                    mock.patch.object(mr.ModelRegistry, '_ollama_capacites', return_value={}), \
                    mock.patch.object(mr.ModelRegistry, '_ollama_fiche', return_value={}):
                registry._discover_ollama_models()
            return dict(registry._models)
        finally:
            registry._models.clear()
            registry._models.update(saved)

    def test_an_embedding_model_stays_an_embedding_model(self):
        info = self._discover()['ollama:bge-m3:latest']
        self.assertEqual('embedding', info.model_type.value)
        self.assertEqual('feature-extraction', info.capabilities['task'])
        self.assertFalse(info.capabilities['completion'])
        self.assertEqual(['embedding'], info.capabilities['abilities'])

    def test_a_model_never_measured_keeps_the_old_completion_fallback(self):
        """Counter-check: without any measured fact, nothing is invented either way."""
        info = self._discover()['ollama:brand-new:7b']
        self.assertEqual('text-generation', info.capabilities['task'])
        self.assertTrue(info.capabilities['completion'])
        self.assertNotIn('abilities', info.capabilities)

    def test_the_directory_fallback_name_finds_the_latest_row(self):
        """The directory fallback names a `latest` tag WITHOUT its suffix (`bge-m3`)."""
        from wama.model_manager.services.model_registry import ModelRegistry
        self.assertEqual({'embedding'}, ModelRegistry._ollama_last_measured('bge-m3'))
        self.assertEqual({'embedding'}, ModelRegistry._ollama_last_measured('bge-m3:latest'))
        self.assertEqual(set(), ModelRegistry._ollama_last_measured('unknown'))

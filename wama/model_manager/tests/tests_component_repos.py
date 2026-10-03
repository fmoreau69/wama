"""A repo declared as a COMPONENT of another model is not a model (2026-10-03).

Measured that day: the generic snapshot sweep catalogued `m-a-p/YuE2-Vae` (the decoder of YuE2)
and `m-a-p/MERT-v2-FullSong` (the encoder parent of SheetSage2) as models of their own, and the
composer's « auto » drew the VAE for a music generation at the fast end of the cursor. The
manifest formalism already says it: a `repo` component is « published apart, with no existence of
its own for use ». Discovery and sync now read that declaration.
"""
from types import SimpleNamespace

from django.test import TestCase

from wama.common.utils import model_locations as ml
from wama.model_manager.models import AIModel
from wama.model_manager.services.model_sync import ModelSyncService


class AComponentRepoIsNoModelTest(TestCase):

    def setUp(self):
        AIModel.objects.create(
            model_key='huggingface:org/Song-3B', name='Song', source='huggingface',
            hf_id='org/Song-3B', composition={'components': [
                {'role': 'model', 'pattern': '*.safetensors'},
                {'role': 'vae', 'repo': 'org/Song-Vae'}]})
        # A model that names ITS OWN repo as a component (codeformer) stays a model.
        AIModel.objects.create(
            model_key='app:restorer', name='Restorer', source='avatarizer', hf_id='org/Restorer',
            composition={'components': [{'role': 'weights', 'repo': 'org/Restorer'}]})

    def test_the_declared_component_repos_are_read_from_the_catalogue(self):
        self.assertEqual({'org/Song-Vae'}, ml.declared_component_repos())

    def test_the_sync_drops_the_generic_row_of_a_component(self):
        AIModel.objects.create(model_key='huggingface:org/Song-Vae', name='Song-Vae',
                               source='huggingface', hf_id='org/Song-Vae',
                               extra_info={'hf_snapshot': True})
        AIModel.objects.create(model_key='huggingface:org/Other', name='Other',
                               source='huggingface', hf_id='org/Other',
                               extra_info={'hf_snapshot': True})
        discovered = {'huggingface:org/Song-3B': SimpleNamespace(hf_id='org/Song-3B')}
        removed = ModelSyncService._drop_superseded_snapshots(
            discovered, seen_keys={'huggingface:org/Song-3B', 'huggingface:org/Other'})
        self.assertEqual(1, removed)
        self.assertFalse(AIModel.objects.filter(model_key='huggingface:org/Song-Vae').exists())
        self.assertTrue(AIModel.objects.filter(model_key='huggingface:org/Other').exists(),
                        'a generic row nobody declares as a component stays')
        self.assertTrue(AIModel.objects.filter(model_key='app:restorer').exists())

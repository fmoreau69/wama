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
            platform_ref='huggingface:org/Song-3B', composition={'components': [
                {'role': 'model', 'pattern': '*.safetensors'},
                {'role': 'vae', 'repo': 'org/Song-Vae'}]})
        # A model that names ITS OWN repo as a component (codeformer) stays a model.
        AIModel.objects.create(
            model_key='app:restorer', name='Restorer', source='avatarizer', platform_ref='huggingface:org/Restorer',
            composition={'components': [{'role': 'weights', 'repo': 'org/Restorer'}]})

    def test_the_declared_component_repos_are_read_from_the_catalogue(self):
        self.assertEqual({'org/Song-Vae'}, ml.declared_component_repos())

    def test_the_sync_drops_the_generic_row_of_a_component(self):
        AIModel.objects.create(model_key='huggingface:org/Song-Vae', name='Song-Vae',
                               source='huggingface', platform_ref='huggingface:org/Song-Vae',
                               extra_info={'hf_snapshot': True})
        AIModel.objects.create(model_key='huggingface:org/Other', name='Other',
                               source='huggingface', platform_ref='huggingface:org/Other',
                               extra_info={'hf_snapshot': True})
        discovered = {'huggingface:org/Song-3B': SimpleNamespace(hf_repo='org/Song-3B')}
        removed = ModelSyncService._drop_superseded_snapshots(
            discovered, seen_keys={'huggingface:org/Song-3B', 'huggingface:org/Other'})
        self.assertEqual(1, removed)
        self.assertFalse(AIModel.objects.filter(model_key='huggingface:org/Song-Vae').exists())
        self.assertTrue(AIModel.objects.filter(model_key='huggingface:org/Other').exists(),
                        'a generic row nobody declares as a component stays')
        self.assertTrue(AIModel.objects.filter(model_key='app:restorer').exists())


class ARowWhoseWeightsAnotherDesignatesTest(TestCase):
    """2026-11-06: a row the discovery no longer makes, whose weights location a discovered row
    DESIGNATES, is that row's duplicate — the rule of the discovery (`model_registry._designated`),
    for any row, not only the Hub's generic snapshots (the YOLOPv2 case is held in the Lab,
    `tests_road_model_download.TheOlderScanRowIsRelievedTest`)."""

    def _drop(self, discovered, seen):
        from unittest import mock
        with mock.patch('wama.model_manager.services.model_installer.forget_in_corpus'):
            return ModelSyncService._drop_rows_superseded_by_location(discovered, seen)

    def test_only_a_row_inside_a_designated_location_goes(self):
        AIModel.objects.create(model_key='app:old', name='old', source='app',
                               extra_info={'path': '/models/fam/models--o--m/snapshots/r1'})
        AIModel.objects.create(model_key='app:sibling', name='sibling', source='app',
                               local_path='/models/fam/models--o--other')
        AIModel.objects.create(model_key='remote:m', name='remote', source='openrouter')
        discovered = {'huggingface:o/m': SimpleNamespace(
            extra_info={'path': '/models/fam/models--o--m/snapshots/r1/model.safetensors'})}
        self.assertEqual(1, self._drop(discovered, {'huggingface:o/m'}))
        self.assertEqual({'app:sibling', 'remote:m'},
                         set(AIModel.objects.values_list('model_key', flat=True)))

    def test_a_family_folder_designates_nothing_and_a_seen_row_stays(self):
        """Counter-proofs: an entry whose `path` names the FAMILY (an aligner) does not relieve
        the models of that family; a row the discovery made is never touched."""
        AIModel.objects.create(model_key='app:inside', name='inside', source='app',
                               extra_info={'path': '/models/fam/models--o--m'})
        AIModel.objects.create(model_key='app:seen', name='seen', source='app',
                               extra_info={'path': '/models/fam/x.pt'})
        discovered = {'app:aligner': SimpleNamespace(extra_info={'path': '/models/fam'}),
                      'app:seen': SimpleNamespace(extra_info={'path': '/models/fam/x.pt'})}
        self.assertEqual(0, self._drop(discovered, {'app:aligner', 'app:seen'}))
        self.assertEqual(2, AIModel.objects.count())


class TheSyncKeepsTheManifestAnatomyTest(TestCase):
    """Measured on 2026-11-03: 10 rows had lost their components, the VAE of YuE2 and the MERT
    parent of SheetSage2 were models again. A backend that NAMES a row (2026-10-31) gave the
    discovery an engine to say — a non-empty composition, and the sync REPLACED the manifest's."""

    KEY = 'huggingface:org/Song-3B'
    DECLARED = {'components': [{'role': 'model', 'pattern': '*.safetensors'},
                               {'role': 'vae', 'repo': 'org/Song-Vae'}],
                'runtime': {'engine': 'song', 'family': 'song'}}

    def _sync(self, composition):
        from wama.model_manager.models import ModelSource, ModelType
        from wama.model_manager.services.model_registry import ModelInfo
        info = ModelInfo(id='org/Song-3B', name='Song', model_type=ModelType.MUSIC,
                         source=ModelSource.HUGGINGFACE, composition=composition)
        ModelSyncService()._sync_model(self.KEY, info)
        return AIModel.objects.get(model_key=self.KEY).composition

    def setUp(self):
        AIModel.objects.create(model_key=self.KEY, name='Song', source='huggingface',
                               platform_ref='huggingface:org/Song-3B', composition=self.DECLARED)

    def test_a_discovery_that_says_only_the_engine_keeps_the_components(self):
        self.assertEqual(self.DECLARED, self._sync({'runtime': {'engine': 'song'}}))
        self.assertEqual({'org/Song-Vae'}, ml.declared_component_repos(),
                         'the component is still no model after the sync')

    def test_the_discovery_still_has_authority_on_the_keys_it_states(self):
        """Counter-proof: an engine or an anatomy the discovery SAYS is written."""
        parts = [{'role': 'model', 'pattern': 'model.safetensors'}]
        self.assertEqual({'components': parts, 'runtime': {'engine': 'other', 'family': 'song'}},
                         self._sync({'runtime': {'engine': 'other'}, 'components': parts}))

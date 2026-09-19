"""La PROVENANCE de `vram_gb` est marquée par le rédacteur et écrite au sync (décision A, 16/09).

POURQUOI. Le tirage lisait `vram_gb` sans savoir s'il tenait d'une déclaration d'app, d'une
heuristique (2 × la taille d'un `.pt`, taille/500 d'un ONNX, taille GGUF pour Ollama) ou d'une
estimation (poids d'un snapshot × 1,2) — 19 rédacteurs, 4 natures, un seul chiffre. La cascade
« mesuré → source → estimé » ne peut pas s'appliquer sans que la source soit nommée.

Un seul point d'écriture (`model_sync._sync_model`), une clé `extra_info['vram_provenance']` ;
le défaut `declared` couvre les 15 rédacteurs qui déclarent et les `ModelInfo` d'avant le champ.
"""
from django.test import TestCase

from wama.model_manager.models import AIModel
from wama.model_manager.services.model_registry import ModelInfo, ModelSource, ModelType
from wama.model_manager.services.model_sync import ModelSyncService


def _info(key, **kw):
    base = dict(id=key, name=key, model_type=ModelType.DIFFUSION, source=ModelSource.WAMA_IMAGER,
                vram_gb=8.0, is_downloaded=True)
    base.update(kw)
    return ModelInfo(**base)


class ProvenanceDeLaVramTest(TestCase):

    def _sync(self, info):
        ModelSyncService()._sync_model(info.id, info)
        return AIModel.objects.get(model_key=info.id).extra_info or {}

    def test_le_defaut_est_DECLARE(self):
        self.assertEqual(self._sync(_info('imager:t-declare'))['vram_provenance'], 'declared')

    def test_un_redacteur_heuristique_ou_estime_le_DIT(self):
        self.assertEqual(self._sync(_info('imager:t-heur', vram_provenance='heuristic'))
                         ['vram_provenance'], 'heuristic')
        self.assertEqual(self._sync(_info('imager:t-est', vram_provenance='estimated'))
                         ['vram_provenance'], 'estimated')

    def test_zero_n_a_pas_de_provenance(self):
        """`0` veut dire INCONNU — un modèle distant, une ligne sans chiffre : rien à marquer."""
        self.assertNotIn('vram_provenance', self._sync(_info('imager:t-zero', vram_gb=0)))

    def test_un_ModelInfo_sans_le_champ_vaut_declare(self):
        """Les jumelles et les tests fabriquent des `ModelInfo` d'avant : ni erreur, ni vide."""
        info = _info('imager:t-ancien')
        info.vram_provenance = ''
        self.assertEqual(self._sync(info)['vram_provenance'], 'declared')

    def test_la_provenance_ne_chasse_pas_les_cles_collantes(self):
        AIModel.objects.create(model_key='imager:t-collant', name='x', model_type='image',
                               source='imager', vram_gb=8.0,
                               extra_info={'vram_measured': {'max_gb': 9.0, 'n': 1}})
        info = self._sync(_info('imager:t-collant', vram_provenance='heuristic'))
        self.assertEqual(info['vram_provenance'], 'heuristic')
        self.assertEqual(info['vram_measured']['max_gb'], 9.0)

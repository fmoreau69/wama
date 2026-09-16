"""
CATÉGORIE et TÂCHE des modèles Ollama — la découverte ne suppose plus (2026-09-16).

⚠ CE QUE CES GARDES PROTÈGENT. La découverte écrivait `task='text-generation'` pour TOUT ce qui
n'est pas un embedding, et en déduisait `model_type='llm'`. Mesuré : `ollama:glm-ocr:latest` (OCR)
déclarait donc exactement la même chose qu'un modèle de chat — et il a été TIRÉ pour une
conversation de l'assistant, au seul titre qu'il était le plus léger du lot. Le même modèle est
pourtant décrit précisément ailleurs (`reader:glm-ocr`, tâche `ocr`).

La tâche vient désormais d'une déclaration par famille (`FAMILLES_OLLAMA`), et la CATÉGORIE s'en
DÉRIVE par la table commune — plus de typage posé à la main.
"""
from django.test import TestCase

from wama.model_manager.models import AIModel, ModelType
from wama.model_manager.services.model_registry import ModelRegistry, _type_ollama
from wama.model_manager.services.model_selector import select_model


class TacheDeclareeTest(TestCase):

    def _caps(self, nom, brutes):
        return ModelRegistry._capacites_canoniques(set(brutes), nom)

    def test_un_modele_de_chat_reste_un_llm_qui_genere_du_texte(self):
        caps = self._caps('qwen3.8:latest', {'completion', 'tools', 'thinking', 'vision'})
        self.assertEqual('text-generation', caps['task'])
        self.assertEqual(ModelType.LLM, _type_ollama(caps['task']))
        self.assertTrue(caps['vision'], "un modèle de chat qui VOIT reste un llm + vision")

    def test_une_famille_declaree_impose_sa_tache_et_donc_sa_categorie(self):
        caps = self._caps('glm-ocr:latest', {'completion', 'tools', 'vision'})
        self.assertEqual('ocr', caps['task'])
        self.assertEqual(ModelType.OCR, _type_ollama(caps['task']))

    def test_une_specialite_declaree_survit_a_la_decouverte(self):
        caps = self._caps('translategemma:12b', {'completion', 'vision'})
        self.assertEqual(('text-generation', 'translation'),
                         (caps['task'], caps.get('specialisation')))

    def test_la_categorie_est_un_membre_de_l_enum_pas_une_chaine(self):
        """Le sync lit `.value` : une chaîne le faisait échouer en silence (mesuré le 16/09)."""
        for tache in ('text-generation', 'ocr', 'feature-extraction', 'inconnue', None):
            self.assertIsInstance(_type_ollama(tache), ModelType, tache)

    def test_un_embedding_reste_un_embedding(self):
        caps = self._caps('bge-m3:latest', {'embedding'})
        self.assertEqual('feature-extraction', caps['task'])
        self.assertEqual(ModelType.EMBEDDING, _type_ollama(caps['task']))


class TirageDeConversationTest(TestCase):
    """La conséquence qui a déclenché la correction : un modèle d'OCR ne doit pas être tiré
    pour une conversation, même s'il est le plus léger."""

    def setUp(self):
        AIModel.objects.create(model_key='ollama:chat:8b', name='chat', model_type='llm',
                               source='ollama', is_downloaded=True, vram_gb=8.0,
                               quality_index=50.0, capabilities={'completion': True,
                                                                 'task': 'text-generation'})
        AIModel.objects.create(model_key='ollama:ocr:1b', name='ocr', model_type='ocr',
                               source='ollama', is_downloaded=True, vram_gb=1.0,
                               quality_index=10.0, capabilities={'completion': True,
                                                                 'task': 'ocr'})

    def test_le_domaine_de_l_assistant_ne_retient_que_la_conversation(self):
        choix = select_model(model_type='llm', requires=['completion'], prefer_loaded=False,
                             vram_budget_gb=24.0, quality_intent=0)
        self.assertEqual('ollama:chat:8b', choix.model_key,
                         "curseur au plus RAPIDE : sans catégorie juste, l'OCR (1 Go) gagnait")

"""Tests de l'INTENTION du tirage (curseur rapide↔qualité, décision Fabien 01/09).

Le lot de candidats ne porte aucun indice de qualité → le classement retombe sur la VRAM
(règle de lot de `_rank_key`) : « meilleur » = « plus gros » ici, ce qui rend les attendus
lisibles. Budgets EXPLICITES partout — la VRAM libre réelle de la machine ne doit jamais
décider d'un résultat de test.
"""

from django.test import TestCase

from wama.model_manager.models import AIModel
from wama.model_manager.services import select_model


def _tts(model_key, name, vram_gb):
    return AIModel.objects.create(
        model_key=model_key, name=name, model_type='speech', source='synthesizer',
        vram_gb=vram_gb, is_available=True, is_downloaded=True,
        capabilities={'task': 'text-to-speech', 'modalities': ['audio']},
    )


class IntentionDuTirageTest(TestCase):

    def setUp(self):
        self.leger = _tts('synthesizer:tts-leger', 'TTS léger', 0.5)
        self.lourd = _tts('synthesizer:tts-lourd', 'TTS lourd', 4.0)

    def _tirer(self, **kwargs):
        kwargs.setdefault('prefer_loaded', False)   # la résidence réelle ne décide pas d'un test
        chosen = select_model(source='synthesizer', **kwargs)
        return chosen.model_key if chosen else None

    def test_fast_prend_le_plus_leger_qui_tient(self):
        self.assertEqual(self._tirer(vram_budget_gb=10, intent='fast'),
                         'synthesizer:tts-leger')

    def test_balanced_reste_le_comportement_historique(self):
        """Sans intention (ou 'balanced') : le plus qualitatif qui tient — inchangé."""
        self.assertEqual(self._tirer(vram_budget_gb=10), 'synthesizer:tts-lourd')
        self.assertEqual(self._tirer(vram_budget_gb=10, intent='balanced'),
                         'synthesizer:tts-lourd')

    def test_precise_ignore_le_budget_l_offload_est_assume(self):
        """Budget 1 Go : seul le léger tient — 'balanced' le prend, 'precise' prend quand
        même le meilleur (l'offload ou l'attente de ressources est le prix de la précision)."""
        self.assertEqual(self._tirer(vram_budget_gb=1), 'synthesizer:tts-leger')
        self.assertEqual(self._tirer(vram_budget_gb=1, intent='precise'),
                         'synthesizer:tts-lourd')

    def test_une_intention_inconnue_vaut_balanced_et_ne_leve_pas(self):
        self.assertEqual(self._tirer(vram_budget_gb=10, intent='turbo'),
                         'synthesizer:tts-lourd')

    def test_fast_departage_a_vram_egale_par_la_qualite(self):
        """Deux modèles au même poids : 'fast' ne tire pas au hasard, la qualité départage
        (ici le lot entier porte un indice → c'est lui qui ordonne)."""
        self.leger.quality_index = 10.0
        self.leger.save(update_fields=['quality_index'])
        self.lourd.quality_index = 20.0
        self.lourd.save(update_fields=['quality_index'])
        jumeau = _tts('synthesizer:tts-jumeau', 'TTS jumeau', 0.5)
        jumeau.quality_index = 30.0
        jumeau.save(update_fields=['quality_index'])
        self.assertEqual(self._tirer(vram_budget_gb=10, intent='fast'),
                         'synthesizer:tts-jumeau')

"""Tests du CURSEUR DE QUALITÉ (échelle continue 0-100, décision Fabien 02/09).

« L'intention n'est pas un branchement, c'est un poids dans le score » : chaque cran doit
pouvoir déplacer l'arbitrage. Le lot ne porte aucun indice de qualité (sauf dit) → le
classement retombe sur la VRAM (règle de lot), ce qui rend les attendus lisibles. Budgets
EXPLICITES partout — la VRAM libre réelle de la machine ne décide jamais d'un test.
"""

from django.test import TestCase

from wama.model_manager.models import AIModel
from wama.model_manager.services import select_model


def _tts(model_key, name, vram_gb, **extra):
    return AIModel.objects.create(
        model_key=model_key, name=name, model_type='speech', source='synthesizer',
        vram_gb=vram_gb, is_available=True, is_downloaded=True,
        capabilities={'task': 'text-to-speech', 'modalities': ['audio']}, **extra,
    )


class CurseurDeQualiteTest(TestCase):

    def setUp(self):
        self.leger = _tts('synthesizer:tts-leger', 'TTS léger', 0.5)
        self.lourd = _tts('synthesizer:tts-lourd', 'TTS lourd', 4.0)

    def _tirer(self, **kwargs):
        kwargs.setdefault('prefer_loaded', False)   # la résidence réelle ne décide pas d'un test
        chosen = select_model(source='synthesizer', **kwargs)
        return chosen.model_key if chosen else None

    def test_curseur_a_zero_prend_le_plus_leger_qui_tient(self):
        self.assertEqual(self._tirer(vram_budget_gb=10, quality_intent=0),
                         'synthesizer:tts-leger')

    def test_curseur_median_garde_le_comportement_historique(self):
        """À 50 (et sans curseur du tout) : le plus qualitatif qui tient — inchangé."""
        self.assertEqual(self._tirer(vram_budget_gb=10), 'synthesizer:tts-lourd')
        self.assertEqual(self._tirer(vram_budget_gb=10, quality_intent=50),
                         'synthesizer:tts-lourd')

    def test_au_dela_du_seuil_le_budget_cesse_de_borner(self):
        """Budget 1 Go : seul le léger tient — à 50 il gagne, à 100 la qualité prime
        quand même (l'offload ou l'attente de ressources est le prix assumé)."""
        self.assertEqual(self._tirer(vram_budget_gb=1, quality_intent=50),
                         'synthesizer:tts-leger')
        self.assertEqual(self._tirer(vram_budget_gb=1, quality_intent=100),
                         'synthesizer:tts-lourd')

    def test_chaque_cran_peut_deplacer_l_arbitrage_sur_un_lot_de_trois(self):
        """L'objection de Fabien aux 3 politiques : sur N candidats, tous doivent être
        atteignables. Trois modèles étagés en qualité ET en coût → trois crans du
        curseur rendent trois choix différents."""
        self.leger.quality_index = 10.0
        self.leger.save(update_fields=['quality_index'])
        moyen = _tts('synthesizer:tts-moyen', 'TTS moyen', 2.0, quality_index=30.0)
        self.lourd.quality_index = 40.0
        self.lourd.save(update_fields=['quality_index'])
        choix = {v: self._tirer(vram_budget_gb=10, quality_intent=v)
                 for v in (0, 55, 100)}
        self.assertEqual(choix[0], 'synthesizer:tts-leger')
        self.assertEqual(choix[55], moyen.model_key)
        self.assertEqual(choix[100], 'synthesizer:tts-lourd')

    def test_une_vram_inconnue_n_est_pas_gratuite(self):
        """Le défaut MESURÉ du 02/09 : Audio8 (vram_gb=0, jamais mesurée) battait Kokoro
        (0,5 mesuré) sur « rapide ». Une mesure absente vaut le PIRE coût du lot."""
        _tts('synthesizer:tts-inconnu', 'TTS sans mesure', 0)
        self.assertEqual(self._tirer(vram_budget_gb=10, quality_intent=0),
                         'synthesizer:tts-leger')

    def test_les_positions_nommees_et_l_inconnu_sont_toleres(self):
        """'fast'/'balanced'/'precise' (1ʳᵉ implémentation) et 'quality' résolvent vers
        leur position ; une valeur absurde vaut équilibré — jamais d'échec."""
        self.assertEqual(self._tirer(vram_budget_gb=10, quality_intent='fast'),
                         'synthesizer:tts-leger')
        self.assertEqual(self._tirer(vram_budget_gb=1, quality_intent='precise'),
                         'synthesizer:tts-lourd')
        self.assertEqual(self._tirer(vram_budget_gb=10, quality_intent='turbo'),
                         'synthesizer:tts-lourd')

    def test_a_cout_egal_la_qualite_departage(self):
        """Deux modèles au même poids : le curseur bas ne tire pas au hasard — la
        qualité départage (le lot entier porte un indice → c'est lui qui ordonne)."""
        self.leger.quality_index = 10.0
        self.leger.save(update_fields=['quality_index'])
        self.lourd.quality_index = 20.0
        self.lourd.save(update_fields=['quality_index'])
        jumeau = _tts('synthesizer:tts-jumeau', 'TTS jumeau', 0.5, quality_index=30.0)
        self.assertEqual(self._tirer(vram_budget_gb=10, quality_intent=0),
                         jumeau.model_key)

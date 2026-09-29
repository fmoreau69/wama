"""UNE seule règle de lecture de la table d'empreintes VRAM (2026-09-16).

La même table (`MODEL_SIZE_PRESETS`) était lue de deux façons :
- `preset_vram_gb` — la clé la PLUS SPÉCIFIQUE qui matche (les clés se préfixent entre elles :
  `qwen-image` ⊂ `qwen-image-edit`, `ltx-video` ⊂ `ltx-video-fp8`) ;
- `get_strategy_for_model` — le nom EXACT, défaut 4 Go.

Un appelant qui passe un identifiant de modèle plutôt qu'une clé de preset tombait donc sur
4 Go et faisait tenter le PLEIN GPU à un modèle de 14 à 23 Go — le débordement WDDM qui a fait
paniquer le noyau le 29/07. Le piège était LATENT (tous les appelants passent aujourd'hui une clé
de preset : `flux`, `cogvideox`, `sdxl`…) : ces gardes le ferment avant qu'un appelant n'y tombe.
"""
from unittest import mock

from django.test import SimpleTestCase

from wama.model_manager.services.memory_manager import (MODEL_SIZE_PRESETS, MemoryManager,
                                                        MemoryStrategy, preset_vram_gb)

CARTE_24_GO = {'total_gb': 24.0, 'free_gb': 23.5}


class LectureUniqueDesEmpreintesTest(SimpleTestCase):

    def _strategie(self, cle, headroom=4.0):
        with mock.patch.object(MemoryManager, 'get_gpu_memory_info', return_value=CARTE_24_GO):
            return MemoryManager.get_strategy_for_model(cle, headroom_gb=headroom)

    def test_un_IDENTIFIANT_de_modele_trouve_l_empreinte_de_sa_famille(self):
        """Le défaut fermé : `cogvideox-5b-i2v` ne tombe plus sur le défaut de 4 Go.

        21 Go + 4 de marge = 25 > 24 : le déchargement s'impose. Avec la lecture par nom EXACT,
        l'identifiant ne matchait rien, 4 Go étaient supposés, et le plein GPU était tenté.
        """
        self.assertEqual(preset_vram_gb('cogvideox-5b-i2v'), MODEL_SIZE_PRESETS['cogvideox'])
        self.assertEqual(self._strategie('cogvideox-5b-i2v'), MemoryStrategy.MODEL_OFFLOAD)

    def test_une_CLE_de_preset_donne_le_meme_verdict_qu_avant(self):
        """Non-régression : c'est ce que passent tous les appelants d'aujourd'hui."""
        self.assertEqual(self._strategie('cogvideox'), MemoryStrategy.MODEL_OFFLOAD)
        self.assertEqual(self._strategie('sdxl'), MemoryStrategy.FULL_GPU)

    def test_la_cle_la_PLUS_SPECIFIQUE_gagne_dans_les_deux_lectures(self):
        """`ltx-video` (18 Go) ⊂ `ltx-video-fp8` (8) : la générique gagnerait en ordre
        d'insertion, et enverrait en déchargement une variante quantisée qui TIENT sur la carte.

        Il faut une carte étroite (12 Go libres) pour que les deux verdicts diffèrent : sur une
        4090 au repos, 18 + 4 tient encore.
        """
        self.assertLess(MODEL_SIZE_PRESETS['ltx-video-fp8'], MODEL_SIZE_PRESETS['ltx-video'],
                        'prémisse : la clé spécifique est la PLUS LÉGÈRE des deux')
        self.assertEqual(preset_vram_gb('ltx-video-13b-0.9.8-distilled-fp8'),
                         MODEL_SIZE_PRESETS['ltx-video-fp8'])
        with mock.patch.object(MemoryManager, 'get_gpu_memory_info',
                               return_value={'total_gb': 24.0, 'free_gb': 12.0}):
            self.assertEqual(
                MemoryManager.get_strategy_for_model('ltx-video-13b-0.9.8-distilled-fp8',
                                                     headroom_gb=4.0),
                MemoryStrategy.FULL_GPU)
            self.assertEqual(
                MemoryManager.get_strategy_for_model('ltx-video-13b-0.9.8-distilled',
                                                     headroom_gb=4.0),
                MemoryStrategy.MODEL_OFFLOAD,
                'contre-épreuve : la version pleine, elle, impose le déchargement')

    def test_une_empreinte_INCONNUE_garde_le_defaut_historique(self):
        """4 Go : le comportement d'avant, pour ne rien changer aux appelants hors table."""
        self.assertIsNone(preset_vram_gb('modele-qui-nexiste-pas'))
        self.assertEqual(self._strategie('modele-qui-nexiste-pas'), MemoryStrategy.FULL_GPU)

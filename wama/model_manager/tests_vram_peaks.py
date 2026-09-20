"""Les DEUX pics et la cascade d'empreinte — décision A de Fabien (`PROJECT_STATUS §④A`, 16/09).

Chaque test tient une phrase de la décision, et les chiffres viennent du parc RÉEL (relevé
2026-09-19/20), pas d'un exemple inventé.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from wama.model_manager.services.memory_manager import (MemoryStrategy, model_footprint_gb,
                                                        peaks_from_weights)


def _row(*, weights=None, measured=None, vram_gb=0, key='imager:temoin'):
    return SimpleNamespace(
        model_key=key, vram_gb=vram_gb,
        extra_info={**({'weights': weights} if weights else {}),
                    **({'vram_measured': {'max_gb': measured}} if measured else {})})


class TwoPeaksTest(SimpleTestCase):

    def test_a_composed_model_has_two_footprints_not_one(self):
        """CogVideoX, mesuré : 20,15 Go de somme, 10,48 de plus gros composant. En plein GPU tout
        coexiste ; en déchargement un composant descend quand le suivant monte, et c'est le plus
        gros qui fixe le plafond. Un seul nombre ne peut pas dire les deux."""
        pics = peaks_from_weights({'total_gb': 20.15, 'largest_gb': 10.48})
        self.assertEqual(pics, {'full': 20.15, 'offload': 10.48},
                         "un pic est un FAIT du modèle : aucune marge ne s'y ajoute — ce qu'on "
                         "garde libre est une politique de la MACHINE, donc du gouverneur")

    def test_without_the_weights_no_peak_is_invented(self):
        self.assertEqual(peaks_from_weights({}), {})
        self.assertEqual(peaks_from_weights({'total_gb': 5.0}), {},
                         "sans le plus gros composant, le pic de déchargement est INCONNU")
        self.assertEqual(peaks_from_weights(None), {})


class FootprintCascadeTest(SimpleTestCase):

    def test_the_measure_never_LOWERS_the_footprint_under_the_source(self):
        """LE POINT SUBTIL de la décision A : « mesurée → source → estimée, **sans jamais
        descendre sous la valeur de la source** ». Ce n'est pas une priorité, c'est un `max` —
        parce que la mesure au chargement est celle d'UNE stratégie. `base.py` relève
        `memory_allocated() - before`, une RÉSIDENCE finale, et aucun `max_memory_allocated`
        n'existe dans le dépôt : la mesure est structurellement un PLANCHER, jamais un pic.
        La prendre pour l'empreinte ferait tenter un plein GPU au chargement suivant."""
        # mesure BASSE (relevée en déchargement) contre une source plus haute → la source gagne
        gb, prov = model_footprint_gb(_row(weights={'total_gb': 20.15, 'largest_gb': 10.48},
                                          measured=6.0))
        self.assertEqual((gb, prov), (10.48, 'source'))
        # mesure plus HAUTE que la source → c'est elle qui fait foi, et la provenance le dit
        gb, prov = model_footprint_gb(_row(weights={'total_gb': 20.15, 'largest_gb': 10.48},
                                          measured=18.0))
        self.assertEqual((gb, prov), (18.0, 'measured+source'))

    def test_the_strategy_decides_WHICH_peak_is_compared(self):
        """« C'est le pic que le filtre compare » — et le pic dépend de ce que le moteur SAIT
        faire. FastWan mesuré : 22,52 de somme, 10,58 de plus gros composant."""
        row = _row(weights={'total_gb': 22.52, 'largest_gb': 10.58})
        self.assertEqual(model_footprint_gb(row, offload=True), (10.58, 'source'))
        self.assertEqual(model_footprint_gb(row, offload=False), (22.52, 'source'))

    def test_each_rung_of_the_cascade_and_the_refusal_to_guess(self):
        self.assertEqual(model_footprint_gb(_row(measured=12.5)), (12.5, 'measured'))
        self.assertEqual(model_footprint_gb(_row(vram_gb=16)), (16.0, 'declared'))
        # rien de déclaré, mais une clé qui matche un preset de famille
        gb, prov = model_footprint_gb(_row(key='imager:cogvideox-5b-i2v'))
        self.assertEqual((gb, prov), (21.0, 'preset'))
        # RIEN du tout : `unknown`, et surtout pas un zéro. Un appelant ne doit pas conclure
        # « ça tient » d'une absence d'information (même règle que `weight_for_spec` → None).
        self.assertEqual(model_footprint_gb(_row(key='x:inconnu-total')), (None, 'unknown'))


class StrategyWithoutGuessworkTest(SimpleTestCase):

    def test_a_known_offload_peak_replaces_the_60_percent_guess(self):
        """Les 60 % / 30 % de `get_memory_strategy` devinaient « le plus gros composant tient ».
        Le ratio réel va de 47 % (FastWan) à 66 % (Hunyuan) : aucun pourcentage fixe ne pouvait
        le représenter. Avec le pic, la question devient exacte."""
        from unittest.mock import patch
        from wama.model_manager.services.memory_manager import MemoryManager
        carte = {'total_gb': 24.0, 'free_gb': 2.0, 'allocated_gb': 22.0, 'reserved_gb': 22.0}
        with patch.object(MemoryManager, 'get_gpu_memory_info', return_value=carte):
            # somme 22,5 + 2 de marge : ne tient pas ; plus gros composant 10,6 + 2 : tient
            self.assertEqual(
                MemoryManager.get_memory_strategy(22.52, headroom_gb=2.0, offload_peak_gb=10.58),
                MemoryStrategy.MODEL_OFFLOAD)
            # un plus gros composant qui ne tient PAS seul : il faut descendre à la couche
            self.assertEqual(
                MemoryManager.get_memory_strategy(60.0, headroom_gb=2.0, offload_peak_gb=30.0),
                MemoryStrategy.SEQUENTIAL_OFFLOAD)

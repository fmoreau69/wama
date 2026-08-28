"""
Mode « dépannage GPU » (`WAMA_GPU_SAFE_MODE`, resource_governor 2 bis) — réduction de la
superposition de charges sur le GPU partagé hôte/WSL pendant le diagnostic des crashs hôte
(INFRA_WSL_VS_WINDOWS §crashs).

CE QUE CES TESTS PROTÈGENT : l'interrupteur est un interrupteur de CONDITIONS — OFF doit
restituer le comportement nominal à l'octet (keep_alive None = défaut Ollama, aucun gate).
Le crash réel, lui, ne se teste pas : jamais de charge GPU lancée par une session.
"""
from unittest import mock

from django.test import TestCase, override_settings

from wama.common.services.resource_governor import pipeline_keep_alive, wait_for_free_vram


class InterrupteurPipelineTest(TestCase):

    @override_settings(WAMA_GPU_SAFE_MODE=True)
    def test_en_mode_depannage_ollama_decharge_sitot_la_reponse(self):
        self.assertEqual(pipeline_keep_alive(), '0')

    @override_settings(WAMA_GPU_SAFE_MODE=False)
    def test_hors_mode_depannage_le_defaut_ollama_est_restitue(self):
        # None = le payload ne porte PAS keep_alive (llm_utils l'omet) → défaut Ollama (~5 min),
        # comportement nominal à l'octet.
        self.assertIsNone(pipeline_keep_alive())


class AttenteVramMesureeTest(TestCase):

    def test_une_vram_suffisante_ne_fait_pas_attendre(self):
        with mock.patch('wama.common.services.resource_governor.effective_free_gb',
                        return_value=20.0):
            ok, libre = wait_for_free_vram(13.0, timeout_s=0.0)
        self.assertTrue(ok)
        self.assertEqual(libre, 20.0)

    def test_le_delai_epuise_rend_la_mesure_pour_une_erreur_DITE(self):
        with mock.patch('wama.common.services.resource_governor.effective_free_gb',
                        return_value=1.5):
            ok, libre = wait_for_free_vram(13.0, timeout_s=0.0)
        self.assertFalse(ok)
        self.assertEqual(libre, 1.5)

    def test_une_liberation_en_cours_d_attente_debloque(self):
        # Un résident qui expire (keep_alive Ollama, TTL de réservation) pendant l'attente.
        mesures = iter([2.0, 2.0, 18.0])
        with mock.patch('wama.common.services.resource_governor.effective_free_gb',
                        side_effect=lambda exclude=None: next(mesures)):
            ok, libre = wait_for_free_vram(13.0, timeout_s=60.0, poll_s=0.0)
        self.assertTrue(ok)
        self.assertEqual(libre, 18.0)

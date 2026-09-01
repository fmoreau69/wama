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


class DiffermentFauteDeVramTest(TestCase):
    """Re-programmer plutôt qu'ATTENDRE dans le worker (décision Fabien, 2026-09-01).

    `wait_for_free_vram()` DORT dans la tâche : elle immobilise un worker Celery. Acceptable
    pour un hoquet de 180 s (son seul appelant de production est le mode dépannage GPU du
    composer), inacceptable pour « la tâche se lancera quand les ressources seront
    disponibles » — N items en attente y feraient N workers bloqués, et la file GPU
    s'arrêterait, y compris pour les tâches légères qui passeraient.
    """

    def setUp(self):
        from wama.synthesizer.models import VoiceSynthesis
        from django.contrib.auth import get_user_model
        u = get_user_model().objects.create_user('diff_test', password='x')
        self.item = VoiceSynthesis.objects.create(user=u, text_content='bonjour')
        self.model = VoiceSynthesis

    def _ctx(self):
        from wama.common.utils.task_skeleton import TaskContext
        return TaskContext('synthesizer', self.model, self.item)

    def _task(self, essais=0):
        class _Retry(Exception):
            pass

        class _T:
            class request:
                retries = essais
            @staticmethod
            def retry(**kw):
                return _Retry(f"retry {kw}")
        return _T, _Retry

    def test_ressources_suffisantes_on_ne_differe_PAS(self):
        from wama.common.utils.task_skeleton import _differer_faute_de_vram
        T, _ = self._task()
        with mock.patch('wama.common.services.resource_governor.effective_free_gb',
                        return_value=20.0):
            differe = _differer_faute_de_vram(T, self._ctx(), self.item, self.model,
                                              self.item.pk, 'synthesizer', 4.0,
                                              'error_message')
        self.assertFalse(differe, "4 Go requis, 20 Go libres : rien ne justifie de différer")

    def test_ressources_insuffisantes_l_item_ATTEND_et_le_worker_est_rendu(self):
        from wama.common.utils.task_skeleton import _differer_faute_de_vram
        T, Retry = self._task()
        with mock.patch('wama.common.services.resource_governor.effective_free_gb',
                        return_value=1.0):
            with self.assertRaises(Retry):
                _differer_faute_de_vram(T, self._ctx(), self.item, self.model,
                                        self.item.pk, 'synthesizer', 24.0, 'error_message')
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'AWAITING_RESOURCES')
        # ⚠ Ce n'est PAS une erreur : on ne laisse pas de trace d'échec sur une attente.
        self.assertEqual(self.item.error_message, '')

    def test_au_bout_du_compte_on_RENONCE_EN_LE_DISANT(self):
        """Une attente non bornée est un blocage silencieux, pas de la patience."""
        from wama.common.utils.task_skeleton import (
            _differer_faute_de_vram, DIFFEREMENTS_MAX)
        T, _ = self._task(essais=DIFFEREMENTS_MAX)
        with mock.patch('wama.common.services.resource_governor.effective_free_gb',
                        return_value=1.0):
            differe = _differer_faute_de_vram(T, self._ctx(), self.item, self.model,
                                              self.item.pk, 'synthesizer', 24.0,
                                              'error_message')
        self.assertTrue(differe)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'FAILURE')
        # Le message DIT la sortie possible — jamais un échec nu, jamais un repli silencieux
        # vers un modèle plus léger (ce serait décider à la place de l'utilisateur).
        self.assertIn('24.0 Go requis', self.item.error_message)
        self.assertIn('qualité', self.item.error_message)

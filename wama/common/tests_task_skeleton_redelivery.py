"""Le squelette de tâche et la RE-LIVRAISON d'un report (2026-09-14).

POURQUOI. RUNNING est posé par les VUES de lancement, avant `.delay()`. Un item différé faute de
VRAM (`_differer_faute_de_vram` → `AWAITING_RESOURCES` → `task.retry`) repart sans repasser par
elles. Deux défauts en découlaient, invisibles tant que `vram_needed` n'est adopté par personne,
et certains dès qu'il le sera :
- l'item restait affiché « En attente de ressources » pendant TOUT son traitement — le
  commentaire du squelette affirmait que `ctx.progress(0)` basculait en RUNNING, ce qui est faux ;
- un report ANNULÉ entre-temps (item remis en attente, supprimé de la file, relancé autrement)
  était quand même traité à la re-livraison.

La première livraison, elle, ne doit RIEN changer : c'est le chemin de toutes les apps
aujourd'hui (converter, describer, reader).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.utils.task_skeleton import run_item_task


def _tache(essais):
    class _T:
        class request:
            id = 'tache-test'
            retries = essais
            delivery_info = {}
    return _T


class RelivraisonApresReportTest(TestCase):

    def setUp(self):
        from wama.synthesizer.models import VoiceSynthesis
        u = get_user_model().objects.create_user('relivraison_test', password='x')
        self.model = VoiceSynthesis
        self.item = VoiceSynthesis.objects.create(user=u, text_content='bonjour')

    def _lancer(self, statut, essais):
        """Lance le squelette ENTIER ; rend les statuts vus PAR LA GLU (donc pendant le traitement)."""
        self.model.objects.filter(pk=self.item.pk).update(status=statut)
        vus = []

        def glu(item, ctx):
            vus.append(self.model.objects.get(pk=item.pk).status)
            return {}

        # `close_old_connections()` ouvre le squelette : dans un `TestCase` (transaction tenue
        # ouverte), il fermerait la connexion du test — 1ᵉʳ run : 4 « connection is closed »,
        # ET une contre-épreuve rouge pour la même raison, donc vacuous. Neutralisé ici seul.
        from unittest import mock
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_tache(essais), app_id='synthesizer', model=self.model,
                          item_id=self.item.pk, process=glu)
        return vus

    def _statut(self):
        return self.model.objects.get(pk=self.item.pk).status

    def test_un_item_RELIVRE_apres_report_est_EN_COURS_pendant_son_traitement(self):
        self.assertEqual(self._lancer('AWAITING_RESOURCES', essais=1), ['RUNNING'],
                         "la card resterait « En attente de ressources » pendant le traitement")
        self.assertEqual(self._statut(), 'SUCCESS')

    def test_un_report_ANNULE_entre_temps_n_est_pas_traite(self):
        """L'utilisateur a arrêté l'item pendant l'attente : la re-livraison ne le relance pas."""
        self.assertEqual(self._lancer('PENDING', essais=1), [],
                         "un report annulé a été traité quand même")
        self.assertEqual(self._statut(), 'PENDING')

    def test_une_PREMIERE_livraison_ne_change_rien(self):
        """Le chemin de toutes les apps aujourd'hui : la vue a posé RUNNING avant `.delay()`."""
        self.assertEqual(self._lancer('RUNNING', essais=0), ['RUNNING'])
        self.assertEqual(self._statut(), 'SUCCESS')

    def test_un_item_EN_ATTENTE_n_est_jamais_bascule_en_cours_par_le_squelette(self):
        """Seul un item qui revient d'un report bascule ; un PENDING garde le comportement
        d'avant (le squelette ne décide pas à la place de la vue qui l'a lancé)."""
        self.assertEqual(self._lancer('PENDING', essais=0), ['PENDING'])

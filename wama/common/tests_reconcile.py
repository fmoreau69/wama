"""Réconciliation des tâches RUNNING orphelines — une tâche RÉUSSIE n'est pas une tâche morte.

⚠⚠ POURQUOI CE FICHIER (2026-09-07). Le scénario nocturne `<app>.batch_processing`, écrit la
veille, a trouvé un défaut RÉEL et visible par l'utilisateur : un lot de deux conversions de
0,3 s partait en « Traitement interrompu (worker arrêté) » alors que le journal du worker
disait « ✓ Terminé » pour les DEUX. Deux cards ROUGES, et les fichiers convertis à côté.

La cause tient en une ligne : `is_task_dead()` répond True pour l'état Celery **SUCCESS** — son
nom dit « terminal », pas « morte », et sa docstring PRÉVIENT qu'il demande « un délai de grâce
côté appelant ». `reconcile_orphaned_running` l'appelait sans aucun délai et basculait l'item en
ÉCHEC.

La course : la tâche publie son état au broker ET écrit le statut de son item — deux écritures,
deux instants. Un rechargement de page tombé entre les deux (et « Démarrer tout » RECHARGE, par
contrat de `queue-actions.js`) lisait l'item encore RUNNING et la tâche déjà terminée, puis
ÉCRASAIT le succès en échec.

Ces tests fixent les deux gardes. Sans eux, la correction se reperdrait au premier refactor —
c'est le genre de défaut qu'on ne retrouve qu'en le cherchant.
"""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from wama.common.utils import process_control


class TacheReussieTest(TestCase):
    """L'état SUCCESS ne doit JAMAIS produire un échec."""

    def setUp(self):
        self.user = User.objects.create_user('reconcile_test', 'r@test.local', 'x')
        from wama.converter.models import ConversionBatch, ConversionJob
        self.lot = ConversionBatch.objects.create(user=self.user, total=1, media_type='image')
        self.job = ConversionJob.objects.create(
            user=self.user, media_type='image', batch=self.lot, batch_row_index=0,
            status='RUNNING', task_id='tache-qui-a-reussi')

    def _reconcilier(self):
        from wama.converter.models import ConversionJob
        return process_control.reconcile_orphaned_running(
            [self.job], snapshot={'workers': (), 'task_ids': ()},
            error_field='error_message'), ConversionJob

    def test_une_tache_en_SUCCESS_ne_bascule_PAS_l_item_en_echec(self):
        """Le défaut mesuré : le travail a été FAIT, l'item ne doit pas devenir rouge."""
        with patch.object(process_control, 'is_task_dead', return_value=True), \
             patch.object(process_control, '_tache_reussie', return_value=True):
            n, Modele = self._reconcilier()
        self.assertEqual(0, n, "une tâche réussie a été comptée comme morte")
        self.assertEqual('RUNNING', Modele.objects.get(pk=self.job.pk).status,
                         "l'item a été basculé en échec alors que sa tâche avait RÉUSSI")

    def test_une_tache_en_ECHEC_bascule_bien_l_item(self):
        """La garde ne doit pas neutraliser le mécanisme : un vrai mort reste réconcilié."""
        with patch.object(process_control, 'is_task_dead', return_value=True), \
             patch.object(process_control, '_tache_reussie', return_value=False):
            n, Modele = self._reconcilier()
        self.assertEqual(1, n)
        frais = Modele.objects.get(pk=self.job.pk)
        self.assertEqual('FAILURE', frais.status)
        self.assertIn('interrompu', (frais.error_message or '').lower())

    def test_un_statut_qui_a_bouge_depuis_la_photo_n_est_PAS_ecrase(self):
        """La seconde garde : la tâche a fini son travail entre la lecture et l'écriture.

        C'est la fenêtre exacte qui laissait un FAILURE écraser un SUCCESS écrit une fraction
        de seconde plus tôt. L'objet en mémoire dit RUNNING, la BASE dit SUCCESS — c'est la
        base qui a raison.
        """
        from wama.converter.models import ConversionJob
        ConversionJob.objects.filter(pk=self.job.pk).update(status='SUCCESS')
        with patch.object(process_control, 'is_task_dead', return_value=True), \
             patch.object(process_control, '_tache_reussie', return_value=False):
            n, Modele = self._reconcilier()
        self.assertEqual(0, n)
        self.assertEqual('SUCCESS', Modele.objects.get(pk=self.job.pk).status,
                         "un succès déjà écrit en base a été écrasé par la réconciliation")

    def test_un_item_sans_task_id_est_ignore(self):
        """Contrat d'origine, préservé : peut-être tout juste démarré (cf. begin_processing)."""
        from wama.converter.models import ConversionJob
        self.job.task_id = ''
        self.job.save(update_fields=['task_id'])
        with patch.object(process_control, 'is_task_dead', return_value=True):
            n, Modele = self._reconcilier()
        self.assertEqual(0, n)
        self.assertEqual('RUNNING', Modele.objects.get(pk=self.job.pk).status)

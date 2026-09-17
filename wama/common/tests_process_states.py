"""Le vocabulaire d'états d'un PROCESS — première pièce de la marche P2 (`ROUTE §10.6`).

POURQUOI CE FICHIER (2026-09-17). Le modèle acté le 15/09 déclare SIX états (§10.6 4.2) et nomme
ce qui doit s'y aligner : l'exécuteur du studio (littéraux), son JS (3 couleurs) et le suivi de
passes du Lab (minuscules). Le commun n'en portait que CINQ — `STALE` manquait, alors que le Lab
l'avait déjà et que sa propre docstring portait la consigne d'alignement. Trois écritures du même
fait : c'est ce que P2 ferme, et P3 (le moteur commun) en dépend.

⚠ Ces gardes tiennent la FRONTIÈRE, pas seulement la présence du mot :
  • `STALE` n'entre PAS dans les `choices` des files (13 modèles les déclarent — une valeur
    qu'aucune file ne sait produire ferait naître 13 migrations pour rien) ;
  • il n'est NI « en attente » NI « final » : il a produit un résultat, mais il appelle une
    relance. Le compter comme terminé dirait « tout est à jour », ce qui est faux.
"""
from django.test import SimpleTestCase

from wama.common.models import (JOB_AWAITING_RESOURCES, JOB_FAILURE, JOB_PENDING,
                                JOB_RUNNING, JOB_STALE, JOB_STATUS_CHOICES,
                                JOB_STATUS_NOT_STARTED, JOB_STATUS_TERMINAL, JOB_SUCCESS,
                                PROCESS_STATUS_CHOICES)

#: Les six états de `WAMA_APP_GENERATION_ROUTE.md §10.6 4.2`, dans l'ordre du tableau.
SIX_ETATS = (JOB_PENDING, JOB_AWAITING_RESOURCES, JOB_RUNNING, JOB_SUCCESS, JOB_FAILURE,
             JOB_STALE)


class VocabulaireDeProcessTest(SimpleTestCase):

    def test_le_vocabulaire_de_process_porte_les_SIX_etats_actes(self):
        valeurs = [v for v, _ in PROCESS_STATUS_CHOICES]
        for etat in SIX_ETATS:
            self.assertIn(etat, valeurs, f'{etat} manque au vocabulaire de process (§10.6 4.2)')
        self.assertEqual(len(valeurs), 6, 'six états, pas un de plus')

    def test_chaque_etat_porte_un_LIBELLE_non_vide(self):
        """Le vocabulaire sert aussi l'UI : une valeur sans libellé se retrouve telle quelle
        à l'écran."""
        for valeur, libelle in PROCESS_STATUS_CHOICES:
            self.assertTrue(str(libelle).strip(), f'{valeur} sans libellé')

    def test_les_FILES_gardent_leurs_cinq_etats(self):
        """⚠ La frontière qui évite 13 migrations pour rien : `STALE` est l'état d'un PROCESS.
        Les files le recevront quand le moteur commun les portera (marche P6)."""
        valeurs = [v for v, _ in JOB_STATUS_CHOICES]
        self.assertEqual(len(valeurs), 5)
        self.assertNotIn(JOB_STALE, valeurs)

    def test_STALE_n_est_NI_en_attente_NI_final(self):
        """Il a produit un résultat (il n'attend pas) mais il appelle une relance (il n'est pas
        terminé). L'agrégation le traite à part : « au moins un STALE → card STALE » (§10.6 4.4)."""
        self.assertNotIn(JOB_STALE, JOB_STATUS_NOT_STARTED)
        self.assertNotIn(JOB_STALE, JOB_STATUS_TERMINAL)

    def test_STALE_n_est_pas_un_echec(self):
        """§10.6 4.3 : le résultat reste lisible et téléchargeable. Confondre les deux ferait
        proposer « relancer » là où il faut proposer « compléter ce qui est périmé »."""
        self.assertNotEqual(JOB_STALE, JOB_FAILURE)


class AlignementDuMondeLabTest(SimpleTestCase):
    """Le Lab avait `stale` AVANT le commun — c'est de lui que le modèle le reprend (§10.6 4.3)."""

    def test_les_cinq_etats_du_Lab_ont_leur_correspondant_au_commun(self):
        from wama_lab.cam_analyzer.models import AnalysisPass
        correspondance = {
            AnalysisPass.Status.PENDING: JOB_PENDING,
            AnalysisPass.Status.RUNNING: JOB_RUNNING,
            AnalysisPass.Status.COMPLETED: 'SUCCESS',
            AnalysisPass.Status.FAILED: JOB_FAILURE,
            AnalysisPass.Status.STALE: JOB_STALE,
        }
        valeurs_communes = {v for v, _ in PROCESS_STATUS_CHOICES}
        for etat_lab, etat_commun in correspondance.items():
            self.assertIn(etat_commun, valeurs_communes,
                          f'{etat_lab} (Lab) sans correspondant au vocabulaire commun')
        self.assertEqual(len(AnalysisPass.Status.choices), 5,
                         "le Lab a gagné un état : l'alignement est à refaire")

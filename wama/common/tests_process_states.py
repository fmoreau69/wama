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


class TableDAliasUNIQUETest(SimpleTestCase):
    """Le dépôt portait TROIS tables d'alias divergentes (`ROUTE §10.3`) et aucun test.

    La convergence du 2026-09-17 les ramène à une seule, au domicile du vocabulaire. Ces gardes
    tiennent ce qui n'était tenu par personne : la traduction des états du monde LAB (dont la
    table la plus consommée ignorait `COMPLETED`/`FAILED`), celle de `stale`, et le fait qu'une
    valeur inconnue ne soit PAS inventée.
    """

    def test_les_etats_STOCKES_du_Lab_se_traduisent_tous(self):
        """⚠ Ce sont des DONNÉES : 72 lignes en base au 17/09 (`completed` 57, `stale` 13,
        `pending` 2). On les TRADUIT à la lecture, on ne les renomme pas."""
        from wama.common.models import normalize_job_status
        attendu = {'pending': JOB_PENDING, 'running': JOB_RUNNING, 'completed': JOB_SUCCESS,
                   'failed': JOB_FAILURE, 'stale': JOB_STALE}
        for stocke, commun in attendu.items():
            self.assertEqual(normalize_job_status(stocke), commun, stocke)

    def test_les_litteraux_du_studio_et_des_apps_historiques_se_traduisent(self):
        from wama.common.models import normalize_job_status
        for brut, commun in (('RUNNING', JOB_RUNNING), ('SUCCESS', JOB_SUCCESS),
                             ('FAILURE', JOB_FAILURE), ('DONE', JOB_SUCCESS),
                             ('ERROR', JOB_FAILURE), ('PROCESSING', JOB_RUNNING),
                             ('STARTED', JOB_RUNNING)):
            self.assertEqual(normalize_job_status(brut), commun, brut)

    def test_une_valeur_INCONNUE_revient_telle_quelle_en_majuscules(self):
        """Non-régression : c'est le comportement des trois tables remplacées. Inventer un état
        serait pire que n'en pas connaître un."""
        from wama.common.models import normalize_job_status
        self.assertEqual(normalize_job_status('draft'), 'DRAFT')
        self.assertEqual(normalize_job_status(''), '')
        self.assertEqual(normalize_job_status(None), '')

    def test_les_DEUX_portes_publiques_donnent_le_meme_verdict(self):
        """`detail_registry.normalize_status` (journal, générateur de vues) et
        `batch_common.normalized_statuses` (lots) doivent lire la MÊME table — c'est
        précisément ce qui manquait : la première ignorait les états du Lab."""
        from types import SimpleNamespace
        from wama.common.utils.batch_common import normalized_statuses
        from wama.common.utils.detail_registry import normalize_status
        for brut in ('completed', 'stale', 'DONE', 'PROCESSING', 'inconnu'):
            self.assertEqual(normalize_status(brut),
                             normalized_statuses([SimpleNamespace(status=brut)])[0], brut)

    def test_le_journal_sait_LIBELLER_les_six_etats(self):
        """Un état absent de sa table tombait sur `capitalize()` — « Awaiting_resources » à
        l'écran. Les libellés viennent désormais du vocabulaire, écrits une seule fois."""
        from wama.common.services.journal import _ETATS_FR
        for etat in SIX_ETATS:
            self.assertTrue(_ETATS_FR.get(etat), f'{etat} sans libellé au journal')


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

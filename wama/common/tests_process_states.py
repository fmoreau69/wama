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
import ast
from unittest import mock

from django.test import SimpleTestCase, TestCase

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


def _generated_status_choices(src: str):
    """La valeur ÉVALUÉE des états du modèle généré — pas une sous-chaîne.

    (Idiome du dépôt, cf. `tests_codegen_lot._types_entree` : chercher le texte attesterait
    de la mise en forme du gabarit, pas de ce que l'app naissante déclarera.)

    ⚠ `models_gen` assemble par DEUX chemins, et ils n'écrivent pas la même forme : la
    fabrique à partir d'un modèle existant rend `choices=[…]` en ligne, celle qui part du
    manifeste seul rend une constante `STATUS_CHOICES` relue par le champ. Une garde qui n'en
    lit qu'une atteste d'un seul chemin — c'est le défaut que `tests_codegen_lot` documente
    (`WAMA_INGEST` perdu par un seul des deux rendus). On lit donc les deux.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and node.targets
                and getattr(node.targets[0], 'id', '') == 'STATUS_CHOICES'):
            return ast.literal_eval(node.value)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and node.targets
                and getattr(node.targets[0], 'id', '') == 'status'
                and isinstance(node.value, ast.Call)):
            for kw in node.value.keywords:
                if kw.arg == 'choices':
                    try:
                        return ast.literal_eval(kw.value)
                    except ValueError:      # `choices=STATUS_CHOICES` — déjà traité plus haut
                        return None
    return None


class UneAppGENEREEParleLeVocabulaireCommunTest(SimpleTestCase):
    """La génération portait une HUITIÈME écriture des libellés d'état (`models_gen.py:27`).

    Mesuré le 2026-09-17 : cette table n'avait que QUATRE états — une app neuve naissait donc
    incapable d'afficher `AWAITING_RESOURCES`, l'état que pose le gouverneur de ressources — et
    libellait `FAILURE` « Erreur » quand les 13 files du monde Médias affichent « Échec ».
    """

    def test_les_libelles_de_la_generation_VIENNENT_du_vocabulaire_commun(self):
        from wama.common.manifests.codegen.models_gen import _status_labels
        from wama.common.models import JOB_STATUS_CHOICES
        self.assertEqual(_status_labels(), dict(JOB_STATUS_CHOICES),
                         "la génération réécrit ses propres libellés d'état")

    def test_les_DEUX_chemins_de_generation_rendent_les_CINQ_etats_de_file(self):
        """Le juge est la sortie RENDUE : c'est elle qui devient le `models.py` de l'app.

        `render_models` dispatche sur la présence d'un modèle EXISTANT : une app déjà là est
        rendue par INTROSPECTION (`choices=[…]` recopiés en ligne), une app créée DE ZÉRO par
        le squelette A5 (constante `STATUS_CHOICES`, seul chemin qui lise les libellés de la
        génération). Les deux doivent rendre le MÊME vocabulaire — sinon régénérer une app et
        en créer une neuve ne donnent pas la même app. C'est le piège que `tests_codegen_lot`
        a déjà payé une fois sur `WAMA_INGEST`, perdu par un seul des deux rendus.
        """
        import copy

        from wama.common.manifests.codegen.models_gen import render_models
        from wama.common.manifests.ingest import extract
        from wama.common.models import JOB_AWAITING_RESOURCES, JOB_STATUS_CHOICES
        manifest = extract('app', 'converter')
        if not manifest:
            self.skipTest('manifeste de converter inextricable')
        from_scratch = copy.deepcopy(manifest)
        from_scratch.get('body', {}).pop('data', None)   # force le squelette « création de zéro »
        for path, payload in (('introspecté', manifest), ('squelette A5', from_scratch)):
            with self.subTest(chemin=path):
                src, reason = render_models(payload)
                if not src:
                    self.skipTest(f'models non générés ({path}) : {reason}')
                choices = _generated_status_choices(src)
                self.assertIsNotNone(choices, f'{path} : aucun état déclaré dans le modèle rendu')
                self.assertEqual(choices, list(JOB_STATUS_CHOICES), path)
                self.assertIn(JOB_AWAITING_RESOURCES, [v for v, _ in choices],
                              f"{path} : l'app ne saurait pas afficher l'état du gouverneur")
                self.assertEqual(dict(choices)['FAILURE'], 'Échec',
                                 f'{path} : libellé divergent de celui des files (« Erreur »)')


class LExecuteurDuStudioParleLeVocabulaireCommunTest(TestCase):
    """L'exécuteur écrivait ses états en littéraux et COMPARAIT des chaînes brutes (§10.6 4.2).

    ⚠ La garde qui compte est la seconde : elle tient un défaut qui ne se voit PAS à
    l'exécution locale. Les runners du studio rendent aujourd'hui le vocabulaire commun, donc
    tout passe ; une app qui répondrait `DONE` ou `ERROR` — deux valeurs que la table d'alias
    connaît et que trois apps historiques emploient — ne satisfaisait aucune des deux
    comparaisons, et la boucle tournait jusqu'au délai de 30 MINUTES avant de lever « délai
    dépassé ». Un symptôme qui accuse la lenteur du modèle, jamais la lecture de l'état.
    """

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create_user('studio_etats', password='x')

    def test_l_executeur_n_ecrit_plus_aucun_etat_en_LITTERAL(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / 'wama/studio/tasks.py').read_text(encoding='utf-8')
        for literal in ("status='RUNNING'", "status='SUCCESS'", "status='FAILURE'",
                        "run.status = 'RUNNING'", "run.status = 'SUCCESS'"):
            self.assertNotIn(literal, src,
                             f"{literal} réintroduit : l'exécuteur se remet à écrire un "
                             f"vocabulaire à lui")

    def test_un_runner_qui_repond_DONE_termine_le_noeud_au_lieu_d_attendre_le_delai(self):
        from wama.common.models import JOB_SUCCESS
        from wama.studio.models import StudioRun
        from wama.studio.tasks import run_pipeline_task

        fake_runner = {
            'create': lambda user, inputs, params: 4242,
            'start': lambda user, item_id: None,
            # `DONE` : le vocabulaire d'une app historique, connu de la table d'alias.
            'poll': lambda user, item_id: {'status': 'DONE', 'progress': 100,
                                           'output': 'studio/output.txt'},
            'output_type': 'document',
        }
        run = StudioRun.objects.create(
            user=self.user,
            graph={'nodes': [{'id': 'n1', 'app': 'converter'}], 'links': []})
        # ⚠ Délai de nœud à ZÉRO : sans lui, une régression ne se manifesterait qu'au bout de
        # 30 min. Avec lui, elle échoue en une seconde — et sur le bon message.
        with mock.patch('wama.studio.services.runners.runner_for', return_value=fake_runner), \
                mock.patch('wama.studio.tasks.POLL_INTERVAL_S', 0), \
                mock.patch('wama.studio.tasks.NODE_TIMEOUT_S', 0):
            run_pipeline_task(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, JOB_SUCCESS, run.error_message)
        self.assertEqual(run.node_states['n1']['status'], JOB_SUCCESS)
        self.assertEqual(run.node_states['n1']['output'], 'studio/output.txt')

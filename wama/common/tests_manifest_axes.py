"""Le kind `dataset` : plan d'expérience (`axes`) et corpus sans flux temporel.

⚠ POURQUOI CE MODULE. Le kind `dataset` existe depuis longtemps et n'avait **AUCUN test** (mesuré
le 2026-08-26 : `validate_dataset_body` n'était cité que par son propre module). Il portait donc
deux défauts qu'aucune morsure ne pouvait exposer :

  ① `signals` était exigé NON VIDE — ce qui refusait un corpus de **questionnaires**, méthodologie
     entière du laboratoire (panel en ligne, tests psychotechniques) qui n'a aucun flux temporel ;
  ② rien ne décrivait la position d'un jeu dans un PLAN D'EXPÉRIENCE, alors que la comparaison par
     groupes de population est une pratique quasi systématique.

Référence : `WAMA_DATA_WORLD.md §13`. Les tests nomment un COMPORTEMENT (convention WAMA : une
méthode `test_*` ne se lit que dans un rapport d'échec, donc en français).
"""
from django.test import SimpleTestCase

from wama.common.manifests.builtin.dataset import AXIS_ROLES, validate_dataset_body


def _corpus(**extra) -> dict:
    """Un corps minimal VALIDE, que chaque test dégrade sur un seul point."""
    body = {
        'source': {'type': 'rtmaps', 'ref': '/srv/corpus/ENA'},
        'signals': [{'id': 'vitesse', 'data_type': 'timeseries'}],
    }
    body.update(extra)
    return body


#: Clé du manifeste `model` cité en provenance d'un facteur appris.
#: ⚠ Extraite en constante à dessein : écrite en littéral, la paire `'key': '<valeur>'` déclenche
#: la règle `generic-api-key` du garde anti-fuite pré-commit (faux positif mesuré le 2026-08-26,
#: entropie 3,93). On déplace la valeur — on ne désarme pas un détecteur pour une fixture.
MODELE_PROFILS = 'profils-conduite-v1'

PLAN = [
    {'key': 'participant', 'role': 'observation'},
    {'key': 'groupe_age', 'role': 'factor', 'contains': 'participant',
     'manipulated': False, 'levels': 'ref:groupes_age', 'derived_from': 'age'},
    {'key': 'scenario', 'role': 'factor', 'crosses': 'participant',
     'manipulated': True, 'counterbalanced': True},
    {'key': 'age', 'role': 'attribute', 'attached_to': 'participant'},
]
TABLES = {'groupes_age': {'values': ['jeunes', 'ages']}}


class PlanDExperience(SimpleTestCase):

    def test_le_plan_complet_du_laboratoire_est_accepte(self):
        errs = validate_dataset_body(_corpus(axes=PLAN, reference_tables=TABLES))
        self.assertEqual(errs, [])

    def test_les_trois_roles_sont_le_vocabulaire_ferme(self):
        self.assertEqual(set(AXIS_ROLES), {'observation', 'factor', 'attribute'})

    def test_un_role_hors_vocabulaire_est_refuse(self):
        axes = [{'key': 'groupe', 'role': 'block'}]
        errs = validate_dataset_body(_corpus(axes=axes))
        self.assertTrue(any("role 'block' invalide" in e for e in errs), errs)

    def test_un_renvoi_vers_un_axe_inexistant_est_refuse(self):
        axes = [{'key': 'p', 'role': 'observation'},
                {'key': 'g', 'role': 'factor', 'contains': 'participant'}]
        errs = validate_dataset_body(_corpus(axes=axes))
        self.assertTrue(any("axe inconnu 'participant'" in e for e in errs), errs)

    def test_niche_ou_croise_jamais_les_deux(self):
        axes = [{'key': 'p', 'role': 'observation'},
                {'key': 'g', 'role': 'factor', 'contains': 'p', 'crosses': 'p'}]
        errs = validate_dataset_body(_corpus(axes=axes))
        self.assertTrue(any('niché OU croisé' in e for e in errs), errs)

    def test_un_attribut_ne_porte_pas_les_cles_de_facteur(self):
        axes = [{'key': 'p', 'role': 'observation'},
                {'key': 'age', 'role': 'attribute', 'manipulated': True}]
        errs = validate_dataset_body(_corpus(axes=axes))
        self.assertTrue(any("'manipulated' n'a de sens que sur un facteur" in e for e in errs), errs)

    def test_un_facteur_ne_se_rattache_pas_par_attached_to(self):
        axes = [{'key': 'p', 'role': 'observation'},
                {'key': 'g', 'role': 'factor', 'attached_to': 'p'}]
        errs = validate_dataset_body(_corpus(axes=axes))
        self.assertTrue(any("'attached_to' n'a de sens que sur un attribute" in e for e in errs), errs)

    def test_des_niveaux_declares_ref_pointent_une_table_qui_existe(self):
        axes = [{'key': 'p', 'role': 'observation'},
                {'key': 'g', 'role': 'factor', 'contains': 'p', 'levels': 'ref:absente'}]
        errs = validate_dataset_body(_corpus(axes=axes, reference_tables=TABLES))
        self.assertTrue(any("reference_tables['absente'] absente" in e for e in errs), errs)

    def test_manipulated_est_un_booleen_pas_une_chaine(self):
        axes = [{'key': 'p', 'role': 'observation'},
                {'key': 'g', 'role': 'factor', 'contains': 'p', 'manipulated': 'oui'}]
        errs = validate_dataset_body(_corpus(axes=axes))
        self.assertTrue(any('manipulated doit être un booléen' in e for e in errs), errs)

    def test_le_grain_doit_etre_declare(self):
        axes = [{'key': 'g', 'role': 'factor'}]
        errs = validate_dataset_body(_corpus(axes=axes))
        self.assertTrue(any("le grain du corpus" in e for e in errs), errs)


class NidificationRecursive(SimpleTestCase):
    """`contains` est RÉCURSIF — une situation de suivi de véhicule porte des sous-situations.
    Ce qui est interdit n'est pas la profondeur, c'est la BOUCLE."""

    def test_trois_niveaux_emboites_sont_acceptes(self):
        axes = [{'key': 'essai', 'role': 'observation'},
                {'key': 'suivi', 'role': 'factor', 'contains': 'essai'},
                {'key': 'campagne', 'role': 'factor', 'contains': 'suivi'}]
        self.assertEqual(validate_dataset_body(_corpus(axes=axes)), [])

    def test_un_cycle_de_nidification_est_refuse(self):
        axes = [{'key': 'p', 'role': 'observation'},
                {'key': 'a', 'role': 'factor', 'contains': 'b'},
                {'key': 'b', 'role': 'factor', 'contains': 'a'}]
        errs = validate_dataset_body(_corpus(axes=axes))
        self.assertTrue(any('cycle de nidification' in e for e in errs), errs)


class PlusieursUnitesDObservation(SimpleTestCase):
    """Deux grains NON emboîtés coexistent (dyade conducteur+passager, plusieurs sujets codés
    dans une même observation). Autorisé — mais alors plus rien d'implicite."""

    def test_deux_grains_avec_rattachements_explicites_sont_acceptes(self):
        axes = [{'key': 'conducteur', 'role': 'observation'},
                {'key': 'passager', 'role': 'observation'},
                {'key': 'trajet', 'role': 'factor', 'crosses': 'conducteur'},
                {'key': 'age', 'role': 'attribute', 'attached_to': 'passager'}]
        self.assertEqual(validate_dataset_body(_corpus(axes=axes)), [])

    def test_deux_grains_rendent_le_rattachement_obligatoire(self):
        axes = [{'key': 'conducteur', 'role': 'observation'},
                {'key': 'passager', 'role': 'observation'},
                {'key': 'trajet', 'role': 'factor'}]
        errs = validate_dataset_body(_corpus(axes=axes))
        self.assertTrue(any('rattachement' in e and 'obligatoire' in e for e in errs), errs)

    def test_un_seul_grain_laisse_le_rattachement_sous_entendu(self):
        axes = [{'key': 'participant', 'role': 'observation'},
                {'key': 'scenario', 'role': 'factor'}]
        self.assertEqual(validate_dataset_body(_corpus(axes=axes)), [])


class FacteurDeriveDUnModele(SimpleTestCase):
    """Un profil de conducteur issu d'un clustering EST un facteur — ses niveaux viennent d'un
    modèle appris et non du protocole. `derived_from` porte la provenance
    (cf. `WAMA_APPRENTISSAGE.md`)."""

    def test_un_facteur_peut_deriver_d_un_manifeste_model(self):
        axes = [{'key': 'conducteur', 'role': 'observation'},
                {'key': 'profil', 'role': 'factor', 'contains': 'conducteur',
                 'manipulated': False,
                 'derived_from': {'kind': 'model', 'key': MODELE_PROFILS}}]
        self.assertEqual(validate_dataset_body(_corpus(axes=axes)), [])

    def test_une_provenance_de_modele_malformee_est_refusee(self):
        axes = [{'key': 'c', 'role': 'observation'},
                {'key': 'profil', 'role': 'factor', 'contains': 'c',
                 'derived_from': {'kind': 'model'}}]
        errs = validate_dataset_body(_corpus(axes=axes))
        self.assertTrue(any('référence de manifeste malformée' in e for e in errs), errs)


class CorpusSansFluxTemporel(SimpleTestCase):
    """Le déblocage des QUESTIONNAIRES : un panel en ligne n'a aucun signal."""

    def test_un_corpus_de_questionnaires_sans_signals_est_accepte(self):
        body = {
            'source': {'type': 'csv', 'ref': '/srv/corpus/panel2026'},
            'axes': [{'key': 'repondant', 'role': 'observation'},
                     {'key': 'vague', 'role': 'factor', 'crosses': 'repondant'},
                     {'key': 'score_nasa_tlx', 'role': 'attribute', 'attached_to': 'repondant'}],
        }
        self.assertEqual(validate_dataset_body(body), [])

    def test_un_dataset_sans_signals_NI_axes_reste_refuse(self):
        body = {'source': {'type': 'csv', 'ref': '/srv/x'}}
        errs = validate_dataset_body(body)
        self.assertTrue(any('dataset vide' in e for e in errs), errs)

    def test_les_signaux_restent_valides_quand_ils_sont_la(self):
        body = _corpus(signals=[{'id': 'v', 'data_type': 'inexistant'}])
        errs = validate_dataset_body(body)
        self.assertTrue(any('hors taxonomie' in e for e in errs), errs)

"""Tests de la brique de NOMS DÉRIVÉS (`wama_data/core/noms.py`).

Doctrine : `WAMA_DATA_WORLD.md §9ter.6 B7` — le nom se DÉRIVE des paramètres, il ne se saisit pas.

⚠ Ce fichier existe parce que l'audit A (§9sexies) a trouvé la doctrine appliquée par **quatre
règles dans trois lieux**, dont une écrite en dur dans une f-string. Le test central n'est donc pas
sur une fonction : c'est `UniciteTest`, qui vérifie qu'il n'en reste **qu'un seul domicile**.
"""
import unittest
from pathlib import Path

from .naming import abbreviate, as_int, annex_name, join_name, derived_name, normalize


class RegleTest(unittest.TestCase):

    def test_nom_produit(self):
        self.assertEqual(derived_name('vitesse', 'mean'), 'vitesse_mean')

    def test_nom_de_jonction_reproduit_la_graphie_d_origine(self):
        # `app.tddTable1.Value(1:3) '_' app.tddTable2.Value(1:3) '_' inf2 '_' sup2`
        self.assertEqual(join_name('debut_bloc', 'fin_bloc', 0, 0), 'deb_fin_0_0')

    def test_les_offsets_non_entiers_sont_conserves(self):
        self.assertEqual(join_name('debut', 'fin', -2.5, 10), 'deb_fin_-2.5_10')

    def test_nom_annexe(self):
        self.assertEqual(annex_name('vitesse', 'calc_per_segment'),
                         'vitesse_calc_per_segment')

    def test_deux_reglages_differents_ne_peuvent_pas_partager_un_nom(self):
        self.assertNotEqual(join_name('debut', 'fin', 0, 15),
                            join_name('debut', 'fin', 0, 45))
        self.assertNotEqual(annex_name('a', 'f'), annex_name('b', 'f'))

    def test_memes_reglages_meme_nom(self):
        self.assertEqual(join_name('debut', 'fin', 0, 15),
                         join_name('debut', 'fin', 0, 15))


class NormaliserTest(unittest.TestCase):
    """Point de passage UNIQUE de la mise en forme — deux variantes produiraient deux noms."""

    def test_minuscules_et_separateurs(self):
        self.assertEqual(normalize('ET(C1, OU(C2, C3))'), 'et_c1_ou_c2_c3')

    def test_pas_de_soulignes_doubles_ni_de_bords(self):
        self.assertEqual(normalize('  (a)  ,  (b)  '), 'a_b')

    def test_idempotent(self):
        once = normalize('ET(C1, C2)')
        self.assertEqual(normalize(once), once)

    def test_texte_vide(self):
        self.assertEqual(normalize(''), '')
        self.assertEqual(normalize(None), '')


class HelpersTest(unittest.TestCase):

    def test_abreger_prend_trois_caracteres_en_minuscules(self):
        self.assertEqual(abbreviate('DEBUT_bloc'), 'deb')
        self.assertEqual(abbreviate('ab'), 'ab')
        self.assertEqual(abbreviate(''), '')

    def test_entier_supprime_la_decimale_inutile(self):
        self.assertEqual(as_int(0.0), '0')
        self.assertEqual(as_int(15), '15')
        self.assertEqual(as_int(-2.5), '-2.5')


class UniciteTest(unittest.TestCase):
    """⚠ LE test de ce fichier : un seul domicile pour la règle de nommage.

    L'audit A a trouvé `derived_name` dans l'adaptateur, `join_name`/`chain_name` dans le cœur,
    et une f-string en dur dans `vue.py`. Ces contrôles empêchent la dispersion de recommencer.
    """

    def test_les_reexports_pointent_LA_MEME_fonction(self):
        # `conditions.py` et l'adaptateur du Calculator réexportent — ils ne redéfinissent pas.
        from .conditions import join_name as depuis_conditions
        from ..functions.temporal.calculation import derived_name as depuis_adaptateur
        self.assertIs(depuis_conditions, join_name)
        self.assertIs(depuis_adaptateur, derived_name)

    def test_nom_chaine_delegue_la_normalisation(self):
        from .conditions import parse, chain_name, render
        arbre = parse('ET(C1, C2)', ['C1', 'C2'])
        self.assertEqual(chain_name(arbre), normalize(render(arbre)))

    def test_la_brique_n_a_AUCUNE_dependance(self):
        # C'est la condition pour que `conditions.py` l'importe sans cycle. Un import de plus ici
        # et `chain_name` ne pourrait plus déléguer.
        import ast
        import inspect

        from . import naming
        arbre = ast.parse(inspect.getsource(naming))
        importes = [n for n in ast.walk(arbre) if isinstance(n, (ast.Import, ast.ImportFrom))]
        noms_importes = [getattr(n, 'module', None) or '' for n in importes]
        self.assertEqual([m for m in noms_importes if m != '__future__'], [],
                         f"la brique de noms a gagné une dépendance : {noms_importes}")


class NomsAbandonnesD28Test(unittest.TestCase):
    """⚠ LA GARDE DE LA MIGRATION D28 (2026-08-26) — l'API du monde est passée à l'anglais.

    Même doctrine que la garde D17 (`containers/tests_containers.py::NomAbandonneTest`) : *un
    renommage ne casse rien, il rend FAUX* — une occurrence réintroduite ne lèverait jamais seule.

    ⚠ MAIS le texte brut ne peut pas servir ici : les anciens noms (`jonction`, `marges`,
    `autour`…) vivent LÉGITIMEMENT dans la prose française des docstrings. La garde est donc
    TOKENISÉE — elle ne regarde que les identifiants (NAME) et les chaînes-clés EXACTES, jamais
    la prose. C'est le même arbitrage que le moteur de la migration elle-même (§14.1.4).
    """

    #: Identifiants français retirés de l'API — un NAME qui réapparaît est une régression.
    NOMS_ABANDONNES = frozenset({
        'autour', 'jonction', 'conditionnelle', 'masque_hysteresis', 'bascules', 'etats',
        'present_dans', 'chevauche', 'ouverts', 'marges', 'marges_spatiales',
        'appliquer', 'glissant', 'derivee', 'cumul', 'par_segment', 'echantillons_du_segment',
        'operateurs_pour', 'valider', 'evaluer', 'rendre', 'analyser', 'condition_depuis_dict',
        'nom_chaine', 'sorte_de_colonne', 'sorte', 'sortes', 'libelle', 'operande',
        'Operateur', 'OPERATEURS', 'Connecteur', 'Arbre', 'NUMERIQUE', 'TEXTE', 'BOOLEEN',
        'rejouer', 'Protocole', 'SessionCodage', 'Modificateur', 'Comportement',
        'ProtocoleInvalide', 'CodageRefuse', 'en_dict', 'depuis_dict', 'comportements',
        'sujets', 'touche', 'couleur', 'requis', 'exclusif', 'est_etat', 'gestes',
        'Colonne', 'Identite', 'Regroupement', 'Fichier', 'exporter', 'apercu', 'lignes',
        'enregistrer_format', 'formats_disponibles', 'formats_ecrivables',
        'declaration_depuis_dict', 'colonnes',
        'manquant', 'presentes', 'abreger', 'normaliser', 'nom_produit', 'nom_jonction',
        'nom_annexe', 'distances_a_point', 'abscisse_curviligne', 'distance_a_point',
        'type_par_defaut', 'frame_depuis_signal', 'frame_depuis_referentiel',
        'signal_depuis_frame', 'adjoindre', 'change_la_cle_temporelle', 'Piste', 'Fenetre',
        'ColonneDerivee', 'Vue', 'Resultat', 'Ecart', 'signaux_declares', 'axes_declares',
        'attributs_de_coordonnees', 'situer', 'verifier', 'charger', 'raison_absence',
        'BASE_REELLE', 'temps_en_secondes', 'modules_lecteurs', 'ecrire', 'Rapport',
        'Contexte', 'Entree', 'SchemaConteneur', 'SchemaTrip', 'SchemaWdat',
        'enregistrer_schema', 'schemas_disponibles', 'extensions_ecrivables', 'schema_pour',
        'modules_schemas', 'valeur_sql', 'nom_table', 'mesurer', 'cle', 'nom',
        'segments_autour', 'segments_jonction', 'segments_conditionnels', 'segments_etats',
        'segments_present_dans', 'segments_marges', 'segments_marges_spatiales',
        'chaine_vers_segments', 'chaine_vers_events', 'codage_rejouer', 'codage_evenements',
        'codage_accord', 'calcul_glissant', 'calcul_derivee', 'calcul_cumul',
        'calcul_par_segment',
    })

    #: Chaînes-contrat retirées (clés de catalogue, jetons d'opérateurs et de statistiques,
    #: clés de dicts sérialisés) — comparées à ÉGALITÉ sur le contenu de la chaîne.
    CLES_ABANDONNEES = frozenset({
        'segment_autour_event', 'segment_jonction', 'segment_conditionnel', 'segment_etats',
        'segment_present_dans', 'segment_marges', 'segment_marges_spatiales',
        'segment_chaine_conditionnelle', 'event_chaine_conditionnelle', 'distance_a_point',
        'calcul_glissant', 'calcul_derivee', 'calcul_cumul', 'calcul_par_segment',
        'codage_segments', 'codage_evenements', 'codage_accord',
        # ⚠ 'contient' N'Y EST PAS : le `libelle` UI de l'opérateur `contains` est le mot
        # français « contient » (légitime — les libellés restent français), et il est
        # indiscernable de l'ancien JETON par égalité de chaîne. Les 7 autres jetons texte
        # suffisent à attraper une réintroduction de la famille.
        'ne_contient_pas', 'commence_par', 'ne_commence_pas_par', 'finit_par',
        'ne_finit_pas_par', 'non_vide', 'moyenne', 'mediane', 'ecart_type', 'etendue',
        'duree_min', 'trou_tolere', 'fenetre_s', 'colonne_code', 'fin_de_session',
        'depuis_debut', 'depuis_fin', 'fermer_dernier', 'montantes', 'descendantes',
    })

    #: Fichiers autorisés à prononcer un identifiant abandonné, et pourquoi — liste courte,
    #: nominative, vérifiée par `test_aucune_derogation_d28_PERIMEE`.
    DEROGATIONS = {
        'core/tests_naming.py': "la garde doit nommer ce qu'elle interdit",
        'apps.py': "FRONTIÈRE SUBSTRAT — `Registre(cle=…)` et `Resultat` sont l'API française "
                   "de `wama/common/registries.py` (dette consignée, §REPRISE 22/08 pending #2) ; "
                   "elle se renomme AVEC le substrat, jamais depuis ici",
    }

    def _fautes(self):
        import io
        import tokenize
        monde = Path(__file__).resolve().parents[1]
        fautes = {}
        for f in sorted(monde.rglob('*.py')):
            if '__pycache__' in str(f):
                continue
            rel = f.relative_to(monde).as_posix()
            if rel in self.DEROGATIONS:
                continue
            src = f.read_text(encoding='utf-8')
            vus = []
            for t in tokenize.generate_tokens(io.StringIO(src).readline):
                if t.type == tokenize.NAME and t.string in self.NOMS_ABANDONNES:
                    vus.append(f"{t.start[0]}:{t.string}")
                elif t.type == tokenize.STRING and t.string[:1] in ("'", '"') \
                        and t.string.strip('\'"') in self.CLES_ABANDONNEES:
                    vus.append(f"{t.start[0]}:{t.string}")
            if vus:
                fautes[rel] = vus
        return fautes

    def test_aucun_identifiant_ni_cle_d_avant_D28_ne_survit(self):
        fautes = self._fautes()
        self.assertEqual(fautes, {},
                         "identifiant ou clé d'AVANT la migration D28 réintroduit — et ça ne "
                         f"lèvera jamais tout seul : {fautes}")

    def test_aucune_derogation_d28_PERIMEE(self):
        monde = Path(__file__).resolve().parents[1]
        for rel in self.DEROGATIONS:
            self.assertTrue((monde / rel).exists(),
                            f"dérogation sans objet — le fichier {rel} n'existe plus")


if __name__ == '__main__':
    unittest.main()

"""Tests de l'Exporter — le pivot long → large de `WAMA_DATA_WORLD.md §6.7`.

Les cas reprennent la forme RÉELLE du livrable mesuré en §6.7 (fenêtres `0_15`, `15_30`…, une
ligne par passation, colonnes préfixées `0_15.*`), et les pièges viennent des résidus lus dans
BIND : une variable demandée que l'export ne sait pas écrire, et une occurrence qui en écrase
une autre faute de rang.
"""
import unittest

from .export import (SEPARATEUR, decimer, en_lignes, nom_de_colonne, pivot_large)


LONG = [
    {'trip_id': 'P01', 'nom': '0_15', 'moyenne': 72.3, 'max': 91},
    {'trip_id': 'P01', 'nom': '15_30', 'moyenne': 68.1, 'max': 88},
    {'trip_id': 'P02', 'nom': '0_15', 'moyenne': 75.0, 'max': 93},
]


class NommageTest(unittest.TestCase):

    def test_la_forme_est_celle_du_livrable_reel(self):
        # §6.7 : « colonnes préfixées "0_15.*" ». Reprise, pas inventée.
        self.assertEqual(nom_de_colonne('0_15', 'moyenne'), f'0_15{SEPARATEUR}moyenne')

    def test_le_rang_n_apparait_QU_A_PARTIR_DE_2(self):
        # Une numérotation systématique rendrait illisible un fichier lu dans un tableur.
        self.assertEqual(nom_de_colonne('freinage', 'max', 1), 'freinage.max')
        self.assertEqual(nom_de_colonne('freinage', 'max', 2), 'freinage#2.max')


class PivotTest(unittest.TestCase):

    def test_une_ligne_par_PASSATION_les_fenetres_cote_a_cote(self):
        larges, colonnes = pivot_large(LONG, cle_ligne=['trip_id'], cle_colonne='nom',
                                       mesures=['moyenne', 'max'])
        self.assertEqual(len(larges), 2, "3 segments, 2 passations → 2 lignes")
        self.assertEqual(larges[0]['trip_id'], 'P01')
        self.assertEqual(larges[0]['0_15.moyenne'], 72.3)
        self.assertEqual(larges[0]['15_30.max'], 88)
        self.assertIn('0_15.moyenne', colonnes)

    def test_une_combinaison_absente_reste_ABSENTE_et_non_zero(self):
        """P02 n'a pas de fenêtre 15_30. Une fenêtre non observée et une fenêtre mesurée à zéro
        ne se corrigent pas de la même façon, et rien dans un tableur ne les distingue."""
        larges, _ = pivot_large(LONG, cle_ligne=['trip_id'], cle_colonne='nom',
                                mesures=['moyenne'])
        p02 = [l for l in larges if l['trip_id'] == 'P02'][0]
        self.assertNotIn('15_30.moyenne', p02)

    def test_une_valeur_manquante_n_ecrit_PAS_la_colonne(self):
        lignes = [{'trip_id': 'P01', 'nom': 'a', 'moyenne': None},
                  {'trip_id': 'P01', 'nom': 'b', 'moyenne': float('nan')}]
        larges, _ = pivot_large(lignes, cle_ligne=['trip_id'], cle_colonne='nom',
                                mesures=['moyenne'])
        self.assertNotIn('a.moyenne', larges[0])
        self.assertNotIn('b.moyenne', larges[0], "NaN est une absence, pas une mesure")

    def test_une_occurrence_REPETEE_n_en_ecrase_pas_une_autre(self):
        """Le trou que la branche morte de `buildHeader` tentait de boucher.

        Deux occurrences du même segment dans une passation : sans rang, la seconde écraserait
        la première en silence — et le livrable perdrait la moitié de ses mesures.
        """
        lignes = [{'trip_id': 'P01', 'nom': 'freinage', 'max': 10},
                  {'trip_id': 'P01', 'nom': 'freinage', 'max': 20},
                  {'trip_id': 'P01', 'nom': 'freinage', 'max': 30}]
        larges, _ = pivot_large(lignes, cle_ligne=['trip_id'], cle_colonne='nom', mesures=['max'])
        self.assertEqual(larges[0]['freinage.max'], 10)
        self.assertEqual(larges[0]['freinage#2.max'], 20)
        self.assertEqual(larges[0]['freinage#3.max'], 30)

    def test_le_rang_est_LOCAL_a_une_passation(self):
        # Sinon le second participant hériterait du compteur du premier, et ses colonnes
        # seraient décalées d'un cran — un décalage silencieux, donc invisible à la relecture.
        lignes = [{'trip_id': 'P01', 'nom': 'x', 'v': 1},
                  {'trip_id': 'P02', 'nom': 'x', 'v': 2}]
        larges, _ = pivot_large(lignes, cle_ligne=['trip_id'], cle_colonne='nom', mesures=['v'])
        self.assertEqual(larges[0]['x.v'], 1)
        self.assertEqual(larges[1]['x.v'], 2, "P02 repart au rang 1")

    def test_l_identite_peut_porter_PLUSIEURS_colonnes(self):
        # BIND écrit `id_participant` ET `id_scenario` côte à côte : l'identité d'une ligne de
        # livrable n'est pas toujours un seul champ.
        lignes = [{'p': 'P01', 's': 'A', 'nom': 'x', 'v': 1},
                  {'p': 'P01', 's': 'B', 'nom': 'x', 'v': 2}]
        larges, colonnes = pivot_large(lignes, cle_ligne=['p', 's'], cle_colonne='nom',
                                       mesures=['v'])
        self.assertEqual(len(larges), 2, "même participant, scénarios différents → 2 lignes")
        self.assertEqual(colonnes[:2], ['p', 's'])

    def test_l_ordre_des_passations_est_celui_d_arrivee(self):
        # Un livrable dont les lignes se réordonnent d'un export à l'autre est incomparable.
        larges, _ = pivot_large(LONG, cle_ligne=['trip_id'], cle_colonne='nom',
                                mesures=['moyenne'])
        self.assertEqual([l['trip_id'] for l in larges], ['P01', 'P02'])

    def test_une_colonne_demandee_mais_ABSENTE_est_une_erreur_NOMMEE(self):
        """La leçon directe du `if strcmp(var_name,'HRinterp')` de BIND : demander une variable
        que l'export ne sait pas écrire y produit un fichier sans mesures, en silence."""
        with self.assertRaises(ValueError) as e:
            pivot_large(LONG, cle_ligne=['trip_id'], cle_colonne='nom', mesures=['inexistante'])
        self.assertIn('inexistante', str(e.exception))

    def test_une_identite_vide_est_refusee(self):
        with self.assertRaises(ValueError):
            pivot_large(LONG, cle_ligne=[], cle_colonne='nom', mesures=['moyenne'])

    def test_aucune_mesure_est_refuse(self):
        with self.assertRaises(ValueError):
            pivot_large(LONG, cle_ligne=['trip_id'], cle_colonne='nom', mesures=[])

    def test_un_corpus_vide_ne_leve_pas(self):
        larges, colonnes = pivot_large([], cle_ligne=['trip_id'], cle_colonne='nom',
                                       mesures=['moyenne'])
        self.assertEqual(larges, [])
        self.assertEqual(colonnes, ['trip_id'])


class AplatissementTest(unittest.TestCase):

    def test_l_en_tete_est_la_premiere_ligne(self):
        larges, colonnes = pivot_large(LONG, cle_ligne=['trip_id'], cle_colonne='nom',
                                       mesures=['moyenne'])
        tableau = en_lignes(larges, colonnes)
        self.assertEqual(tableau[0], colonnes)
        self.assertEqual(len(tableau), len(larges) + 1)

    def test_un_trou_s_ecrit_VIDE_et_non_zero(self):
        # Dans un tableur, une cellule vide se lit « pas de donnée » ; `0` se lit comme une mesure.
        larges, colonnes = pivot_large(LONG, cle_ligne=['trip_id'], cle_colonne='nom',
                                       mesures=['moyenne'])
        tableau = en_lignes(larges, colonnes)
        ligne_p02 = tableau[2]
        self.assertIn('', ligne_p02)


class DecimationTest(unittest.TestCase):

    def test_garde_une_ligne_sur_n(self):
        self.assertEqual(decimer(list(range(10)), 3), [0, 3, 6, 9])

    def test_le_defaut_n_enleve_RIEN(self):
        # Contrairement au `subSampling = 1000` écrit en dur dans le batch de BIND.
        self.assertEqual(decimer([1, 2, 3]), [1, 2, 3])

    def test_un_pas_nul_ou_negatif_est_refuse(self):
        with self.assertRaises(ValueError):
            decimer([1, 2, 3], 0)

"""Tests du Calculator — les DEUX modes de `WAMA_DATA_WORLD.md §6.7`.

Les cas visent les endroits où un calcul se trompe SANS erreur : un trou de données rempli de
valeurs plausibles, un segment ouvert compté comme une durée observée, une fenêtre exprimée en
échantillons qui change de sens d'un flux à l'autre. Un calcul faux qui lève est bénin ; un
calcul faux qui rend un flottant crédible ne se découvre qu'à la publication.
"""
import math
import unittest

from .calculation import (STATISTIQUES, appliquer, cumul, derivee, echantillons_du_segment,
                          glissant, par_segment)


class VocabulaireCommunTest(unittest.TestCase):
    """Une statistique doit dire la MÊME chose dans les deux modes — c'est le point de conception."""

    def test_la_meme_statistique_donne_la_meme_valeur_dans_les_deux_modes(self):
        times = [0.0, 1.0, 2.0, 3.0, 4.0]
        valeurs = [10.0, 20.0, 30.0, 40.0, 50.0]
        # Mode ② sur un segment couvrant tout, et mode ① sur une fenêtre couvrant tout.
        segment = par_segment([{'start': 0.0, 'end': 4.0}], times, valeurs, ['moyenne'])[0]
        fenetre = glissant(times, valeurs, 100.0, 'moyenne')[2]
        self.assertEqual(segment['moyenne'], fenetre)
        self.assertEqual(segment['moyenne'], 30.0)

    def test_une_statistique_inconnue_NOMME_les_disponibles(self):
        # Un message qui dit seulement « inconnue » oblige à ouvrir le code pour écrire la suite.
        with self.assertRaises(ValueError) as e:
            appliquer('moyenne_geometrique', [1.0])
        self.assertIn('moyenne', str(e.exception))

    def test_le_minimum_de_points_est_DECLARE_pas_decide_par_l_appelant(self):
        # `delta` sur un seul point vaudrait 0 — « pas de variation » alors qu'on n'a rien observé.
        self.assertIsNone(appliquer('delta', [5.0]))
        self.assertEqual(appliquer('delta', [5.0, 8.0]), 3.0)
        self.assertIsNone(appliquer('ecart_type', [5.0]))
        # `nombre` est le seul défini sur l'ensemble vide : compter zéro mesure est une réponse.
        self.assertEqual(appliquer('nombre', []), 0)
        self.assertIsNone(appliquer('moyenne', []))

    def test_toute_statistique_declaree_est_calculable(self):
        # Garde anti-« vert sur du vide » : le jour où l'on en ajoute une, elle est éprouvée ici
        # sans qu'on ait à y penser.
        self.assertGreaterEqual(len(STATISTIQUES), 10)
        for nom in STATISTIQUES:
            with self.subTest(statistique=nom):
                self.assertIsNotNone(appliquer(nom, [1.0, 2.0, 3.0]))


class GlissantTest(unittest.TestCase):

    def test_la_fenetre_est_une_DUREE_donc_independante_de_la_cadence(self):
        """LE point : deux flux à cadences différentes, même fenêtre de 2 s, même moyenne.

        Une fenêtre en nombre d'échantillons donnerait ici deux résultats différents pour la même
        question — et c'est précisément ce que WAMA Data existe pour éviter.
        """
        lent = glissant([0.0, 1.0, 2.0], [0.0, 10.0, 20.0], 2.0, 'moyenne')
        rapide = glissant([0.0, 0.5, 1.0, 1.5, 2.0], [0.0, 5.0, 10.0, 15.0, 20.0], 2.0, 'moyenne')
        self.assertEqual(lent[1], 10.0)
        self.assertEqual(rapide[2], 10.0)

    def test_la_fenetre_causale_ne_lit_PAS_l_avenir(self):
        times = [0.0, 1.0, 2.0, 3.0]
        valeurs = [0.0, 0.0, 100.0, 100.0]
        causale = glissant(times, valeurs, 1.0, 'moyenne', centre=False)
        # À t=1 le saut n'a pas encore eu lieu : une fenêtre causale l'ignore.
        self.assertEqual(causale[1], 0.0)
        centree = glissant(times, valeurs, 2.0, 'moyenne', centre=True)
        self.assertGreater(centree[1], 0.0, "une fenêtre centrée voit l'échantillon suivant")

    def test_un_trou_ne_produit_pas_une_valeur_calculee_sur_un_point(self):
        times = [0.0, 1.0, 2.0, 10.0]
        valeurs = [1.0, 2.0, 3.0, 99.0]
        sortie = glissant(times, valeurs, 2.0, 'moyenne', min_points=2)
        self.assertIsNone(sortie[3], "isolé dans sa fenêtre — donc pas de statistique")
        self.assertIsNotNone(sortie[1])

    def test_une_valeur_absente_est_ignoree_et_non_comptee_pour_zero(self):
        times = [0.0, 1.0, 2.0]
        sortie = glissant(times, [10.0, None, 20.0], 10.0, 'moyenne')
        self.assertEqual(sortie[0], 15.0, "la moyenne porte sur les valeurs PRÉSENTES")
        sortie_nan = glissant(times, [10.0, float('nan'), 20.0], 10.0, 'moyenne')
        self.assertEqual(sortie_nan[0], 15.0, "NaN est une absence, pas une valeur")

    def test_une_fenetre_entierement_absente_rend_absent_et_non_zero(self):
        sortie = glissant([0.0, 1.0], [None, None], 10.0, 'moyenne')
        self.assertEqual(sortie, [None, None])

    def test_la_colonne_produite_reste_alignee_sur_le_signal(self):
        # Condition pour pouvoir l'adjoindre : une longueur différente serait inexploitable.
        times = [0.0, 1.0, 2.0, 3.0, 4.0]
        self.assertEqual(len(glissant(times, [1.0] * 5, 2.0, 'moyenne')), len(times))

    def test_des_temps_non_croissants_sont_REFUSES(self):
        # Le résultat serait faux sans erreur — la dichotomie suppose l'ordre.
        with self.assertRaises(ValueError):
            glissant([0.0, 2.0, 1.0], [1.0, 2.0, 3.0], 1.0)

    def test_une_fenetre_nulle_ou_negative_est_refusee(self):
        with self.assertRaises(ValueError):
            glissant([0.0], [1.0], 0.0)

    def test_des_longueurs_differentes_sont_refusees(self):
        with self.assertRaises(ValueError):
            glissant([0.0, 1.0], [1.0], 1.0)


class DeriveeTest(unittest.TestCase):

    def test_une_pente_constante_donne_une_derivee_constante(self):
        times = [0.0, 1.0, 2.0, 3.0]
        d = derivee(times, [0.0, 2.0, 4.0, 6.0])
        for i, v in enumerate(d):
            with self.subTest(indice=i):
                self.assertAlmostEqual(v, 2.0)

    def test_deux_echantillons_au_MEME_instant_ne_donnent_pas_un_infini(self):
        # Une cadence irrégulière en produit ; un `inf` contaminerait toute statistique en aval.
        d = derivee([0.0, 0.0, 1.0], [1.0, 5.0, 9.0])
        self.assertIsNone(d[0])
        for v in d:
            if v is not None:
                self.assertFalse(math.isinf(v))

    def test_un_voisin_absent_rend_absent(self):
        d = derivee([0.0, 1.0, 2.0], [1.0, None, 3.0])
        self.assertIsNotNone(d[1], "la différence centrée saute la valeur manquante du milieu")
        self.assertIsNone(d[0], "le bord dépend du voisin immédiat, absent ici")

    def test_un_signal_trop_court_ne_leve_pas(self):
        self.assertEqual(derivee([0.0], [1.0]), [None])
        self.assertEqual(derivee([], []), [])


class CumulTest(unittest.TestCase):

    def test_un_signal_constant_donne_valeur_fois_duree(self):
        c = cumul([0.0, 1.0, 2.0, 3.0], [2.0, 2.0, 2.0, 2.0])
        self.assertAlmostEqual(c[-1], 6.0)

    def test_le_premier_point_vaut_zero(self):
        # L'intégrale d'un instant à lui-même, quelle que soit la valeur du signal.
        self.assertEqual(cumul([5.0, 6.0], [42.0, 42.0])[0], 0.0)

    def test_un_trou_n_invente_pas_d_aire(self):
        avec_trou = cumul([0.0, 1.0, 2.0], [2.0, None, 2.0])
        # Aucun intervalle complet : le cumul se maintient à 0 au lieu d'interpoler 4.0.
        self.assertEqual(avec_trou[-1], 0.0)


class ParSegmentTest(unittest.TestCase):

    TIMES = [0.0, 1.0, 2.0, 3.0, 4.0]
    VALEURS = [10.0, 20.0, 30.0, 40.0, 50.0]

    def test_un_jeu_d_indicateurs_par_segment_dans_l_ordre_recu(self):
        jeux = par_segment([{'start': 0.0, 'end': 1.0}, {'start': 3.0, 'end': 4.0}],
                           self.TIMES, self.VALEURS, ['moyenne'])
        self.assertEqual([j['moyenne'] for j in jeux], [15.0, 45.0])

    def test_les_bornes_sont_INCLUSIVES_des_deux_cotes(self):
        # Même convention que `chevauche` du Segmenter — deux conventions se contrediraient.
        jeu = par_segment([{'start': 1.0, 'end': 2.0}], self.TIMES, self.VALEURS, ['nombre'])[0]
        self.assertEqual(jeu['nombre'], 2)

    def test_un_segment_SANS_echantillon_rend_absent_et_non_zero(self):
        """La faute qui remplit une colonne de zéros crédibles là où il n'y a pas eu de mesure."""
        jeu = par_segment([{'start': 100.0, 'end': 200.0}], self.TIMES, self.VALEURS,
                          ['moyenne', 'somme'])[0]
        self.assertIsNone(jeu['moyenne'])
        self.assertIsNone(jeu['somme'], "la somme de rien n'est pas 0")
        self.assertEqual(jeu['n'], 0, "`n` dit POURQUOI l'indicateur est absent")

    def test_un_segment_OUVERT_n_a_pas_de_duree_observee(self):
        """Doctrine héritée du codage : une durée refermée par la fin de l'enregistrement n'est
        pas une durée mesurée. Les confondre fausse toute statistique de durée."""
        jeu = par_segment([{'start': 2.0, 'end': None}], self.TIMES, self.VALEURS, ['moyenne'])[0]
        self.assertIsNone(jeu['duree'])
        self.assertTrue(jeu['tronque'])
        self.assertEqual(jeu['moyenne'], 40.0, "il agrège tout de même jusqu'au dernier échantillon")

    def test_un_segment_ferme_porte_sa_duree_et_n_est_pas_tronque(self):
        jeu = par_segment([{'start': 1.0, 'end': 3.0}], self.TIMES, self.VALEURS, ['moyenne'])[0]
        self.assertEqual(jeu['duree'], 2.0)
        self.assertFalse(jeu['tronque'])

    def test_une_fin_en_NaN_est_lue_comme_OUVERTE(self):
        # Le piège pandas : `None` mêlé à des flottants devient `NaN` à l'aller-retour.
        jeu = par_segment([{'start': 2.0, 'end': float('nan')}], self.TIMES, self.VALEURS)[0]
        self.assertTrue(jeu['tronque'])
        self.assertIsNone(jeu['duree'])

    def test_plusieurs_statistiques_en_une_passe(self):
        jeu = par_segment([{'start': 0.0, 'end': 4.0}], self.TIMES, self.VALEURS,
                          ['moyenne', 'min', 'max', 'nombre'])[0]
        self.assertEqual((jeu['moyenne'], jeu['min'], jeu['max'], jeu['nombre']),
                         (30.0, 10.0, 50.0, 5))

    def test_les_champs_de_service_accompagnent_TOUJOURS_le_resultat(self):
        jeu = par_segment([{'start': 0.0, 'end': 1.0}], self.TIMES, self.VALEURS)[0]
        for champ in ('n', 'duree', 'tronque'):
            self.assertIn(champ, jeu)

    def test_les_valeurs_absentes_ne_comptent_pas_dans_n(self):
        jeu = par_segment([{'start': 0.0, 'end': 2.0}], [0.0, 1.0, 2.0], [10.0, None, 30.0],
                          ['moyenne'])[0]
        self.assertEqual(jeu['n'], 2)
        self.assertEqual(jeu['moyenne'], 20.0)

    def test_aucun_segment_rend_aucun_jeu(self):
        self.assertEqual(par_segment([], self.TIMES, self.VALEURS), [])

    def test_une_statistique_inconnue_est_refusee_AVANT_tout_calcul(self):
        with self.assertRaises(ValueError):
            par_segment([{'start': 0.0, 'end': 1.0}], self.TIMES, self.VALEURS, ['inexistante'])


class EchantillonsTest(unittest.TestCase):

    def test_une_fin_inconnue_vaut_l_infini(self):
        # Convention du Segmenter (`present_dans`, `chevauche`) — reprise, pas re-tranchée.
        dans = echantillons_du_segment({'start': 1.0, 'end': None}, [0.0, 1.0, 2.0], [1, 2, 3])
        self.assertEqual(dans, [2, 3])

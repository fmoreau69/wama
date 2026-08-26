"""Tests de la brique de NOMS DÉRIVÉS (`wama_data/core/noms.py`).

Doctrine : `WAMA_DATA_WORLD.md §9ter.6 B7` — le nom se DÉRIVE des paramètres, il ne se saisit pas.

⚠ Ce fichier existe parce que l'audit A (§9sexies) a trouvé la doctrine appliquée par **quatre
règles dans trois lieux**, dont une écrite en dur dans une f-string. Le test central n'est donc pas
sur une fonction : c'est `UniciteTest`, qui vérifie qu'il n'en reste **qu'un seul domicile**.
"""
import unittest

from .noms import abreger, entier, nom_annexe, nom_jonction, nom_produit, normaliser


class RegleTest(unittest.TestCase):

    def test_nom_produit(self):
        self.assertEqual(nom_produit('vitesse', 'mean'), 'vitesse_mean')

    def test_nom_de_jonction_reproduit_la_graphie_d_origine(self):
        # `app.tddTable1.Value(1:3) '_' app.tddTable2.Value(1:3) '_' inf2 '_' sup2`
        self.assertEqual(nom_jonction('debut_bloc', 'fin_bloc', 0, 0), 'deb_fin_0_0')

    def test_les_offsets_non_entiers_sont_conserves(self):
        self.assertEqual(nom_jonction('debut', 'fin', -2.5, 10), 'deb_fin_-2.5_10')

    def test_nom_annexe(self):
        self.assertEqual(nom_annexe('vitesse', 'calc_per_segment'),
                         'vitesse_calc_per_segment')

    def test_deux_reglages_differents_ne_peuvent_pas_partager_un_nom(self):
        self.assertNotEqual(nom_jonction('debut', 'fin', 0, 15),
                            nom_jonction('debut', 'fin', 0, 45))
        self.assertNotEqual(nom_annexe('a', 'f'), nom_annexe('b', 'f'))

    def test_memes_reglages_meme_nom(self):
        self.assertEqual(nom_jonction('debut', 'fin', 0, 15),
                         nom_jonction('debut', 'fin', 0, 15))


class NormaliserTest(unittest.TestCase):
    """Point de passage UNIQUE de la mise en forme — deux variantes produiraient deux noms."""

    def test_minuscules_et_separateurs(self):
        self.assertEqual(normaliser('ET(C1, OU(C2, C3))'), 'et_c1_ou_c2_c3')

    def test_pas_de_soulignes_doubles_ni_de_bords(self):
        self.assertEqual(normaliser('  (a)  ,  (b)  '), 'a_b')

    def test_idempotent(self):
        once = normaliser('ET(C1, C2)')
        self.assertEqual(normaliser(once), once)

    def test_texte_vide(self):
        self.assertEqual(normaliser(''), '')
        self.assertEqual(normaliser(None), '')


class HelpersTest(unittest.TestCase):

    def test_abreger_prend_trois_caracteres_en_minuscules(self):
        self.assertEqual(abreger('DEBUT_bloc'), 'deb')
        self.assertEqual(abreger('ab'), 'ab')
        self.assertEqual(abreger(''), '')

    def test_entier_supprime_la_decimale_inutile(self):
        self.assertEqual(entier(0.0), '0')
        self.assertEqual(entier(15), '15')
        self.assertEqual(entier(-2.5), '-2.5')


class UniciteTest(unittest.TestCase):
    """⚠ LE test de ce fichier : un seul domicile pour la règle de nommage.

    L'audit A a trouvé `nom_produit` dans l'adaptateur, `nom_jonction`/`nom_chaine` dans le cœur,
    et une f-string en dur dans `vue.py`. Ces contrôles empêchent la dispersion de recommencer.
    """

    def test_les_reexports_pointent_LA_MEME_fonction(self):
        # `conditions.py` et l'adaptateur du Calculator réexportent — ils ne redéfinissent pas.
        from .conditions import nom_jonction as depuis_conditions
        from ..functions.temporal.calculation import nom_produit as depuis_adaptateur
        self.assertIs(depuis_conditions, nom_jonction)
        self.assertIs(depuis_adaptateur, nom_produit)

    def test_nom_chaine_delegue_la_normalisation(self):
        from .conditions import analyser, nom_chaine, rendre
        arbre = analyser('ET(C1, C2)', ['C1', 'C2'])
        self.assertEqual(nom_chaine(arbre), normaliser(rendre(arbre)))

    def test_la_brique_n_a_AUCUNE_dependance(self):
        # C'est la condition pour que `conditions.py` l'importe sans cycle. Un import de plus ici
        # et `nom_chaine` ne pourrait plus déléguer.
        import ast
        import inspect

        from . import noms
        arbre = ast.parse(inspect.getsource(noms))
        importes = [n for n in ast.walk(arbre) if isinstance(n, (ast.Import, ast.ImportFrom))]
        noms_importes = [getattr(n, 'module', None) or '' for n in importes]
        self.assertEqual([m for m in noms_importes if m != '__future__'], [],
                         f"la brique de noms a gagné une dépendance : {noms_importes}")


if __name__ == '__main__':
    unittest.main()

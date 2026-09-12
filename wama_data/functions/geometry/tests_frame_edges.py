"""Bords d'image touchés par une bbox — la notion « l'objet SORT du champ ».

Ce qui est gardé ici n'est pas l'arithmétique (elle est triviale) mais les DÉCISIONS :
  - une bbox invalide n'est PAS une sortie de champ (sinon une donnée manquante se lirait
    comme un objet qui s'en va, et le levier de continuité d'aire s'effondrerait dessus) ;
  - le haut et le bas ne sont pas des bords LATÉRAUX (ils ne tronquent pas la largeur) ;
  - la marge reste un argument : les deux consommateurs historiques ont 6 et 8 px, et
    l'extraction ne devait RIEN changer à leur comportement.

    python3 -m unittest wama_data.functions.geometry.tests_frame_edges
"""
import unittest

from .frame_edges import DEFAULT_MARGIN_PX, bbox_edges, touches_side_edge


class BordsTouchesTest(unittest.TestCase):

    W, H = 384, 248

    def test_une_bbox_au_centre_ne_touche_AUCUN_bord(self):
        self.assertEqual(bbox_edges([100, 100, 200, 180], self.W, self.H), frozenset())

    def test_chaque_bord_est_detectable_SEPAREMENT(self):
        for bb, attendu in (([0, 100, 50, 180], 'left'),
                            ([330, 100, 384, 180], 'right'),
                            ([100, 0, 200, 60], 'top'),
                            ([100, 200, 200, 248], 'bottom')):
            with self.subTest(bord=attendu):
                self.assertEqual(bbox_edges(bb, self.W, self.H), frozenset([attendu]))

    def test_un_objet_qui_remplit_l_image_touche_les_QUATRE(self):
        self.assertEqual(bbox_edges([0, 0, 384, 248], self.W, self.H),
                         frozenset({'left', 'right', 'top', 'bottom'}))

    def test_une_bbox_INVALIDE_n_est_PAS_une_sortie_de_champ(self):
        """🔴 La décision qui compte : l'absence de mesure et le départ d'un objet sont deux
        choses. Les confondre ferait lire « il sort du champ » sur une donnée manquante."""
        for bb in (None, [], [1, 2], 'nawak', [None, None, None, None]):
            with self.subTest(bbox=bb):
                self.assertEqual(bbox_edges(bb, self.W, self.H), frozenset())
                self.assertFalse(touches_side_edge(bb, self.W, self.H))

    def test_le_HAUT_et_le_BAS_ne_sont_pas_des_bords_LATERAUX(self):
        """Un objet coupé en haut garde une largeur et un centre justes — donc son cap au
        ratio et son latéral tiennent. C'est ce que testent les consommateurs historiques."""
        self.assertFalse(touches_side_edge([100, 0, 200, 60], self.W, self.H))
        self.assertFalse(touches_side_edge([100, 200, 200, 248], self.W, self.H))
        self.assertTrue(touches_side_edge([0, 100, 50, 180], self.W, self.H))


class LaMargeResteUnArgumentTest(unittest.TestCase):
    """Les deux consommateurs historiques ont des marges DIFFÉRENTES (6 et 8 px) ;
    l'extraction ne devait rien changer à leur comportement. Unifier est une décision à
    mesurer (elle changerait le jeu d'observations de l'estimateur de pitch), pas un effet
    de bord de refactoring."""

    W, H = 384, 248

    def test_une_bbox_a_7px_du_bord_depend_de_la_marge(self):
        bb = [7.0, 100, 200, 180]
        self.assertFalse(touches_side_edge(bb, self.W, self.H, margin_px=6.0))
        self.assertTrue(touches_side_edge(bb, self.W, self.H, margin_px=8.0))

    def test_le_defaut_est_celui_du_consommateur_le_plus_ancien(self):
        self.assertEqual(DEFAULT_MARGIN_PX, 8.0)

    def test_la_condition_extraite_egale_l_ancienne_EXPRESSION(self):
        """Non-régression : pour chaque marge, la brique doit rendre exactement ce que
        rendait l'expression littérale qu'elle remplace."""
        for marge in (6.0, 8.0):
            for x1 in (0, 5, 6, 7, 8, 9, 50):
                for x2 in (100, 374, 375, 376, 377, 378, 384):
                    bb = [x1, 100, x2, 180]
                    ancienne = (bb[0] <= marge or bb[1 + 1] >= self.W - marge)
                    with self.subTest(marge=marge, x1=x1, x2=x2):
                        self.assertEqual(
                            touches_side_edge(bb, self.W, self.H, margin_px=marge),
                            ancienne)


if __name__ == '__main__':
    unittest.main(verbosity=2)

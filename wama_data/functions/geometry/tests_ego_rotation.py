"""Tests de la rotation propre — scènes SYNTHÉTIQUES à vérité connue.

Deux tests portent tout le reste :

  • `SeparationRotationTranslationTest` — c'est la raison d'être du modèle à 3 paramètres.
    L'estimateur naïf qu'on écrit spontanément (« médiane des Δx divisée par la focale »)
    donne le bon résultat sur une rotation pure, et un lacet FANTÔME dès que la caméra
    avance sans que les points soient symétriques autour du point de fuite. Le test le
    reproduit exactement.

  • `ConventionDeSigneTest` — un signe faux ne lève rien et double silencieusement tous les
    désaccords mesurés. Le projet s'est déjà fait prendre (cf. le pitch de Depth Pro,
    changelog 2026-08-05).

    python3 -m unittest wama_data.functions.geometry.tests_ego_rotation
"""
import math
import unittest

from .ego_rotation import estimate_ego_rotation, yaw_disagreement

#: Rig ENA : très basse définition et grand-angle — fx ≈ 134 px sur 384×248.
FX, CX, CY = 134.0, 192.0, 124.0


def _grille(x_min=20, x_max=370, y_min=20, y_max=230, pas=35):
    """Points du décor répartis dans l'image."""
    return [(float(x), float(y))
            for x in range(x_min, x_max, pas)
            for y in range(y_min, y_max, pas)]


def _applique(points, yaw_deg=0.0, pitch_deg=0.0, expansion=0.0):
    """Déplace des points selon le modèle direct — la vérité terrain des tests.

    Le décor défile à l'OPPOSÉ de la rotation caméra : `yaw_deg` est ici le lacet de la
    caméra (positif = à droite), donc les points partent vers la gauche.
    """
    out = []
    for (x, y) in points:
        dx = -FX * math.radians(yaw_deg) + expansion * (x - CX)
        dy = FX * math.radians(pitch_deg) + expansion * (y - CY)
        out.append((x, y, x + dx, y + dy))
    return out


class ConventionDeSigneTest(unittest.TestCase):

    def test_un_virage_a_DROITE_rend_un_lacet_POSITIF(self):
        r = estimate_ego_rotation(_applique(_grille(), yaw_deg=+3.0), FX, (CX, CY))
        self.assertAlmostEqual(r['yaw_deg'], 3.0, places=4)

    def test_un_virage_a_GAUCHE_rend_un_lacet_NEGATIF(self):
        r = estimate_ego_rotation(_applique(_grille(), yaw_deg=-3.0), FX, (CX, CY))
        self.assertAlmostEqual(r['yaw_deg'], -3.0, places=4)

    def test_le_tangage_NEZ_EN_L_AIR_est_positif(self):
        r = estimate_ego_rotation(_applique(_grille(), pitch_deg=+2.0), FX, (CX, CY))
        self.assertAlmostEqual(r['pitch_deg'], 2.0, places=4)


class SeparationRotationTranslationTest(unittest.TestCase):
    """Le cœur : rotation et translation avant ont des signatures distinctes."""

    def test_une_rotation_pure_ne_produit_AUCUNE_expansion(self):
        r = estimate_ego_rotation(_applique(_grille(), yaw_deg=2.0), FX, (CX, CY))
        self.assertAlmostEqual(r['yaw_deg'], 2.0, places=4)
        self.assertAlmostEqual(r['expansion'], 0.0, places=6)

    def test_une_marche_avant_pure_ne_produit_AUCUN_lacet(self):
        r = estimate_ego_rotation(_applique(_grille(), expansion=0.05), FX, (CX, CY))
        self.assertAlmostEqual(r['yaw_deg'], 0.0, places=4)
        self.assertGreater(r['expansion'], 0.04)

    def test_marche_avant_sur_points_ASYMETRIQUES_toujours_aucun_lacet(self):
        """LE test. Points cantonnés à droite de l'image : la moyenne des Δx est très
        positive alors que la caméra ne tourne pas. Un estimateur « médiane des Δx / f »
        annoncerait ici un virage franc. Vérifié : il l'annoncerait bien."""
        pts = _grille(x_min=250, x_max=370, pas=20)
        m = _applique(pts, expansion=0.05)

        naif = sum(x1 - x0 for (x0, _, x1, _) in m) / len(m)
        lacet_naif = -math.degrees(naif / FX)
        self.assertGreater(abs(lacet_naif), 1.0,
                           "le piège doit être réel, sinon le test ne prouve rien")

        r = estimate_ego_rotation(m, FX, (CX, CY))
        self.assertAlmostEqual(r['yaw_deg'], 0.0, places=3)

    def test_rotation_ET_translation_simultanees_sont_demelees(self):
        r = estimate_ego_rotation(
            _applique(_grille(), yaw_deg=1.5, pitch_deg=-0.7, expansion=0.03), FX, (CX, CY))
        self.assertAlmostEqual(r['yaw_deg'], 1.5, places=4)
        self.assertAlmostEqual(r['pitch_deg'], -0.7, places=4)
        self.assertAlmostEqual(r['expansion'], 0.03, places=5)


class PointPrincipalTest(unittest.TestCase):

    def test_ignorer_le_centre_optique_FAUSSE_le_lacet(self):
        """Le défaut (0, 0) n'est pas anodin : le documenter ne suffit pas, on le mesure."""
        m = _applique(_grille(), expansion=0.05)
        juste = estimate_ego_rotation(m, FX, (CX, CY))
        sans = estimate_ego_rotation(m, FX)          # principal_point par défaut
        self.assertAlmostEqual(juste['yaw_deg'], 0.0, places=3)
        self.assertGreater(abs(sans['yaw_deg']), 1.0)


class RobustesseTest(unittest.TestCase):

    def test_les_appariements_ABERRANTS_sont_rejetes(self):
        m = _applique(_grille(), yaw_deg=2.0)
        # 4 correspondances fausses (objet mobile, ou appariement raté).
        m[3] = (m[3][0], m[3][1], m[3][0] + 60.0, m[3][1] - 45.0)
        m[10] = (m[10][0], m[10][1], m[10][0] - 55.0, m[10][1] + 30.0)
        m[17] = (m[17][0], m[17][1], m[17][0] + 70.0, m[17][1] + 50.0)
        m[24] = (m[24][0], m[24][1], m[24][0] - 65.0, m[24][1] - 20.0)

        r = estimate_ego_rotation(m, FX, (CX, CY))
        self.assertAlmostEqual(r['yaw_deg'], 2.0, delta=0.15)
        self.assertLess(r['n_inliers'], len(m))

    def test_le_residu_DENONCE_une_scene_qui_ne_suit_pas_le_modele(self):
        """Le résidu est le juge : sans lui, une mesure fausse passerait pour bonne."""
        import random
        rng = random.Random(12)
        propre = _applique(_grille(), yaw_deg=2.0)
        bruit = [(x0, y0, x1 + rng.uniform(-12, 12), y1 + rng.uniform(-12, 12))
                 for (x0, y0, x1, y1) in propre]

        self.assertLess(estimate_ego_rotation(propre, FX, (CX, CY))['residual_px'], 0.01)
        self.assertGreater(estimate_ego_rotation(bruit, FX, (CX, CY))['residual_px'], 2.0)

    def test_trop_peu_de_points_rend_None_plutot_qu_un_chiffre_fragile(self):
        self.assertIsNone(estimate_ego_rotation(_applique([(10.0, 10.0)], yaw_deg=1.0),
                                                FX, (CX, CY)))

    def test_une_focale_absente_rend_None(self):
        self.assertIsNone(estimate_ego_rotation(_applique(_grille(), yaw_deg=1.0), 0))


class VitesseEtDesaccordTest(unittest.TestCase):

    def test_dt_donne_des_degres_par_seconde(self):
        r = estimate_ego_rotation(_applique(_grille(), yaw_deg=1.0), FX, (CX, CY), dt_s=0.1)
        self.assertAlmostEqual(r['yaw_rate_dps'], 10.0, places=3)

    def test_sans_dt_aucune_vitesse_n_est_inventee(self):
        r = estimate_ego_rotation(_applique(_grille(), yaw_deg=1.0), FX, (CX, CY))
        self.assertNotIn('yaw_rate_dps', r)

    def test_le_desaccord_avec_la_reference_est_une_valeur_ABSOLUE_en_dps(self):
        self.assertAlmostEqual(yaw_disagreement(10.0, 7.5), 2.5, places=6)
        self.assertAlmostEqual(yaw_disagreement(-10.0, 7.5), 17.5, places=6)

    def test_une_source_manquante_ne_fabrique_pas_un_desaccord_nul(self):
        self.assertIsNone(yaw_disagreement(None, 7.5))
        self.assertIsNone(yaw_disagreement(10.0, None))

    def test_un_cap_de_reference_GELE_ne_produit_AUCUN_desaccord(self):
        """LE garde d'honnêteté (piège G7 transposé au cap).

        Sous 0,30 m de déplacement, `ego_pose` TIENT le cap au dernier connu : sa dérivée
        vaut 0 par construction. Sans ce garde, une navette qui tourne à l'arrêt rendrait
        un désaccord égal au lacet vu — un artefact du gel présenté comme une erreur de cap,
        et maximal là où la vision est justement la plus fiable."""
        self.assertIsNone(yaw_disagreement(12.0, 0.0, reference_held=True))
        # Sans le gel, la même paire est une mesure parfaitement légitime.
        self.assertAlmostEqual(yaw_disagreement(12.0, 0.0), 12.0, places=6)

    def test_une_reference_FIABLE_a_l_arret_reste_comparable(self):
        """Le cap de l'API navette vaut à l'arrêt : le garde porte sur la SOURCE, pas sur
        la vitesse — d'où un drapeau passé par l'appelant, pas un seuil deviné ici."""
        self.assertAlmostEqual(yaw_disagreement(12.0, 11.0, reference_held=False), 1.0,
                               places=6)


class ContratPurTest(unittest.TestCase):
    """Le wrapper est ce que le CATALOGUE appelle — `view.apply()` lui passe un TypedFrame et
    range son retour. Brancher le noyau en `fn` (tuples → dict) casserait à l'exécution alors
    que le manifeste s'annonce chaînable : c'est le défaut que ces tests verrouillent."""

    def _frame(self, matches):
        import pandas as pd
        from wama.common.catalog.data_types import DataType, TypedFrame
        return TypedFrame(pd.DataFrame(
            [{'x0': a, 'y0': b, 'x1': c, 'y1': d} for (a, b, c, d) in matches]),
            DataType.TABLE)

    def test_TypedFrame_en_entree_TypedFrame_en_sortie(self):
        from wama.common.catalog.data_types import DataType, TypedFrame
        from .ego_rotation import ego_rotation

        out = ego_rotation(self._frame(_applique(_grille(), yaw_deg=2.0)),
                           focal_px=FX, principal_point=(CX, CY))
        self.assertIsInstance(out, TypedFrame)
        self.assertEqual(out.data_type, DataType.SCALAR)
        self.assertEqual(out.df.iloc[0]['metric'], 'ego_yaw_deg')
        self.assertAlmostEqual(out.df.iloc[0]['value'], 2.0, places=4)

    def test_le_diagnostic_va_dans_meta_pas_dans_la_table(self):
        from .ego_rotation import ego_rotation
        out = ego_rotation(self._frame(_applique(_grille(), yaw_deg=2.0)),
                           focal_px=FX, principal_point=(CX, CY))
        for key in ('pitch_deg', 'expansion', 'n_inliers', 'residual_px'):
            self.assertIn(key, out.meta)
        self.assertTrue(out.meta['usable'])

    def test_une_mesure_INEXPLOITABLE_le_dit_au_lieu_de_rendre_un_chiffre(self):
        """Un résidu élevé ne doit pas se lire comme une mesure valide."""
        import random
        from .ego_rotation import ego_rotation
        rng = random.Random(7)
        bruit = [(x0, y0, x1 + rng.uniform(-15, 15), y1 + rng.uniform(-15, 15))
                 for (x0, y0, x1, y1) in _applique(_grille(), yaw_deg=2.0)]
        self.assertFalse(ego_rotation(self._frame(bruit), focal_px=FX,
                                      principal_point=(CX, CY)).meta['usable'])

    def test_entree_vide_rend_un_TypedFrame_pas_une_exception(self):
        from wama.common.catalog.data_types import TypedFrame
        from .ego_rotation import ego_rotation
        out = ego_rotation(self._frame([]), focal_px=FX)
        self.assertIsInstance(out, TypedFrame)
        self.assertIsNone(out.df.iloc[0]['value'])
        self.assertFalse(out.meta['usable'])

    def test_le_catalogue_pointe_le_WRAPPER_et_non_le_noyau(self):
        from wama.common.catalog.function_catalog import get, load_all
        load_all()
        spec = get('ego_rotation')
        self.assertIsNotNone(spec)
        self.assertEqual(spec.fn.__name__, 'ego_rotation',
                         "fn doit être le wrapper TypedFrame, pas estimate_ego_rotation")


if __name__ == '__main__':
    unittest.main(verbosity=2)

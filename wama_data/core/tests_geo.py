"""Tests des primitives géodésiques (`wama_data/core/geo.py`).

⚠ Ce module est le DOMICILE UNIQUE d'un calcul implémenté quatre fois ailleurs dans le dépôt
(deux fois dans `cam_analyzer`, plus deux projections locales). Les valeurs de référence viennent
donc de la géodésie, pas d'une de ces copies — sinon on ne testerait que la fidélité à un doublon.
"""
import math
import unittest

from .geo import RAYON_TERRE_M, abscisse_curviligne, distances_a_point, haversine


class HaversineTest(unittest.TestCase):

    def test_distance_nulle(self):
        self.assertEqual(haversine(45.0, 5.0, 45.0, 5.0), 0.0)

    def test_un_degre_de_latitude_vaut_environ_111_km(self):
        # Référence géodésique : 1° de latitude ≈ 111,19 km partout sur le globe.
        d = haversine(45.0, 5.0, 46.0, 5.0)
        self.assertAlmostEqual(d, 111194.9, delta=1.0)

    def test_un_degre_de_longitude_retrecit_avec_la_latitude(self):
        # À 60°N, un degré de longitude vaut la moitié de ce qu'il vaut à l'équateur (cos 60° = ½).
        equateur = haversine(0.0, 0.0, 0.0, 1.0)
        nord = haversine(60.0, 0.0, 60.0, 1.0)
        self.assertAlmostEqual(nord / equateur, 0.5, delta=0.001)

    def test_courte_distance_realiste(self):
        # ~40 m : l'échelle du rayon d'analyse d'un carrefour. C'est là que la loi des cosinus
        # sphériques perdrait sa précision — motif du choix de haversine.
        d = haversine(45.75000, 4.85000, 45.75036, 4.85000)
        self.assertAlmostEqual(d, 40.0, delta=0.5)

    def test_symetrie(self):
        self.assertAlmostEqual(haversine(45.0, 5.0, 46.0, 6.0),
                               haversine(46.0, 6.0, 45.0, 5.0), places=9)

    def test_antipodes(self):
        self.assertAlmostEqual(haversine(0.0, 0.0, 0.0, 180.0), math.pi * RAYON_TERRE_M, delta=1.0)


class DistancesAPointTest(unittest.TestCase):

    def test_serie_de_distances(self):
        d = distances_a_point([45.0, 46.0], [5.0, 5.0], 45.0, 5.0)
        self.assertEqual(d[0], 0.0)
        self.assertAlmostEqual(d[1], 111194.9, delta=1.0)

    def test_une_position_ABSENTE_rend_None_pas_une_distance(self):
        # ⚠ Le point du module : remplacer un trou GPS par 0.0 placerait le sujet au large de
        # l'Afrique — une distance énorme, plausible, et fausse.
        d = distances_a_point([45.0, None, float('nan')], [5.0, 5.0, 5.0], 45.0, 5.0)
        self.assertEqual(d[0], 0.0)
        self.assertIsNone(d[1])
        self.assertIsNone(d[2])

    def test_une_longitude_absente_suffit_a_invalider(self):
        d = distances_a_point([45.0], [None], 45.0, 5.0)
        self.assertIsNone(d[0])

    def test_longueurs_incoherentes_refusees(self):
        with self.assertRaises(ValueError):
            distances_a_point([45.0, 46.0], [5.0], 45.0, 5.0)

    def test_serie_vide(self):
        self.assertEqual(distances_a_point([], [], 45.0, 5.0), [])


class AbscisseCurviligneTest(unittest.TestCase):
    """La colonne qui rend les marges spatiales exprimables — distance CUMULÉE le long de la trace."""

    # 4 points plein nord espacés d'~40 m chacun (cf. test_courte_distance_realiste).
    LATS = [45.75000, 45.75036, 45.75072, 45.75108]
    LONS = [4.85000] * 4

    def test_cumul_monotone_depuis_zero(self):
        a = abscisse_curviligne(self.LATS, self.LONS)
        self.assertEqual(a[0], 0.0)
        self.assertAlmostEqual(a[1], 40.0, delta=0.5)
        self.assertAlmostEqual(a[3], 120.0, delta=1.5)
        self.assertEqual(a, sorted(x for x in a if x is not None))

    def test_un_trou_rend_None_et_REPORTE_la_distance_sans_l_inventer(self):
        # ⚠ Le point de la fonction : le trou n'avance pas l'abscisse, la position valide
        # suivante cumule depuis la DERNIÈRE valide — 80 m d'un bloc, pas 40 + 40 inventés.
        a = abscisse_curviligne([self.LATS[0], None, self.LATS[2]],
                                [4.85000, 4.85000, 4.85000])
        self.assertEqual(a[0], 0.0)
        self.assertIsNone(a[1])
        self.assertAlmostEqual(a[2], 80.0, delta=1.0)

    def test_immobile_n_accumule_rien(self):
        a = abscisse_curviligne([45.0, 45.0, 45.0], [5.0, 5.0, 5.0])
        self.assertEqual(a, [0.0, 0.0, 0.0])

    def test_longueurs_incoherentes_refusees(self):
        with self.assertRaises(ValueError):
            abscisse_curviligne([45.0], [])


if __name__ == '__main__':
    unittest.main()

"""Tests de la brique d'unités d'affichage (`wama/common/utils/units.py`, D27).

⚠ LE test de ce fichier est celui de l'OFFSET (°C → °F) : c'est lui qui justifie pint contre
une table de facteurs maison — un facteur rend 0 °C = 0 °F, plausible et faux.
"""
import unittest

from wama.common.utils.units import convert, convert_series, display_unit, render


class ConvertTest(unittest.TestCase):

    def test_km_h_vers_mph(self):
        self.assertAlmostEqual(convert(30.0, 'km/h', 'mph'), 18.6411, places=3)

    def test_celsius_vers_fahrenheit_porte_un_OFFSET_pas_un_facteur(self):
        # ⚠ Le point du module : une table de facteurs rendrait 0 °C → 0 °F.
        self.assertAlmostEqual(convert(0.0, 'degC', 'degF'), 32.0, places=6)
        self.assertAlmostEqual(convert(100.0, 'degC', 'degF'), 212.0, places=6)

    def test_un_trou_reste_un_trou(self):
        self.assertIsNone(convert(None, 'km/h', 'mph'))
        self.assertIsNone(convert(float('nan'), 'km/h', 'mph'))

    def test_une_unite_inconnue_est_REFUSEE_pas_ignoree(self):
        # Afficher une valeur sous une étiquette fausse serait pire qu'une erreur.
        with self.assertRaises(Exception):
            convert(1.0, 'foobars_par_schtroumpf', 'mph')

    def test_une_serie_preserve_ses_trous_a_leur_place(self):
        s = convert_series([0.0, None, 100.0], 'degC', 'degF')
        self.assertAlmostEqual(s[0], 32.0, places=6)
        self.assertIsNone(s[1])
        self.assertAlmostEqual(s[2], 212.0, places=6)


class DisplayUnitTest(unittest.TestCase):

    def test_le_systeme_metrique_ne_touche_pas_l_unite_source(self):
        self.assertEqual(display_unit('km/h', 'metric'), 'km/h')

    def test_imperial_remappe_par_DIMENSION_pas_par_nom(self):
        # Toute unité de vitesse doit atterrir sur mph — pas seulement km/h.
        self.assertEqual(display_unit('km/h', 'imperial'), 'mph')
        self.assertEqual(display_unit('m/s', 'imperial'), 'mph')
        self.assertEqual(display_unit('degC', 'imperial'), 'degF')

    def test_une_unite_inconnue_reste_AFFICHABLE(self):
        # Une préférence ne doit jamais rendre une colonne inaffichable.
        self.assertEqual(display_unit('bpm_de_synthetiseur', 'imperial'),
                         'bpm_de_synthetiseur')

    def test_une_unite_vide_reste_vide(self):
        self.assertEqual(display_unit('', 'imperial'), '')

    def test_une_dimension_hors_table_reste_dans_l_unite_source(self):
        # La table impériale est volontairement minimale : une masse n'y est pas → inchangée.
        self.assertEqual(display_unit('kg', 'imperial'), 'kg')


class RenderTest(unittest.TestCase):

    def test_rendu_converti_dans_le_systeme_prefere(self):
        self.assertTrue(render(30.0, 'km/h', 'imperial').startswith('18.64'))

    def test_rendu_metrique_inchange(self):
        self.assertTrue(render(30.0, 'km/h', 'metric').startswith('30'))

    def test_un_trou_se_rend_VIDE_jamais_zero(self):
        self.assertEqual(render(None, 'km/h', 'imperial'), '')


if __name__ == '__main__':
    unittest.main()

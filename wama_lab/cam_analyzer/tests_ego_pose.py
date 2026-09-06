"""Tests de `effective_gps_track` — le point d'accès UNIQUE de la pose navette (2026-09-05).

Le test qui compte est `test_bascule_OFF_rend_la_trace_BRUTE_a_l_identite` : c'est lui qui
atteste que le ⚑ `shuttle_filter` à son défaut (OFF) laisse les 6 consommateurs serveur
EXACTEMENT sur ce qu'ils lisaient avant — la promesse « tous OFF = état d'aujourd'hui » sur
laquelle repose l'ordre de travail (corrections d'abord, test D.3 en dernier).

Sans base : une session factice suffit (la fonction ne lit que `config`, `results_summary`,
`gps_track`).
"""
import unittest

from wama_lab.cam_analyzer.utils.ego_pose import effective_gps_track


class _Session:
    def __init__(self, gps_track, features=None, shuttle_filter=None):
        self.gps_track = gps_track
        self.config = {'features': features or {}}
        self.results_summary = {'shuttle_filter': shuttle_filter} if shuttle_filter else {}


GT = [
    {'ts': 0.0, 'lat': 45.7578, 'lon': 4.8320, 'heading': None, 'speed_kmh': 0.0},
    {'ts': 1.0, 'lat': 45.7579, 'lon': 4.8321, 'heading': 37.0, 'speed_kmh': 10.8},
    {'ts': 2.0, 'lat': 45.7580, 'lon': 4.8322, 'heading': 41.0, 'speed_kmh': 10.9},
]
FILTRE = {'track': [
    {'ts': 0.0, 'lat_f': 45.75781, 'lon_f': 4.83201, 'heading_f': None, 'heading_f_held': True},
    {'ts': 1.0, 'lat_f': 45.75791, 'lon_f': 4.83211, 'heading_f': 38.5, 'heading_f_held': False},
    {'ts': 2.0, 'lat_f': 45.75801, 'lon_f': 4.83221, 'heading_f': 38.9, 'heading_f_held': False},
]}


class BasculeTest(unittest.TestCase):

    def test_bascule_OFF_rend_la_trace_BRUTE_a_l_identite(self):
        """Même si un calcul filtré traîne en base : OFF ⇒ brut, sinon l'A/B mentirait."""
        s = _Session(GT, features={'shuttle_filter': False}, shuttle_filter=FILTRE)
        out = effective_gps_track(s)
        self.assertIs(out, s.gps_track, "OFF doit rendre l'objet même, pas une copie")

    def test_defaut_du_registre_est_OFF_donc_identite_sans_surcharge(self):
        s = _Session(GT, features={}, shuttle_filter=FILTRE)
        self.assertIs(effective_gps_track(s), s.gps_track)

    def test_ON_sans_calcul_stocke_rend_le_brut(self):
        s = _Session(GT, features={'shuttle_filter': True})
        self.assertIs(effective_gps_track(s), s.gps_track)

    def test_ON_avec_calcul_remplace_lat_lon_heading_et_garde_les_BRUTS(self):
        s = _Session(GT, features={'shuttle_filter': True}, shuttle_filter=FILTRE)
        out = effective_gps_track(s)
        self.assertEqual(len(out), 3)
        p = out[1]
        self.assertEqual((p['lat'], p['lon'], p['heading']), (45.75791, 4.83211, 38.5))
        self.assertEqual((p['lat_raw'], p['lon_raw'], p['heading_raw']), (45.7579, 4.8321, 37.0))
        self.assertFalse(p['heading_held'])
        # champs non filtrés intacts
        self.assertEqual(p['ts'], 1.0)
        self.assertEqual(p['speed_kmh'], 10.8)

    def test_un_cap_filtre_ABSENT_laisse_le_cap_brut(self):
        """Avant tout mouvement, `heading_f` est None : on ne doit pas écraser le brut par None."""
        s = _Session(GT, features={'shuttle_filter': True}, shuttle_filter=FILTRE)
        p0 = effective_gps_track(s)[0]
        self.assertIsNone(p0['heading'])          # brut était None aussi ici
        self.assertTrue(p0['heading_held'])
        self.assertEqual(p0['lat'], 45.75781)     # la position, elle, est filtrée

    def test_un_point_sans_correspondance_de_ts_reste_brut(self):
        gt = GT + [{'ts': 9.0, 'lat': 45.76, 'lon': 4.84, 'heading': 50.0}]
        s = _Session(gt, features={'shuttle_filter': True}, shuttle_filter=FILTRE)
        out = effective_gps_track(s)
        self.assertIs(out[3], gt[3])

    def test_la_trace_brute_n_est_JAMAIS_mutee(self):
        import copy
        s = _Session(copy.deepcopy(GT), features={'shuttle_filter': True}, shuttle_filter=FILTRE)
        effective_gps_track(s)
        self.assertEqual(s.gps_track, GT, "gps_track est la source de vérité : lecture seule")


if __name__ == '__main__':
    unittest.main(verbosity=2)

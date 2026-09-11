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


class CommandeAccelerometreTest(unittest.TestCase):
    """`longitudinal_accel_series` — la série d'accélération servie au filtre (⚑ `imu_command`).

    Ce qui doit être gardé ici n'est pas le lissage mais les deux FAITS MESURÉS dont tout
    dépend : l'axe avant (`ax`, signe +) et l'estimation du biais À L'ARRÊT. Une inversion
    silencieuse de l'un ou l'autre rendrait une trajectoire plausible et FAUSSE.
    """

    @staticmethod
    def _session(biais=0.0, a_roule=0.5, n=200):
        """Moitié à l'arrêt (accélération nulle + biais), moitié en mouvement."""
        imu, gps = [], []
        for i in range(n):
            t = i * 0.1
            arret = i < n // 2
            imu.append({'ts': t, 'ax': (0.0 if arret else a_roule) / 9.80665 + biais / 9.80665,
                        'ay': 0.0, 'az': 0.95})
            gps.append({'ts': t, 'lat': 45.0, 'lon': 4.0,
                        'speed_kmh': 0.0 if arret else 12.0})
        s = _Session(gps)
        s.imu_track = imu
        return s

    def test_l_axe_avant_DECLARE_est_celui_qui_a_ete_mesure(self):
        from wama_lab.cam_analyzer.utils import ego_pose
        self.assertEqual(ego_pose.IMU_FORWARD_AXIS, 'ax')
        self.assertEqual(ego_pose.IMU_FORWARD_SIGN, 1.0)

    def test_le_biais_est_estime_A_L_ARRET_et_non_sur_toute_la_trace(self):
        from wama_lab.cam_analyzer.utils.ego_pose import longitudinal_accel_series
        at, infos = longitudinal_accel_series(self._session(biais=0.30, a_roule=0.5))
        self.assertIsNotNone(at)
        self.assertEqual(infos['bias_source'], 'arrêt')
        self.assertAlmostEqual(infos['bias_ms2'], 0.30, places=2)
        # une moyenne GLOBALE aurait absorbé la moitié roulante (0,30 + 0,25 = 0,55)
        self.assertLess(infos['bias_ms2'], 0.40)

    def test_le_biais_retire_rend_l_acceleration_REELLE(self):
        from wama_lab.cam_analyzer.utils.ego_pose import longitudinal_accel_series
        at, _ = longitudinal_accel_series(self._session(biais=0.30, a_roule=0.5))
        self.assertAlmostEqual(at(2.0), 0.0, places=1)      # à l'arrêt
        self.assertAlmostEqual(at(18.0), 0.5, places=1)     # en mouvement

    def test_sans_IMU_la_serie_est_ABSENTE_et_le_dit(self):
        from wama_lab.cam_analyzer.utils.ego_pose import longitudinal_accel_series
        s = _Session(GT)
        s.imu_track = []
        at, raison = longitudinal_accel_series(s)
        self.assertIsNone(at)
        self.assertIn('IMU', raison)

    def test_sans_arrets_le_repli_est_ANNONCE_pas_silencieux(self):
        from wama_lab.cam_analyzer.utils.ego_pose import longitudinal_accel_series
        imu = [{'ts': i * 0.1, 'ax': 0.05, 'ay': 0.0, 'az': 0.95} for i in range(200)]
        gps = [{'ts': i * 0.1, 'lat': 45.0, 'lon': 4.0, 'speed_kmh': 20.0} for i in range(200)]
        s = _Session(gps)
        s.imu_track = imu
        _at, infos = longitudinal_accel_series(s)
        self.assertIn('arrêts trop rares', infos['bias_source'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

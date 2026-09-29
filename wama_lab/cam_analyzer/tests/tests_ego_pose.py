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


class LaBasculeCOMMANDE_vraiment_le_filtreTest(unittest.TestCase):
    """La couture APPLICATIVE : ⚑ `imu_command` ON ⇒ le filtre est réellement commandé.

    Trouvé par le balayage mécanique des gardes : `compute_shuttle_filter` n'était nommée par
    AUCUN test. Les gardes du 11/09 vivaient toutes DANS la brique pure — or c'est ici que la
    bascule rencontre la fonction, et une bascule qui n'arrive pas rendrait une trace
    parfaitement plausible, calculée comme avant, sous un drapeau annoncé ON.
    """

    class _SessionEcrivable(_Session):
        def __init__(self, features):
            n = 120
            gps, imu = [], []
            for i in range(n):
                t = i * 0.5
                gps.append({'ts': t, 'lat': 45.0 + i * 2e-5, 'lon': 4.0 + i * 1e-5,
                            'heading': 37.0, 'speed_kmh': 12.0})
            for i in range(n * 5):
                imu.append({'ts': i * 0.1, 'ax': 0.03, 'ay': 0.0, 'az': 0.95})
            super().__init__(gps, features=features)
            self.imu_track = imu
            self.sauvegardes = 0

        def save(self, **kw):
            self.sauvegardes += 1

    def _rapport(self, features):
        from wama_lab.cam_analyzer.utils.ego_pose import compute_shuttle_filter
        s = self._SessionEcrivable(features)
        rep = compute_shuttle_filter(s)
        self.assertEqual(s.sauvegardes, 1, "le calcul se persiste une fois")
        return rep

    def test_bascule_OFF_le_filtre_n_est_PAS_commande(self):
        rep = self._rapport({'shuttle_filter': True})
        self.assertNotIn('commanded', rep)
        self.assertEqual(rep['sigma_a'], 0.8)

    def test_bascule_ON_le_filtre_EST_commande_et_le_rapport_le_DIT(self):
        rep = self._rapport({'shuttle_filter': True, 'imu_command': True})
        self.assertTrue(rep.get('commanded'))
        self.assertEqual(rep['sigma_a'], 0.25)
        self.assertIn('imu', rep)
        self.assertEqual(rep['imu']['axis'], 'ax')

    def test_bascule_ON_mais_AUCUN_IMU_retombe_sur_le_filtre_libre_sans_planter(self):
        from wama_lab.cam_analyzer.utils.ego_pose import compute_shuttle_filter
        s = self._SessionEcrivable({'shuttle_filter': True, 'imu_command': True})
        s.imu_track = []
        rep = compute_shuttle_filter(s)
        self.assertNotIn('commanded', rep)
        self.assertEqual(rep['sigma_a'], 0.8)

    def test_le_sigma_commande_vient_de_la_CONSTANTE_pas_d_un_litteral(self):
        """Sans ça, changer la constante casse un test sur `0.25` sans dire pourquoi."""
        from wama_data.functions.driving.ego_trajectory_filter import (
            DEFAULT_SIGMA_A, DEFAULT_SIGMA_A_COMMANDED)
        rep = self._rapport({'shuttle_filter': True, 'imu_command': True})
        self.assertEqual(rep['sigma_a'], DEFAULT_SIGMA_A_COMMANDED)
        self.assertEqual(rep['sigma_a_libre'], DEFAULT_SIGMA_A)
        self.assertLess(DEFAULT_SIGMA_A_COMMANDED, DEFAULT_SIGMA_A,
                        "commander le filtre DOIT resserrer sa dispersion de processus")


class LeLisseurAcceptEUneCommandeTest(unittest.TestCase):
    """`kalman_rts_cv(command=…)` directement — la brique commune, sans passer par le GPS.

    Elle sert AUSSI le tracking des objets (`trajectory_smoother`) : son contrat par défaut
    doit rester bit-identique, et c'est la seule garde qui le dise à ce niveau.
    """

    @staticmethod
    def _serie(n=60, dt=0.5, a=0.4):
        """Mouvement uniformément accéléré vers l'est : x = ½·a·t², y = 0."""
        return [(i * dt, 0.5 * a * (i * dt) ** 2, 0.0) for i in range(n)]

    def test_sans_commande_le_resultat_est_INCHANGE(self):
        from wama_data.functions.kinematics.rts_smoother import kalman_rts_cv
        pts = self._serie()
        self.assertEqual(kalman_rts_cv(pts), kalman_rts_cv(pts, command=None))

    def test_la_commande_est_prise_dans_la_PREDICTION(self):
        from wama_data.functions.kinematics.rts_smoother import kalman_rts_cv
        pts = self._serie()
        libre = kalman_rts_cv(pts, sigma_a=0.2)
        cmde = kalman_rts_cv(pts, sigma_a=0.2, command=lambda t: (0.4, 0.0))
        self.assertNotEqual(libre, cmde, "la commande n'arrive pas jusqu'au filtre")
        # la vitesse finale doit être plus proche de la vérité a·t quand on la commande
        vrai = 0.4 * pts[-1][0]
        self.assertLess(abs(cmde[-1][3] - vrai), abs(libre[-1][3] - vrai))

    def test_une_commande_VIDE_est_ignoree_sans_planter(self):
        from wama_data.functions.kinematics.rts_smoother import kalman_rts_cv
        pts = self._serie()
        self.assertEqual(kalman_rts_cv(pts), kalman_rts_cv(pts, command=lambda t: (None, None)))


if __name__ == '__main__':
    unittest.main(verbosity=2)

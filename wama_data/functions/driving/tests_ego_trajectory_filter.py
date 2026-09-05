"""Tests du filtre de trajectoire ego — vérité SYNTHÉTIQUE connue, bruit reproductible.

Le test qui compte est `LeFiltreAmelioreTest.test_le_cap_filtre_est_MOINS_bruite_que_le_cap_brut`
: c'est la raison d'être du module (§[2] : le cap brut est la source d'erreur dominante). Un
filtre qui lisse la position mais rend un cap aussi bruité qu'avant n'aurait rien réglé.

    python3 -m unittest wama_data.functions.driving.tests_ego_trajectory_filter
"""
import math
import random
import unittest

from wama.common.catalog.data_types import DataType, TypedFrame

from .ego_trajectory_filter import filter_gps_points, filter_ego_track, _angle_diff

LAT0, LON0 = 45.7578, 4.8320
M_LAT = 111_320.0


def _trace(n=120, dt=1.0, speed=3.0, heading_deg=37.0, noise_m=2.0, seed=7,
           stop_from=None):
    """Ligne droite à cap constant, 1 fixe/s, bruit gaussien `noise_m` ; option arrêt."""
    rng = random.Random(seed)
    m_lon = M_LAT * math.cos(math.radians(LAT0))
    h = math.radians(heading_deg)
    pts, truth = [], []
    e = n_ = 0.0
    prev = None
    for i in range(n):
        t = i * dt
        moving = stop_from is None or t < stop_from
        if moving and i:
            e += speed * dt * math.sin(h)
            n_ += speed * dt * math.cos(h)
        lat = LAT0 + (n_ + rng.gauss(0, noise_m)) / M_LAT
        lon = LON0 + (e + rng.gauss(0, noise_m)) / m_lon
        # cap BRUT comme ego_pose le fait : bearing entre fixes bruts, tenu si < 0,30 m
        heading = None
        if prev is not None:
            de = (lon - prev[1]) * m_lon
            dn = (lat - prev[0]) * M_LAT
            if math.hypot(de, dn) >= 0.30:
                heading = math.degrees(math.atan2(de, dn)) % 360.0
            else:
                heading = prev[2]
        prev = (lat, lon, heading)
        pts.append({'ts': t, 'lat': lat, 'lon': lon, 'heading': heading})
        truth.append((LAT0 + n_ / M_LAT, LON0 + e / m_lon, heading_deg if moving else None))
    return pts, truth


def _rms_pos(pts, truth, key_lat, key_lon):
    m_lon = M_LAT * math.cos(math.radians(LAT0))
    acc, k = 0.0, 0
    for p, (tlat, tlon, _) in zip(pts, truth):
        if p.get(key_lat) is None:
            continue
        de = (p[key_lon] - tlon) * m_lon
        dn = (p[key_lat] - tlat) * M_LAT
        acc += de * de + dn * dn
        k += 1
    return math.sqrt(acc / k) if k else float('nan')


class LeFiltreAmelioreTest(unittest.TestCase):

    def setUp(self):
        self.pts, self.truth = _trace()
        self.out, self.report = filter_gps_points(self.pts)

    def test_la_position_filtree_est_plus_proche_de_la_verite_que_la_brute(self):
        brut = _rms_pos(self.out, self.truth, 'lat', 'lon')
        filt = _rms_pos(self.out, self.truth, 'lat_f', 'lon_f')
        self.assertLess(filt, brut * 0.6,
                        f"le filtre devrait diviser l'erreur RMS (brut {brut:.2f} m, filtré {filt:.2f} m)")

    def test_le_cap_filtre_est_MOINS_bruite_que_le_cap_brut(self):
        """LE test. Cap vrai = 37° constant. Le bearing brut entre fixes espacés de 3 m avec
        ±2 m de bruit oscille de dizaines de degrés — c'est le ±10-25° de §[2]."""
        err_brut = [abs(_angle_diff(p['heading'], 37.0)) for p in self.out[5:] if p.get('heading') is not None]
        err_filt = [abs(_angle_diff(p['heading_f'], 37.0)) for p in self.out[5:] if p.get('heading_f') is not None]
        med_brut = sorted(err_brut)[len(err_brut) // 2]
        med_filt = sorted(err_filt)[len(err_filt) // 2]
        self.assertGreater(med_brut, 8.0, "le piège doit être réel : cap brut nettement bruité")
        self.assertLess(med_filt, med_brut / 3.0,
                        f"cap filtré médian {med_filt:.1f}° vs brut {med_brut:.1f}°")

    def test_le_rapport_chiffre_l_AB(self):
        r = self.report
        self.assertTrue(r['filtered'])
        self.assertEqual(r['n'], len(self.pts))
        self.assertGreater(r['displacement_rms_m'], 0.5)
        self.assertGreater(r['heading_delta_median_deg'], 5.0)


class ArretTest(unittest.TestCase):

    def test_a_l_arret_le_cap_est_TENU_et_marque_comme_tel(self):
        pts, _ = _trace(n=90, stop_from=50.0, noise_m=1.0)
        out, report = filter_gps_points(pts)
        stopped = [p for p in out if p['ts'] >= 60.0]
        # Le cap tenu vaut le dernier cap en mouvement (~37°), et il est ÉTIQUETÉ tenu :
        # un consommateur peut refuser de le comparer (cf. `ego_rotation.yaw_disagreement`).
        self.assertTrue(all(p['heading_f_held'] for p in stopped[3:]))
        self.assertTrue(all(abs(_angle_diff(p['heading_f'], 37.0)) < 20.0 for p in stopped[3:]))
        self.assertGreater(report['heading_held_ratio'], 0.3)

    def test_en_mouvement_franc_le_cap_n_est_PAS_tenu(self):
        out, _ = filter_gps_points(_trace()[0])
        self.assertTrue(all(not p['heading_f_held'] for p in out[5:]))

    def test_le_filtre_converge_en_moins_de_2_s_apres_un_arret_franc(self):
        """Un lisseur RTS n'a pas de retard de phase : l'arrêt est vu quasi immédiatement.
        (Mesuré 1 s ; on tolère 2 s.) C'est ce qui le distingue d'une EMA."""
        pts, _ = _trace(n=90, stop_from=50.0, noise_m=1.0)
        out, _ = filter_gps_points(pts)
        first = next(p['ts'] for p in out if p['ts'] >= 50.0 and p['heading_f_held'])
        self.assertLessEqual(first - 50.0, 2.0)

    def test_a_2_m_de_bruit_GPS_la_LIMITE_du_seuil_est_documentee_pas_cachee(self):
        """À ±2 m, la vitesse filtrée résiduelle à l'arrêt monte à ~1 m/s max : quelques points
        passent le seuil. On exige ≥ 75 % tenus — et on écrit ici que ce n'est pas 100 %."""
        pts, _ = _trace(n=90, stop_from=50.0, noise_m=2.0, seed=11)
        out, report = filter_gps_points(pts)
        stopped = [p for p in out if p['ts'] >= 53.0]
        ratio = sum(1 for p in stopped if p['heading_f_held']) / len(stopped)
        self.assertGreaterEqual(ratio, 0.75, f"{ratio:.2f} tenus à ±2 m")


class ContratEnricherTest(unittest.TestCase):

    def test_memes_lignes_colonnes_brutes_INTACTES(self):
        pts, _ = _trace(n=30)
        out, _ = filter_gps_points(pts)
        self.assertEqual(len(out), len(pts))
        for p, q in zip(pts, out):
            self.assertEqual((p['lat'], p['lon'], p['ts'], p['heading']),
                             (q['lat'], q['lon'], q['ts'], q['heading']))

    def test_un_point_sans_coordonnees_est_recopie_sans_champs_filtres(self):
        pts, _ = _trace(n=30)
        pts[10] = {'ts': 10.0, 'lat': None, 'lon': None}
        out, _ = filter_gps_points(pts)
        self.assertNotIn('lat_f', out[10])
        self.assertIn('lat_f', out[11])

    def test_moins_de_3_points_rend_l_entree_et_le_dit(self):
        out, report = filter_gps_points([{'ts': 0, 'lat': LAT0, 'lon': LON0}])
        self.assertFalse(report['filtered'])
        self.assertNotIn('lat_f', out[0])

    def test_le_wrapper_TypedFrame_honore_le_contrat_pure(self):
        import pandas as pd
        pts, _ = _trace(n=40)
        tf = TypedFrame(pd.DataFrame(pts), DataType.GEO_TRACK, meta={'source': 'test'})
        out = filter_ego_track(tf, time_field='ts')
        self.assertIsInstance(out, TypedFrame)
        self.assertEqual(out.data_type, DataType.GEO_TRACK)
        self.assertEqual(len(out.df), 40)
        for c in ('lat_f', 'lon_f', 'speed_f_kmh', 'heading_f', 'heading_f_held'):
            self.assertIn(c, out.df.columns)
        self.assertIn('ego_filter', out.meta)
        self.assertEqual(out.meta['source'], 'test', "les meta amont sont conservées")

    def test_le_wrapper_accepte_time_OU_ts(self):
        import pandas as pd
        pts, _ = _trace(n=20)
        for p in pts:
            p['time'] = p.pop('ts')
        out = filter_ego_track(TypedFrame(pd.DataFrame(pts), DataType.GEO_TRACK))
        self.assertIn('lat_f', out.df.columns)

    def test_le_catalogue_pointe_le_wrapper(self):
        from wama.common.catalog.function_catalog import get, load_all
        load_all()
        spec = get('ego_track_filter')
        self.assertIsNotNone(spec)
        self.assertEqual(spec.fn.__name__, 'filter_ego_track')


if __name__ == '__main__':
    unittest.main(verbosity=2)

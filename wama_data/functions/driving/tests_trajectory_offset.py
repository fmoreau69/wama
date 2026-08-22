"""Tests des fonctions pures de `trajectory_offset`.

POURQUOI CE FICHIER A ÉTÉ RÉÉCRIT (2026-08-21)
    Il était un SCRIPT autonome : il chargeait le module par chemin
    (`spec.loader.exec_module`) puis exécutait ses contrôles au niveau module, en terminant par
    `sys.exit()`. Or son nom commence par « tests », donc le découvreur de Django l'importait —
    et l'import déclenchait deux pannes, dont une que le diagnostic initial n'avait pas vue :

      1. `exec_module` RÉ-EXÉCUTE le module déjà importé par `driving/__init__.py`, donc rejoue
         `register(FunctionSpec(...))` → « FunctionSpec dupliqué : trajectory_offset ».
         La garde du catalogue faisait exactement son travail : elle SIGNALAIT le double chargement.
      2. plus grave : `sys.exit()` au niveau module aurait **tué le lanceur de tests** même une
         fois le doublon réglé.

    La justification d'origine du chargement par chemin (« importer le paquet déclencherait
    l'auto-déclaration des FunctionSpec, donc Django ») était inexacte : `function_catalog` et
    `data_types` sont du Python pur, sans Django. Ce qui gênait était l'effet de bord
    d'enregistrement — or Python met les modules en cache, donc un import NORMAL ne l'exécute
    qu'une fois. D'où la réécriture en `unittest` avec import ordinaire.

    Effet secondaire souhaitable : ces 22 contrôles rejoignent la suite (`manage.py test`), alors
    qu'ils en étaient exclus et ne tournaient que si quelqu'un pensait à lancer le script.
"""
import math
import unittest

from . import trajectory_offset as oa


class DecompositionTest(unittest.TestCase):
    """1. Décomposition global/local."""

    REC = {
        "global": {"de_m": 3.0, "dn_m": -1.0, "n": 30},
        "per_window": {
            "0": {"de_m": 3.0, "dn_m": -1.0, "n": 10},   # pile la médiane -> local nul
            "1": {"de_m": 8.0, "dn_m": -1.0, "n": 12},   # +5 m est en local
            "2": {"de_m": 1.0, "dn_m": 1.0, "n": 8},     # -2 est / +2 nord
        },
    }

    def setUp(self):
        self.d = oa.decompose(self.REC)

    def test_biais_camera_est_la_mediane_globale(self):
        self.assertEqual(self.d["camera"], {"de_m": 3.0, "dn_m": -1.0})

    def test_fenetre_a_la_mediane_donne_un_local_nul(self):
        self.assertEqual(self.d["gps_local"]["0"], {"de_m": 0.0, "dn_m": 0.0, "n": 10})

    def test_fenetre_1_cinq_metres_est(self):
        self.assertAlmostEqual(self.d["gps_local"]["1"]["de_m"], 5.0, places=9)

    def test_fenetre_2_deux_ouest_deux_nord(self):
        self.assertAlmostEqual(self.d["gps_local"]["2"]["de_m"], -2.0, places=9)
        self.assertAlmostEqual(self.d["gps_local"]["2"]["dn_m"], 2.0, places=9)

    def test_rec_vide(self):
        self.assertEqual(oa.decompose({}),
                         {"camera": {"de_m": 0.0, "dn_m": 0.0}, "gps_local": {}})


class AncresTest(unittest.TestCase):
    """2. Ancres et rétraction par masquage."""

    WINS = [
        {"lat": 45.75, "lon": 4.83, "t_enter": 10.0, "t_exit": 20.0},
        {"lat": 45.76, "lon": 4.84, "t_enter": 110.0, "t_exit": 130.0},
        {"lat": 45.77, "lon": 4.85, "t_enter": 210.0, "t_exit": 230.0},
    ]

    def setUp(self):
        self.d = oa.decompose(DecompositionTest.REC)
        self.sans_masque = oa.build_anchors(self.WINS, self.d)

    def test_trois_ancres(self):
        self.assertEqual(len(self.sans_masque), 3)

    def test_ts_est_le_milieu_de_traversee(self):
        self.assertEqual(self.sans_masque[0]["ts"], 15.0)
        self.assertEqual(self.sans_masque[1]["ts"], 120.0)

    def test_triees_par_temps(self):
        ts = [x["ts"] for x in self.sans_masque]
        self.assertEqual(ts, sorted(ts))

    def test_sans_masque_alpha_vaut_un(self):
        self.assertTrue(all(x["alpha"] == 1.0 for x in self.sans_masque))

    def test_ciel_degage_annule_la_correction(self):
        # Ciel dégagé sur la fenêtre 1 -> correction rétractée ; canyon sur la 2 -> pleine.
        a = oa.build_anchors(self.WINS, self.d, mask_by_key={"0": 0.0, "1": 0.0, "2": 24.0})
        w1 = [x for x in a if x["ts"] == 120.0][0]
        self.assertEqual(w1["de_m"], 0.0)
        self.assertEqual(w1["alpha"], 0.0)

    def test_canyon_profond_plafonne_alpha_a_un(self):
        a = oa.build_anchors(self.WINS, self.d, mask_by_key={"0": 0.0, "1": 0.0, "2": 24.0})
        w2 = [x for x in a if x["ts"] == 220.0][0]
        self.assertEqual(w2["alpha"], 1.0)

    def test_fenetre_hors_index_ignoree(self):
        self.assertEqual(
            oa.build_anchors([], {"gps_local": {"7": {"de_m": 1, "dn_m": 1, "n": 1}}}), [])

    def test_rapport_coherent(self):
        rep = oa.correction_report(self.sans_masque)
        self.assertEqual(rep["n_anchors"], 3)
        self.assertGreater(rep["max_shift_m"], 0)


class InterpolationTest(unittest.TestCase):
    """3. Interpolation et bornes."""

    ANCHORS = [{"ts": 0.0, "de_m": 0.0, "dn_m": 0.0, "n": 10, "alpha": 1.0},
               {"ts": 100.0, "de_m": 10.0, "dn_m": -4.0, "n": 10, "alpha": 1.0}]

    def test_milieu_a_poids_egaux_donne_la_moitie(self):
        de, dn = oa.offset_at(self.ANCHORS, 50.0)
        self.assertAlmostEqual(de, 5.0, places=6)
        self.assertAlmostEqual(dn, -2.0, places=6)

    def test_avant_la_premiere_ancre_maintien(self):
        self.assertEqual(oa.offset_at(self.ANCHORS, -999.0), (0.0, 0.0))

    def test_apres_la_derniere_maintien(self):
        self.assertEqual(oa.offset_at(self.ANCHORS, 9999.0), (10.0, -4.0))

    def test_aucune_ancre_offset_nul(self):
        self.assertEqual(oa.offset_at([], 42.0), (0.0, 0.0))


class SigneTest(unittest.TestCase):
    """4. SIGNE — le point critique : une inversion ici décale toute la trace."""

    def test_offset_est_negatif_deplace_vers_l_ouest(self):
        # Le passage vu par la caméra est projeté 5 m à l'EST du vrai (ortho) :
        #   de = ortho - camera = -5  ->  la position supposée était 5 m trop à l'est
        #   -> la correction doit ramener le véhicule vers l'OUEST (longitude qui diminue).
        anch = [{"ts": 0.0, "de_m": -5.0, "dn_m": 0.0, "n": 5, "alpha": 1.0}]
        corr = oa.correct_track([{"ts": 0.0, "lat": 45.75, "lon": 4.83}], anch)
        self.assertLess(corr[0]["lon"], 4.83)
        shift_m = (corr[0]["lon"] - 4.83) * 111320.0 * math.cos(math.radians(45.75))
        self.assertAlmostEqual(shift_m, -5.0, delta=0.01)

    def test_original_preserve_et_tracabilite(self):
        anch = [{"ts": 0.0, "de_m": -5.0, "dn_m": 0.0, "n": 5, "alpha": 1.0}]
        corr = oa.correct_track([{"ts": 0.0, "lat": 45.75, "lon": 4.83}], anch)
        self.assertEqual(corr[0]["lat_raw"], 45.75)
        self.assertEqual(corr[0]["lon_raw"], 4.83)
        self.assertEqual(corr[0]["corr_de_m"], -5.0)

    def test_dn_positif_augmente_la_latitude(self):
        anch = [{"ts": 0.0, "de_m": 0.0, "dn_m": 8.0, "n": 5, "alpha": 1.0}]
        c = oa.correct_track([{"ts": 0.0, "lat": 45.75, "lon": 4.83}], anch)
        self.assertGreater(c[0]["lat"], 45.75)
        self.assertAlmostEqual((c[0]["lat"] - 45.75) * 111320.0, 8.0, delta=0.01)


class RobustesseTest(unittest.TestCase):
    """5. Robustesse."""

    def test_trace_vide(self):
        self.assertEqual(oa.correct_track([], InterpolationTest.ANCHORS), [])

    def test_sans_ancre_trace_inchangee(self):
        track = [{"ts": 0.0, "lat": 45.75, "lon": 4.83}]
        self.assertEqual(oa.correct_track(track, []), track)

    def test_point_sans_coordonnees_tolere(self):
        self.assertIsNone(
            oa.correct_track([{"ts": 1.0}], InterpolationTest.ANCHORS)[0].get("lat"))


class MasqueAbsentTest(unittest.TestCase):
    """6. Masque ABSENT ≠ ciel dégagé — garde contre une panne SILENCIEUSE.

    Si le réseau de masquage est indisponible, une fenêtre est simplement ABSENTE du dict. La
    traiter comme « ciel dégagé » annulerait toute la correction sans que rien ne le signale.
    """

    def setUp(self):
        self.d = oa.decompose(DecompositionTest.REC)

    def test_masque_absent_preserve_la_correction(self):
        a = oa.build_anchors(AncresTest.WINS, self.d, mask_by_key={"2": 24.0})
        w1 = [x for x in a if x["ts"] == 120.0][0]
        self.assertEqual(w1["alpha"], 1.0)
        self.assertAlmostEqual(w1["de_m"], 5.0, places=9)

    def test_masque_explicitement_nul_retracte(self):
        a = oa.build_anchors(AncresTest.WINS, self.d, mask_by_key={"1": 0.0})
        w1 = [x for x in a if x["ts"] == 120.0][0]
        self.assertEqual(w1["alpha"], 0.0)


if __name__ == "__main__":       # exécution directe encore possible
    unittest.main(verbosity=2)

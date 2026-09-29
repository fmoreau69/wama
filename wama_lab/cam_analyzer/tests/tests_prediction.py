"""⚑ `prediction_kalman` — la branche Kalman du TTC/PET était INATTEIGNABLE (2026-09-11).

Le paramètre `method` existait, la fonction `extrapolate_kalman` était testée côté
`wama_data`, et **aucun appelant ne la choisissait** : `tasks.compute_indicators_task`
appelait `annotate_prediction_indicators(session)` sans `method`. Un paramètre qu'aucun
appelant ne pose n'est pas un réglage, c'est une branche morte (`CHAINE §D.5 ④`).

Ce qui est gardé ici : la RÉSOLUTION de la méthode (bascule vs argument explicite) et le
CONTRAT DE RETOUR — qui est passé d'un entier à un dict le même jour, parce qu'une bascule
comparable doit s'accompagner d'une métrique chiffrée. Les deux se testent sans base et sans
détections : la sortie anticipée (« moins de 5 points GPS ») porte déjà `method`, ce qui est
précisément la raison de l'y avoir mise.
"""
import unittest

from wama_lab.cam_analyzer.utils.prediction_adapter import annotate_prediction_indicators


class _Session:
    """Session factice SANS trace GPS exploitable → sortie anticipée, donc aucun accès base."""

    def __init__(self, features=None):
        self.gps_track = [{'ts': 0.0, 'lat': 45.0, 'lon': 4.0}]
        self.config = {'features': features or {}}
        self.results_summary = {}
        self.id = 'factice'

    def save(self, **kw):
        raise AssertionError("aucune écriture attendue sur la sortie anticipée")


class LaMethodeEstResolueTest(unittest.TestCase):

    def test_defaut_du_registre_OFF_donc_le_script_d_origine(self):
        rep = annotate_prediction_indicators(_Session())
        self.assertEqual(rep['method'], 'speed_accel')

    def test_la_bascule_ON_selectionne_KALMAN(self):
        """C'est LE test de la réparation : sans lui, la branche reste inatteignable."""
        rep = annotate_prediction_indicators(_Session({'prediction_kalman': True}))
        self.assertEqual(rep['method'], 'kalman')

    def test_un_appel_EXPLICITE_reste_prioritaire_sur_la_bascule(self):
        """Les tests et les appels ciblés doivent pouvoir forcer une méthode sans toucher
        à la configuration de la session."""
        rep = annotate_prediction_indicators(_Session(), method='kalman')
        self.assertEqual(rep['method'], 'kalman')

    def test_une_bascule_ABSENTE_du_registre_ne_fait_pas_planter(self):
        rep = annotate_prediction_indicators(_Session({'inconnue': True}))
        self.assertEqual(rep['method'], 'speed_accel')


class LeContratDeRetourTest(unittest.TestCase):

    CLES = {'annotated', 'ttc', 'pet', 'ttc_median', 'pet_median', 'method',
            'placement_sources', 'causal_smoothing'}

    def test_le_retour_est_un_DICT_qui_porte_la_metrique(self):
        rep = annotate_prediction_indicators(_Session())
        self.assertIsInstance(rep, dict)
        self.assertEqual(set(rep), self.CLES)
        self.assertEqual(rep['annotated'], 0)

    def test_l_appelant_UNIQUE_a_suivi_le_changement_de_contrat(self):
        """Garde contre le défaut le plus probable de ce commit : la fonction rendait un
        ENTIER, la tâche l'affichait tel quel. Un dict non déballé afficherait le dict
        entier dans la console de l'app sans rien casser — donc sans se voir."""
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / 'wama_lab' / 'cam_analyzer'
               / 'tasks.py').read_text(encoding='utf-8')
        self.assertIn("pred = annotate_prediction_indicators(session)", src)
        self.assertIn("n = pred.get('annotated', 0)", src)
        self.assertIn("'prediction': pred", src,
                      "la métrique doit être PERSISTÉE dans output_summary, sinon l'A/B "
                      "ne survit pas à la fin de la tâche")


class LaProjectionSolAtteintLaPredictionTest(unittest.TestCase):
    """§D.5 ② — la prédiction plaçait TOUT au pinhole, ⚑ `auto_ground_calib` ne l'atteignait pas.

    Elle héritait de la correction EGO (⚑ `shuttle_filter`, via `effective_gps_track`) mais
    d'AUCUNE correction OBJET, alors que le tracker applique la projection sol. Sur la session
    de référence, où cette bascule est ON avec une calib `front`/`right`, le même objet avait
    donc DEUX positions monde : celle du tracker et celle du TTC.

    Ces gardes sont par LECTURE DE SOURCE. C'est assumé et c'est leur périmètre : exercer la
    projection demande une session, ses caméras, ses détections et une calib persistée — le
    banc le fait (A/B réel), pas un test unitaire. Ce qu'on garde ici est ce qu'un test PEUT
    garder : que la recette soit la MÊME que celle du tracker, et qu'elle ne se dégrade pas
    en silence.
    """

    @staticmethod
    def _src(nom):
        from pathlib import Path
        from django.conf import settings
        return (Path(settings.BASE_DIR) / 'wama_lab' / 'cam_analyzer' / 'utils'
                / nom).read_text(encoding='utf-8')

    def test_la_prediction_tente_le_SOL_avant_le_pinhole(self):
        src = self._src('prediction_adapter.py')
        i_sol = src.index('ego = ground_ego(_gproj[c.position]')
        i_pin = src.index('ego = pinhole_ego(d, iw, ih, fov_v_deg')
        self.assertLess(i_sol, i_pin,
                        "le pinhole doit être le REPLI, pas le chemin principal")

    def test_la_prediction_a_sa_PROPRE_bascule_et_le_TTC_reste_au_pinhole_par_defaut(self):
        """🔴 Garde de DÉCISION (Fabien, 2026-09-12) : la projection sol avait été RETIRÉE du
        TTC parce que le résultat était très mauvais avec l'homographie — dont la calib sol
        dérive. Le TTC reste donc au pinhole tant que l'homographie n'est pas améliorée.

        ⚠ Ma 1ʳᵉ version de ce test exigeait la MÊME condition que le tracker, « pour ne pas
        dédoubler un interrupteur ». C'était figer une confusion : le tracker et le TTC ont
        deux placements et la différence est VOULUE. *Une frontière voulue se lit comme une
        réponse, jamais comme un trou à combler* — et celle-ci était écrite dans le docstring
        du module.
        """
        from wama_lab.cam_analyzer.utils.features import FEATURES
        f = {x.key: x for x in FEATURES}
        self.assertIn('prediction_ground', f)
        self.assertFalse(f['prediction_ground'].default,
                         "le TTC reste au pinhole tant que l'homographie n'est pas améliorée")
        src = self._src('prediction_adapter.py')
        self.assertIn("_feat.get('prediction_ground', False)", src)
        self.assertNotIn("_feat.get('auto_ground_calib'", src,
                         "la bascule du TRACKER ne doit pas piloter le placement du TTC")

    def test_la_SOURCE_de_placement_est_comptee_et_RENDUE(self):
        """G7 : le repli `ground → pinhole` était silencieux, donc un A/B comparait du pinhole
        à un MÉLANGE sans le dire. Un placement mixte se COMPTE."""
        src = self._src('prediction_adapter.py')
        self.assertIn("_src_counts[_psrc] += 1", src)
        self.assertIn("'placement_sources': dict(_src_counts)", src)

    def test_le_rapport_porte_la_cle_meme_sans_projection(self):
        rep = annotate_prediction_indicators(_Session())
        self.assertIn('placement_sources', rep)
        self.assertEqual(rep['placement_sources'], {})

    def test_la_prediction_ne_LIT_toujours_pas_world_en(self):
        """🔴 Garde d'INTENTION (`CHAINE §F`), pas de style. `world_en` est lissé Kalman+RTS,
        donc informé du FUTUR du track. L'injecter réduirait artificiellement l'écart
        prédit/réel — la grandeur même que la méthode cherche. Ce test existe pour qu'une
        session future ne « corrige » pas ce qu'elle prendrait pour un oubli.

        ⚠ Sa 1ʳᵉ version cherchait la CHAÎNE `world_en` et échouait sur le COMMENTAIRE qui
        explique pourquoi on ne l'utilise pas : *une garde qui ne distingue pas le code de
        ce qui en parle interdit d'expliquer sa propre raison d'être.* On vise donc les
        formes d'ACCÈS, les seules qui liraient la valeur.
        """
        src = self._src('prediction_adapter.py')
        for acces in ("get('world_en'", '["world_en"]', "['world_en']",
                      'get("world_en"'):
            with self.subTest(acces=acces):
                self.assertNotIn(acces, src)


class LeLissageCausalTest(unittest.TestCase):
    """§D.5 ③ — la fenêtre de lissage était CENTRÉE, donc informée de ±2 points postérieurs.

    Peu (≈ 0,17 s) au regard du RTS de `world_en` qui voit tout le track, mais la méthode
    (`§F`) fait de l'écart prédit/réel sa grandeur d'intérêt : tout futur en entrée la réduit
    artificiellement. D'où une bascule et une mesure, plutôt qu'une correction silencieuse.
    """

    @staticmethod
    def _rampe(n=12):
        """Trajectoire à SAUT au milieu : un lissage causal et un lissage centré ne peuvent
        pas rendre le même résultat au point du saut — sinon le test ne prouverait rien."""
        import numpy as np
        pts = [[i * 0.5, 0.0 if i < 6 else 10.0, 0.0] for i in range(n)]
        return np.array(pts, dtype=float)

    def test_le_lissage_CAUSAL_n_utilise_AUCUN_point_posterieur(self):
        """Le test qui porte l'intention : on modifie le FUTUR d'un point et sa valeur
        lissée ne doit pas bouger. Une fenêtre centrée, elle, bougerait."""
        from wama_lab.cam_analyzer.utils.prediction_adapter import smooth_trajectory
        a = self._rampe()
        b = a.copy()
        # ⚠ Le point modifié doit tomber DANS la fenêtre centrée du point observé, sinon le
        # test ne prouve rien : à i=5 avec window=5, elle couvre [3..7]. Ma 1ʳᵉ version
        # modifiait à partir de 8 — hors fenêtre — et les deux lissages rendaient la même
        # valeur, ce qui se lisait « le centré ne regarde pas le futur ».
        b[6:, 1] = 999.0                      # on change UNIQUEMENT le futur du point 5
        i = 5
        self.assertAlmostEqual(smooth_trajectory(a, causal=True)[i, 1],
                               smooth_trajectory(b, causal=True)[i, 1], places=9)
        self.assertNotAlmostEqual(smooth_trajectory(a, causal=False)[i, 1],
                                  smooth_trajectory(b, causal=False)[i, 1], places=3)

    def test_le_defaut_reste_la_fenetre_CENTREE(self):
        from wama_lab.cam_analyzer.utils.prediction_adapter import smooth_trajectory
        a = self._rampe()
        self.assertTrue((smooth_trajectory(a) == smooth_trajectory(a, causal=False)).all())

    def test_la_bascule_est_LUE_et_RAPPORTEE(self):
        rep = annotate_prediction_indicators(_Session({'prediction_causal_smoothing': True}))
        self.assertTrue(rep['causal_smoothing'])
        self.assertFalse(annotate_prediction_indicators(_Session())['causal_smoothing'])

    def test_une_trajectoire_plus_courte_que_la_fenetre_est_rendue_TELLE_QUELLE(self):
        from wama_lab.cam_analyzer.utils.prediction_adapter import smooth_trajectory
        a = self._rampe(n=3)
        for causal in (False, True):
            with self.subTest(causal=causal):
                self.assertTrue((smooth_trajectory(a, causal=causal) == a).all())


if __name__ == '__main__':
    unittest.main(verbosity=2)

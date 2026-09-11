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

    CLES = {'annotated', 'ttc', 'pet', 'ttc_median', 'pet_median', 'method'}

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


if __name__ == '__main__':
    unittest.main(verbosity=2)

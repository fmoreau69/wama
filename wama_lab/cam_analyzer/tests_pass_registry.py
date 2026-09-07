"""Le registre des passes (`pass_tracking.PASSES`) — déclaration UNIQUE du pipeline (2026-09-07).

Le test qui compte est `test_PassType_et_PASSES_declarent_le_MEME_ensemble` : `PassType` reste la
source des libellés et des valeurs persistées, le registre celle du graphe ; s'ils divergent, une
passe existe pour la base et pas pour le panneau (ou l'inverse) — exactement la dérive que six
copies du même graphe rendaient possible sans qu'aucun test ne la voie.

    python manage.py test wama_lab.cam_analyzer.tests_pass_registry
"""
import unittest

from wama_lab.cam_analyzer.utils import pass_tracking as pt


class RegistreTest(unittest.TestCase):

    def test_PassType_et_PASSES_declarent_le_MEME_ensemble(self):
        from wama_lab.cam_analyzer.models import AnalysisPass
        self.assertEqual(set(AnalysisPass.PassType.values), set(pt.ORDER))

    def test_cles_uniques_et_etages_connus(self):
        self.assertEqual(len(set(pt.ORDER)), len(pt.ORDER))
        for p in pt.PASSES:
            with self.subTest(passe=p.key):
                self.assertIn(p.stage, ('analyse', 'calcul'))

    def test_toute_dependance_designe_une_passe_du_registre(self):
        for p in pt.PASSES:
            for d in p.depends_on:
                with self.subTest(passe=p.key, amont=d):
                    self.assertIn(d, pt._BY_KEY)

    def test_un_calcul_ne_depend_jamais_d_un_calcul_seul_sans_analyse_en_amont(self):
        """Un étage CALCUL dérive des données : remonter ses amonts doit toujours atteindre
        l'analyse (sinon la passe calculerait à partir de rien)."""
        def _racines(k, vus=None):
            vus = vus or set()
            for d in pt._DEPENDS_ON.get(k, []):
                if d not in vus:
                    vus.add(d); _racines(d, vus)
            return vus
        for p in pt.PASSES:
            if p.stage != 'calcul':
                continue
            with self.subTest(passe=p.key):
                self.assertTrue(any(pt._STAGE[r] == 'analyse' for r in _racines(p.key)))

    def test_les_derives_portent_les_MEMES_noms_pour_les_consommateurs_existants(self):
        # recompute_stale, get_passes_status et views lisent ces dicts par leur nom historique.
        self.assertEqual(set(pt._WATCHED), set(pt.ORDER))
        self.assertEqual(set(pt._STAGE), set(pt.ORDER))
        self.assertEqual(set(pt._DEPENDS_ON), set(pt.ORDER))
        self.assertEqual(pt._PER_CAMERA_PASSES, {'yolo_detect', 'yolopv2_lanes', 'sam3_markings'})

    def test_les_valeurs_d_avant_le_registre_sont_CONSERVEES(self):
        """Empreinte des six dicts tels qu'ils étaient écrits à la main (relevé 2026-09-07) :
        le registre les REMPLACE, il ne doit pas les changer — sauf les deux dépendances
        ajoutées (depth ← yolo_detect, depth_calc ← depth), absentes à tort avant."""
        self.assertEqual(pt._WATCHED['yolo_detect'], ['model_path', 'iou_threshold', 'tracker'])
        self.assertEqual(pt._WATCHED['sam3_markings'],
                         ['sam3_markings_enabled', 'sam3_markings_prompts', 'sam3_as_road_fallback'])
        self.assertEqual(pt._WATCHED['temporal_segments'], ['target_classes', 'confidence'])
        self.assertEqual(pt._DEPENDS_ON['indicators'], ['global_tracking', 'distance'])
        self.assertEqual(pt._DEPENDS_ON['conflicts'], ['lane_events', 'distance'])
        self.assertEqual(pt._DEPENDS_ON['sam3_markings'], ['extraction', 'intersection_windows'])
        self.assertEqual(pt._STAGE['depth'], 'analyse')
        self.assertEqual(pt._STAGE['depth_calc'], 'calcul')
        self.assertEqual(pt._DEPENDS_ON['depth'], ['yolo_detect'])
        self.assertEqual(pt._DEPENDS_ON['depth_calc'], ['depth'])


class OrdreTopologiqueTest(unittest.TestCase):

    def test_tout_amont_precede_son_aval_sur_l_etage_calcul_entier(self):
        ordre = pt.topological_order(pt.stage_keys('calcul'))
        pos = {k: i for i, k in enumerate(ordre)}
        for k in ordre:
            for d in pt._DEPENDS_ON[k]:
                if d in pos:
                    with self.subTest(passe=k, amont=d):
                        self.assertLess(pos[d], pos[k])

    def test_le_cas_qui_a_motive_la_chaine(self):
        """`conflicts` ne doit JAMAIS partir avant `distance` ni `lane_events`."""
        ordre = pt.topological_order({'conflicts', 'distance', 'lane_events'})
        self.assertEqual(ordre, ['lane_events', 'distance', 'conflicts'])

    def test_les_amonts_absents_de_la_demande_ne_sont_pas_ajoutes(self):
        self.assertEqual(pt.topological_order({'indicators'}), ['indicators'])

    def test_a_egalite_l_ordre_de_declaration_est_conserve(self):
        self.assertEqual(pt.topological_order(pt.stage_keys('analyse')), pt.stage_keys('analyse'))


class DispatchTest(unittest.TestCase):

    def test_chaque_task_declaree_existe_dans_tasks(self):
        import importlib
        tasks = importlib.import_module('wama_lab.cam_analyzer.tasks')
        for p in pt.PASSES:
            if p.task:
                with self.subTest(passe=p.key):
                    fn = getattr(tasks, p.task, None)
                    self.assertIsNotNone(fn, f"{p.task} absent de tasks.py")
                    self.assertTrue(hasattr(fn, 'si'), "doit être une tâche Celery (signature .si)")

    def test_les_passes_sans_task_sont_celles_portees_ailleurs(self):
        sans = {p.key for p in pt.PASSES if not p.task}
        # extraction = panneau RTMaps ; intersection_windows = synchrone (recompute_intersection_
        # windows) ; yolo/yolopv2 = process_session_task SEUL. ⚠ lane_events et distance ont bien
        # une tâche dédiée : enchaînées dans process_session_task quand YOLO tourne, elles se
        # relancent SEULES sinon (sans repayer YOLO) — 1ʳᵉ rédaction de ce test les excluait à tort.
        self.assertEqual(sans, {'extraction', 'intersection_windows', 'yolo_detect', 'yolopv2_lanes'})


if __name__ == '__main__':
    unittest.main(verbosity=2)

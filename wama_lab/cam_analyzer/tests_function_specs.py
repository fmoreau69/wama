"""Les déclarations de capacité du cam_analyzer (`function_specs.py`) — ce que le système
sait des traitements, et qui doit rester vrai quand le code bouge.

Le contrôle générique vit dans `wama.common.tests_catalogues.FunctionCatalogConformiteTest` ;
ici, ce qui est PROPRE à l'app : le rôle `reference` de la trace ego (marche C), et la
correspondance passe ↔ fonction (palier D13 ③, export du registre `PASSES` en pipeline).
"""
from django.test import SimpleTestCase


class RoleDesPortsCamAnalyzerTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from wama.common.catalog.function_catalog import load_all, FUNCTION_CATALOG
        load_all()
        cls.specs = {k: s for k, s in FUNCTION_CATALOG.items() if k.startswith('cam_analyzer.')}

    def test_le_registre_de_l_app_est_peuple(self):
        self.assertGreaterEqual(len(self.specs), 20)

    def test_une_entree_optionnelle_est_une_reference_jamais_du_travail(self):
        """Marche C (`WAMA_DATA_WORLD §9`) : `track`/`road_map` `optional=True` étaient des
        références DE FAIT sans le dire — un port optionnel de travail n'existe pas ici."""
        for cle, spec in self.specs.items():
            for p in spec.inputs:
                if p.optional:
                    with self.subTest(fonction=cle, port=p.key):
                        self.assertEqual(p.group, 'reference')

    def test_la_trace_ego_a_cote_des_detections_est_une_reference(self):
        """La trace SERT à positionner les détections ; elle n'est transformée que par le
        filtre navette, où elle est LA donnée de travail (et le port le dit)."""
        for cle, spec in self.specs.items():
            cles = [p.key for p in spec.inputs]
            if 'track' not in cles:
                continue
            port = next(p for p in spec.inputs if p.key == 'track')
            with self.subTest(fonction=cle):
                if cle == 'cam_analyzer.shuttle_filter':
                    self.assertEqual(port.group, '', "le filtre transforme la trace : travail")
                elif 'detections' in cles or 'depth' in cles or 'markings' in cles:
                    self.assertEqual(port.group, 'reference')

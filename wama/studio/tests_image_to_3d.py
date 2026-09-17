"""§17ter trou 4 — image → objet 3D : ce qui s'atteste SANS GPU.

La déclaration (spec de fonction, ses ports, son `impl`), le lien modèle ↔ moteur (catalogue →
`backend_for_key` → `TripoSRBackend`), le contrat du backend, le routage Celery, et le geste
neuf de l'exécuteur : une fonction app-bound reçoit les FICHIERS de l'amont par port, sans
jamais recevoir ce que sa tâche n'accepte pas. L'inférence elle-même se valide au premier run
GPU, avec Fabien.
"""
from django.test import TestCase, override_settings


def fake_impl(image, user_id, resolution=256):
    """Une `impl` sans Celery : rend ce qu'elle a reçu (le contrat, pas le calcul)."""
    return {'image': image, 'user_id': user_id, 'resolution': resolution}


class LaFonctionEstDeclareeTest(TestCase):
    def setUp(self):
        from wama.common.catalog import function_catalog as fc
        fc.load_all()
        self.fc = fc

    def test_studio_image_to_3d_est_au_catalogue_avec_ses_ports(self):
        """⚠ Les DEUX ports parlent NATURE média (2026-09-17) : une image entre, un objet 3d
        sort. La sortie a porté `DataType.OBJECT_3D` quatre jours — un jumeau du même objet
        dans la taxonomie Data, retiré sur décision de Fabien."""
        from wama.common.catalog.data_types import known_types
        spec = self.fc.get('studio.image_to_3d')
        self.assertIsNotNone(spec)
        self.assertEqual(spec.binding, self.fc.Binding.APP)
        self.assertEqual([(p.key, p.data_type) for p in spec.inputs], [('image', 'image')])
        self.assertEqual(spec.outputs[0].data_type, '3d')
        self.assertNotIn('object_3d', known_types(),
                         'le jumeau est revenu dans la taxonomie du monde Data')
        self.assertIn('plausible', spec.tags)                  # §17ter : déclaré, pas en mémoire

    def test_son_impl_se_resout_et_exige_l_image_et_l_utilisateur(self):
        from wama.studio.tasks import _impl_callable, app_function_job_kwargs
        spec = self.fc.get('studio.image_to_3d')
        self.assertTrue(hasattr(_impl_callable(spec.impl), 'apply_async'))
        self.assertEqual(set(app_function_job_kwargs(spec.impl)), {'image', 'user_id'})


class LeModeleEtSonMoteurTest(TestCase):
    def test_la_decouverte_declare_TripoSR_avec_son_moteur_et_sa_nature_plausible(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        reg = ModelRegistry()
        reg._models = {}
        reg._discover_image_to_3d_models()
        m = reg._models['huggingface:triposr']
        self.assertEqual(m.composition['runtime']['engine'], 'triposr')
        self.assertEqual(m.capabilities['task'], 'image-to-3d')
        self.assertEqual(m.capabilities['reconstruction'], 'plausible')
        self.assertEqual(m.hf_id, 'stabilityai/TripoSR')

    def test_le_moteur_triposr_est_pilote_par_le_backend_sous_contrat(self):
        from wama.common.backends.base import BaseModelBackend
        from wama.common.backends.image_to_3d_backend import TripoSRBackend
        from wama.common.backends.manager import backend_for_engine
        self.assertIs(backend_for_engine('triposr'), TripoSRBackend)
        self.assertTrue(issubclass(TripoSRBackend, BaseModelBackend))
        self.assertEqual(TripoSRBackend.ENGINE, 'triposr')
        self.assertFalse(TripoSRBackend.supports_cloning)
        self.assertGreater(TripoSRBackend.recommended_vram_gb, 0)

    def test_la_cle_de_catalogue_resout_le_backend(self):
        from wama.common.backends.image_to_3d_backend import TripoSRBackend
        from wama.common.backends.manager import backend_for_key
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='huggingface:triposr', name='TripoSR', model_type='vision',
                               source='huggingface', capabilities={'task': 'image-to-3d'},
                               composition={'runtime': {'engine': 'triposr'}})
        self.assertIs(backend_for_key('huggingface:triposr'), TripoSRBackend)

    def test_missing_packages_nomme_le_code_vendorise_quand_il_manque(self):
        """Le vendoring fait partie de la disponibilité — un backend qui se croirait prêt sans
        `tsr/` planterait au `load()`, pas au grisage."""
        from unittest.mock import patch
        from pathlib import Path
        from wama.common.backends import image_to_3d_backend as m
        with patch.object(m, 'VENDOR_DIR', Path('/nulle/part')):
            manques = m.TripoSRBackend.missing_packages()
        self.assertTrue(any(x.startswith('vendor:triposr') for x in manques), manques)


class LeRoutageTest(TestCase):
    def test_les_taches_gpu_du_studio_vont_sur_la_file_gpu_pas_sur_l_orchestrateur(self):
        from django.conf import settings
        routes = settings.CELERY_TASK_ROUTES
        self.assertEqual(routes['wama.studio.gpu_tasks.*']['queue'], 'gpu')
        self.assertEqual(routes['wama.studio.tasks.*']['queue'], 'studio')
        from wama.common.services.resource_governor import APP_TIERS
        self.assertIn('studio', APP_TIERS)


class LExecuteurPasseLesFichiersDeLAmontTest(TestCase):
    def test_une_fonction_app_recoit_ses_fichiers_par_port_et_rien_d_autre(self):
        from wama.common.catalog.function_catalog import FunctionSpec, PortSpec, Binding
        from wama.studio.tasks import _run_app_function
        spec = FunctionSpec(key='t.fake', name='f', description='', category='transform',
                            binding=Binding.APP, app='studio',
                            impl='studio.tests_image_to_3d:fake_impl',
                            inputs=[PortSpec('image', 'image')])
        res = _run_app_function(spec, {'user_id': 7, 'resolution': '128'}, lambda **k: None, 10,
                                inputs={'image': 'users/7/x.png', 'autre': 'ignoré'})
        self.assertEqual(res, {'image': 'users/7/x.png', 'user_id': 7, 'resolution': '128'})

    def test_sans_l_image_le_manque_est_nomme(self):
        from wama.common.catalog.function_catalog import FunctionSpec, PortSpec, Binding
        from wama.studio.tasks import _run_app_function
        spec = FunctionSpec(key='t.fake2', name='f', description='', category='transform',
                            binding=Binding.APP, app='studio',
                            impl='studio.tests_image_to_3d:fake_impl',
                            inputs=[PortSpec('image', 'image')])
        with self.assertRaisesRegex(ValueError, 'image'):
            _run_app_function(spec, {'user_id': 7}, lambda **k: None, 10, inputs={})

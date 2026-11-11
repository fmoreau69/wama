"""Chantier B1 — le squelette ATTEND sans plafond, REFUSE ce qui ne tiendra jamais, LIBÈRE sur
accord explicite, DÉCLARE sa tâche au gouverneur et BORNE sa durée (2026-09-20).

POURQUOI. Trois cas de Fabien (20/09) au lieu de « différer puis échouer » ; et deux faits
mesurés : « une tâche GPU tourne » n'était visible que dans les statuts des tables d'app, et
`--pool=solo` n'honore aucune limite de temps Celery (`concurrency/solo.py:29`).

Aucun GPU, aucun Redis : la sonde et la carte sont simulées, le registre est le faux Redis.
"""
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.services import resource_governor as gov
from wama.common.tests.tests_vram_ledger import SYSTEM_MONITOR, _FauxRedis
from wama.common.utils.task_skeleton import _differer_faute_de_vram, run_item_task, TaskContext


class _Retry(Exception):
    pass


def _task(essais=0):
    class _T:
        class request:
            id = 'tache-test'
            retries = essais
            delivery_info = {}

        @staticmethod
        def retry(**kw):
            return _Retry(f"retry {kw}")
    return _T


class _Base(TestCase):

    def setUp(self):
        from wama.synthesizer.models import VoiceSynthesis
        self.user = get_user_model().objects.create_user('b1_owner', password='x')
        self.other = get_user_model().objects.create_user('b1_other', password='x')
        self.model = VoiceSynthesis
        self.item = VoiceSynthesis.objects.create(user=self.user, text_content='bonjour')
        self.redis = _FauxRedis()
        for kw in ({'_redis': mock.Mock(return_value=self.redis)},
                   {'total_vram_gb': mock.Mock(return_value=24.0)}):
            p = mock.patch.multiple(gov, **kw)
            p.start()
            self.addCleanup(p.stop)
        # Une carte VIDE de 24 Go : ce qu'elle peut libérer (`card_ceiling_gb`) ne dépend pas du poste.
        for p in (mock.patch(SYSTEM_MONITOR, return_value=[{'memory_free_gb': 24.0,
                                                             'memory_used_gb': 0.0}]),
                  mock.patch('wama.common.utils.task_skeleton.close_old_connections')):
            p.start()
            self.addCleanup(p.stop)

    def _ctx(self):
        return TaskContext('synthesizer', self.model, self.item)

    def _defer(self, needed, free=1.0, essais=0):
        with mock.patch.object(gov, 'effective_free_gb', return_value=free):
            return _differer_faute_de_vram(_task(essais), self._ctx(), self.item, self.model,
                                           self.item.pk, 'synthesizer', needed, 'error_message')

    def _status(self):
        self.item.refresh_from_db()
        return self.item.status


class ThreeCasesTest(_Base):

    def test_what_never_fits_is_refused_at_once_and_said(self):
        self.assertTrue(self._defer(32.5))
        self.assertEqual(self._status(), 'FAILURE')
        self.assertIn('même seul', self.item.error_message)

    def test_what_the_card_cannot_free_is_refused_and_the_held_part_is_said(self):
        """2026-11-05 : 3,7 Go tenus hors de WAMA laissent 20,3 Go au mieux. FLUX.1-dev en poids
        pleins (22,17) « tenait seul » face au total et attendait sans fin."""
        with mock.patch(SYSTEM_MONITOR, return_value=[{'memory_free_gb': 20.3,
                                                       'memory_used_gb': 3.7}]):
            self.assertTrue(self._defer(22.17))
        self.assertEqual(self._status(), 'FAILURE')
        self.assertIn('libérer au mieux 20.3', self.item.error_message)
        self.assertIn('hors de WAMA', self.item.error_message)

    def test_what_fits_alone_but_not_now_waits_without_a_ceiling_and_says_who_holds(self):
        gov.reserve_vram('wama.x.Big:1#imager:qwen-image-2', 18.0)
        with self.assertRaises(_Retry) as cm:
            self._defer(20.0, essais=999)
        # Pas `None` : pour Celery, `max_retries=None` vaut « le défaut de la tâche » (3), pas
        # « sans plafond » — la première vraie attente est morte à la 3ᵉ re-livraison (03/10).
        from wama.common.utils.task_skeleton import WAIT_RETRIES_UNLIMITED
        self.assertIn(f"'max_retries': {WAIT_RETRIES_UNLIMITED}", str(cm.exception))
        self.assertEqual(self._status(), 'AWAITING_RESOURCES')
        self.assertEqual(self.item.error_message, '')

    def test_the_owner_s_grant_asks_the_tenants_and_is_consumed(self):
        gov.grant_release('synthesizer', self.item.pk, user_id=self.user.pk)
        with mock.patch.object(gov, 'obtain_vram', return_value=(True, 22.0)) as obtain:
            self.assertFalse(self._defer(20.0))
        obtain.assert_called_once()
        self.assertEqual(obtain.call_args.args[0], 20.0)
        self.assertIsNone(gov.release_granted('synthesizer', self.item.pk))

    def test_a_grant_the_launch_did_not_need_does_not_outlive_it(self):
        """L'accord sert une fois : un item parti sans lui ne le garde pas pour sa relance."""
        gov.grant_release('synthesizer', self.item.pk, user_id=self.user.pk)
        with mock.patch.object(gov, 'obtain_vram') as obtain:
            self.assertFalse(self._defer(20.0, free=22.0))
        obtain.assert_not_called()
        self.assertIsNone(gov.release_granted('synthesizer', self.item.pk))

    def test_a_stranger_s_grant_is_ignored_and_the_item_waits(self):
        gov.grant_release('synthesizer', self.item.pk, user_id=self.other.pk)
        with mock.patch.object(gov, 'obtain_vram') as obtain:
            with self.assertRaises(_Retry):
                self._defer(20.0)
        obtain.assert_not_called()

    def test_an_admin_s_grant_is_honoured(self):
        from wama.accounts.permissions import set_account_tier
        admin = get_user_model().objects.create_user('b1_admin', password='x')
        set_account_tier(admin, 'admin')
        gov.grant_release('synthesizer', self.item.pk, user_id=admin.pk)
        with mock.patch.object(gov, 'obtain_vram', return_value=(True, 22.0)):
            self.assertFalse(self._defer(20.0))

    def test_when_the_release_does_not_suffice_the_item_waits_with_the_measured_free(self):
        gov.grant_release('synthesizer', self.item.pk, user_id=self.user.pk)
        with mock.patch.object(gov, 'obtain_vram', return_value=(False, 3.0)):
            with self.assertRaises(_Retry):
                self._defer(20.0)
        self.assertEqual(self._status(), 'AWAITING_RESOURCES')


class OffloadingEngineNeedTest(TestCase):
    """Le besoin dérivé du modèle est le pic de la stratégie que son moteur SAIT appliquer
    (2026-11-01) : FLUX.1-dev, relevé réel 31,42 Go de somme pour 22,17 de transformer, était
    refusé « il ne tiendra jamais » sur une carte de 24 Go que son moteur sait occuper déchargé."""

    KEY = 'imager:flux-1-dev'

    def setUp(self):
        from wama.model_manager.models import AIModel
        AIModel.objects.create(
            model_key=self.KEY, name='flux-1-dev', model_type='image', source='imager',
            is_downloaded=True, capabilities={'task': 'text-to-image'},
            composition={'runtime': {'engine': 'diffusers'}},
            extra_info={'weights': {'total_gb': 31.42, 'largest_gb': 22.17}})

    def _need(self):
        from wama.common.utils.task_skeleton import _vram_need
        with mock.patch.object(gov, 'resident_here_gb', return_value=0.0):
            return _vram_need(None, None, self.KEY)

    def test_an_engine_that_offloads_is_judged_on_its_largest_component(self):
        self.assertEqual(self._need(), 22.17)

    def test_an_engine_that_does_not_offload_keeps_the_sum(self):
        class _Resident:
            OFFLOADS = False
        with mock.patch('wama.common.backends.manager.backend_for_key', return_value=_Resident):
            self.assertEqual(self._need(), 31.42)

    def test_the_flux_row_resolves_to_a_backend_that_offloads(self):
        from wama.common.backends.manager import backend_for_key
        backend = backend_for_key(self.KEY)
        self.assertIsNotNone(backend)
        self.assertTrue(backend.OFFLOADS, backend.__name__)


#: Le relevé RÉEL de FLUX.1-dev (composants et paramètres, en-têtes safetensors).
FLUX_WEIGHTS = {
    'total_gb': 31.42, 'largest_gb': 22.17,
    'components': {'vae': 0.156, 'transformer': 22.168, 'text_encoder': 0.229,
                   'text_encoder_2': 8.871},
    'precision': {'vae': {'params': 83819683}, 'transformer': {'params': 11901408320},
                  'text_encoder': {'params': 123060480}, 'text_encoder_2': {'params': 4762310656}},
}


class _Card(TestCase):
    """Un registre vide et une carte posée par le test — et des précisions de FLUX qui ne dépendent
    pas du disque du poste : les poids publiés à part (le GGUF) sont cherchés dans un dossier vide,
    le vrai fichier pouvant être installé ici (`GgufPrecisionTest` y pose le sien)."""

    def setUp(self):
        import dataclasses
        import shutil
        import tempfile
        from wama.common.backends.diffusers_backend import DiffusersBackend
        self.redis = _FauxRedis()
        self.folder = tempfile.mkdtemp(prefix='wama_gguf_')
        self.addCleanup(shutil.rmtree, self.folder, True)
        precisions = tuple(dataclasses.replace(p, weights_dir=self.folder) if p.weights else p
                           for p in DiffusersBackend.FLUX_PRECISIONS)
        for p in (mock.patch.object(gov, '_redis', return_value=self.redis),
                  mock.patch.object(gov, 'total_vram_gb', return_value=23.99),
                  mock.patch.object(DiffusersBackend, 'FLUX_PRECISIONS', precisions)):
            p.start()
            self.addCleanup(p.stop)

    def card(self, free, used):
        return mock.patch(SYSTEM_MONITOR, return_value=[{'memory_free_gb': free,
                                                         'memory_used_gb': used}])


class PrecisionChosenByTheGovernorTest(_Card):
    """La précision de FLUX se choisit au GOUVERNEUR, parmi celles que le moteur déclare
    (accord de Fabien, 2026-11-05). Mesuré ce jour-là : la règle du moteur (RAM, puis total de la
    carte) prenait sur 24 Go les poids pleins ou le 8 bits, qui ne tiennent pas, jamais le 4 bits."""

    KEY = 'imager:flux-1-dev'

    def setUp(self):
        super().setUp()
        from wama.model_manager.models import AIModel
        AIModel.objects.create(
            model_key=self.KEY, name='flux-1-dev', model_type='image', source='imager',
            is_downloaded=True, capabilities={'task': 'text-to-image'},
            platform_ref='huggingface:black-forest-labs/FLUX.1-dev',
            composition={'runtime': {'engine': 'diffusers'}},
            extra_info={'weights': FLUX_WEIGHTS})

    def test_on_this_card_the_governor_retains_the_4_bits(self):
        with self.card(20.3, 3.7):
            choice = gov.chosen_precision(self.KEY)
        self.assertEqual((choice.precision.label, choice.peak_gb, choice.reduced), ('NF4', 8.87, True))
        self.assertEqual(choice.faithful_gb, 22.17)

    def test_a_card_that_holds_the_full_weights_gets_them_with_the_same_declaration(self):
        with self.card(60.0, 0.0), mock.patch.object(gov, 'total_vram_gb', return_value=80.0):
            choice = gov.chosen_precision(self.KEY)
        self.assertEqual((choice.precision.label, choice.reduced), ('BF16', False))

    def test_the_8_bits_needs_the_machine_margin_above_its_peak(self):
        """19,96 + la marge (1,5) : 21,46 Go. Sur 22 Go libérables, le 8 bits ; sur 20,3, non."""
        with self.card(22.0, 1.99):
            self.assertEqual(gov.chosen_precision(self.KEY).precision.label, 'INT8')

    def test_the_load_never_takes_more_faithful_than_what_fits_now(self):
        """La carte a pu changer entre la garde et le chargement : le chargement ne prend jamais une
        précision plus fidèle que ce que le libre de l'instant tient."""
        with self.card(22.0, 1.99), mock.patch.object(gov, 'effective_free_gb', return_value=12.0):
            self.assertEqual(gov.chosen_precision(self.KEY, fits_now=True).precision.label, 'NF4')

    def test_a_precision_whose_library_is_missing_is_not_offered(self):
        from wama.common.backends.diffusers_backend import DiffusersBackend
        with self.card(20.3, 3.7), mock.patch('importlib.util.find_spec', return_value=None):
            choice = gov.chosen_precision(self.KEY, DiffusersBackend)
        self.assertEqual(choice.precision.label, 'BF16',
                         "sans bitsandbytes, seule la précision des fichiers reste")

    def test_the_guard_asks_the_peak_of_the_chosen_precision_and_tells_the_card(self):
        from wama.common.utils.task_skeleton import _vram_need
        said = []
        ctx = mock.Mock(console=lambda msg, **kw: said.append(msg))
        with self.card(20.3, 3.7):
            self.assertEqual(_vram_need(None, None, self.KEY, ctx), 8.87)
        self.assertEqual(len(said), 1)
        self.assertIn('NF4', said[0])
        self.assertIn('22.2', said[0])

    def test_the_engine_applies_the_governor_s_choice(self):
        """Une carte où le gouverneur retient le 8 bits : le repli du moteur (le plus réduit) dirait
        4 bits — le test distingue donc le choix du gouverneur de l'absence de choix."""
        from wama.common.backends.diffusers_backend import DiffusersBackend
        engine = DiffusersBackend()
        engine.catalogue_key = self.KEY
        with self.card(22.0, 1.99), mock.patch.object(gov, 'effective_free_gb', return_value=22.0):
            self.assertEqual(engine._get_flux_strategy(),
                             {'quantization': '8bit', 'label': 'INT8', 'gguf': ''})

    def test_without_a_catalogue_key_the_engine_takes_the_most_reduced(self):
        from wama.common.backends.diffusers_backend import DiffusersBackend
        self.assertEqual(DiffusersBackend()._get_flux_strategy()['label'], 'NF4')

    def test_the_logo_lora_is_reduced_on_its_backbone(self):
        """L'adaptateur se pose sur sa dorsale : c'est elle que la précision réduit, son fichier
        (0,04 Go) s'y ajoute — l'option B de l'empreinte (décision du 2026-09-21)."""
        from wama.model_manager.models import AIModel
        AIModel.objects.filter(model_key=self.KEY).update(
            extra_info={'weights': FLUX_WEIGHTS, 'model_type': 'base',
                        'base_model': 'black-forest-labs/FLUX.1-dev'})
        AIModel.objects.create(
            model_key='imager:flux-lora-logo-design', name='LoRA logo', model_type='image',
            source='imager', is_downloaded=True, capabilities={'task': 'text-to-image'},
            platform_ref='huggingface:Shakker-Labs/FLUX.1-dev-LoRA-Logo-Design',
            composition={'runtime': {'engine': 'diffusers'}},
            extra_info={'weights': {'total_gb': 0.036, 'largest_gb': 0.036},
                        'model_type': 'lora', 'base_model': 'black-forest-labs/FLUX.1-dev'})
        with self.card(20.3, 3.7):
            choice = gov.chosen_precision('imager:flux-lora-logo-design')
        self.assertEqual((choice.precision.label, choice.peak_gb), ('NF4', 8.91))

    def test_a_variant_replacing_a_backbone_component_is_reduced_on_the_merged_anatomy(self):
        """Une variante affinée qui publie son seul transformer, sous le rôle de sa dorsale
        (2026-11-10, le cas d'ACE-Step SFT : « Dorsale ») : son transformer REMPLACE celui de la
        dorsale — le pic est celui de FLUX réduit (8,87), pas 8,87 + ses 22,17 Go de fichier."""
        from wama.model_manager.models import AIModel
        AIModel.objects.create(
            model_key='imager:flux-finetune', name='FLUX affiné', model_type='image',
            source='imager', is_downloaded=True, capabilities={'task': 'text-to-image'},
            platform_ref='huggingface:org/flux-finetune',
            composition={'runtime': {'engine': 'diffusers'}},
            extra_info={'base_model': 'black-forest-labs/FLUX.1-dev', 'base_model_relation': 'finetune',
                        'weights': {'total_gb': 22.168, 'largest_gb': 22.168,
                                    'components': {'transformer': 22.168},
                                    'precision': {'transformer': {'params': 11901408320}}}})
        from wama.common.backends.diffusers_backend import DiffusersBackend
        # La variante n'est pas au `model_config` de l'imager : le moteur lui déclare les
        # précisions de FLUX comme à sa dorsale.
        with self.card(20.3, 3.7), mock.patch.object(
                DiffusersBackend, 'load_precisions',
                classmethod(lambda cls, model_id: cls.FLUX_PRECISIONS)):
            choice = gov.chosen_precision('imager:flux-finetune', DiffusersBackend)
        self.assertEqual((choice.precision.label, choice.peak_gb), ('NF4', 8.87))

    def test_an_engine_without_precisions_keeps_the_catalogue_cascade(self):
        class _Plain:
            OFFLOADS = False

            @classmethod
            def load_precisions(cls, model_id):
                return ()
        self.assertIsNone(gov.chosen_precision(self.KEY, _Plain))


class ServedModelNeedTest(_Card):
    """Un modèle déjà chargé dans le process qui le SERVIRA n'est pas un besoin (2026-11-05)."""

    def _row(self, key, engine, gb):
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key=key, name=key, model_type='speech', source=key.split(':')[0],
                               is_downloaded=True, vram_gb=gb,
                               composition={'runtime': {'engine': engine}})

    def _need(self, key, backend=None):
        from wama.common.utils.task_skeleton import _vram_need
        with self.card(9.39, 14.2), \
                mock.patch('wama.common.backends.manager.backend_for_key', return_value=backend):
            return _vram_need(None, None, key)

    def test_a_voice_model_the_voice_service_holds_is_not_waited_for(self):
        class _Voice:
            OFFLOADS = False
            SERVED_BY = 'tts_service'

            @classmethod
            def load_precisions(cls, model_id):
                return ()
        self._row('synthesizer:higgs-test', 'higgs', 11.5)
        self.redis.hset(gov._TENANTS_KEY, 'tts_service', '4242')
        gov.reserve_vram('b.Higgs:4242#synthesizer:higgs-test', 11.5, allocated=True)
        self.assertIsNone(self._need('synthesizer:higgs-test', _Voice))
        gov.release_reservation('b.Higgs:4242#synthesizer:higgs-test')
        self.assertEqual(self._need('synthesizer:higgs-test', _Voice), 11.5,
                         "absent du service, il faut la place de le charger")

    def test_an_ollama_model_the_host_holds_is_not_waited_for(self):
        self._row('ollama:qwen-test:latest', 'ollama', 18.18)
        gov.reserve_vram(gov.ollama_host_owner('qwen-test:latest'), 18.18,
                         allocated=gov.OUTSIDE_TORCH)
        self.assertIsNone(self._need('ollama:qwen-test:latest'))


class ServedByTwinTest(TestCase):
    """`SERVED_BY` nomme un SERVICE du registre des sources, et ce service se déclare tenant sous ce
    même nom — sinon le gouverneur ne retrouve pas ses résidents."""

    def test_every_served_by_is_a_declared_local_service(self):
        from wama.common.backends.glm_ocr_backend import GlmOcrBackend
        from wama.common.backends.pii_detection_base import PIIDetectionBackend
        from wama.common.backends.tensorflow_base import TensorFlowBackend
        from wama.common.backends.tts_base import TTSBackend
        from wama.common.external_sources import SOURCES
        from wama.common.utils.ollama_host import ollama_engine_inventory
        services = {s.key for s in SOURCES if s.kind == 'service'}
        declared = {TTSBackend.SERVED_BY, PIIDetectionBackend.SERVED_BY, GlmOcrBackend.SERVED_BY,
                    TensorFlowBackend.SERVED_BY,
                    ollama_engine_inventory()['ollama'].SERVED_BY, gov.OLLAMA_HOST_SOURCE}
        self.assertEqual(declared - services, set())

    def test_each_service_names_its_tenant_by_the_key_its_engines_name(self):
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR) / 'wama' / 'common'
        self.assertIn('Tenant(TTS_SERVICE', (base / 'tts' / 'service.py').read_text(encoding='utf-8'))
        self.assertIn('contract_tenant(PRIVACY_SERVICE',
                      (base / 'privacy' / 'service.py').read_text(encoding='utf-8'))
        self.assertIn('Tenant(TENSORFLOW_SERVICE',
                      (base / 'tensorflow_service' / 'service.py').read_text(encoding='utf-8'))


class FluxPrecisionTwinTest(TestCase):
    """Ce que le moteur FLUX DÉCLARE, il sait le charger : chaque précision réduite a son chargement
    — bitsandbytes, ou les poids publiés à part qu'une ligne du catalogue porte (le GGUF) — et
    chaque étiquette se pèse (`dtype_bytes`)."""

    def test_every_declared_precision_is_loadable_and_weighable(self):
        from wama.common.backends.diffusers_backend import DiffusersBackend
        from wama.model_manager.services.memory_manager import dtype_bytes
        for precision in DiffusersBackend.FLUX_PRECISIONS:
            self.assertIsNotNone(dtype_bytes(precision.label), precision.label)
            if precision.quantized and not precision.weights:
                self.assertIn(precision.label, DiffusersBackend._FLUX_BNB)
            if precision.weights:
                self.assertEqual(precision.library, 'gguf', precision.label)
        self.assertEqual(DiffusersBackend.load_precisions('flux-1-dev'),
                         DiffusersBackend.FLUX_PRECISIONS)
        self.assertEqual(DiffusersBackend.load_precisions('stable-diffusion-xl'), ())


class GgufPrecisionTest(_Card):
    """Le Q8_0 GGUF de FLUX.1-dev (2026-11-06) : une précision dont les poids sont PUBLIÉS à part et
    installés par la route (pilote `files`, ligne `FLUX_GGUF_KEY`). Absente tant que son fichier
    n'est pas en place ; en place, elle se pèse à la taille DÉCLARÉE du fichier (11,84 Go, ses
    échelles comprises) et passe avant le 8 bits de bitsandbytes. Le dossier de la précision est
    le dossier jetable de `_Card` : le vrai fichier est peut-être installé sur ce poste."""

    KEY = 'imager:flux-1-dev'

    def setUp(self):
        super().setUp()
        from wama.model_manager.models import AIModel
        AIModel.objects.create(
            model_key=self.KEY, name='flux-1-dev', model_type='image', source='imager',
            is_downloaded=True, capabilities={'task': 'text-to-image'},
            platform_ref='huggingface:black-forest-labs/FLUX.1-dev',
            composition={'runtime': {'engine': 'diffusers'}},
            extra_info={'weights': FLUX_WEIGHTS})

    def _place_the_file(self):
        from pathlib import Path
        from wama.common.backends.diffusers_backend import FLUX_GGUF_WEIGHTS
        (Path(self.folder) / FLUX_GGUF_WEIGHTS).write_bytes(b'gguf')

    def test_absent_its_precision_is_not_offered(self):
        with self.card(20.3, 3.7):
            self.assertEqual(gov.chosen_precision(self.KEY).precision.label, 'NF4')

    def test_in_place_it_is_weighed_by_its_declared_size_and_retained(self):
        self._place_the_file()
        with self.card(20.3, 3.7):
            choice = gov.chosen_precision(self.KEY)
        # max(transformeur GGUF 12 708 281 504 o = 11,84 Gio, T5 8,87) : tout se décharge.
        self.assertEqual((choice.precision.label, choice.peak_gb), ('Q8_0', 11.84))

    def test_the_engine_loads_the_installed_file(self):
        from pathlib import Path
        from wama.common.backends.diffusers_backend import DiffusersBackend, FLUX_GGUF_WEIGHTS
        self._place_the_file()
        engine = DiffusersBackend()
        engine.catalogue_key = self.KEY
        with self.card(20.3, 3.7), mock.patch.object(gov, 'effective_free_gb', return_value=20.3):
            strategy = engine._get_flux_strategy()
        self.assertEqual(strategy, {'quantization': 'gguf', 'label': 'Q8_0',
                                    'gguf': str(Path(self.folder) / FLUX_GGUF_WEIGHTS)})

    def test_its_declaration_is_one_the_files_driver_accepts(self):
        from wama.common.backends.diffusers_backend import FLUX_GGUF_FILES, flux_gguf_folder
        from wama.common.utils.model_locations import models_root
        from wama.model_manager.services.model_installer import declared_files_error
        self.assertIsNone(declared_files_error({'files': list(FLUX_GGUF_FILES),
                                                'target_dir': str(flux_gguf_folder())}))
        flux_gguf_folder().resolve().relative_to(models_root().resolve())

    def test_the_catalogue_row_is_found_by_discovery_and_draws_no_task(self):
        """La ligne existe absente, installable par la route — et aucune tâche ne la tire : elle est
        FLUX.1-dev quantifié (relation `quantized`), pas un modèle à choisir."""
        from wama.common.backends.diffusers_backend import FLUX_GGUF_KEY
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = ModelRegistry.__new__(ModelRegistry)
        registry._models, registry.discovery_errors = {}, []
        registry._discover_precision_weights_models()
        self.assertEqual(registry.discovery_errors, [])
        row = registry._models[FLUX_GGUF_KEY]
        self.assertEqual((row.extra_info['base_model'], row.extra_info['base_model_relation']),
                         ('black-forest-labs/FLUX.1-dev', 'quantized'))
        self.assertEqual((row.extra_info['quantization'], row.extra_info['license']),
                         ('Q8_0', 'flux-1-dev-non-commercial'))
        self.assertEqual(row.extra_info['declared_files'][0]['path'], 'flux1-dev-Q8_0.gguf')
        self.assertNotIn('task', row.capabilities)


class OffloadDeclarationTwinTest(TestCase):
    """`OFFLOADS` dit ce que le code FAIT : une classe de `common/backends/` qui appelle un
    déchargement le déclare, et une classe qui le déclare en appelle un. Lu par AST."""

    CALLS = {'enable_model_cpu_offload', 'enable_sequential_cpu_offload', 'apply_offload_strategy'}

    def test_offloading_backends_and_their_declaration_agree(self):
        import ast
        from pathlib import Path
        from django.conf import settings
        folder = Path(settings.BASE_DIR) / 'wama' / 'common' / 'backends'
        calls_without, flagged_without, seen = [], [], 0
        for path in sorted(folder.glob('*.py')):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if not isinstance(node, ast.ClassDef):
                    continue
                offloads = any(
                    isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and c.func.attr in self.CALLS for c in ast.walk(node))
                declared = any(
                    isinstance(s, ast.Assign) and any(getattr(t, 'id', '') == 'OFFLOADS'
                                                      for t in s.targets)
                    and getattr(s.value, 'value', None) is True for s in node.body)
                seen += offloads
                if offloads and not declared:
                    calls_without.append(f'{path.name}:{node.name}')
                if declared and not offloads:
                    flagged_without.append(f'{path.name}:{node.name}')
        self.assertGreaterEqual(seen, 8, "le relevé ne voit plus les backends qui déchargent")
        self.assertEqual(calls_without, [], "déchargent sans déclarer OFFLOADS = True")
        self.assertEqual(flagged_without, [], "déclarent OFFLOADS = True sans décharger")


class TaskLineAndTimeGuardTest(_Base):

    def _run(self, glu, limit_s=None):
        with mock.patch.object(gov, 'task_time_limit_s', return_value=limit_s or 1800):
            run_item_task(_task(), app_id='synthesizer', model=self.model,
                          item_id=self.item.pk, process=glu)

    def test_the_running_task_is_declared_to_the_governor_for_the_time_of_the_process(self):
        seen = []

        def glu(item, ctx):
            seen.append([(t['app'], t['item']) for t in gov.running_tasks()])
            return {}

        self._run(glu)
        self.assertEqual(seen, [[('synthesizer', self.item.pk)]])
        self.assertEqual(gov.running_tasks(), [])
        self.assertEqual(self._status(), 'SUCCESS')

    def test_the_line_is_released_even_when_the_process_fails(self):
        def glu(item, ctx):
            raise RuntimeError('boum')

        self._run(glu)
        self.assertEqual(gov.running_tasks(), [])
        self.assertEqual(self._status(), 'FAILURE')

    def test_the_duration_limit_stops_the_process_cleanly_and_says_so(self):
        """`--pool=solo` n'honore aucune limite Celery : la garde du squelette la tient, dans le
        thread principal (ici aussi), et l'échec est relançable et explicite."""
        import signal
        if not hasattr(signal, 'SIGALRM'):
            self.skipTest('SIGALRM absent (Windows)')

        def glu(item, ctx):
            for _ in range(200):
                time.sleep(0.05)
            return {}

        t0 = time.monotonic()
        self._run(glu, limit_s=1)
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual(self._status(), 'FAILURE')
        self.assertIn('Durée maximale', self.item.error_message)
        self.assertEqual(gov.running_tasks(), [])


class GrantEndpointAndMuteAssistantTest(TestCase):
    """L'accord explicite passe par UN endpoint commun ; pendant une libération, l'assistant
    répond un message d'attente (texte) et la voix rend 503 — jamais un silence."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('b1_web', password='x')
        self.redis = _FauxRedis()
        p = mock.patch.object(gov, '_redis', return_value=self.redis)
        p.start()
        self.addCleanup(p.stop)
        self.client.force_login(self.user)

    def _media(self, owner):
        from wama.anonymizer.models import Media
        return Media.objects.create(user=owner, file='anonymizer/x/input/grant.png',
                                    file_ext='.png')

    def test_the_grant_is_recorded_with_the_user_who_gave_it(self):
        from django.urls import reverse
        item = self._media(self.user)
        r = self.client.post(reverse('model_manager:api_vram_grant'),
                             data=f'{{"app": "anonymizer", "item": {item.pk}}}',
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(gov.release_granted('anonymizer', item.pk)['user'], self.user.pk)
        r = self.client.post(reverse('model_manager:api_vram_grant'), data='{"app": ""}',
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_nobody_grants_for_an_item_they_do_not_own(self):
        """The route's OWN guard (2026-09-27): the skeleton re-checks when honouring, but a grant
        on someone else's item is not even written."""
        from django.urls import reverse
        other = get_user_model().objects.create_user('b1_other', password='x')
        item = self._media(other)
        r = self.client.post(reverse('model_manager:api_vram_grant'),
                             data=f'{{"app": "anonymizer", "item": {item.pk}}}',
                             content_type='application/json')
        self.assertEqual(r.status_code, 404)
        self.assertIsNone(gov.release_granted('anonymizer', item.pk))

    def test_the_grant_needs_a_logged_in_user(self):
        from django.urls import reverse
        self.client.logout()
        r = self.client.post(reverse('model_manager:api_vram_grant'),
                             data='{"app": "imager", "item": 7}',
                             content_type='application/json')
        self.assertIn(r.status_code, (302, 401, 403))
        self.assertIsNone(gov.release_granted('imager', 7))

    def test_the_awaiting_card_carries_the_grant_link_only_when_the_item_is_named(self):
        from django.template.loader import render_to_string
        with_link = render_to_string('common/_card_state.html',
                                     {'status': 'AWAITING_RESOURCES', 'app': 'imager', 'pk': 7})
        self.assertIn('vram-grant', with_link)
        self.assertIn('data-item="7"', with_link)
        without = render_to_string('common/_card_state.html', {'status': 'AWAITING_RESOURCES'})
        self.assertNotIn('vram-grant', without)
        self.assertIn('En attente de ressources', without)

    def test_the_assistant_stays_silent_with_a_waiting_message_during_a_release(self):
        from django.urls import reverse
        gov.request_release(20.0, requester='1')
        with mock.patch('wama.common.services.assistant_engine.conversation_turn') as turn:
            r = self.client.post(reverse('ai_chat'), data='{"message": "bonjour"}',
                                 content_type='application/json')
        turn.assert_not_called()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['busy'])
        self.assertIn('libère la carte', r.json()['response'])
        r = self.client.post(reverse('kokoro_tts'), data='{"text": "bonjour"}',
                             content_type='application/json')
        self.assertEqual(r.status_code, 503)
        self.assertTrue(r.json()['busy'])


class TaskTimeLimitSettingTest(TestCase):

    def test_the_default_is_thirty_minutes_and_the_user_can_raise_it(self):
        from wama.common.utils.user_settings import save_user_app_settings
        u = get_user_model().objects.create_user('b1_limit', password='x')
        # Une app SANS durée propre (l'imager a la sienne depuis le 2026-10-03, mesurée).
        self.assertEqual(gov.task_time_limit_s('describer', None), 1800)
        self.assertEqual(gov.task_time_limit_s('describer', u), 1800)
        save_user_app_settings(u, 'common', {gov.USER_SETTING_MAX_TASK_MINUTES: 90})
        self.assertEqual(gov.task_time_limit_s('describer', u), 5400)
        with mock.patch.dict(gov.TASK_MAX_MINUTES, {'composer': 45}):
            self.assertEqual(gov.task_time_limit_s('composer', None), 2700)
            self.assertEqual(gov.task_time_limit_s('composer', u), 5400)

    def test_a_model_can_carry_its_own_limit_set_in_the_model_manager(self):
        """2026-09-24 (Fabien: « 30 min, un peu léger pour une génération de vidéo »): the
        catalogue entry of a model carries its limit; the user's own setting still wins."""
        from wama.common.utils.user_settings import save_user_app_settings
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='enhancer:slow-video-test', name='slow', source='enhancer',
                               extra_info={gov.MODEL_INFO_MAX_TASK_MINUTES: 120})
        self.assertEqual(gov.task_time_limit_s('enhancer', None, model_key='enhancer:slow-video-test'), 7200)
        self.assertEqual(gov.task_time_limit_s('enhancer', None, model_key='enhancer:unknown'), 1800)
        u = get_user_model().objects.create_user('b1_limit_model', password='x')
        save_user_app_settings(u, 'common', {gov.USER_SETTING_MAX_TASK_MINUTES: 45})
        self.assertEqual(gov.task_time_limit_s('enhancer', u, model_key='enhancer:slow-video-test'), 2700)

    def test_the_model_manager_writes_and_clears_the_limit(self):
        from django.urls import reverse
        from wama.model_manager.models import AIModel
        m = AIModel.objects.create(model_key='enhancer:limit-api-test', name='l', source='enhancer')
        admin = get_user_model().objects.create_superuser('b1_limit_admin', password='x')
        self.client.force_login(admin)
        url = reverse('model_manager:api_model_task_limit')
        r = self.client.post(url, data=f'{{"model_id": {m.pk}, "minutes": 90}}',
                             content_type='application/json')
        self.assertEqual(200, r.status_code, r.content)
        m.refresh_from_db()
        self.assertEqual(90, m.extra_info[gov.MODEL_INFO_MAX_TASK_MINUTES])
        self.client.post(url, data=f'{{"model_id": {m.pk}, "minutes": 0}}',
                         content_type='application/json')
        m.refresh_from_db()
        self.assertNotIn(gov.MODEL_INFO_MAX_TASK_MINUTES, m.extra_info)
        r = self.client.post(url, data=f'{{"model_id": {m.pk}, "minutes": -5}}',
                             content_type='application/json')
        self.assertEqual(400, r.status_code)

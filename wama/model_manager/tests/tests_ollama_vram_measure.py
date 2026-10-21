"""La VRAM d'un modèle de l'Ollama hôte, MESURÉE au chargement et rendue au catalogue (2026-10-20).

POURQUOI. La voie mesurée (`record_measured_vram` → `persist_measured_vram` →
`extra_info['vram_measured']` → `model_footprint_gb`) n'était alimentée que par `_wrap_load`,
l'allocateur torch d'un process WAMA. Un modèle Ollama se charge dans un autre process : le
catalogue gardait l'heuristique de la découverte (la taille du fichier), et `/api/ps` sous-compte
— mesuré le 2026-10-20 : embeddinggemma-2 y annonce 0,45 Go pour 2,14 pris par la carte (ses
projecteurs n'y sont pas). Doc : `WAMA_MEMORY.md §7sexies.1`.

CE QUI EST PROTÉGÉ, sans GPU ni Ollama (tout est simulé) :
- un chargement observé PROPREMENT consigne l'écart de la carte, sous le détenteur de l'Ollama
  hôte ;
- une observation SALE ne consigne rien, quelle qu'en soit la raison ;
- l'appel s'exécute UNE fois et rend son résultat, mesure ou pas, panne de mesure comprise ;
- la mesure consignée atteint la ligne du catalogue et c'est elle que lit le besoin VRAM ;
- un modèle résident tient UNE ligne au gouverneur, qui pèse au moins son besoin de catalogue ;
- les appels de conversation (`ollama_chat`, l'assistant, la vision du describer) sont mesurés,
  et olmOCR décharge Ollama par les briques communes.
"""
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.services import resource_governor as gov
from wama.common.tests import tests_vram_ledger as ledger_tests
from wama.model_manager.services.model_registry import ModelRegistry

REGISTRY = 'wama.model_manager.services.model_registry.ModelRegistry'
GOV = 'wama.common.services.resource_governor'
MONITOR = 'wama.common.services.system_monitor.SystemMonitor.get_gpu_info'
NAME = 'embeddinggemma-2:latest'
GIB = 1024 ** 3


def _ps(name=NAME, size_gb=0.45, vram_gb=None):
    size = int(size_gb * GIB)
    return {'name': name, 'size': size, 'size_vram': int(vram_gb * GIB) if vram_gb else size}


def _card(*mib):
    """Les relevés successifs de la carte ; None = nvidia-smi sans réponse."""
    return [None if value is None else [{'memory_used': value}] for value in mib]


@override_settings(WAMA_TASKS_DISPATCHED=True)
class OllamaLoadMeasureTest(SimpleTestCase):
    """La mesure elle-même, comme sur le côté autorisé (`runtime_side`) : en test, elle ne
    relève rien (`test_outside_the_authorised_side_nothing_is_read`)."""

    def _measure(self, *, before=(), after=(_ps(),), card=(7000, 9190, 9195), ledger=({}, {}),
                 name=NAME):
        load = mock.Mock(return_value='vecteurs')
        with mock.patch(f'{REGISTRY}.ollama_ps', side_effect=[list(before), list(after)]), \
                mock.patch(f'{GOV}.reservations', side_effect=list(ledger)), \
                mock.patch(MONITOR, side_effect=_card(*card)) as monitor, \
                mock.patch(f'{GOV}.record_measured_vram') as record, \
                mock.patch('time.sleep'):
            result = ModelRegistry.measure_ollama_load(name, load)
        self.assertEqual(result, 'vecteurs')
        load.assert_called_once_with()
        return record, monitor

    def test_a_clean_load_records_what_the_card_took(self):
        record, _ = self._measure()
        owner, gb = record.call_args.args
        self.assertEqual(owner, f'ollama-host#ollama:{NAME}')
        self.assertAlmostEqual(gb, (9195 - 7000) / 1024, places=3)
        self.assertGreater(gb, 0.45 * 4, "plus que ce qu'annonce /api/ps : les projecteurs y sont")

    def test_a_name_without_tag_is_the_latest_tag(self):
        record, _ = self._measure(name='embeddinggemma-2')
        self.assertEqual(record.call_args.args[0], f'ollama-host#ollama:{NAME}')

    def test_an_already_resident_model_is_not_measured(self):
        record, monitor = self._measure(before=(_ps(),), card=())
        record.assert_not_called()
        monitor.assert_not_called()

    def test_a_dirty_observation_records_nothing(self):
        other = _ps('gemma4:e4b', 9.0)
        cases = {
            'absent after the call': dict(after=()),
            # La carte peut dépasser l'annonce (projecteurs) même quand Ollama a versé des couches
            # en RAM : seul `size_vram` le dit.
            'layers spilled to RAM': dict(after=(_ps(size_gb=1.0, vram_gb=0.4),)),
            'another Ollama model loaded': dict(after=(_ps(), other)),
            'another Ollama model unloaded': dict(before=(other,), after=(_ps(),)),
            'the governor ledger moved': dict(ledger=({}, {'w.X:1#@m': 8.0})),
            'the card is still moving': dict(card=(7000, 9190, 9600)),
            'the card is unreadable': dict(card=(7000, None, None)),
            'less than Ollama announces': dict(card=(7000, 7100, 7100)),
        }
        for label, kwargs in cases.items():
            with self.subTest(case=label):
                record, _ = self._measure(**kwargs)
                record.assert_not_called()

    def test_a_failing_measure_never_fails_the_call(self):
        load = mock.Mock(return_value='vecteurs')
        with mock.patch(f'{REGISTRY}.ollama_ps', side_effect=[[], [_ps()]]), \
                mock.patch(f'{GOV}.reservations', side_effect=[{}, {}]), \
                mock.patch(MONITOR, side_effect=[[{'memory_used': 7000}], RuntimeError('smi')]), \
                mock.patch(f'{GOV}.record_measured_vram') as record, \
                mock.patch('time.sleep'):
            self.assertEqual(ModelRegistry.measure_ollama_load(NAME, load), 'vecteurs')
        load.assert_called_once_with()
        record.assert_not_called()

    def test_a_call_that_does_not_keep_the_model_reads_nothing(self):
        """À `keep_alive` '0', Ollama a rendu le modèle avant qu'on relève : ni `/api/ps` ni la
        carte. La règle vit dans la mesure, une fois pour tous les appelants."""
        load = mock.Mock(return_value='vecteurs')
        with mock.patch(f'{REGISTRY}.ollama_ps') as ps, mock.patch(MONITOR) as monitor:
            for kept in ('0', '0s', 0):
                self.assertEqual(ModelRegistry.measure_ollama_load(NAME, load, keep_alive=kept),
                                 'vecteurs')
        self.assertEqual(load.call_count, 3)
        ps.assert_not_called()
        monitor.assert_not_called()

    @override_settings(WAMA_TASKS_DISPATCHED=False)
    def test_outside_the_authorised_side_nothing_is_read(self):
        """En test (courtier `memory://`) la mesure n'irait nulle part : un appel simulé de
        `ollama_chat` interrogeait pourtant l'Ollama réel, Redis et nvidia-smi."""
        load = mock.Mock(return_value='vecteurs')
        with mock.patch(f'{REGISTRY}.ollama_ps') as ps, mock.patch(MONITOR) as monitor:
            self.assertEqual(ModelRegistry.measure_ollama_load(NAME, load), 'vecteurs')
        load.assert_called_once_with()
        ps.assert_not_called()
        monitor.assert_not_called()

    def test_an_error_of_the_call_itself_is_not_swallowed(self):
        with mock.patch(f'{REGISTRY}.ollama_ps', return_value=[]), \
                mock.patch(f'{GOV}.reservations', return_value={}), \
                mock.patch(MONITOR, return_value=[{'memory_used': 7000}]), \
                self.assertRaises(ValueError):
            ModelRegistry.measure_ollama_load(NAME, mock.Mock(side_effect=ValueError('entrée')))


class OllamaMeasureReachesTheCatalogueTest(TestCase):

    def test_the_recorded_measure_is_the_need_of_the_catalogue_row(self):
        """La chaîne entière, détenteur RÉEL (`model_keys_of` non simulé) : la clé de catalogue se
        lit dans le suffixe du détenteur de l'Ollama hôte, la persistance écrit la ligne, et le
        besoin VRAM commun (`vram_needed_gb`) rend la mesure au lieu de l'heuristique."""
        from wama.common.services.resource_governor import ollama_host_owner
        from wama.common.utils.auto_model import vram_needed_gb
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.model_sync import ModelSyncService

        key = f'ollama:{NAME}'
        AIModel.objects.create(model_key=key, name=NAME, model_type='embedding', source='ollama',
                               vram_gb=1.3, is_downloaded=True,
                               is_available=True, extra_info={'disk_gb': 1.3})
        self.assertEqual(vram_needed_gb(key), 1.3, "avant : l'heuristique de la découverte")
        with mock.patch(f'{GOV}.measured_vram',
                        return_value={ollama_host_owner(NAME): (2.14, 1_789_000_000.0)}), \
                mock.patch(f'{GOV}.forget_measured_vram'):
            self.assertEqual(ModelSyncService().persist_measured_vram(), 1)
        row = AIModel.objects.get(model_key=key)
        self.assertEqual(row.extra_info['vram_measured']['max_gb'], 2.14)
        self.assertEqual(row.vram_gb, 1.3, 'vram_gb reste la valeur de la découverte')
        self.assertEqual(vram_needed_gb(key), 2.14)


class OllamaResidencyLineTest(ledger_tests._AvecRegistre):
    """UNE ligne au gouverneur par modèle résident de l'Ollama hôte (2026-10-20).

    Le client des vecteurs annonçait sous `vectors-<espace>#…` pendant que la synchro posait
    `ollama-host#…` pour le même modèle : il comptait deux fois dans la VRAM libre des autres
    (le pilote vu de WSL ne voit rien de l'hôte, ces lignes sont tout ce qu'il en sait), dans
    les résidents et dans les inactifs ; et décharger le modèle laissait la première en fantôme.
    Le registre est un dictionnaire (`tests_vram_ledger`), Ollama est simulé."""

    KEY = f'ollama:{NAME}'
    OWNER = f'ollama-host#ollama:{NAME}'

    def _refresh(self, ps=(), need=None):
        with mock.patch(f'{REGISTRY}.ollama_ps', return_value=list(ps)), \
                mock.patch('wama.common.utils.auto_model.vram_needed_gb', return_value=need):
            return ModelRegistry.refresh_ollama_residency()

    def _announce(self, need=2.14):
        from wama.common.vectors import service_client
        with mock.patch.object(service_client, 'need_gb', return_value=need):
            self.assertTrue(service_client.reserve('media'))

    def test_a_space_and_the_host_refresh_hold_one_line_for_one_model(self):
        self._announce()
        self.assertEqual(self._refresh(ps=[_ps()], need=2.14), 1)
        self.assertEqual(gov.reservations(), {self.OWNER: 2.14})
        self.assertEqual(gov.resident_models(), {self.KEY: 2.14})
        self.assertAlmostEqual(gov.unseen_reserved_gb('driver'), 2.14)
        self.assertEqual([r['model_key'] for r in gov.idle_models(0)], [self.KEY])

    def test_the_host_line_weighs_at_least_the_catalogue_need(self):
        cases = {
            # `/api/ps` oublie les projecteurs : la mesure du catalogue l'emporte.
            'the catalogue above /api/ps': (0.45, 2.14, 2.14),
            'nothing known at the catalogue': (0.45, None, 0.45),
            # Une fenêtre de contexte plus grande que celle de la mesure : Ollama dit vrai.
            '/api/ps above the catalogue': (3.0, 2.14, 3.0),
        }
        for label, (ps_gb, need, expected) in cases.items():
            with self.subTest(case=label):
                self._refresh(ps=[_ps(size_gb=ps_gb)], need=need)
                self.assertAlmostEqual(gov.reservations()[self.OWNER], expected, places=2)

    def test_a_fresh_announcement_survives_a_refresh_that_does_not_see_it_yet(self):
        self._announce()
        self._refresh(ps=[])
        self.assertIn(self.OWNER, gov.reservations(), "le chargement annoncé n'a pas abouti")
        self.t += ModelRegistry.ANNOUNCE_GRACE_S + 1
        self._refresh(ps=[])
        self.assertEqual(gov.reservations(), {}, 'Ollama a rendu le modèle : la ligne part')

    def test_unloading_the_model_frees_its_only_line(self):
        from wama.model_manager.services.memory_manager import MemoryManager
        self._announce()
        self._refresh(ps=[_ps()], need=2.14)
        with mock.patch('requests.post', return_value=mock.Mock(raise_for_status=lambda: None)):
            self.assertTrue(MemoryManager.unload_model(self.KEY))
        self.assertEqual(gov.reservations(), {})


class OllamaCallersAreMeasuredTest(SimpleTestCase):
    """Les appels qui CHARGENT un modèle de l'Ollama hôte et le gardent passent par la mesure
    (`ollama_host.measured_load`) : les modèles de conversation n'en avaient aucune, faute d'un
    point commun — il y en a deux (`llm_utils.ollama_chat`, le tour de l'assistant), plus la
    chauffe du banc, qui tient son client ; la sonde de vision passe par `ollama_chat` depuis le
    2026-10-21, le Describer par elle. Et olmOCR décharge Ollama par les briques."""

    MEASURE = f'{REGISTRY}.measure_ollama_load'

    def _measure(self):
        return mock.patch(self.MEASURE, side_effect=lambda name, load, keep_alive=None: load())

    def test_without_the_model_manager_the_call_runs_bare(self):
        """Hors Django (le service de vectorisation tourne sans ORM), la mesure ne s'importe pas :
        l'appel s'exécute quand même, une fois, et rend son résultat."""
        import sys

        from wama.common.utils import ollama_host
        call = mock.Mock(return_value='vecteurs')
        with mock.patch.dict(sys.modules, {'wama.model_manager.services.model_registry': None}):
            self.assertEqual('vecteurs', ollama_host.measured_load(NAME, call))
        call.assert_called_once_with()

    def test_a_local_chat_goes_through_the_load_measure(self):
        from wama.common.utils import llm_utils
        reply = mock.Mock(status_code=200, json=lambda: {'message': {'content': 'ok'}})
        client = mock.MagicMock()
        client.__enter__.return_value.post.return_value = reply
        messages = [{'role': 'user', 'content': 'x'}]
        with mock.patch('httpx.Client', return_value=client), self._measure() as measured:
            self.assertEqual(llm_utils.ollama_chat(messages, model='qwen3.8:latest'), ('ok', None))
            self.assertEqual(llm_utils.ollama_chat(messages, model='qwen3.8:latest',
                                                   keep_alive='0'), ('ok', None))
        self.assertEqual([(c.args[0], c.kwargs['keep_alive']) for c in measured.call_args_list],
                         [('qwen3.8:latest', None), ('qwen3.8:latest', '0')])

    def test_an_assistant_turn_goes_through_the_load_measure(self):
        from wama.common.services import assistant_engine
        usage = {'input_tokens': 3, 'output_tokens': 1}
        with mock.patch.object(assistant_engine, '_ollama_stream', return_value=('ok', usage)), \
                self._measure() as measured:
            self.assertEqual(assistant_engine._ollama_call([], 'gemma4:e4b'), ('ok', usage))
        self.assertEqual(measured.call_args.args[0], 'gemma4:e4b')

    def test_a_vision_description_goes_through_the_load_measure(self):
        import tempfile

        from wama.describer.backends import image_backend
        client = mock.MagicMock()
        post = client.__enter__.return_value.post
        post.return_value = mock.Mock(status_code=200,
                                      json=lambda: {'message': {'content': 'une voiture'}})
        with tempfile.NamedTemporaryFile(suffix='.png') as image, \
                mock.patch('httpx.Client', return_value=client), self._measure() as measured:
            image.write(b'png')
            image.flush()
            self.assertEqual(image_backend._describe_with_ollama_vision(
                'gemma4:12b', image.name, 'Décris.'), 'une voiture')
        self.assertEqual(measured.call_args.args[0], 'gemma4:12b')
        # Le client COMMUN de vision, à la longueur du Describer — plus son propre appel ; sans
        # réglage, aucune température : celle du modèle (2026-10-21).
        sent = post.call_args.kwargs['json']
        self.assertEqual(({'num_predict': image_backend.VISION_NUM_PREDICT}, 'Décris.'),
                         (sent['options'], sent['messages'][0]['content']))

    def test_the_vision_probe_goes_through_the_load_measure(self):
        import tempfile

        from wama.model_manager.services import vision_probe
        client = mock.MagicMock()
        client.__enter__.return_value.post.return_value = mock.Mock(
            status_code=200, json=lambda: {'message': {'content': 'un chat'}})
        with tempfile.NamedTemporaryFile(suffix='.png') as image, \
                mock.patch('httpx.Client', return_value=client), self._measure() as measured:
            image.write(b'png')
            image.flush()
            self.assertEqual({'ok': True, 'description': 'un chat'}, vision_probe.describe_image_ollama(
                image.name, model='gemma4:12b', keep_alive='120s'))
        self.assertEqual(('gemma4:12b', '120s'),
                         (measured.call_args.args[0], measured.call_args.kwargs['keep_alive']))

    def test_the_generation_bench_measures_its_warm_up_load(self):
        """La CHAUFFE charge le modèle ; les passes chronométrées le trouvent résident."""
        from wama.model_manager.services import bench
        entry = mock.Mock(source='ollama', model_key='ollama:qwen3.8:latest')
        entry.name = 'qwen3.8:latest'
        reply = {'eval_count': 10, 'eval_duration': 1e9, 'load_duration': 3e9}
        with mock.patch.object(bench, '_ollama_generate', return_value=reply) as generate, \
                mock.patch('wama.common.services.resource_governor.gpu_safe_mode',
                           return_value=False), \
                mock.patch('wama.model_manager.services.eta_estimator.record_run'), \
                self._measure() as measured:
            bench._bench_generation(entry, 'Dis bonjour.', runs=2)
        self.assertEqual(['qwen3.8:latest'], [c.args[0] for c in measured.call_args_list])
        self.assertEqual(3, generate.call_count, 'la chauffe et deux passes')

    def test_olmocr_unloads_ollama_through_the_common_gestures(self):
        from wama.common.backends.olmocr_backend import OlmOCRBackend
        resident = [{'name': 'gemma4:e4b'}, {'name': NAME}]
        with mock.patch(f'{REGISTRY}.ollama_ps', return_value=resident), \
                mock.patch('wama.model_manager.services.memory_manager.MemoryManager.unload_model',
                           return_value=True) as unload, \
                mock.patch('httpx.get', side_effect=AssertionError('second lecteur de /api/ps')):
            self.assertEqual(OlmOCRBackend._unload_ollama_models(), 2)
        self.assertEqual([c.args[0] for c in unload.call_args_list],
                         ['ollama:gemma4:e4b', f'ollama:{NAME}'])

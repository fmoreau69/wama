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
- la mesure consignée atteint la ligne du catalogue et c'est elle que lit le besoin VRAM.
"""
from unittest import mock

from django.test import SimpleTestCase, TestCase

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


class OllamaLoadMeasureTest(SimpleTestCase):

    def _measure(self, *, before=(), after=(_ps(),), card=(7000, 9190, 9195), ledger=({}, {}),
                 name=NAME):
        load = mock.Mock(return_value='vecteurs')
        with mock.patch(f'{REGISTRY}._ollama_ps', side_effect=[list(before), list(after)]), \
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
        with mock.patch(f'{REGISTRY}._ollama_ps', side_effect=[[], [_ps()]]), \
                mock.patch(f'{GOV}.reservations', side_effect=[{}, {}]), \
                mock.patch(MONITOR, side_effect=[[{'memory_used': 7000}], RuntimeError('smi')]), \
                mock.patch(f'{GOV}.record_measured_vram') as record, \
                mock.patch('time.sleep'):
            self.assertEqual(ModelRegistry.measure_ollama_load(NAME, load), 'vecteurs')
        load.assert_called_once_with()
        record.assert_not_called()

    def test_an_error_of_the_call_itself_is_not_swallowed(self):
        with mock.patch(f'{REGISTRY}._ollama_ps', return_value=[]), \
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

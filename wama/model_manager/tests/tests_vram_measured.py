"""La VRAM MESURÉE au chargement est rendue au CATALOGUE — à part de `vram_gb` (2026-09-14).

POURQUOI. `_wrap_load` mesure l'empreinte réelle à chaque chargement depuis le 29/07, mais la
mesure ne servait qu'au registre à TTL du gouverneur, puis était jetée : `vram_gb` restait
déclaré ou estimé (« Estimated VRAM in GB »), et `vram_estimated` ne se levait jamais. Le trou a
été relevé deux fois (mémoire du 03/09, instance « BANC LLM » du 14/09), et Fabien a retenu le
champ MESURÉ SÉPARÉ.

CE QUI EST PROTÉGÉ :
- la mesure entre dans `extra_info['vram_measured']` (dernière, maximum, nombre de relevés, date) ;
- `vram_gb` N'EST PAS TOUCHÉ — la découverte le réécrit à chaque synchro et le tirage le lit ;
  y écrire la mesure aurait été effacé au passage suivant (`ModelSyncService._sync_model`) ;
- la clé SURVIT à une synchro (clé collante) ;
- seule une mesure RENDUE est oubliée : une mesure non résolue reste au gouverneur.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from wama.model_manager.models import AIModel
from wama.model_manager.services.model_sync import ModelSyncService

GOV = 'wama.common.services.resource_governor'
CLE = 'imager:qwen-image-2'
OWNER = 'wama.common.backends.qwen_image_backend.QwenImageBackend:1#@qwen-image-2'


def _ligne(**extra):
    return AIModel.objects.create(
        model_key=CLE, name=CLE, model_type='image', source='imager',
        vram_gb=extra.pop('vram_gb', 16.0), is_downloaded=True, is_available=True,
        extra_info=extra.pop('extra_info', {}), **extra)


class PersistanceDeLaMesureTest(TestCase):

    def _persister(self, mesures, cles):
        with mock.patch(f'{GOV}.measured_vram', return_value=mesures), \
                mock.patch(f'{GOV}.model_keys_of', side_effect=lambda o: cles.get(o, [])), \
                mock.patch(f'{GOV}.forget_measured_vram') as oubli:
            n = ModelSyncService().persist_measured_vram()
        return n, oubli

    def test_la_mesure_entre_au_catalogue_SANS_toucher_vram_gb(self):
        """Le cas du 29/07 rejoué : 16 Go déclarés, 38,1 Go alloués au chargement."""
        _ligne(vram_gb=16.0)
        n, _ = self._persister({OWNER: (38.1, 1_789_000_000.0)}, {OWNER: [CLE]})
        m = AIModel.objects.get(model_key=CLE)
        self.assertEqual(n, 1)
        self.assertEqual(m.vram_gb, 16.0, "vram_gb reste la valeur déclarée que lit le tirage")
        mesure = m.extra_info['vram_measured']
        self.assertEqual((mesure['last_gb'], mesure['max_gb'], mesure['n']), (38.1, 38.1, 1))
        self.assertTrue(mesure['at'])

    def test_les_releves_s_accumulent_et_le_maximum_se_garde(self):
        """Un chargement avec offload mesure MOINS : le dernier relevé ne doit pas effacer le pic."""
        _ligne(extra_info={'vram_measured': {'last_gb': 38.1, 'max_gb': 38.1, 'n': 1}})
        self._persister({OWNER: (14.0, 1_789_000_000.0)}, {OWNER: [CLE]})
        v = AIModel.objects.get(model_key=CLE).extra_info['vram_measured']
        self.assertEqual((v['last_gb'], v['max_gb'], v['n']), (14.0, 38.1, 2))

    def test_seules_les_mesures_RENDUES_sont_oubliees(self):
        """Une mesure dont la clé ne se résout pas encore reste au gouverneur pour un autre essai."""
        _ligne()
        inconnu = 'x.Y:1#@inconnu'
        _, oubli = self._persister({OWNER: (38.1, 111.0), inconnu: (2.0, 222.0)}, {OWNER: [CLE]})
        oubli.assert_called_once_with({OWNER: 111.0})

    def test_une_SYNCHRO_ne_l_efface_pas(self):
        """`_sync_model` réécrit `extra_info` depuis la découverte, qui ne sait rien de la mesure."""
        _ligne(extra_info={'vram_measured': {'last_gb': 38.1, 'max_gb': 38.1, 'n': 1}})
        decouverte = SimpleNamespace(
            name='Qwen-Image', model_type=SimpleNamespace(value='image'),
            source=SimpleNamespace(value='imager'), description='', description_short='',
            vram_gb=16.0, ram_gb=0, is_downloaded=True, is_loaded=False, format='',
            preferred_format='', can_convert_to=[], backend_ref='', extra_info={},
            hf_id='', quality_index=None, capabilities={}, composition={})
        ModelSyncService()._sync_model(CLE, decouverte)
        m = AIModel.objects.get(model_key=CLE)
        self.assertEqual(m.extra_info['vram_measured']['max_gb'], 38.1)
        self.assertEqual(m.vram_gb, 16.0)

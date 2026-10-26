"""
L'ETA d'un modèle DISTANT se range sous sa SOURCE, et un modèle CHAUD ne paie pas de chargement
(`eta_estimator.compute_place` / `is_warm`, décision de Fabien le 2026-10-26).

Mesuré le jour même : les tours d'assistant chez Albert et ILaaS s'apprenaient sous la carte
locale, et `transcriber:albert` existait sous DEUX empreintes (`cpu` et la RTX) — deux moyennes
pour une seule vitesse, celle du fournisseur. Et le transcriber déclarait son modèle « non chargé »
à chaque card alors qu'il le garde en mémoire depuis le 2026-09-25 : l'estimation lui ajoutait un
chargement qui n'avait pas lieu.

Aucun de ces défauts ne se voit à l'exécution : l'ETA reste PLAUSIBLE, juste fausse.
"""
import importlib
from types import SimpleNamespace
from unittest import mock

from django.apps import apps as django_apps
from django.test import TestCase

from wama.model_manager.models import ModelRuntimeStat
from wama.model_manager.services import eta_estimator
from wama.model_manager.services.eta_estimator import (
    _DEFAULT_LOAD, _DEFAULT_PER_UNIT, comparable_speeds, compute_place, estimate, is_warm,
    learned_speed, record_run,
)

LOCAL = 'fake-gpu|0GB'
RESIDENT = 'wama.common.services.resource_governor.resident_models'


def _on_this_machine():
    return mock.patch.object(eta_estimator, 'hardware_fingerprint', return_value=LOCAL)


class ComputePlaceTest(TestCase):

    def test_a_remote_model_is_placed_under_its_source_in_each_key_form(self):
        with _on_this_machine():
            self.assertEqual(compute_place('albert:whisper-large-v3'), 'albert')          # catalogue
            self.assertEqual(compute_place('assistant-turn:ilaas:qwen-3.8-27b'), 'ilaas')  # usage
            self.assertEqual(compute_place('transcriber:albert'), 'albert')               # moteur

    def test_counter_proof_a_local_key_stays_on_this_hardware(self):
        with _on_this_machine():
            self.assertEqual(compute_place('transcriber:whisper-large-v3'), LOCAL)
            # Un SEGMENT nomme la source, jamais une sous-chaîne.
            self.assertEqual(compute_place('transcriber:albertine'), LOCAL)

    def test_a_remote_run_is_learned_and_read_back_under_its_source(self):
        with _on_this_machine():
            record_run('eta-guard:albert:some-model', size=100, unit='token', process_seconds=5)
            self.assertTrue(ModelRuntimeStat.objects.filter(
                model_key='eta-guard:albert:some-model', hardware_fingerprint='albert').exists())
            self.assertFalse(ModelRuntimeStat.objects.filter(
                model_key='eta-guard:albert:some-model', hardware_fingerprint=LOCAL).exists())
            self.assertEqual(learned_speed('eta-guard:albert:some-model')[2], 1)

    def test_comparable_speeds_reads_each_key_at_its_own_place(self):
        with _on_this_machine():
            record_run('albert:eta-guard-remote', size=10, unit='token', process_seconds=2)
            record_run('eta-guard:local-model', size=10, unit='token', process_seconds=4)
            speeds = comparable_speeds(['albert:eta-guard-remote', 'eta-guard:local-model'])
        self.assertEqual(speeds, {'albert:eta-guard-remote': 0.2, 'eta-guard:local-model': 0.4})


class RemoteModelsNeverLearnALoadTest(TestCase):

    def test_a_load_measured_on_a_remote_model_is_not_learned(self):
        with _on_this_machine():
            record_run('albert:eta-guard-remote', size=10, unit='token', process_seconds=2,
                       load_seconds=7)
        self.assertIsNone(ModelRuntimeStat.objects.get(model_key='albert:eta-guard-remote')
                          .load_ema_seconds)

    def test_counter_proof_a_local_model_learns_its_load(self):
        with _on_this_machine():
            record_run('eta-guard:local-model', size=10, unit='token', process_seconds=2,
                       load_seconds=7)
        self.assertEqual(ModelRuntimeStat.objects.get(model_key='eta-guard:local-model')
                         .load_ema_seconds, 7)


class WarmModelsPayNoLoadTest(TestCase):
    """L'a priori de domaine seul (aucune ligne apprise) : la différence est le chargement."""

    SIZE = 10
    COMPUTE = _DEFAULT_PER_UNIT['audio_sec'] * SIZE
    LOAD = _DEFAULT_LOAD['audio_sec']

    def _estimate(self, key, resident=None):
        with _on_this_machine(), mock.patch(RESIDENT, return_value=resident or {}):
            return estimate(key, size=self.SIZE, unit='audio_sec')

    def test_a_remote_model_pays_no_load(self):
        self.assertAlmostEqual(self._estimate('albert:eta-guard-asr'), self.COMPUTE)
        self.assertAlmostEqual(self._estimate('transcriber:albert'), self.COMPUTE)

    def test_a_resident_local_model_pays_no_load_under_its_key_or_a_prefixed_one(self):
        resident = {'transcriber:eta-guard-asr': 3.0}
        self.assertAlmostEqual(self._estimate('transcriber:eta-guard-asr', resident), self.COMPUTE)
        self.assertAlmostEqual(self._estimate('assistant-turn:transcriber:eta-guard-asr', resident),
                               self.COMPUTE)

    def test_counter_proof_a_cold_local_model_pays_its_load(self):
        self.assertAlmostEqual(self._estimate('transcriber:eta-guard-asr'), self.COMPUTE + self.LOAD)
        self.assertAlmostEqual(self._estimate('transcriber:eta-guard-asr', {'other:model': 1.0}),
                               self.COMPUTE + self.LOAD)

    def test_the_caller_that_knows_the_model_loaded_still_decides(self):
        with _on_this_machine(), mock.patch(RESIDENT, return_value={}):
            self.assertAlmostEqual(estimate('transcriber:eta-guard-asr', size=self.SIZE,
                                            unit='audio_sec', model_loaded=True), self.COMPUTE)

    def test_is_warm_on_an_empty_key_is_false(self):
        with mock.patch(RESIDENT, return_value={'': 1.0}):
            self.assertFalse(is_warm(''))


class TranscribeEtaReadsWarmthTest(TestCase):
    """`transcribe_eta` (le process `transcribe`) disait « non chargé » quel que soit l'état."""

    TRIPLET = ('transcriber:whisper', 60.0, 'audio_sec')

    def _warmth(self, card, resident):
        from wama.transcriber import workers
        with mock.patch.object(workers, 'transcriber_eta_key_size', return_value=self.TRIPLET), \
                mock.patch(RESIDENT, return_value=resident):
            return workers.transcribe_eta(card)[3]

    def test_the_model_that_ran_resident_is_warm(self):
        card = SimpleNamespace(model_key='transcriber:eta-guard-asr', backend='auto')
        self.assertTrue(self._warmth(card, {'transcriber:eta-guard-asr': 3.0}))

    def test_the_requested_model_resident_is_warm_before_any_run(self):
        card = SimpleNamespace(model_key='', backend='transcriber:eta-guard-asr')
        self.assertTrue(self._warmth(card, {'transcriber:eta-guard-asr': 3.0}))

    def test_counter_proof_cold_or_auto_is_not_warm(self):
        self.assertFalse(self._warmth(
            SimpleNamespace(model_key='transcriber:eta-guard-asr', backend='auto'), {}))
        # « auto » n'a pas encore de modèle : rien à dire de sa résidence.
        self.assertFalse(self._warmth(SimpleNamespace(model_key='', backend='auto'),
                                      {'auto': 1.0}))


class MigrationPutsRemoteRowsUnderTheirSourceTest(TestCase):
    """`model_manager/0028` : la transformation des lignes déjà apprises."""

    def _migrate(self):
        module = importlib.import_module(
            'wama.model_manager.migrations.0028_eta_remote_models_under_their_source')
        module.remote_rows_under_their_source(django_apps, None)

    def test_a_remote_key_split_over_two_fingerprints_keeps_its_best_row_under_its_source(self):
        ModelRuntimeStat.objects.create(model_key='eta-guard:albert', hardware_fingerprint='cpu',
                                        unit='audio_sec', samples=1, per_unit_ema_seconds=9.0)
        ModelRuntimeStat.objects.create(model_key='eta-guard:albert', hardware_fingerprint=LOCAL,
                                        unit='audio_sec', samples=22, per_unit_ema_seconds=0.1,
                                        load_ema_seconds=4.0)
        self._migrate()
        row = ModelRuntimeStat.objects.get(model_key='eta-guard:albert')
        self.assertEqual((row.hardware_fingerprint, row.samples, row.load_ema_seconds),
                         ('albert', 22, None))

    def test_counter_proof_a_local_row_is_untouched(self):
        ModelRuntimeStat.objects.create(model_key='eta-guard:local-model', hardware_fingerprint=LOCAL,
                                        unit='token', samples=3, per_unit_ema_seconds=0.1,
                                        load_ema_seconds=4.0)
        self._migrate()
        row = ModelRuntimeStat.objects.get(model_key='eta-guard:local-model')
        self.assertEqual((row.hardware_fingerprint, row.load_ema_seconds), (LOCAL, 4.0))

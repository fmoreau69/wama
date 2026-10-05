"""La résolution écarte un backend dont le CONTRAT ne correspond pas à la tâche (2026-09-29).

LE DÉFAUT MESURÉ. Le manifeste de Supra2-IMG-ONNX (texte→image, moteur `onnxruntime`) appliqué
avant son backend, le modèle se retrouvait routé vers `AIUpscaler` : seul backend `onnxruntime`,
sans liste de modèles, il gagnait par la règle « un seul backend déclare ce moteur → c'est lui ».
Un moteur de niveau bibliothèque ne suffit pas à choisir.

CE QUE CES GARDES TIENNENT :
  1. avec la tâche, un backend hors contrat LIANT est écarté (contre-épreuve : sans elle, choisi) ;
  2. un contrat NON liant (`detect`) ne refuse rien — Table Transformer dérive du contrat commun ;
  3. le cas réel : Supra2-IMG-ONNX va à son backend, écrit par le rôle et validé par Fabien.
  4. (2026-09-30) sous un contrat LIANT, le candidat unique qui DÉCLARE sa liste ne sert que
     ses modèles — FrWhisper n'est plus confié à Qwen3-ASR — et le select le GRISE avec la
     raison au lieu de le proposer ; hors contrat liant, rien ne change.
Aucun import de backend : la résolution est statique.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from wama.common.backends.manager import backend_missing, invalidate_engine_cache
from wama.common.services.backend_inventory import (
    TASK_CONTRACTS, resolvable_entries, resolve_entry,
)


class ContractRoutingTest(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.entries = resolvable_entries()

    def test_an_upscaler_does_not_run_a_text_to_image_model(self):
        upscaler = [e for e in self.entries
                    if e.engine == 'onnxruntime' and e.module.endswith('ai_upscaler')]
        self.assertEqual(1, len(upscaler))
        self.assertIs(upscaler[0], resolve_entry('onnxruntime', 'Org/Img', upscaler),
                      "contre-épreuve : sans la tâche, le seul backend du moteur est choisi")
        self.assertIsNone(resolve_entry('onnxruntime', 'Org/Img', upscaler, task='text-to-image'))

    def test_a_non_binding_contract_rejects_nothing(self):
        self.assertFalse(TASK_CONTRACTS['detect'][2])
        chosen = resolve_entry('transformers', 'microsoft/table-transformer-detection',
                               self.entries, task='detect')
        self.assertIsNotNone(chosen)
        self.assertIn('table_transformer', chosen.module)

    def test_supra2_goes_to_the_backend_written_for_it(self):
        chosen = resolve_entry('onnxruntime', 'Bartholomheow/Supra2-IMG-ONNX', self.entries,
                               task='text-to-image')
        self.assertIsNotNone(chosen)
        self.assertTrue(chosen.module.endswith('supra2_img_onnx_backend'), chosen.module)


class DeclaredModelListTest(SimpleTestCase):
    """`QwenASRBackend` was the only transcription backend of the `transformers` engine: rule 1
    handed it FrWhisper and LinTO, two models installed « weights only » that it cannot load.
    Since 2026-10-01 FrWhisper has its own backend (`tests_validated_asr_backends`) — the unlisted
    model here is therefore a made-up one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.entries = resolvable_entries()

    def _chosen(self, model_id, task='transcription'):
        chosen = resolve_entry('transformers', model_id, self.entries, task=task)
        return chosen.name if chosen else None

    def test_a_listed_model_still_reaches_the_single_candidate(self):
        self.assertEqual('QwenASRBackend', self._chosen('qwen3-asr-1.7b'))

    def test_an_unlisted_model_is_not_handed_to_the_single_candidate(self):
        self.assertIsNone(self._chosen('org/unlisted-asr'))

    def test_the_select_greys_it_with_the_reason_and_keeps_the_listed_one(self):
        invalidate_engine_cache()

        def row(key, task='transcription'):
            return SimpleNamespace(model_key=key, capabilities={'task': task},
                                   composition={'runtime': {'engine': 'transformers'}},
                                   source='huggingface', is_proposed=False, execution='local')
        self.assertIn('aucun backend de transcription',
                      backend_missing(row('huggingface:org/unlisted-asr')) or '')
        self.assertIsNone(backend_missing(row('transcriber:qwen3-asr-1.7b')))
        # Hors contrat liant, le verdict reste permissif (rien ne change pour `detect`).
        self.assertIsNone(backend_missing(row('huggingface:org/unlisted', task='detect')))


class MusicContractIsBindingTest(SimpleTestCase):
    """2026-10-05 — `text-to-music` was NOT binding: ACE-Step (engine `transformers`, no music
    backend) passed for executable, offered without greying and DRAWABLE by « auto », then failed
    at launch. Binding, it is said unlaunchable; the five served music models keep their backend."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.entries = resolvable_entries()

    def _row(self, key, engine):
        return SimpleNamespace(model_key=key, capabilities={'task': 'text-to-music'},
                               composition={'runtime': {'engine': engine}},
                               source=key.split(':', 1)[0], is_proposed=False, execution='local')

    def test_a_music_model_no_backend_serves_is_said_unlaunchable(self):
        invalidate_engine_cache()
        self.assertTrue(TASK_CONTRACTS['text-to-music'][2])
        self.assertIn('aucun backend de text-to-music',
                      backend_missing(self._row('huggingface:ACE-Step/Ace-Step1.5', 'transformers'))
                      or '')

    def test_the_served_music_models_keep_their_backend(self):
        for engine, model_id, module in (('audiocraft', 'musicgen-small', 'audiocraft_backend'),
                                         ('yue', 'm-a-p/YuE2-3B', 'yue2_3b_backend')):
            with self.subTest(engine=engine):
                chosen = resolve_entry(engine, model_id, self.entries, task='text-to-music')
                self.assertIsNotNone(chosen)
                self.assertTrue(chosen.module.endswith(module), chosen.module)

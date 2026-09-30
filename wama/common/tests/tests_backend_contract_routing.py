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
    """`QwenASRBackend` is the only transcription backend of the `transformers` engine: rule 1
    handed it FrWhisper and LinTO, two models installed « weights only » that it cannot load."""

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
        self.assertIsNone(self._chosen('aihpi/FrWhisper'))

    def test_the_select_greys_it_with_the_reason_and_keeps_the_listed_one(self):
        invalidate_engine_cache()

        def row(key, task='transcription'):
            return SimpleNamespace(model_key=key, capabilities={'task': task},
                                   composition={'runtime': {'engine': 'transformers'}},
                                   source='huggingface', is_proposed=False, execution='local')
        self.assertIn('aucun backend de transcription',
                      backend_missing(row('huggingface:aihpi/FrWhisper')) or '')
        self.assertIsNone(backend_missing(row('transcriber:qwen3-asr-1.7b')))
        # Hors contrat liant, le verdict reste permissif (rien ne change pour `detect`).
        self.assertIsNone(backend_missing(row('huggingface:org/unlisted', task='detect')))

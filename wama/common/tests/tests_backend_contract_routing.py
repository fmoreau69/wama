"""La résolution écarte un backend dont le CONTRAT ne correspond pas à la tâche (2026-09-29).

LE DÉFAUT MESURÉ. Le manifeste de Supra2-IMG-ONNX (texte→image, moteur `onnxruntime`) appliqué
avant son backend, le modèle se retrouvait routé vers `AIUpscaler` : seul backend `onnxruntime`,
sans liste de modèles, il gagnait par la règle « un seul backend déclare ce moteur → c'est lui ».
Un moteur de niveau bibliothèque ne suffit pas à choisir.

CE QUE CES GARDES TIENNENT :
  1. avec la tâche, un backend hors contrat LIANT est écarté (contre-épreuve : sans elle, choisi) ;
  2. un contrat NON liant (`detect`) ne refuse rien — Table Transformer dérive du contrat commun ;
  3. le cas réel : Supra2-IMG-ONNX va à son backend, écrit par le rôle et validé par Fabien.
Aucun import de backend : la résolution est statique.
"""
from django.test import SimpleTestCase

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

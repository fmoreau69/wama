"""Le format RECOMMANDÉ d'un modèle se DÉRIVE de son moteur déclaré — jamais de son type.

POURQUOI (2026-11-08, Fabien : « schéma-driven, universel, parfaitement aligné sur le
fonctionnement de WAMA »). La politique de formats était PAR CATÉGORIE, atteinte par le type du
modèle (sept des onze `ModelType` recopiés, les quatre autres retombant en silence sur
« diffusion ») : 60 des 145 modèles installés affichaient « Recommended: onnx » alors que leur
moteur lit leur format actuel — 48 YOLO que lit ultralytics, des NeMo, Kokoro, Higgs… Le format
qu'un modèle devrait avoir est celui que lit le moteur qui l'exécute (`format_policy`,
`REMOVAL_LEDGER R229`).
"""
from django.test import TestCase

from wama.model_manager.models import AIModel


def _row(key, model_type, fmt, engine=None):
    composition = {'runtime': {'engine': engine}} if engine else {}
    return AIModel.objects.create(model_key=key, name=key, model_type=model_type, source='huggingface',
                                  format=fmt, is_downloaded=True, composition=composition)


class PreferredFormatFollowsTheEngineTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.yolo = _row('anonymizer:yolo:x.pt', 'vision', 'pt', 'ultralytics')
        cls.graph = _row('huggingface:org/graph', 'vision', 'pt', 'onnxruntime')
        cls.nemo = _row('huggingface:org/asr', 'speech', 'nemo', 'nemo')
        cls.music = _row('huggingface:org/song', 'music', 'safetensors')

    def test_the_recommendation_is_the_format_the_declared_engine_reads(self):
        self.assertEqual('onnx', self.graph.preferred_format)
        self.assertEqual('nemo', self.nemo.preferred_format)

    def test_an_engine_that_reads_several_formats_or_no_engine_recommends_nothing(self):
        """Ultralytics lit le `.pt` comme l'`.onnx` ; une ligne sans moteur ne dit rien — et ne
        retombe plus sur la politique « diffusion »."""
        self.assertEqual('', self.yolo.preferred_format)
        self.assertEqual('', self.music.preferred_format)

    def test_the_type_does_not_decide(self):
        """Deux modèles du MÊME type, deux moteurs : deux recommandations."""
        self.assertEqual(self.yolo.model_type, self.graph.model_type)
        self.assertNotEqual(self.yolo.preferred_format, self.graph.preferred_format)

    def test_the_conversion_suggestions_name_only_what_the_engine_cannot_read(self):
        from wama.model_manager.services.format_converter import FormatConverter
        suggestions = FormatConverter().scan_and_suggest()
        self.assertEqual([('huggingface:org/graph', 'pt', 'onnx', 'onnxruntime')],
                         [(s.model_id, s.current_format, s.suggested_format, s.engine)
                          for s in suggestions])
        stats = FormatConverter().get_format_stats()
        self.assertEqual({'compliant': 1, 'non_compliant': 1, 'percentage': 50.0}, stats['compliance'])

    def test_the_format_a_declared_anatomy_carries_wins_over_the_dominant_file_on_disk(self):
        """LinTO range une conversion `transformers` près de l'archive `.nemo` qu'il déclare : la
        synchro l'écrivait `safetensors` (format dominant du disque), et le badge lui proposait de
        convertir… vers ce qu'il a déjà. Une anatomie mixte (DiT + latent `.pt`) ne tranche pas."""
        from wama.common.utils.format_policy import declared_weight_format
        from wama.model_manager.services.model_registry import ModelInfo, ModelSource, ModelType
        from wama.model_manager.services.model_sync import ModelSyncService
        self.assertEqual('nemo', declared_weight_format(
            {'components': [{'role': 'model', 'pattern': 'linto.nemo'}]}))
        self.assertEqual('bin', declared_weight_format(
            {'components': [{'role': 'model', 'format': 'bin', 'pattern': 'state_dict.*'}]}))
        self.assertEqual('', declared_weight_format(
            {'components': [{'role': 'dit', 'pattern': 'a/model.safetensors'},
                            {'role': 'latent', 'pattern': 'a/silence.pt'}]}))
        key = 'huggingface:org/linto'
        composition = {'runtime': {'engine': 'nemo'},
                       'components': [{'role': 'model', 'format': 'nemo', 'pattern': 'linto.nemo'}]}
        ModelSyncService()._sync_model(key, ModelInfo(
            id=key, name='linto', model_type=ModelType.SPEECH, source=ModelSource.HUGGINGFACE,
            is_downloaded=True, format='safetensors', composition=composition))
        row = AIModel.objects.get(model_key=key)
        self.assertEqual(('nemo', 'nemo'), (row.format, row.preferred_format))

    def test_the_manifest_does_not_declare_a_derived_format(self):
        from wama.common.manifests.builtin.model import extract_model
        formats = extract_model(self.graph.model_key)['body']['formats']
        self.assertEqual({'format': 'pt', 'can_convert_to': []}, formats)

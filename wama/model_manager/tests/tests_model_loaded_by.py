"""
Un modèle installé dit QUI l'exécute — backend, ou module qui le charge lui-même (2026-10-31).

L'INVENTAIRE QUI A DÉCIDÉ CE MÉCANISME (142 modèles installés et locaux, catalogue réel) : 10
lignes « condamnées » par `backend_missing`, dont SIX servaient pourtant :
  • cinq sont chargées HORS de tout backend, et chaque découverte le disait en commentaire seulement
    (le banc, le service vocal, le Face Analyzer, le Cam Analyzer, le navigateur) →
    `composition.runtime.loaded_by`, le module qui ouvre le fichier ;
  • une a bien un backend (`PyannoteDiarizerBackend`), qui la nomme par sa clé de catalogue dans
    son `SUPPORTED_MODELS` — mais la ligne, arrivée par la prospection, n'avait pas de moteur →
    la découverte lit cette moitié du lien (`_overlay_engines_named_by_backends`).
Le champ `not_runnable` des outils de l'assistant reprend ce verdict : sans ces déclarations, il
aurait dit pyannote ou Smart Turn « inutilisables ».
"""
import importlib.util

from django.test import TestCase

from wama.model_manager.services.model_registry import ModelInfo, ModelRegistry, ModelSource, ModelType

PYANNOTE = 'huggingface:pyannote/speaker-diarization-community-1'


def _registry():
    """Un registre nu (le vrai est un singleton qui balaierait tout le disque)."""
    r = object.__new__(ModelRegistry)
    r._models, r.discovery_errors = {}, []
    return r


def _line(key, composition=None):
    return ModelInfo(id=key, name=key, model_type=ModelType.VISION, source=ModelSource.HUGGINGFACE,
                     composition=composition or {})


class LoadedByTest(TestCase):

    DISCOVERIES = ('_discover_face_analyzer_models', '_discover_road_models',
                   '_discover_quality_metric_models', '_discover_hand_gesture_models',
                   '_discover_turn_end_models', '_discover_language_identification_models',
                   '_discover_page_orientation_models')

    #: La librairie que le moteur déclaré de chaque ligne fait requérir à son manifeste
    #: (2026-11-06). Une ligne SANS moteur y figure avec sa raison : rien d'autre ne l'excuse.
    EXPECTED_LIBRARIES = {
        'face_analyzer:mediapipe-face-landmarker': ['mediapipe'],
        'github:CAIC-AD/YOLOPv2:V0.0.1': ['opencv-python', 'torch', 'torchvision'],
        'pytorch_download:lpips-alexnet': ['lpips'],
        'huggingface:pipecat-ai/smart-turn-v3': ['onnxruntime-gpu'],
        'huggingface:Systran/faster-whisper-tiny': ['faster-whisper'],
        'github:mindee/doctr:v0.8.1': ['python-doctr'],
    }
    #: Exécuté par la version NAVIGATEUR de MediaPipe : aucune librairie Python à requérir.
    WITHOUT_ENGINE = {'mediapipe_models:gesture-recognizer'}

    def _declared(self):
        r = _registry()
        for name in self.DISCOVERIES:
            getattr(r, name)()
        self.assertEqual([], r.discovery_errors)
        return {key: (info.composition or {}).get('runtime', {})
                for key, info in r._models.items()
                if (info.composition or {}).get('runtime', {}).get('loaded_by')}

    def test_each_brick_model_names_a_module_that_exists(self):
        declared = self._declared()
        self.assertEqual(7, len(declared), declared)
        for key, runtime in declared.items():
            with self.subTest(model=key):
                self.assertIsNotNone(importlib.util.find_spec(runtime['loaded_by']),
                                     f"{runtime['loaded_by']} introuvable")

    def test_each_loader_names_the_engine_its_manifest_requires(self):
        """Le modèle porte son moteur, et un moteur est une librairie (registre `backends`) :
        sans lui, le manifeste de Whisper tiny disait `requires: []` alors que la sonde des
        langues tourne sur faster-whisper — la désinstaller n'aurait rien refusé."""
        from wama.common.manifests.builtin.model import _requires_librairies
        declared = self._declared()
        self.assertEqual(set(self.EXPECTED_LIBRARIES) | self.WITHOUT_ENGINE, set(declared))
        for key, runtime in declared.items():
            with self.subTest(model=key):
                required = [r['key'] for r in
                            _requires_librairies({'composition': {'runtime': runtime}}, key)]
                if key in self.WITHOUT_ENGINE:
                    self.assertNotIn('engine', runtime)
                    self.assertEqual([], required)
                else:
                    self.assertEqual(self.EXPECTED_LIBRARIES[key], required)

    def test_a_loader_is_never_handed_to_the_backend_of_its_engine(self):
        """Whisper tiny déclare `faster-whisper`, le moteur que pilote le backend Whisper : son
        exécutant reste la brique (`loaded_by`), jamais le backend — la même règle que
        `backend_missing`."""
        from wama.common.backends.manager import backend_for_model
        from wama.common.backends.whisper_backend import WhisperBackend
        runtime = {'engine': 'faster-whisper', 'loaded_by': 'wama.common.utils.spoken_language'}
        self.assertIsNone(backend_for_model(_line('huggingface:Systran/faster-whisper-tiny',
                                                  {'runtime': runtime})))
        # Contre-épreuve : la même ligne sans `loaded_by` va au backend du moteur.
        self.assertIs(WhisperBackend, backend_for_model(_line(
            'huggingface:Systran/faster-whisper-large-v3', {'runtime': {'engine': 'faster-whisper'}})))

    def test_a_model_loaded_by_a_module_is_not_condemned(self):
        from wama.common.backends.manager import backend_missing
        line = _line('pytorch_download:lpips-alexnet',
                     {'runtime': {'loaded_by': 'wama.model_manager.services.bench'}})
        self.assertIsNone(backend_missing(line))
        # Contre-épreuve : la même ligne sans sa déclaration n'a aucune route.
        self.assertIsNotNone(backend_missing(_line('pytorch_download:lpips-alexnet')))

    def test_the_disk_does_not_give_an_engine_to_a_declared_loader(self):
        """Un snapshot diffusers sur le disque : sans `loaded_by`, la passe en dériverait le moteur
        (contre-épreuve sur la ligne voisine, identique mais sans déclaration)."""
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'model_index.json').write_text(json.dumps({'_class_name': 'X'}))
            r = _registry()
            for key, runtime in (('huggingface:o/declared', {'loaded_by': 'wama.common.tts.service'}),
                                 ('huggingface:o/bare', {})):
                line = _line(key, {'runtime': runtime} if runtime else {})
                line.extra_info = {'path': folder}
                r._models[key] = line
            r._overlay_engines_derived_from_disk()
        self.assertNotIn('engine', r._models['huggingface:o/declared'].composition['runtime'])
        self.assertEqual('diffusers',
                         r._models['huggingface:o/bare'].composition['runtime']['engine'])

    def test_the_manifest_accepts_a_loader_or_an_engine_but_not_an_empty_runtime(self):
        from wama.common.manifests.builtin.model import _validate_composition
        self.assertEqual([], _validate_composition({'runtime': {'loaded_by': 'wama.common.tts.service'}}))
        self.assertEqual([], _validate_composition({'runtime': {'engine': 'audio-cpp',
                                                                'family': 'minimax_music3'}}))
        self.assertTrue(_validate_composition({'runtime': {}}))


class EngineNamedByItsBackendTest(TestCase):

    def test_the_inventory_reads_the_catalogue_keys_listed_by_a_backend(self):
        from wama.common.services.backend_inventory import resolvable_entries
        pyannote = [e for e in resolvable_entries() if e.name == 'PyannoteDiarizerBackend']
        self.assertEqual(1, len(pyannote))
        self.assertIn(PYANNOTE, pyannote[0].served_keys)
        self.assertEqual('pyannote', pyannote[0].engine)

    def test_a_line_without_engine_receives_the_engine_of_the_backend_that_names_it(self):
        r = _registry()
        r._models[PYANNOTE] = _line(PYANNOTE)
        r._overlay_engines_named_by_backends()
        self.assertEqual('pyannote', r._models[PYANNOTE].composition['runtime']['engine'])

    def test_a_declared_engine_is_never_replaced(self):
        """Contre-épreuve : la passe ne comble que le vide."""
        r = _registry()
        r._models[PYANNOTE] = _line(PYANNOTE, {'runtime': {'engine': 'autre'}})
        r._overlay_engines_named_by_backends()
        self.assertEqual('autre', r._models[PYANNOTE].composition['runtime']['engine'])

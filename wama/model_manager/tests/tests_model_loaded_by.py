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
                   '_discover_turn_end_models')

    def test_each_brick_model_names_a_module_that_exists(self):
        r = _registry()
        for name in self.DISCOVERIES:
            getattr(r, name)()
        declared = {key: (info.composition or {}).get('runtime', {}).get('loaded_by')
                    for key, info in r._models.items()}
        declared = {k: v for k, v in declared.items() if v}
        self.assertEqual(5, len(declared), declared)
        for key, module in declared.items():
            with self.subTest(model=key):
                self.assertIsNotNone(importlib.util.find_spec(module), f'{module} introuvable')

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

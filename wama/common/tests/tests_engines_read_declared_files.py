"""Five models the ROUTE installs and their engines read by PATH (2026-11-02) — Whisper large-v3
(the transcriber's model), Whisper tiny (spoken language), Coqui XTTS v2, docTR and docTR's page
orientation classifier. Each library used to fetch its weights at first use, outside the
catalogue: faster-whisper by model NAME, Coqui through its own manager (which also re-read the
remote `config.json` at every load), docTR through `ocr_predictor(pretrained=True)`.

What is held here, per model:
  * the declaration passes the lock of the `files` driver (origin frozen: Hub commit or GitHub
    release) ;
  * the catalogue row is MEASURED — absent, it is installable by its declared files ; present,
    downloaded ;
  * the engine never reaches the library's downloader: absent, it says the route ; present, the
    library receives a FOLDER (or finds its file where it looks first).
"""
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.backends import coqui_backend, doctr_backend, ocr_base, whisper_backend
from wama.common.utils import spoken_language


def _fill(root, files):
    """Les fichiers déclarés, à leur taille, sous `root` — sans octets réels."""
    for f in files:
        path = Path(root) / f['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as out:
            out.truncate(f['size'])


class DeclarationsTest(SimpleTestCase):

    DECLARED = {
        'transcriber:whisper': (whisper_backend.WHISPER_FILES['large-v3'],
                                {('huggingface', 'Systran/faster-whisper-large-v3')}),
        spoken_language.MODEL_KEY: (spoken_language.LANGUAGE_ID_FILES,
                                    {('huggingface', 'Systran/faster-whisper-tiny')}),
        'synthesizer:coqui-xtts': (coqui_backend.COQUI_FILES['coqui-xtts'],
                                   {('huggingface', 'coqui/XTTS-v2')}),
        doctr_backend.DOCTR_KEY: (doctr_backend.DOCTR_FILES, {('github', None)}),
        ocr_base.PAGE_ORIENTATION_KEY: (ocr_base.PAGE_ORIENTATION_FILES, {('github', None)}),
    }

    def test_every_declaration_passes_the_lock_with_a_frozen_origin(self):
        from wama.model_manager.services.model_installer import declared_files_error
        for key, (files, origins) in self.DECLARED.items():
            with self.subTest(model=key):
                self.assertIsNone(declared_files_error(
                    {'kind': 'files', 'ref': key, 'files': files, 'target_dir': '/x'}))
                self.assertEqual(origins, {(f['origin']['source'], f['origin'].get('repo'))
                                           for f in files})

    def test_docTR_files_sit_where_the_library_looks_and_carry_its_hash_prefix(self):
        """`download_from_url` reads `<DOCTR_CACHE_DIR>/models/<name>` without downloading when the
        file's sha256 starts with the prefix in its name."""
        for f in doctr_backend.DOCTR_FILES + ocr_base.PAGE_ORIENTATION_FILES:
            with self.subTest(file=f['path']):
                name = f['origin']['file']
                self.assertEqual(f'models/{name}', f['path'])
                self.assertTrue(f['sha256'].startswith(name.rsplit('-', 1)[1].split('.')[0]))
                self.assertTrue(f['origin']['release'].startswith('mindee/doctr:'))

    def test_coqui_files_keep_the_folder_the_library_used(self):
        folder = {Path(f['path']).parent for f in coqui_backend.COQUI_FILES['coqui-xtts']}
        self.assertEqual({Path('tts/tts_models--multilingual--multi-dataset--xtts_v2')}, folder)


class CatalogueRowsAreMeasuredTest(SimpleTestCase):
    """Absent → not downloaded and installable by its declared files ; present → downloaded."""

    def _rows(self, root):
        from wama.model_manager.services.model_registry import ModelRegistry
        root = Path(root)
        speech = {**settings.MODEL_PATHS.get('speech', {}),
                  'whisper': root / 'models' / 'speech' / 'whisper',
                  'coqui': root / 'models' / 'speech' / 'coqui'}
        ocr = {**settings.MODEL_PATHS.get('ocr', {}), 'doctr': root / 'models' / 'ocr' / 'doctr'}
        with self.settings(AI_MODELS_DIR=root,
                           MODEL_PATHS={**settings.MODEL_PATHS, 'speech': speech, 'ocr': ocr}):
            registry = ModelRegistry()
            registry._models = {}
            registry._discover_transcriber_models()
            registry._discover_synthesizer_models()
            registry._discover_reader_models()
            registry._discover_language_identification_models()
            registry._discover_page_orientation_models()
            self.assertEqual([], registry.discovery_errors)
            from wama.model_manager.models import AIModel
            from wama.model_manager.services.model_installer import spec_for_catalog_row
            specs = {key: spec_for_catalog_row(AIModel(model_key=key,
                                                       extra_info=registry._models[key].extra_info))
                     for key in DeclarationsTest.DECLARED}
        return registry._models, specs, speech, ocr

    def test_absent_rows_are_installable_by_their_declared_files(self):
        with tempfile.TemporaryDirectory() as root:
            models, specs, speech, ocr = self._rows(root)
        expected_dir = {'transcriber:whisper': speech['whisper'],
                        spoken_language.MODEL_KEY: speech['whisper'],
                        'synthesizer:coqui-xtts': speech['coqui'],
                        doctr_backend.DOCTR_KEY: ocr['doctr'],
                        ocr_base.PAGE_ORIENTATION_KEY: ocr['doctr']}
        for key, (files, _origins) in DeclarationsTest.DECLARED.items():
            with self.subTest(model=key):
                self.assertFalse(models[key].is_downloaded, 'measured, never assumed')
                self.assertEqual(('files', str(expected_dir[key]), files),
                                 (specs[key]['kind'], specs[key]['target_dir'], specs[key]['files']))

    def test_the_transcriber_row_keeps_the_identity_of_the_original_model(self):
        with tempfile.TemporaryDirectory() as root:
            models, _specs, _speech, _ocr = self._rows(root)
        self.assertEqual('huggingface:openai/whisper-large-v3',
                         models['transcriber:whisper'].platform_ref)
        self.assertEqual('language-identification',
                         models[spoken_language.MODEL_KEY].capabilities['task'])
        self.assertEqual('page-orientation',
                         models[ocr_base.PAGE_ORIENTATION_KEY].capabilities['task'])

    def test_counter_proof_declared_files_in_place_make_the_rows_downloaded(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            _fill(root / 'models' / 'speech' / 'whisper', whisper_backend.WHISPER_FILES['large-v3']
                  + spoken_language.LANGUAGE_ID_FILES)
            _fill(root / 'models' / 'speech' / 'coqui', coqui_backend.COQUI_FILES['coqui-xtts'])
            _fill(root / 'models' / 'ocr' / 'doctr', doctr_backend.DOCTR_FILES + ocr_base.PAGE_ORIENTATION_FILES)
            models, _specs, _speech, _ocr = self._rows(root)
        for key in DeclarationsTest.DECLARED:
            with self.subTest(model=key):
                self.assertTrue(models[key].is_downloaded)

    def test_an_importable_docTR_package_no_longer_makes_its_row_downloaded(self):
        """It used to: `import doctr` succeeding was the fallback « downloaded »."""
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.dict(sys.modules, {'doctr': types.ModuleType('doctr')}):
            models, _specs, _speech, _ocr = self._rows(root)
        self.assertFalse(models[doctr_backend.DOCTR_KEY].is_downloaded)


class SpeechFolderTest(SimpleTestCase):
    """ONE reading of a speech model's folder (`tts_base.speech_folder`) for Phonon, Whisper, Coqui
    and the enhancer's audio engines — they each carried a copy until 2026-11-02."""

    def test_the_declared_setting_is_read_without_creating_anything(self):
        from wama.common.backends.tts_base import speech_folder
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'nowhere' / 'whisper'
            speech = {**settings.MODEL_PATHS.get('speech', {}), 'whisper': folder}
            with self.settings(MODEL_PATHS={**settings.MODEL_PATHS, 'speech': speech}):
                self.assertEqual(folder, speech_folder('whisper'))
                self.assertEqual(folder, whisper_backend.whisper_folder())
            self.assertFalse(folder.exists(), 'no side effect, unlike `speech_dir`')

    def test_without_settings_the_same_folder_under_AI_models_never_the_home(self):
        """The voice service runs without Django."""
        from wama.common.backends import tts_base
        broken = mock.PropertyMock(side_effect=RuntimeError('settings not configured'))
        with mock.patch.object(type(settings), 'MODEL_PATHS', broken, create=True), \
                mock.patch.object(tts_base, 'ai_models_dir', return_value=Path('/ai')):
            self.assertEqual(Path('/ai/models/speech/resemble-enhance'),
                             tts_base.speech_folder('resemble_enhance', 'resemble-enhance'))
            self.assertEqual(Path('/ai/models/speech/coqui'), coqui_backend.coqui_folder())


class _FakeWhisperModel:
    seen = []

    def __init__(self, source, **kwargs):
        self.seen.append((source, kwargs))


def _fake_faster_whisper():
    _FakeWhisperModel.seen = []
    return mock.patch.dict(sys.modules, {
        'faster_whisper': types.SimpleNamespace(WhisperModel=_FakeWhisperModel)})


class WhisperReadsItsFolderTest(SimpleTestCase):

    def test_the_declared_size_is_loaded_by_its_folder(self):
        backend = whisper_backend.WhisperBackend()
        with _fake_faster_whisper(), \
                mock.patch.object(whisper_backend, 'ct2_installed', return_value=True):
            self.assertTrue(backend.load('large-v3'))
        folder = whisper_backend.ct2_model_dir(whisper_backend.WHISPER_FILES['large-v3'])
        self.assertEqual(str(folder), _FakeWhisperModel.seen[0][0],
                         'a FOLDER: faster-whisper downloads only for a NAME')
        self.assertEqual('large-v3', backend._current_model, 'the catalogue reads the size')

    def test_an_absent_declared_size_is_never_reached_by_name(self):
        backend = whisper_backend.WhisperBackend()
        with _fake_faster_whisper(), \
                mock.patch.object(whisper_backend, 'ct2_installed', return_value=False), \
                self.assertLogs('wama.common.backends.whisper_backend', 'ERROR') as logs:
            self.assertFalse(backend.load('large-v3'))
        self.assertEqual([], _FakeWhisperModel.seen)
        self.assertIn('transcriber:whisper', '\n'.join(logs.output))

    def test_counter_proof_an_undeclared_size_keeps_its_name_and_the_family_folder(self):
        """A `WAMA_ASSISTANT_STT_MODEL` set to another size: nothing declared to install — the
        family folder (lever A), as before."""
        backend = whisper_backend.WhisperBackend()
        with _fake_faster_whisper():
            self.assertTrue(backend.load('small'))
        source, kwargs = _FakeWhisperModel.seen[0]
        self.assertEqual(('small', str(whisper_backend.whisper_folder())),
                         (source, kwargs['download_root']))


class SpokenLanguageReadsItsFolderTest(SimpleTestCase):

    def setUp(self):
        spoken_language._detector = None
        self.addCleanup(setattr, spoken_language, '_detector', None)

    def test_an_absent_model_is_never_downloaded_and_says_the_route(self):
        with _fake_faster_whisper(), \
                mock.patch.object(spoken_language, 'model_installed', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'model manager.*faster-whisper-tiny'):
                spoken_language._model()
        self.assertEqual([], _FakeWhisperModel.seen)

    def test_an_installed_model_is_read_by_its_folder(self):
        with _fake_faster_whisper(), \
                mock.patch.object(spoken_language, 'model_installed', return_value=True):
            spoken_language._model()
        source, kwargs = _FakeWhisperModel.seen[0]
        self.assertEqual(str(spoken_language.model_folder()), source)
        self.assertNotIn('download_root', kwargs)


class CoquiReadsItsFolderTest(SimpleTestCase):
    """The SAME load as `TTS(<name>)` for XTTS — `Synthesizer(model_dir=…)` — without the
    library's manager. ⚠ Not `TTS(model_path=…)`: another loader, the wrong output sample rate."""

    def _fake_tts(self, built):
        class FakeTTS:
            def __init__(self, model_name='', **kwargs):
                built.append(('TTS', model_name, kwargs))
                self.encoder_path = self.encoder_config_path = None

            def to(self, device):
                return self

        class FakeSynthesizer:
            def __init__(self, **kwargs):
                built.append(('Synthesizer', kwargs))
        api = types.ModuleType('TTS.api')
        api.TTS = FakeTTS
        synthesizer = types.ModuleType('TTS.utils.synthesizer')
        synthesizer.Synthesizer = FakeSynthesizer
        return mock.patch.dict(sys.modules, {'TTS': types.ModuleType('TTS'), 'TTS.api': api,
                                             'TTS.utils': types.ModuleType('TTS.utils'),
                                             'TTS.utils.synthesizer': synthesizer})

    def _patches(self, installed):
        return (mock.patch.object(coqui_backend, 'coqui_installed', return_value=installed),
                mock.patch('wama.common.utils.torchaudio_compat.patch_torchaudio_soundfile'),
                mock.patch.object(coqui_backend, '_device', return_value='cpu'))

    def test_an_installed_model_is_read_by_its_folder_like_the_library_does(self):
        built = []
        installed, torchaudio, device = self._patches(True)
        with self._fake_tts(built), installed, torchaudio, device:
            self.assertTrue(coqui_backend.CoquiBackend().load('coqui-xtts'))
        self.assertEqual(('TTS', '', {'progress_bar': False}), built[0],
                         'no model NAME: the manager never downloads nor re-reads the remote config')
        kind, kwargs = built[1]
        self.assertEqual('Synthesizer', kind)
        self.assertEqual(str(coqui_backend.coqui_model_dir('coqui-xtts')), kwargs['model_dir'])
        self.assertEqual((None, None, False),
                         (kwargs['tts_checkpoint'], kwargs['tts_config_path'], kwargs['use_cuda']))

    def test_an_absent_model_never_reaches_the_library_and_says_the_route(self):
        built = []
        installed, torchaudio, device = self._patches(False)
        with self._fake_tts(built), installed, torchaudio, device:
            with self.assertRaisesRegex(RuntimeError, 'model manager.*coqui-xtts'):
                coqui_backend.CoquiBackend().load('coqui-xtts')
        self.assertEqual([], built)


class DocTRReadsItsFilesTest(SimpleTestCase):

    def _fake_doctr(self, calls):
        models = types.ModuleType('doctr.models')
        models.ocr_predictor = lambda **k: calls.append(('ocr', k))
        models.page_orientation_predictor = lambda **k: calls.append(('orientation', k))
        io = types.ModuleType('doctr.io')
        io.DocumentFile = mock.Mock()
        return mock.patch.dict(sys.modules, {'doctr': types.ModuleType('doctr'),
                                             'doctr.models': models, 'doctr.io': io})

    def test_an_absent_pipeline_never_reaches_the_library_and_says_the_route(self):
        calls = []
        with self._fake_doctr(calls), \
                mock.patch.object(doctr_backend, 'doctr_installed', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'model manager.*reader:doctr'):
                doctr_backend.DocTRBackend()._predict('page.png')
        self.assertEqual([], calls)

    def test_an_absent_orientation_classifier_is_not_downloaded_and_not_remembered(self):
        """A comfort: the image goes as is — and once installed, the next call loads it."""
        calls = []
        self.addCleanup(ocr_base._ORIENTATION_PREDICTOR.clear)
        ocr_base._ORIENTATION_PREDICTOR.clear()
        with self._fake_doctr(calls), \
                mock.patch.object(ocr_base, 'page_orientation_installed', return_value=False):
            self.assertIsNone(ocr_base._orientation_predictor())
        self.assertEqual([], calls)
        with self._fake_doctr(calls), \
                mock.patch.object(ocr_base, 'page_orientation_installed', return_value=True):
            ocr_base._orientation_predictor()
        self.assertEqual([('orientation', {'pretrained': True})], calls)

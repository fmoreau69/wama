"""Models the ROUTE installs and their engines read WITHOUT downloading (2026-11-02) — Coqui
XTTS v2, docTR and docTR's page orientation classifier by their DECLARED files ; Whisper large-v3
(the transcriber's model) and Whisper tiny (spoken language) as repos of the Hub (2026-11-05).
Each library used to fetch its weights at first use, outside the catalogue: faster-whisper by
model NAME, Coqui through its own manager (which also re-read the remote `config.json` at every
load), docTR through `ocr_predictor(pretrained=True)`.

What is held here, per model:
  * a declaration of files passes the lock of the `files` driver (origin frozen: Hub commit or
    GitHub release) ; a Hub row names the repo the engine READS, and its original model ;
  * the catalogue row is MEASURED — absent, it is installable by the route ; present, downloaded ;
  * the engine never reaches the library's downloader: absent, it says the route ; present, the
    library receives a FOLDER (or finds its file where it looks first), or reads the installed
    snapshot with `local_files_only`.

And Kokoro's VOICES (2026-11-03): the model was read by path since 2026-09-04, but each voice went
to `KPipeline` by NAME, which `hf_hub_download`s it into the shared cache at first use.
"""
import ast
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
        'synthesizer:coqui-xtts':(coqui_backend.COQUI_FILES['coqui-xtts'],
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


#: Whisper's rows (2026-11-05) — the catalogue key and the size the engine reads.
WHISPER_ROWS = {'transcriber:whisper': 'large-v3', spoken_language.MODEL_KEY: 'tiny'}


def _discover(test, root):
    """The rows of the five models, discovered under a throwaway `AI-models`, and their specs."""
    from wama.model_manager.models import AIModel
    from wama.model_manager.services.model_installer import spec_for_catalog_row
    from wama.model_manager.services.model_registry import ModelRegistry
    root = Path(root)
    speech = {**settings.MODEL_PATHS.get('speech', {}),
              'whisper': root / 'models' / 'speech' / 'whisper',
              'coqui': root / 'models' / 'speech' / 'coqui'}
    ocr = {**settings.MODEL_PATHS.get('ocr', {}), 'doctr': root / 'models' / 'ocr' / 'doctr'}
    with test.settings(AI_MODELS_DIR=root,
                       MODEL_PATHS={**settings.MODEL_PATHS, 'speech': speech, 'ocr': ocr}):
        registry = ModelRegistry()
        registry._models = {}
        registry._discover_transcriber_models()
        registry._discover_synthesizer_models()
        registry._discover_reader_models()
        registry._discover_language_identification_models()
        registry._discover_page_orientation_models()
        test.assertEqual([], registry.discovery_errors)
        specs = {key: spec_for_catalog_row(AIModel(model_key=key,
                                                   platform_ref=registry._models[key].platform_ref or '',
                                                   extra_info=registry._models[key].extra_info))
                 for key in [*DeclarationsTest.DECLARED, *WHISPER_ROWS]}
    return registry._models, specs, speech, ocr


def _hub_snapshot(family, repo, files=('config.json', 'model.bin')):
    """A repo of the Hub as the route leaves it: `models--org--nom/snapshots/<commit>/…`."""
    from wama.common.utils.model_locations import hf_folder_name
    revision = Path(family) / hf_folder_name(repo) / 'snapshots' / ('0' * 40)
    revision.mkdir(parents=True, exist_ok=True)
    for name in files:
        (revision / name).write_bytes(b'0' * 16)
    return revision


class CatalogueRowsAreMeasuredTest(SimpleTestCase):
    """Absent → not downloaded and installable by its declared files ; present → downloaded."""

    def test_absent_rows_are_installable_by_their_declared_files(self):
        with tempfile.TemporaryDirectory() as root:
            models, specs, speech, ocr = _discover(self, root)
        expected_dir = {'synthesizer:coqui-xtts': speech['coqui'],
                        doctr_backend.DOCTR_KEY: ocr['doctr'],
                        ocr_base.PAGE_ORIENTATION_KEY: ocr['doctr']}
        for key, (files, _origins) in DeclarationsTest.DECLARED.items():
            with self.subTest(model=key):
                self.assertFalse(models[key].is_downloaded, 'measured, never assumed')
                self.assertEqual(('files', str(expected_dir[key]), files),
                                 (specs[key]['kind'], specs[key]['target_dir'], specs[key]['files']))

    def test_the_new_rows_name_their_task(self):
        with tempfile.TemporaryDirectory() as root:
            models, _specs, _speech, _ocr = _discover(self, root)
        self.assertEqual('language-identification',
                         models[spoken_language.MODEL_KEY].capabilities['task'])
        self.assertEqual('page-orientation',
                         models[ocr_base.PAGE_ORIENTATION_KEY].capabilities['task'])

    def test_counter_proof_declared_files_in_place_make_the_rows_downloaded(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            _fill(root / 'models' / 'speech' / 'coqui', coqui_backend.COQUI_FILES['coqui-xtts'])
            _fill(root / 'models' / 'ocr' / 'doctr', doctr_backend.DOCTR_FILES + ocr_base.PAGE_ORIENTATION_FILES)
            models, _specs, _speech, _ocr = _discover(self, root)
        for key in DeclarationsTest.DECLARED:
            with self.subTest(model=key):
                self.assertTrue(models[key].is_downloaded)

    def test_an_importable_docTR_package_no_longer_makes_its_row_downloaded(self):
        """It used to: `import doctr` succeeding was the fallback « downloaded »."""
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.dict(sys.modules, {'doctr': types.ModuleType('doctr')}):
            models, _specs, _speech, _ocr = _discover(self, root)
        self.assertFalse(models[doctr_backend.DOCTR_KEY].is_downloaded)


class WhisperRowsAreHubRowsTest(SimpleTestCase):
    """Whisper large-v3 and tiny (2026-11-05): a row names the repo the engine READS — Systran's
    CTranslate2 conversion, the only format faster-whisper reads — and carries the model it
    converts (`base_model`, relation `quantized`, the Hub's word for a format export). The route
    installs it like any repo of the Hub, in Whisper's family folder. From 02 to 05/11 the row
    named OpenAI's repo while its declared files came from Systran's."""

    def test_absent_rows_are_installed_by_the_hub_driver_in_the_family_folder(self):
        from wama.model_manager.services.model_installer import pull_hf_model
        with tempfile.TemporaryDirectory() as root:
            models, specs, speech, _ocr = _discover(self, root)
            for key, size in WHISPER_ROWS.items():
                with self.subTest(model=key):
                    spec = specs[key]
                    self.assertFalse(models[key].is_downloaded, 'measured, never assumed')
                    self.assertNotIn('declared_files', models[key].extra_info)
                    self.assertEqual(('hf', whisper_backend.WHISPER_REPOS[size]['repo']),
                                     (spec['kind'], spec['ref']))
                    with self.settings(AI_MODELS_DIR=Path(root)):
                        target = pull_hf_model(spec['ref'], spec['category'], spec.get('family'),
                                               dry_run=True)['target']
                    self.assertEqual(Path(speech['whisper']), Path(target),
                                     'installed where the engine reads it')

    def test_a_row_names_the_repo_read_and_carries_the_original_model(self):
        with tempfile.TemporaryDirectory() as root:
            models, _specs, _speech, _ocr = _discover(self, root)
        expected = {'transcriber:whisper': ('Systran/faster-whisper-large-v3', 'openai/whisper-large-v3'),
                    spoken_language.MODEL_KEY: ('Systran/faster-whisper-tiny', 'openai/whisper-tiny')}
        for key, (read, original) in expected.items():
            with self.subTest(model=key):
                info = models[key]
                self.assertEqual(f'huggingface:{read}', info.platform_ref)
                self.assertEqual((original, 'quantized'),
                                 (info.extra_info['base_model'], info.extra_info['base_model_relation']))

    def test_the_original_model_reaches_the_catalogue_as_a_format_export(self):
        """`quantized` keeps the bench matching by repo (`hub_repos`) and never makes the
        original model a backbone to install with it."""
        from wama.model_manager.models import AIModel
        info = whisper_backend.whisper_base_model('large-v3')
        row = AIModel(model_key='transcriber:whisper',
                      platform_ref='huggingface:Systran/faster-whisper-large-v3', extra_info=info)
        self.assertEqual({'systran/faster-whisper-large-v3', 'openai/whisper-large-v3'},
                         row.hub_repos())

    def test_counter_proof_an_installed_snapshot_makes_the_rows_downloaded(self):
        with tempfile.TemporaryDirectory() as root:
            family = Path(root) / 'models' / 'speech' / 'whisper'
            for size in WHISPER_ROWS.values():
                _hub_snapshot(family, whisper_backend.WHISPER_REPOS[size]['repo'])
            models, _specs, _speech, _ocr = _discover(self, root)
        for key in WHISPER_ROWS:
            with self.subTest(model=key):
                self.assertTrue(models[key].is_downloaded)

    def test_a_snapshot_without_weights_is_not_downloaded(self):
        """A config left by an aborted load (the Qwen3-ASR case) — the common judgment."""
        with tempfile.TemporaryDirectory() as root:
            family = Path(root) / 'models' / 'speech' / 'whisper'
            _hub_snapshot(family, 'Systran/faster-whisper-large-v3', files=('config.json',))
            models, _specs, _speech, _ocr = _discover(self, root)
        self.assertFalse(models['transcriber:whisper'].is_downloaded)


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


class WhisperReadsTheInstalledSnapshotTest(SimpleTestCase):
    """A declared size is read by its repo in the family folder WITHOUT network
    (`local_files_only`) — faster-whisper resolves it like `snapshot_download` (lever A), and the
    flag forbids the download the route alone may do."""

    def test_the_declared_size_is_read_from_the_family_folder_without_network(self):
        backend = whisper_backend.WhisperBackend()
        with _fake_faster_whisper(), \
                mock.patch.object(whisper_backend, 'whisper_installed', return_value=True):
            self.assertTrue(backend.load('large-v3'))
        source, kwargs = _FakeWhisperModel.seen[0]
        self.assertEqual(('Systran/faster-whisper-large-v3', str(whisper_backend.whisper_folder()), True),
                         (source, kwargs['download_root'], kwargs['local_files_only']))
        self.assertEqual('large-v3', backend._current_model, 'the catalogue reads the size')

    def test_an_absent_declared_size_never_reaches_the_library_and_says_the_route(self):
        backend = whisper_backend.WhisperBackend()
        with _fake_faster_whisper(), \
                mock.patch.object(whisper_backend, 'whisper_installed', return_value=False), \
                self.assertLogs('wama.common.backends.whisper_backend', 'ERROR') as logs:
            self.assertFalse(backend.load('large-v3'))
        self.assertEqual([], _FakeWhisperModel.seen)
        self.assertIn('model manager', '\n'.join(logs.output))
        self.assertIn('Systran/faster-whisper-large-v3', '\n'.join(logs.output))

    def test_installed_is_the_common_judgment_on_the_snapshot_the_route_leaves(self):
        with tempfile.TemporaryDirectory() as root:
            family = Path(root) / 'whisper'
            speech = {**settings.MODEL_PATHS.get('speech', {}), 'whisper': family}
            with self.settings(MODEL_PATHS={**settings.MODEL_PATHS, 'speech': speech}):
                self.assertFalse(whisper_backend.whisper_installed('large-v3'))
                _hub_snapshot(family, 'Systran/faster-whisper-large-v3', files=('config.json',))
                self.assertFalse(whisper_backend.whisper_installed('large-v3'), 'a config only')
                _hub_snapshot(family, 'Systran/faster-whisper-large-v3')
                self.assertTrue(whisper_backend.whisper_installed('large-v3'))

    def test_counter_proof_an_undeclared_size_keeps_its_name_and_the_family_folder(self):
        """A `WAMA_ASSISTANT_STT_MODEL` set to another size: nothing declared to install — the
        family folder (lever A), as before, and the library may fetch it."""
        backend = whisper_backend.WhisperBackend()
        with _fake_faster_whisper():
            self.assertTrue(backend.load('small'))
        source, kwargs = _FakeWhisperModel.seen[0]
        self.assertEqual(('small', str(whisper_backend.whisper_folder()), False),
                         (source, kwargs['download_root'], kwargs['local_files_only']))


class SpokenLanguageReadsTheInstalledSnapshotTest(SimpleTestCase):
    """The language probe's model, loaded by its backend (`WhisperLanguageBackend`, 2026-11-06) —
    the same reading of a declared size as `WhisperBackend` (`whisper_model_source`)."""

    def _backend(self):
        from wama.common.backends.whisper_language_backend import WhisperLanguageBackend
        return WhisperLanguageBackend()

    def test_an_absent_model_is_never_downloaded_and_says_the_route(self):
        with _fake_faster_whisper(), \
                mock.patch.object(whisper_backend, 'whisper_installed', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'model manager.*faster-whisper-tiny'):
                self._backend().load(spoken_language.MODEL_KEY)
        self.assertEqual([], _FakeWhisperModel.seen)

    def test_an_installed_model_is_read_from_the_family_folder_without_network(self):
        with _fake_faster_whisper(), \
                mock.patch.object(whisper_backend, 'whisper_installed', return_value=True):
            self.assertTrue(self._backend().load(spoken_language.MODEL_KEY))
        source, kwargs = _FakeWhisperModel.seen[0]
        self.assertEqual(('Systran/faster-whisper-tiny', str(whisper_backend.whisper_folder()), True,
                          'cpu', 'int8'),
                         (source, kwargs['download_root'], kwargs['local_files_only'],
                          kwargs['device'], kwargs['compute_type']))
        self.assertEqual(whisper_backend.WHISPER_REPOS['tiny']['repo'], spoken_language.HF_REPO,
                         'one declaration of the size, beside its engine')


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
        """A comfort: the image goes as is — and once installed, the next call loads it. Since
        2026-11-07 the classifier is loaded by its backend (`DocTROrientationBackend`)."""
        from wama.common.backends import doctr_orientation_backend
        calls = []
        backend = doctr_orientation_backend.DocTROrientationBackend()
        with self._fake_doctr(calls), \
                mock.patch.object(doctr_orientation_backend, 'page_orientation_installed',
                                  return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'model manager.*mindee/doctr'):
                backend.load()
        self.assertEqual([], calls)
        with self._fake_doctr(calls), \
                mock.patch.object(doctr_orientation_backend, 'page_orientation_installed',
                                  return_value=True):
            self.assertTrue(backend.load())
        self.assertEqual([('orientation', {'pretrained': True})], calls)


class KokoroReadsItsVoicesTest(SimpleTestCase):
    """A voice reaches `KPipeline` as the `.pt` FILE of the installed snapshot, never as a name:
    `load_single_voice` downloads a name (`hf_hub_download`, no `cache_dir`) into the shared cache."""

    def setUp(self):
        from wama.common.backends import kokoro_backend
        self.kokoro = kokoro_backend
        kokoro_backend.local_voice.cache_clear()
        self.addCleanup(kokoro_backend.local_voice.cache_clear)

    def _snapshot(self, root):
        return mock.patch('wama.common.utils.hf_weights.poids_locaux', return_value=str(root))

    def test_a_voice_is_the_file_of_the_family_snapshot(self):
        with tempfile.TemporaryDirectory() as root, self._snapshot(root) as weights:
            path = self.kokoro.local_voice('ff_siwis')
        self.assertEqual(str(Path(root) / 'voices' / 'ff_siwis.pt'), path)
        (repo, folder), kwargs = weights.call_args
        self.assertEqual((self.kokoro.REPO_ID, self.kokoro.speech_dir('kokoro')), (repo, folder),
                         'the family folder, lever B — never the shared cache')
        self.assertEqual(['voices/ff_siwis.pt'], kwargs['patterns'])

    def test_the_engine_hands_the_pipeline_a_file_not_a_name(self):
        voices = []

        class FakePipeline:
            g2p = None

            def __call__(self, text, voice=None, speed=1.0):
                voices.append(voice)
                return iter([(None, None, [0.0, 0.1])])

        backend = self.kokoro.KokoroBackend()
        with tempfile.TemporaryDirectory() as root, self._snapshot(root), \
                mock.patch.object(backend, '_get_pipeline', return_value=FakePipeline()), \
                mock.patch.object(self.kokoro, 'say_lexicon_through'), \
                mock.patch.object(self.kokoro, 'write_wav_int16', return_value='out.wav'):
            backend.process('Bonjour', language='fr')
        self.assertEqual(1, len(voices))
        self.assertTrue(voices[0].endswith('.pt'), f'a NAME is downloaded by the library: {voices[0]}')
        self.assertTrue(voices[0].startswith(root))

    def test_every_kokoro_pipeline_is_built_and_fed_by_the_engine_bricks(self):
        """By AST over `wama/`: `kokoro` is imported by the engine alone (`local_pipeline` is the
        ONE constructor), and every `voice=` given where a pipeline is obtained goes through
        `local_voice`. A new consumer that passes a name turns this red."""
        base = Path(settings.BASE_DIR) / 'wama'
        importers, unfed = set(), []
        for path in base.rglob('*.py'):
            if 'tests' in path.parts or 'migrations' in path.parts:
                continue
            source = path.read_text(encoding='utf-8')
            if 'kokoro' not in source:
                continue
            tree = ast.parse(source)
            rel = path.relative_to(base).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == 'kokoro':
                    importers.add(rel)
            if 'local_pipeline(' not in source and '_get_pipeline(' not in source:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg == 'voice' and not (isinstance(kw.value, ast.Call)
                                                  and getattr(kw.value.func, 'id', '') == 'local_voice'):
                        unfed.append(f'{rel}:{node.lineno}')
        self.assertEqual({'common/backends/kokoro_backend.py'}, importers)
        self.assertEqual([], unfed, 'a voice given by NAME is downloaded outside the route')

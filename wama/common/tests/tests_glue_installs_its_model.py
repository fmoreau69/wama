"""Each app's glue asks the ROUTE for the model it is about to load (`ctx.ensure_model`), and lets
the wait through — decision of Fabien, 2026-10-16 : « la tâche attendra jusqu'à ce que
l'installation soit complètement faite ».

The skeleton covers the CARD's model (`run_item_task(model_key=…)`, `tests_model_readiness`) ;
here, the models a glue resolves itself — a process of a pipeline, a model chosen at launch, a
secondary one. Each test gives the glue a context whose `ensure_model` WAITS, and checks the key
it was asked for and that the wait is not turned into a failure.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from wama.common.utils.task_skeleton import ServiceNotReady


def _waiting_context(stop_at=None):
    """A context whose `ensure_model` records the keys and WAITS at `stop_at` (the first if None)."""
    asked = []

    def ensure_model(key):
        asked.append(key)
        if stop_at is None or key == stop_at:
            raise ServiceNotReady(f'Installation de « {key} » en cours')
        return key
    return mock.MagicMock(ensure_model=mock.MagicMock(side_effect=ensure_model)), asked


class GlueInstallsItsModelTest(SimpleTestCase):

    def test_reader_reading_engine_and_the_wait_is_not_shown_as_an_error(self):
        from wama.reader import tasks
        ctx, asked = _waiting_context()
        item = SimpleNamespace(filename='a.png', page_count=1, backend='reader:doctr', pk=1, user=None,
                               input_file=SimpleNamespace(name='a.png', path='/x/a.png'))
        with mock.patch.object(tasks, '_set_progress') as progress, \
                self.assertRaises(ServiceNotReady):
            tasks._read(item, ctx)
        self.assertEqual(['reader:doctr'], asked)
        self.assertFalse(any('Erreur' in str(c.args) for c in progress.call_args_list))

    def test_synthesizer_voice_engine(self):
        from wama.synthesizer import workers
        ctx, asked = _waiting_context()
        item = mock.MagicMock(tts_model='synthesizer:bark', word_count=3)
        with mock.patch.object(workers, 'extract_text_from_file', return_value='bonjour à tous'), \
                mock.patch.object(workers, '_console'), \
                mock.patch.object(workers, '_clear_during'), \
                self.assertRaises(ServiceNotReady):
            workers._synthesize(item, ctx)
        self.assertEqual(['synthesizer:bark'], asked)

    def test_avatarizer_voice_engine(self):
        from wama.avatarizer import workers
        ctx, asked = _waiting_context()
        job = mock.MagicMock(tts_model='synthesizer:coqui-xtts')
        with mock.patch.object(workers, '_console'), self.assertRaises(ServiceNotReady):
            workers._speak(job, ctx)
        self.assertEqual(['synthesizer:coqui-xtts'], asked)

    def test_avatarizer_face_restorer(self):
        from wama.avatarizer import workers
        ctx, asked = _waiting_context()
        with mock.patch.object(workers, '_backend') as backend, self.assertRaises(ServiceNotReady):
            workers._codeformer(mock.MagicMock(), '/x/animated.mp4', ctx)
        self.assertEqual(['avatarizer:codeformer'], asked)
        backend.assert_not_called()

    def test_describer_speech_model(self):
        from wama.describer import workers
        ctx, asked = _waiting_context()
        with mock.patch.object(workers, 'asr_key', return_value='transcriber:whisper'), \
                self.assertRaises(ServiceNotReady):
            workers._transcribe_step(mock.MagicMock(), ctx)
        self.assertEqual(['transcriber:whisper'], asked)

    def test_describer_designated_writing_model(self):
        from wama.describer import workers
        ctx, asked = _waiting_context()
        with mock.patch.object(workers, '_options',
                               return_value={'vision_model': 'describer:blip', 'llm_model': 'auto'}), \
                mock.patch('wama.describer.function_specs.nature_of', return_value='image'), \
                mock.patch('wama.common.backends.manager.route_for_nature') as route, \
                self.assertRaises(ServiceNotReady):
            workers._describe_step(mock.MagicMock(), ctx)
        self.assertEqual(['describer:blip'], asked)
        route.return_value.assert_not_called()

    def _auto_image(self, ctx, best):
        from wama.describer import workers
        from wama.describer.backends import image_backend
        with mock.patch.object(workers, '_options',
                               return_value={'vision_model': 'auto', 'llm_model': 'auto'}), \
                mock.patch('wama.describer.function_specs.nature_of', return_value='image'), \
                mock.patch.object(image_backend, '_best_ollama_vision_model', return_value=best), \
                mock.patch.object(image_backend, '_gpu_safe_mode', return_value=False), \
                mock.patch('wama.common.backends.manager.route_for_nature') as route, \
                self.assertRaises(ServiceNotReady):
            workers._describe_step(mock.MagicMock(), ctx)
        route.return_value.assert_not_called()

    def test_describer_auto_vision_asks_the_whole_cascade_its_fallback_included(self):
        """2026-10-19 : under « auto » the backend picked its model at load — the best Ollama
        vision model installed, BLIP if it does not answer. BLIP absent was pulled at load."""
        from wama.describer.backends.model_choice import BLIP_KEY, catalog_key_of
        ctx, asked = _waiting_context(stop_at=BLIP_KEY)
        self._auto_image(ctx, 'gemma4:12b')
        self.assertEqual([catalog_key_of('gemma4:12b'), BLIP_KEY], asked)

    def test_describer_auto_vision_without_ollama_asks_blip(self):
        from wama.describer.backends.model_choice import BLIP_KEY
        ctx, asked = _waiting_context()
        self._auto_image(ctx, None)
        self.assertEqual([BLIP_KEY], asked)

    def test_describer_auto_key_frames_ask_blip(self):
        from wama.describer import workers
        from wama.describer.backends.model_choice import BLIP_KEY
        ctx, asked = _waiting_context()
        with mock.patch.object(workers, '_options', return_value={'vision_model': 'auto'}), \
                mock.patch('wama.describer.backends.video_backend.caption_frames') as frames, \
                self.assertRaises(ServiceNotReady):
            workers._frames_step(mock.MagicMock(), ctx)
        self.assertEqual([BLIP_KEY], asked)
        frames.assert_not_called()

    def test_anonymizer_every_detector_it_will_run(self):
        from wama.anonymizer import tasks
        ctx, asked = _waiting_context(stop_at='anonymizer:sam3')
        with mock.patch.object(tasks, '_detection_kwargs',
                               return_value=({'use_sam3': True}, ['anonymizer:yolov8n-face'])), \
                self.assertRaises(ServiceNotReady):
            tasks._detect(mock.MagicMock(), ctx)
        self.assertEqual(['anonymizer:yolov8n-face', 'anonymizer:sam3'], asked)

    def test_transcriber_diarization_pipeline(self):
        from wama.common.backends.pyannote_diarizer import catalogue_key_for
        from wama.transcriber import workers
        ctx, asked = _waiting_context()
        t = mock.MagicMock(diarization_model=None, segments_json=[{'start_time': 0.0}])
        with mock.patch.object(workers, '_run_state', return_value={}), \
                mock.patch.object(workers, '_segments_in_memory', return_value=[object()]), \
                mock.patch('wama.common.backends.pyannote_diarizer.is_available', return_value=True), \
                mock.patch('wama.common.backends.pyannote_diarizer.diarize') as diarize, \
                self.assertRaises(ServiceNotReady):
            workers._diarize_step(t, ctx)
        self.assertEqual([catalogue_key_for(None)], asked)
        diarize.assert_not_called()

    def test_transcriber_acoustic_aligner(self):
        from wama.transcriber import workers
        ctx, asked = _waiting_context()
        t = mock.MagicMock(segments_json=[{'start_time': 0.0, 'text': 'x'}], language='fr')
        aligner = SimpleNamespace(model_key='transcriber:wav2vec2-fr', name='wav2vec2 fr')
        with mock.patch.object(workers, '_needs_acoustic_alignment', return_value=True), \
                mock.patch.object(workers, '_aligner_model', return_value=aligner), \
                mock.patch('wama.common.backends.manager.backend_for_model') as load, \
                self.assertRaises(ServiceNotReady):
            workers._align_document(t, ctx)
        self.assertEqual(['transcriber:wav2vec2-fr'], asked)
        load.assert_not_called()

    def test_composer_score_extractor(self):
        """2026-10-19 : the composer's secondary processes resolved their model and loaded it —
        a model drawn among the installed ones never waited, a model CHOSEN on the card would
        have been pulled at load."""
        from wama.composer import tasks
        ctx, asked = _waiting_context()
        with mock.patch('wama.composer.utils.model_choice.score_extractor',
                        return_value='composer:sheetsage2'), \
                mock.patch('wama.common.backends.manager.backend_for_key') as load, \
                self.assertRaises(ServiceNotReady):
            tasks._extract_score(mock.MagicMock(), ctx)
        self.assertEqual(['composer:sheetsage2'], asked)
        load.assert_not_called()

    def test_composer_full_score_model_set_on_the_card(self):
        from wama.composer import tasks
        ctx, asked = _waiting_context()
        gen = mock.MagicMock(parts_model='huggingface:org/other-transcriber')
        with mock.patch('wama.common.backends.manager.backend_for_key') as load, \
                self.assertRaises(ServiceNotReady):
            tasks._parts(gen, ctx)
        self.assertEqual(['huggingface:org/other-transcriber'], asked)
        load.assert_not_called()

    def test_the_generated_model_glue_asks_too(self):
        """The task generator's MODEL flavour (an app born from the chain) carries the gesture."""
        from wama.common.manifests.codegen import tasks_gen
        source = tasks_gen.__file__
        with open(source, encoding='utf-8') as handle:
            text = handle.read()
        emitted = text.index("'    ctx.ensure_model(key)'")
        self.assertLess(text.index("resolve_model_choice(opts.pop"), emitted)
        self.assertLess(emitted, text.index("'    engine = backend_instance_for_key(key, user=item.user)'"))

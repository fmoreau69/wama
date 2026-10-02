"""
FrWhisper and Kyutai STT 1B — the two transcription backends written by the `backend` role and
validated on 2026-10-01. Both failed on EVERY transcription as written (b193bbc3); what is held
here without GPU nor weights: they are the backends the catalogue resolves for their models, and
the two conversions the real run proved wrong (Kyutai's frame-aligned tokens → timed words,
FrWhisper's Whisper windows → segments). The runtime itself was attested by a real run on 5 min
of SUMM-RE (`WAMA_QUALITE`).
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from wama.common.backends.frwhisper_backend import FrWhisperBackend
from wama.common.backends.stt_1b_en_fr_trfs_backend import KyutaiSttBackend


class DecodedAtTheModelRateTest(SimpleTestCase):
    """`decode_audio` leaves a WAV at its NATIVE rate; Kyutai then heard 16 kHz as 24 kHz (sped up
    by half, 2026-10-01). `decode_audio_at` guarantees the rate a speech model expects."""

    def _wav(self, rate, seconds=1.0):
        import tempfile

        import numpy as np
        import soundfile as sf
        handle = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        handle.close()
        self.addCleanup(lambda: __import__('os').unlink(handle.name))
        sf.write(handle.name, np.zeros(int(rate * seconds), dtype='float32'), rate)
        return handle.name

    def test_a_wav_comes_back_at_the_requested_rate(self):
        from wama.common.utils.audio_decode import decode_audio, decode_audio_at
        path = self._wav(16000)
        self.assertEqual(16000, decode_audio(path, target_sr=24000)[1], 'the trap: native rate')
        audio, rate = decode_audio_at(path, target_sr=24000)
        self.assertEqual((24000, 24000), (rate, len(audio)))

    def test_counter_check_a_wav_already_at_the_rate_is_untouched(self):
        from wama.common.utils.audio_decode import decode_audio_at
        audio, rate = decode_audio_at(self._wav(16000), target_sr=16000)
        self.assertEqual((16000, 16000), (rate, len(audio)))


class TheCatalogueResolvesThemTest(SimpleTestCase):
    """Three transcription backends now drive `transformers`: the model id decides."""

    def test_each_model_reaches_its_own_backend(self):
        from wama.common.backends.manager import backend_for_engine
        self.assertIs(FrWhisperBackend,
                      backend_for_engine('transformers', 'aihpi/FrWhisper', task='transcription'))
        self.assertIs(KyutaiSttBackend, backend_for_engine(
            'transformers', 'kyutai/stt-1b-en_fr-trfs', task='transcription'))

    def test_counter_check_qwen_keeps_its_models(self):
        from wama.common.backends.manager import backend_for_engine
        from wama.common.backends.qwen_asr_backend import QwenASRBackend
        self.assertIs(QwenASRBackend,
                      backend_for_engine('transformers', 'qwen3-asr-0.6b', task='transcription'))


class _Tokenizer:
    """SentencePiece-like: id → piece, `▁` opens a word."""
    PIECES = {10: '▁On', 11: '▁est', 12: '▁une', 13: '▁asso', 14: 'ciation', 15: '▁?'}
    all_special_ids = [0]

    def convert_ids_to_tokens(self, token_id):
        return self.PIECES.get(token_id)

    @staticmethod
    def convert_tokens_to_string(pieces):
        return ''.join(pieces).replace('▁', ' ')


class KyutaiTimedWordsTest(SimpleTestCase):
    """One token per 80 ms audio frame, behind the audio by the extractor's declared delay."""

    def _backend(self):
        backend = KyutaiSttBackend()
        backend._processor = SimpleNamespace(tokenizer=_Tokenizer())
        backend._model = SimpleNamespace(config=SimpleNamespace(pad_token_id=3, bos_token_id=48000))
        return backend

    def test_a_word_is_timed_by_the_frame_of_its_first_piece_minus_the_delay(self):
        ids = [48000, 3, 3, 10, 3, 11, 12, 3, 3, 13, 14, 3, 15]
        words = self._backend()._words(ids, 0.08, 0.5)
        self.assertEqual(['On', 'est', 'une', 'association', '?'], [w['word'] for w in words])
        association = words[3]
        self.assertEqual((0.22, 0.38), (association['start'], association['end']),
                         'frames 9 and 10, minus 0.5 s: two pieces, one word')

    def test_padding_and_the_start_token_carry_nothing_and_time_never_goes_negative(self):
        words = self._backend()._words([48000, 10, 3, 3], 0.08, 0.5)
        self.assertEqual([{'word': 'On', 'start': 0.0, 'end': 0.08}], words)


class _Inputs(dict):
    """What `WhisperProcessor(...)` returns: a mapping with `input_features` and `.to()`."""

    def __init__(self, frames):
        super().__init__(input_features=SimpleNamespace(shape=(1, 128, frames)))
        self.input_features = self['input_features']

    def to(self, *args):
        return self


class FrWhisperWindowsTest(SimpleTestCase):

    TEXTS = [' un peu', 'je crois ', '   ']

    def _run(self, language=None, seconds=65):
        """65 s of audio → three windows; the model says one text per window, the last empty."""
        import numpy as np
        backend = FrWhisperBackend()
        backend._loaded, backend._device, backend._dtype = True, 'cpu', None
        texts = iter(self.TEXTS)
        backend._processor = mock.Mock(side_effect=lambda *a, **k: _Inputs(3000),
                                       batch_decode=lambda out, **k: [next(texts)])
        backend._model = mock.Mock(generate=mock.Mock(return_value='tokens'))
        with mock.patch('wama.common.utils.audio_decode.decode_audio',
                        return_value=(np.zeros(16000 * seconds, dtype='float32'), 16000)):
            return backend, backend.transcribe('x.wav', language=language)

    def test_each_window_of_at_most_30_s_becomes_a_segment_and_they_rejoin_with_a_space(self):
        _, result = self._run()
        self.assertTrue(result.success, result.error)
        self.assertEqual('un peu je crois', result.text, 'decoded as one block they fused: « peuje »')
        spans = [(s.start_time, s.end_time) for s in result.segments]
        self.assertEqual(2, len(spans), 'the empty third window is dropped')
        self.assertEqual(spans[0][1], spans[1][0], 'contiguous windows')
        self.assertTrue(all(end - start <= 30.0 for start, end in spans), spans)

    def test_no_time_tokens_are_forced_and_the_language_reaches_the_decoding(self):
        """Forcing time tokens on this fine-tune made it STOP mid-window (2026-10-02: WER 82 %
        with, 56 % without, same 26 s extract)."""
        backend, _ = self._run(language='fr-FR')
        options = backend._model.generate.call_args.kwargs
        self.assertEqual(('fr', False), (options['language'], options['return_timestamps']))
        self.assertNotIn('return_segments', options)

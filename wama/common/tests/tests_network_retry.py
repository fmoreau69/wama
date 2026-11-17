"""La reprise d'un appel à une source externe après une panne PASSAGÈRE (`common/utils/network_retry`).

2026-11-17 : l'installation de `FluidVoice-Labs/fluid-speech-pro` a échoué en 0,9 s — le Hub n'a pas
répondu à cet instant (`LocalEntryNotFoundError`) — et la même demande, refaite trois minutes plus
tard, a tout téléchargé. Demande de Fabien : une nouvelle tentative automatique, avec une courte
pause. Ce que ces gardes tiennent : ce qui se reprend (et ce qui ne se reprend jamais), l'attente
que la source demande, le nombre de reprises, et l'adoption par les pilotes de la route.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.test import SimpleTestCase

from wama.common.utils import network_retry as nr


class _Response:
    def __init__(self, status, headers=None):
        self.status_code, self.headers = status, headers or {}


class _HttpError(Exception):
    def __init__(self, status, headers=None):
        super().__init__(f'HTTP {status}')
        self.response = _Response(status, headers)


class LocalEntryNotFoundError(Exception):
    """Le nom que lève `huggingface_hub` quand le Hub ne répond pas et qu'aucune copie n'existe."""


class ConnectTimeout(Exception):
    pass


@mock.patch('time.sleep')
class WhatIsRetriedTest(SimpleTestCase):

    def _flaky(self, *errors, result='done'):
        calls = []

        def call():
            calls.append(1)
            if len(calls) <= len(errors):
                raise errors[len(calls) - 1]
            return result
        return call, calls

    def test_a_hub_that_did_not_answer_is_asked_again_after_a_short_pause(self, sleep):
        call, calls = self._flaky(LocalEntryNotFoundError('cannot find the snapshot folder'))
        self.assertEqual('done', nr.with_retries(call, 'org/model'))
        self.assertEqual(2, len(calls))
        sleep.assert_called_once_with(nr.RETRY_WAITS_S[0])

    def test_the_pauses_grow_and_the_last_error_comes_back_as_it_was(self, sleep):
        errors = [ConnectTimeout('slow')] * (len(nr.RETRY_WAITS_S) + 1)
        call, calls = self._flaky(*errors)
        with self.assertRaises(ConnectTimeout):
            nr.with_retries(call, 'org/model')
        self.assertEqual(len(nr.RETRY_WAITS_S) + 1, len(calls))
        self.assertEqual([mock.call(w) for w in nr.RETRY_WAITS_S], sleep.call_args_list)

    def test_the_wait_the_source_asks_for_is_kept_and_capped(self, sleep):
        for asked, waited in (('3', 3.0), ('7200', float(nr.MAX_WAIT_S))):
            with self.subTest(asked):
                sleep.reset_mock()
                call, _ = self._flaky(_HttpError(429, {'Retry-After': asked}))
                nr.with_retries(call, 'org/model')
                sleep.assert_called_once_with(waited)

    def test_a_fault_of_the_request_is_never_retried(self, sleep):
        """Same request, same answer: a missing repository, a refused access, a 400."""
        for status in (400, 401, 403, 404):
            with self.subTest(status):
                call, calls = self._flaky(_HttpError(status))
                with self.assertRaises(_HttpError):
                    nr.with_retries(call, 'org/model')
                self.assertEqual(1, len(calls))
        call, calls = self._flaky(ValueError('bad spec'))
        with self.assertRaises(ValueError):
            nr.with_retries(call, 'org/model')
        self.assertEqual(1, len(calls))
        sleep.assert_not_called()

    def test_a_status_inside_a_connection_error_decides(self, sleep):
        """A 404 wrapped in a connection-looking error stays a 404; a 503 is transient."""
        wrapped = ConnectTimeout('wrapper')
        wrapped.__cause__ = _HttpError(404)
        self.assertEqual('', nr.transient_reason(wrapped))
        self.assertEqual('HTTP 503', nr.transient_reason(_HttpError(503)))

    def test_the_caller_is_told_while_it_waits(self, sleep):
        told = []
        call, _ = self._flaky(_HttpError(502))
        nr.with_retries(call, 'org/model', on_retry=lambda *a: told.append(a))
        self.assertEqual([(2, len(nr.RETRY_WAITS_S) + 1, nr.RETRY_WAITS_S[0], 'HTTP 502')], told)


@mock.patch('time.sleep')
class TheInstallDriversRetryTest(SimpleTestCase):
    """Chaque pilote de la route passe par la règle commune (`model_installer.retrying`)."""

    def test_the_hub_driver_takes_up_a_snapshot_the_hub_did_not_serve(self, sleep):
        from wama.model_manager.services import model_installer as mi
        attempts = []

        def snapshot_download(**kwargs):
            attempts.append(kwargs['repo_id'])
            if len(attempts) == 1:
                raise LocalEntryNotFoundError('Please check your internet connection')
            return '/models/snap'
        said = []
        meter = mock.Mock(say=said.append, measuring=mock.MagicMock())
        with TemporaryDirectory() as tmp, \
                mock.patch('wama.common.utils.model_locations.model_dir', return_value=Path(tmp)), \
                mock.patch('huggingface_hub.snapshot_download', side_effect=snapshot_download), \
                mock.patch.object(mi, 'format_duplicates', return_value=[]), \
                mock.patch.object(mi, 'verify_hf_snapshot',
                                  return_value={'ok': True, 'verified': {'against': 'published'}}):
            res = mi.pull_hf_model('Org/model', 'speech', meter=meter)
        self.assertTrue(res['ok'], res)
        self.assertEqual(2, len(attempts))
        self.assertTrue(any('nouvelle tentative 2/' in s for s in said), said)

    def test_a_download_taken_up_from_zero_counts_its_bytes_once(self, sleep):
        from wama.model_manager.services import model_installer as mi

        class Stream:
            def __init__(self, fail):
                self.fail = fail

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size):
                yield b'x' * 5
                if self.fail:
                    raise ConnectTimeout('cut')
                yield b'y' * 3
        streams = iter([Stream(True), Stream(False)])
        meter = mi.InstallMeter(lambda s: None, expected_bytes=8, every_s=0)
        with TemporaryDirectory() as tmp, mock.patch('requests.get', side_effect=lambda *a, **k: next(streams)):
            res = mi.download_asset('https://example.org/w.bin', str(Path(tmp) / 'w.bin'), meter=meter)
        self.assertTrue(res['ok'], res)
        self.assertEqual(8, meter.done, 'the cut attempt gave back what it had counted')

    def test_the_hub_reading_of_the_prospection_keeps_its_one_retry(self, sleep):
        from wama.model_manager.services import prospector
        calls = []

        def call():
            calls.append(1)
            raise _HttpError(429, {'Retry-After': '2'})
        with self.assertRaises(prospector.HubRateLimited):
            prospector._hub_call(call, 'org/model')
        self.assertEqual(2, len(calls))
        sleep.assert_called_once_with(2.0)

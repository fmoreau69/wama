"""What the route lays is checked against the strongest fingerprint its SOURCE gives (2026-11-05).

Fabien: « uniformité et universalité, du mieux possible quelle que soit la source ». The `files`
and `github` drivers checked a PINNED sha256 per file ; the `hf` driver delegated to
`huggingface_hub`, which checks only the SIZE of what it receives ; the `yolo` driver had a 1 MB
floor. Now:
  * hf     — each file of the revision pulled, against what the Hub PUBLISHES for it: the sha256
             of an LFS file, the git blob id of the others ;
  * yolo   — the `digest` the GitHub API publishes for the asset of the current release, whose
             real tag freezes the address ;
  * ollama — the daemon checks every layer itself: the result says so ;
and every result says what was verified (`verified`), which the install journal keeps.
The network is faked: no test downloads.
"""
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from wama.model_manager.services import model_installer as mi

REVISION = 'a' * 40
CONFIG = b'{"model_type": "whisper"}\n'
WEIGHTS = b'\x00ct2-weights' * 4096


def _sibling(name, body, lfs=False):
    """A file as `HfApi.model_info(files_metadata=True)` publishes it."""
    if lfs:
        return SimpleNamespace(rfilename=name, size=len(body), blob_id='f' * 40,
                               lfs={'size': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
                                    'pointer_size': 134})
    blob_id = hashlib.sha1(b'blob %d\0' % len(body) + body).hexdigest()
    return SimpleNamespace(rfilename=name, size=len(body), blob_id=blob_id, lfs=None)


class GitBlobIdTest(SimpleTestCase):
    """The common brick of file fingerprints (`common/utils/provenance`), beside `sha256_of`."""

    def test_the_id_is_the_one_git_computes(self):
        from wama.common.utils.provenance import git_blob_sha1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'hello'
            path.write_bytes(b'hello\n')
            # `printf 'hello\n' | git hash-object --stdin`
            self.assertEqual('ce013625030ba8dba906f756967f9e9ca394464a', git_blob_sha1(path))
            self.assertEqual('', git_blob_sha1(Path(tmp) / 'absent'), 'never raises')


class HubSnapshotIsVerifiedTest(SimpleTestCase):
    """`verify_hf_snapshot`: the layout the library leaves (`blobs/` + links under
    `snapshots/<commit>/`), confronted with what the Hub publishes for that commit."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        repo = Path(self.tmp) / 'models--org--x'
        self.snapshot = repo / 'snapshots' / REVISION
        self.snapshot.mkdir(parents=True)
        self.blob = repo / 'blobs' / hashlib.sha256(WEIGHTS).hexdigest()
        self.blob.parent.mkdir()
        self.blob.write_bytes(WEIGHTS)
        try:
            (self.snapshot / 'model.bin').symlink_to(self.blob)
        except OSError:                      # no symlink right: the library copies too
            shutil.copy(self.blob, self.snapshot / 'model.bin')
        (self.snapshot / 'config.json').write_bytes(CONFIG)

    def _published(self, config=CONFIG, weights=WEIGHTS):
        return [_sibling('config.json', config), _sibling('model.bin', weights, lfs=True),
                _sibling('README.md', b'# x\n')]

    def _verify(self, published):
        with patch('wama.model_manager.services.prospector.hub_files',
                   return_value=published) as hub:
            return mi.verify_hf_snapshot('org/x', self.snapshot, token=False), hub

    def test_files_matching_what_the_hub_publishes_pass(self):
        res, hub = self._verify(self._published())
        self.assertTrue(res['ok'], res)
        self.assertEqual({'against': 'published', 'count': 2}, res['verified'])
        self.assertEqual((('org/x',), {'revision': REVISION, 'token': False}),
                         (hub.call_args.args, hub.call_args.kwargs),
                         'the fingerprints of the revision pulled, read with the same token')

    def test_a_weight_differing_from_its_published_sha256_is_removed_and_refused(self):
        res, _hub = self._verify(self._published(weights=WEIGHTS + b'!'))
        self.assertFalse(res['ok'])
        self.assertIn('model.bin', res['error'])
        self.assertFalse(self.blob.exists(), 'the blob goes, like the `.part` of `download_asset`')
        self.assertFalse(os.path.lexists(self.snapshot / 'model.bin'))
        self.assertTrue((self.snapshot / 'config.json').exists(), 'a matching file stays')

    def test_a_small_file_is_checked_by_its_git_blob_id(self):
        res, _hub = self._verify(self._published(config=CONFIG.replace(b'whisper', b'whispeR')))
        self.assertFalse(res['ok'])
        self.assertIn('config.json', res['error'])
        self.assertFalse((self.snapshot / 'config.json').exists())
        self.assertTrue(self.blob.exists())

    def test_unreadable_fingerprints_refuse_and_remove_nothing(self):
        res, _hub = self._verify(None)
        self.assertFalse(res['ok'])
        self.assertIn('illisibles', res['error'])
        self.assertTrue(self.blob.exists() and (self.snapshot / 'config.json').exists())

    def test_a_file_unknown_to_the_revision_is_refused(self):
        (self.snapshot / 'extra.bin').write_bytes(b'0')
        res, _hub = self._verify(self._published())
        self.assertFalse(res['ok'])
        self.assertIn('extra.bin', res['error'])

    def test_a_folder_that_is_not_a_revision_is_refused_before_any_request(self):
        with patch('wama.model_manager.services.prospector.hub_files') as hub:
            res = mi.verify_hf_snapshot('org/x', self.tmp)
        self.assertFalse(res['ok'])
        hub.assert_not_called()

    def test_the_driver_rejects_what_the_check_rejects(self):
        with tempfile.TemporaryDirectory() as root, self.settings(AI_MODELS_DIR=root), \
                patch('huggingface_hub.snapshot_download', return_value=str(self.snapshot)), \
                patch.object(mi, 'format_duplicates', return_value=[]), \
                patch('wama.model_manager.services.prospector.hub_files',
                      return_value=self._published(weights=b'other')):
            res = mi.pull_hf_model('org/x', 'speech', family='whisper', token=False)
        self.assertEqual((False, 'fingerprint'), (res['ok'], res.get('reason')))

    def test_counter_proof_the_driver_says_what_it_verified(self):
        with tempfile.TemporaryDirectory() as root, self.settings(AI_MODELS_DIR=root), \
                patch('huggingface_hub.snapshot_download', return_value=str(self.snapshot)), \
                patch.object(mi, 'format_duplicates', return_value=[]), \
                patch('wama.model_manager.services.prospector.hub_files',
                      return_value=self._published()):
            res = mi.pull_hf_model('org/x', 'speech', family='whisper', token=False)
        self.assertTrue(res['ok'], res)
        self.assertEqual({'against': 'published', 'count': 2}, res['verified'])


#: The current release of `ultralytics/assets`, as the API publishes it (measured 2026-11-05:
#: v8.4.0, its 313 assets each carry a `digest`).
RELEASE = {'tag_name': 'v8.4.0', 'assets': [
    {'name': 'yolo11n-seg.pt', 'size': 6182636, 'digest': 'sha256:' + 'B' * 64},
    {'name': 'yolo11n.pt', 'size': 5613764, 'digest': None}]}


class YoloIsVerifiedAgainstThePublishedDigestTest(SimpleTestCase):

    def _pull(self, root, name='yolo11n-seg', release=RELEASE, download=None):
        with self.settings(AI_MODELS_DIR=root), \
                patch('wama.model_manager.services.prospector.github_release',
                      return_value=release) as api, \
                patch.object(mi, 'download_asset',
                             return_value=download or {'ok': True}) as dl:
            return mi.pull_yolo_weights(name), api, dl

    def test_the_asset_of_the_release_read_is_fetched_with_its_digest(self):
        from wama.common.external_sources import base_url
        with tempfile.TemporaryDirectory() as root:
            res, api, dl = self._pull(root)
        api.assert_called_once_with('ultralytics/assets:latest')
        self.assertEqual(f"{base_url('github')}/ultralytics/assets/releases/download/v8.4.0/"
                         'yolo11n-seg.pt', dl.call_args.args[0],
                         'the real tag freezes the address: « latest » may move meanwhile')
        self.assertEqual(('b' * 64, 1_000_000), (dl.call_args.kwargs['sha256'],
                                                 dl.call_args.kwargs['min_bytes']))
        self.assertEqual({'against': 'published', 'count': 1}, res['verified'])

    def test_without_a_published_digest_the_published_size_is_checked(self):
        with tempfile.TemporaryDirectory() as root:
            res, _api, dl = self._pull(root, name='yolo11n')
        self.assertEqual(('', 5613764), (dl.call_args.kwargs['sha256'], dl.call_args.kwargs['size']))
        self.assertEqual('size', res['verified']['against'])

    def test_an_unreadable_release_downloads_nothing(self):
        for release in (None, {}):
            with self.subTest(release=release), tempfile.TemporaryDirectory() as root:
                res, _api, dl = self._pull(root, release=release)
                self.assertFalse(res['ok'])
                dl.assert_not_called()

    def test_an_asset_absent_from_the_release_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            res, _api, dl = self._pull(root, name='yolo99z')
        self.assertIn('absent', res['error'])
        dl.assert_not_called()

    def test_a_file_in_place_is_confronted_with_the_published_digest(self):
        body = b'yolo-weights'
        release = {'tag_name': 'v8.4.0', 'assets': [
            {'name': 'yolo11n-seg.pt', 'size': len(body),
             'digest': 'sha256:' + hashlib.sha256(body).hexdigest()}]}
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'models' / 'vision' / 'yolo' / 'segment' / 'yolo11n-seg.pt'
            target.parent.mkdir(parents=True)
            target.write_bytes(body)
            same, _api, dl = self._pull(root, release=release)
            target.write_bytes(b'tampered')
            other, _api, _dl = self._pull(root, release=release)
        self.assertEqual((True, True), (same['ok'], same.get('already')))
        dl.assert_not_called()
        self.assertFalse(other['ok'])
        self.assertIn('AUTRE empreinte', other['error'])


class DownloadAssetChecksThePublishedSizeTest(SimpleTestCase):

    def test_a_size_differing_from_the_published_one_leaves_nothing(self):
        from .tests_github_install import PAYLOAD, _FakeResponse
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, 'x.pt')
            with patch('requests.get', return_value=_FakeResponse(PAYLOAD)):
                wrong = mi.download_asset('https://example/x.pt', target, size=len(PAYLOAD) + 1)
            self.assertEqual([], os.listdir(tmp))
            with patch('requests.get', return_value=_FakeResponse(PAYLOAD)):
                right = mi.download_asset('https://example/x.pt', target, size=len(PAYLOAD))
        self.assertFalse(wrong['ok'])
        self.assertIn('taille', wrong['error'])
        self.assertTrue(right['ok'], right)


class OllamaSaysTheDaemonVerifiedTest(SimpleTestCase):

    class _Stream:
        def __init__(self, lines):
            self.lines = lines

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            pass

        def iter_lines(self):
            return iter(self.lines)

    def _pull(self, lines):
        with patch('requests.post', return_value=self._Stream(lines)):
            return mi.pull_ollama_model('qwen3:4b')

    def test_the_daemons_check_is_reported(self):
        res = self._pull([b'{"status": "pulling manifest"}', b'{"status": "verifying sha256 digest"}',
                          b'{"status": "success"}'])
        self.assertEqual({'against': 'published', 'by': 'ollama'}, res['verified'])

    def test_counter_proof_nothing_is_claimed_when_the_daemon_did_not_say_it(self):
        res = self._pull([b'{"status": "success"}'])
        self.assertTrue(res['ok'])
        self.assertNotIn('verified', res)

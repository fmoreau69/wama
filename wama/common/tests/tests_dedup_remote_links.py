"""
`dedup_remote_links` — retirer du distant les copies pleines de liens de snapshot HF (2026-09-28).

Un fichier retiré à tort est une PERTE dans la seule archive ; un fichier gardé à tort n'est que
de la place. Ces tests tiennent donc d'abord ce qui doit être GARDÉ, puis l'aller-retour complet :
ce que le nettoyage retire, le tirage (`mirror_tree` du distant vers le local) doit le rendre.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from wama.common.management.commands.dedup_remote_links import apply, plan
from wama.common.services.mirror_sync import LINKS_MANIFEST, mirror_tree


def _can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.symlink('x', Path(tmp) / 'probe')
            return True
        except (OSError, NotImplementedError):
            return False


class RemoteDedupTest(SimpleTestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / 'remote'
        self.repo = self.root / 'diffusion' / 'fam' / 'models--Org--Name'
        (self.repo / 'blobs').mkdir(parents=True)
        self.snap = self.repo / 'snapshots' / 'rev'
        self.snap.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _classes(self, probe=64):
        return {e['path'].name: e['class'] for e in plan(self.root, probe=probe)}

    def test_a_full_copy_of_a_blob_is_matched_and_a_lookalike_is_kept(self):
        """Same size, different content: NOT a duplicate — deleting it would lose the only copy."""
        (self.repo / 'blobs' / 'abc').write_bytes(b'A' * 500)
        (self.snap / 'model.safetensors').write_bytes(b'A' * 500)
        (self.snap / 'lookalike.bin').write_bytes(b'A' * 499 + b'B')
        classes = self._classes()
        self.assertEqual('matched', classes['model.safetensors'])
        self.assertEqual('unique', classes['lookalike.bin'])

    def test_a_file_without_any_blob_of_its_size_is_kept(self):
        (self.repo / 'blobs' / 'abc').write_bytes(b'A' * 500)
        (self.snap / 'config.json').write_text('{"x": 1}')
        self.assertEqual('unique', self._classes()['config.json'])

    def test_two_blobs_that_both_match_make_it_ambiguous_and_kept(self):
        (self.repo / 'blobs' / 'one').write_bytes(b'A' * 500)
        (self.repo / 'blobs' / 'two').write_bytes(b'A' * 500)
        (self.snap / 'model.safetensors').write_bytes(b'A' * 500)
        self.assertEqual('ambiguous', self._classes()['model.safetensors'])

    def test_a_manifest_entry_pointing_at_a_missing_blob_is_kept(self):
        (self.snap / 'model.safetensors').write_bytes(b'A' * 500)
        rel = self.snap.relative_to(self.root) / 'model.safetensors'
        (self.root / LINKS_MANIFEST).write_text(json.dumps({rel.as_posix(): '../../blobs/gone'}))
        self.assertEqual('mismatch', self._classes()['model.safetensors'])

    def test_planning_alone_writes_and_removes_nothing(self):
        (self.repo / 'blobs' / 'abc').write_bytes(b'A' * 500)
        (self.snap / 'model.safetensors').write_bytes(b'A' * 500)
        plan(self.root, probe=64)
        self.assertTrue((self.snap / 'model.safetensors').exists())
        self.assertFalse((self.root / LINKS_MANIFEST).exists())

    @unittest.skipUnless(_can_symlink(), "symlinks unavailable on this host")
    def test_what_the_cleanup_removes_a_restore_gives_back(self):
        """Round trip: cleanup records the link, then removes; a restore recreates the link."""
        content = os.urandom(3000)
        (self.repo / 'blobs' / 'abc').write_bytes(content)
        (self.snap / 'model.safetensors').write_bytes(content)
        (self.snap / 'config.json').write_text('{"only": "copy"}')
        result = apply(self.root, plan(self.root, probe=256))
        self.assertEqual((1, 3000, 1), (result['removed'], result['freed_bytes'], result['linked']))
        self.assertTrue((self.snap / 'model.safetensors').is_symlink(),
                        "the full copy becomes a link to its blob")
        self.assertTrue((self.snap / 'config.json').exists(), "the only copy stays")
        self.assertEqual([], [e for e in plan(self.root, probe=256) if e['class'] == 'matched'],
                         "a second pass finds nothing left to clean")

        local = Path(self._tmp.name) / 'local'
        local.mkdir()
        mirror_tree(self.root, local)
        restored = local / self.snap.relative_to(self.root) / 'model.safetensors'
        self.assertTrue(restored.is_symlink())
        self.assertEqual(content, restored.read_bytes())
        self.assertEqual('{"only": "copy"}',
                         (local / self.snap.relative_to(self.root) / 'config.json').read_text())

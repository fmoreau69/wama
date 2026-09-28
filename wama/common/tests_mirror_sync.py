"""
`mirror_tree` et les liens symboliques INTERNES (2026-09-28).

Le miroir recopiait chaque poids d'un cache HuggingFace DEUX fois — le blob, puis le lien de
`snapshots/` qui le désigne (`is_file()` suit les liens) : 115 Go distants pour 54 Go locaux sur
qwen-image. Un lien vers un fichier DE la source est désormais décrit dans `LINKS_MANIFEST`, et
le tirage le recrée. Ces tests tiennent les deux sens — une sauvegarde qui ne se restaure pas
n'en est pas une.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from wama.common.services.mirror_sync import LINKS_MANIFEST, mirror_tree


def _can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.symlink('x', Path(tmp) / 'probe')
            return True
        except (OSError, NotImplementedError):
            return False


@unittest.skipUnless(_can_symlink(), "symlinks unavailable on this host (Windows without developer mode)")
class InternalLinksTest(SimpleTestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.src = self.base / 'src'
        self.dest = self.base / 'dest'
        self.dest.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _hf_snapshot(self, root: Path):
        """The real huggingface_hub layout: one blob, one snapshot link pointing at it."""
        repo = root / 'diffusion' / 'fam' / 'models--Org--Name'
        (repo / 'blobs').mkdir(parents=True)
        (repo / 'blobs' / 'abc').write_bytes(b'w' * 4096)
        (repo / 'snapshots' / 'rev').mkdir(parents=True)
        os.symlink('../../blobs/abc', repo / 'snapshots' / 'rev' / 'model.safetensors')
        return repo

    def test_an_internal_link_is_described_in_the_manifest_not_copied_again(self):
        repo = self._hf_snapshot(self.src)
        summary = mirror_tree(self.src, self.dest)
        rel_blob = repo.relative_to(self.src) / 'blobs' / 'abc'
        rel_link = (repo.relative_to(self.src) / 'snapshots' / 'rev' / 'model.safetensors').as_posix()
        self.assertTrue((self.dest / rel_blob).is_file(), "the blob itself is backed up")
        self.assertFalse((self.dest / rel_link).exists(), "the link must not become a second copy")
        manifest = json.loads((self.dest / LINKS_MANIFEST).read_text(encoding='utf-8'))
        self.assertEqual({rel_link: '../../blobs/abc'}, manifest)
        self.assertEqual((1, 1, 1), (summary['copied'], summary['linked'], summary['total_files']))
        self.assertTrue(summary['success'])

    def test_a_restore_recreates_the_link_and_ignores_an_old_full_copy(self):
        """Pull direction (`restore_backup`): the remote holds the blob, the manifest, AND the full
        copy an older backup left at the link's path. The link comes back as a LINK — the old
        full copy is not pulled, or the restore would double the local disk."""
        backup = self.base / 'backup'
        repo = self._hf_snapshot(self.src)
        backup.mkdir()
        mirror_tree(self.src, backup)
        rel_link = repo.relative_to(self.src) / 'snapshots' / 'rev' / 'model.safetensors'
        (backup / rel_link).parent.mkdir(parents=True, exist_ok=True)
        (backup / rel_link).write_bytes(b'w' * 4096)          # the pre-fix duplicate
        summary = mirror_tree(backup, self.dest)
        restored = self.dest / rel_link
        self.assertTrue(restored.is_symlink(), "the snapshot entry must be a link again")
        self.assertEqual(b'w' * 4096, restored.read_bytes(), "and it must reach the blob")
        self.assertEqual(1, summary['copied'], "only the blob travels")
        self.assertFalse((self.dest / LINKS_MANIFEST).exists(), "the manifest describes, it is not restored")

    def test_a_link_pointing_outside_the_source_is_still_copied(self):
        """No other copy of an EXTERNAL target exists in the archive: its content must travel."""
        outside = self.base / 'elsewhere.bin'
        outside.write_bytes(b'e' * 100)
        self.src.mkdir()
        os.symlink(outside, self.src / 'pointer.bin')
        summary = mirror_tree(self.src, self.dest)
        self.assertEqual(b'e' * 100, (self.dest / 'pointer.bin').read_bytes())
        self.assertEqual(0, summary['linked'])
        self.assertFalse((self.dest / LINKS_MANIFEST).exists())

    def test_the_manifest_is_merged_never_rewritten_empty(self):
        """The archive is cumulative: an entry written by an earlier backup stays."""
        (self.dest / LINKS_MANIFEST).write_text(json.dumps({'old/link': '../blob'}), encoding='utf-8')
        repo = self._hf_snapshot(self.src)
        mirror_tree(self.src, self.dest)
        manifest = json.loads((self.dest / LINKS_MANIFEST).read_text(encoding='utf-8'))
        self.assertIn('old/link', manifest)
        self.assertIn((repo.relative_to(self.src) / 'snapshots' / 'rev' / 'model.safetensors').as_posix(),
                      manifest)

    def test_a_dry_run_counts_links_and_writes_nothing(self):
        self._hf_snapshot(self.src)
        summary = mirror_tree(self.src, self.dest, dry_run=True)
        self.assertEqual(1, summary['linked'])
        self.assertEqual([], [p for p in self.dest.iterdir() if p.name != '.wama_test'])

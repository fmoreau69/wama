"""Un fichier DÉPOSÉ au converter — par un visiteur sans compte, l'app est publique — ne fait
rien lire ni écrire au serveur hors de son dossier de travail (2026-11-06, audit de sécurité ;
chaque garde a été rouge avant son correctif) :

  - une archive dont un membre sort du dossier d'extraction est REFUSÉE ; un lien symbolique
    déposé par l'extraction est retiré, le réempaquetage ne suit aucun lien ;
  - le HTML rendu en PDF n'a ni origine `file://`, ni script, ni accès au réseau — Chromium comme
    WeasyPrint (`inline_only_fetcher`) ;
  - pandoc tourne en `--sandbox`, le moteur TeX ne lit que sous le dossier courant.
"""
import io
import os
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from wama.converter.backends.archive_backend import (HostileArchive, _check_member_names,
                                                     _extract_to, _repack)


class HostileArchivesTest(SimpleTestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='wama_hostile_')
        self.addCleanup(shutil.rmtree, self.root, True)
        self.dest = os.path.join(self.root, 'work', 'extract')
        os.makedirs(self.dest)
        self.secret = os.path.join(self.root, 'secret.txt')
        Path(self.secret).write_text('OUTSIDE', encoding='utf-8')

    def _tar(self, name, members):
        path = os.path.join(self.root, name)
        import time
        with tarfile.open(path, 'w') as tf:
            for member, payload in members:
                member.mtime = int(time.time())      # un zip refuse une date d'avant 1980
                if payload is None:
                    tf.addfile(member)
                else:
                    member.size = len(payload)
                    tf.addfile(member, io.BytesIO(payload))
        return path

    def test_a_member_escaping_the_folder_rejects_the_whole_archive(self):
        src = self._tar('escape.tar', [(tarfile.TarInfo('../escaped.txt'), b'x')])
        with self.assertRaises(HostileArchive):
            _extract_to(src, self.dest)
        self.assertFalse(os.path.exists(os.path.join(self.root, 'work', 'escaped.txt')))

    def test_a_link_pointing_outside_rejects_the_archive(self):
        link = tarfile.TarInfo('link.txt')
        link.type = tarfile.SYMTYPE
        link.linkname = self.secret
        src = self._tar('link_out.tar', [(link, None)])
        with self.assertRaises(HostileArchive):
            _extract_to(src, self.dest)
        self.assertFalse(os.path.lexists(os.path.join(self.dest, 'link.txt')))

    def test_a_link_inside_is_dropped_and_never_followed_when_repacking(self):
        link = tarfile.TarInfo('link.txt')
        link.type = tarfile.SYMTYPE
        link.linkname = 'inner.txt'
        src = self._tar('link_in.tar', [(tarfile.TarInfo('inner.txt'), b'inner'), (link, None)])
        _extract_to(src, self.dest)
        self.assertFalse(os.path.lexists(os.path.join(self.dest, 'link.txt')))
        out = os.path.join(self.root, 'out.zip')
        _repack(self.dest, out, 'zip')
        with zipfile.ZipFile(out) as zf:
            self.assertEqual(zf.namelist(), ['inner.txt'])

    def test_a_plain_archive_still_converts(self):
        src = self._tar('plain.tar', [(tarfile.TarInfo('a/b.txt'), b'ok')])
        _extract_to(src, self.dest)
        self.assertEqual(Path(self.dest, 'a', 'b.txt').read_text(encoding='utf-8'), 'ok')

    def test_member_names_of_the_other_formats_are_judged_before_extraction(self):
        for hostile in (['/etc/passwd'], ['a/../b'], ['C:/x'], ['..\\x']):
            with self.assertRaises(HostileArchive, msg=hostile):
                _check_member_names(hostile)
        _check_member_names(['a/b.txt', 'c'])          # rien à redire


class DocumentsReadNothingTest(SimpleTestCase):

    def test_weasyprint_fetches_only_inline_resources(self):
        from wama.common.utils.html_render import inline_only_fetcher
        for url in ('file:///etc/passwd', 'http://127.0.0.1:8001/health', 'https://example.org/x'):
            with self.assertRaises(ValueError, msg=url):
                inline_only_fetcher(url)
        try:
            import weasyprint  # noqa: F401
        except ImportError:
            self.skipTest('WeasyPrint absent')
        got = inline_only_fetcher('data:text/plain;base64,aGVsbG8=')
        content = got.read() if hasattr(got, 'read') else got['string']     # WeasyPrint 69 / ≤ 62
        self.assertEqual(content, b'hello')

    def test_chromium_renders_a_document_without_disk_or_network(self):
        from wama.common.utils import html_render
        try:
            import playwright  # noqa: F401
        except ImportError:
            self.skipTest('Playwright absent')
        root = tempfile.mkdtemp(prefix='wama_html_')
        self.addCleanup(shutil.rmtree, root, True)
        secret = Path(root, 'secret.txt')
        secret.write_text('TEMOIN-SECRET-' * 3, encoding='utf-8')
        page = Path(root, 'doc.html')
        page.write_text(
            '<html><body><h1>Titre visible</h1>'
            f'<iframe src="file://{secret.as_posix()}" width="600" height="300"></iframe>'
            '<img src="http://127.0.0.1:1/x.png"><script>document.title="JS-RAN";'
            'document.body.innerHTML+="<p>TEMOIN-SCRIPT</p>"</script></body></html>',
            encoding='utf-8')
        out = Path(root, 'doc.pdf')
        if not html_render._html_to_pdf_chromium(str(page), str(out)):
            self.skipTest('Chromium indisponible ici')
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF absent pour relire le PDF')
        text = ''.join(p.get_text() for p in fitz.open(str(out)))
        self.assertIn('Titre visible', text)
        self.assertNotIn('TEMOIN-SECRET', text, 'une iframe file:// a été rendue')
        self.assertNotIn('TEMOIN-SCRIPT', text, 'un script du document a tourné')

    def test_pandoc_runs_in_its_sandbox(self):
        from wama.converter.backends import document_backend
        root = tempfile.mkdtemp(prefix='wama_pandoc_')
        self.addCleanup(shutil.rmtree, root, True)
        src = Path(root, 'in.md')
        src.write_text('# Titre', encoding='utf-8')
        previous = os.environ.pop('openin_any', None)
        self.addCleanup(lambda: os.environ.update({'openin_any': previous}) if previous is not None
                        else os.environ.pop('openin_any', None))
        with mock.patch('pypandoc.convert_file') as convert, \
                mock.patch('os.path.exists', return_value=True):
            document_backend.convert_document(str(src), str(Path(root, 'out.txt')), 'txt')
        self.assertIn('--sandbox', convert.call_args.kwargs['extra_args'])
        self.assertEqual(os.environ.get('openin_any'), 'p')

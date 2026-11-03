"""The DOCUMENT domain of the Anonymizer (2026-11-02, ROADMAP §16.4bis): the personal data of a
document, detected in its text and blacked out in the file itself, its form kept.

Nothing new is invented: the domain is a DECLARATION (`app_modes`, its own schema), the element is
the same `Media` (its nature puts it in the domain, read by the detail spec), the gate is the
common one of its surface, and its three processes live in the app's single pipeline, each one
reserved to its domain by `ProcessSpec.applies` — the OCR process is the common one
(`ocr_process`), detection and blacking out are the privacy brick on the common text layer.
"""
import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

User = get_user_model()


def _scanned_pdf(path):
    """A one-page PDF without a text layer (an image of a text): the OCR proposes itself."""
    import fitz
    with fitz.open() as native:
        page = native.new_page()
        page.insert_text((72, 100), 'Contact: Anne Martin, anne.martin@exemple.fr', fontsize=11)
        pixmap, size = page.get_pixmap(dpi=100), page.rect
    with fitz.open() as pdf:
        pdf.new_page(width=size.width, height=size.height).insert_image(
            fitz.Rect(0, 0, size.width, size.height), pixmap=pixmap)
        pdf.save(str(path))


def _native_pdf(path, text='Écrire à anne.martin@exemple.fr pour toute question.'):
    import fitz
    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 100), text, fontsize=11)
        pdf.save(str(path))


class DocumentDomainDeclarationTest(SimpleTestCase):

    def test_the_anonymizer_has_a_document_domain_with_its_own_schema(self):
        from wama.common.utils.app_modes import accepts, domain_schema, get_domains
        self.assertEqual(['image_video', 'document'], [d['id'] for d in get_domains('anonymizer')])
        self.assertEqual(('document',), accepts('anonymizer', 'document'))
        [ocr] = domain_schema('anonymizer', 'document')
        self.assertEqual('ocr_scanned_pages', ocr['name'])
        self.assertEqual({'port': 'work_file', 'property': 'needs_ocr'}, ocr['default_from'])

    def test_a_media_is_in_the_domain_of_its_nature(self):
        from wama.anonymizer.models import Media
        from wama.common.utils.app_modes import element_domain
        self.assertEqual('document', element_domain(Media(media_type='document')))
        for nature in ('image', 'video'):
            self.assertEqual('image_video', element_domain(Media(media_type=nature)))

    def test_the_document_formats_are_those_the_text_layer_rewrites_in_their_form(self):
        """`.txt` and `.md` are left out on purpose: here they are BATCH descriptors."""
        from wama.common.app_registry import APP_CATALOG
        from wama.common.utils.document_text import SUPPORTED_EXTS
        declared = {e for e in APP_CATALOG['anonymizer']['input_extensions']
                    if e in SUPPORTED_EXTS}
        self.assertEqual({'.pdf', '.docx'}, declared)


class TheGateIsTheCommonOneTest(SimpleTestCase):
    """`_check_media_type` reads the gate of its surface (`app_modes.surface_file_nature`): a
    hand-written MIME list refused every document — and `.webp`, `.webm`, `.tif` that the drop
    zone offered."""

    def test_a_document_passes_and_says_its_nature(self):
        from wama.anonymizer.views import _check_media_type
        self.assertEqual('document', _check_media_type('lettre.pdf'))
        self.assertEqual('document', _check_media_type('lettre.docx'))
        self.assertEqual('image', _check_media_type('photo.webp'))
        self.assertEqual('video', _check_media_type('clip.webm'))

    def test_what_the_app_does_not_accept_is_refused(self):
        from wama.anonymizer.views import _check_media_type
        for name in ('notes.txt', 'archive.zip', 'x.xyz'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                _check_media_type(name)


class EachDomainHasItsProcessesTest(SimpleTestCase):
    """One pipeline per app; each process takes place for ITS domain (`ProcessSpec.applies`)."""

    def _keys(self, media):
        from wama.anonymizer.function_specs import PIPELINE
        return [spec.key for spec in PIPELINE.applicable(media)]

    def test_a_document_goes_through_ocr_detection_and_blacking_out(self):
        from wama.anonymizer.models import Media
        self.assertEqual(['ocr', 'detect_text', 'occult_text'],
                         self._keys(Media(media_type='document', ocr_scanned_pages=True)))
        # The OCR is OPTIONAL, with its switch: off, the text layer alone is read.
        self.assertEqual(['detect_text', 'occult_text'],
                         self._keys(Media(media_type='document', ocr_scanned_pages=False)))

    def test_an_image_or_a_video_keeps_detection_blur_and_output(self):
        from wama.anonymizer.models import Media
        for nature in ('image', 'video'):
            with self.subTest(nature=nature):
                self.assertEqual(['detect', 'blur', 'output'],
                                 self._keys(Media(media_type=nature, ocr_scanned_pages=True)))


class TheBatchModalOpensOnTheDomainOfItsBatchTest(SimpleTestCase):
    """The ⚙ of a batch opens the schema of ITS domain: one opener per declared domain, which the
    common brick picks by the button's `data-domain` (`onBatchSettings(fn, {domain})`) — the app
    does not read the DOM for it (the revérification of 2026-11-02 found that reading)."""

    def test_the_page_script_has_one_opener_per_domain(self):
        from pathlib import Path
        from django.conf import settings
        from wama.common.utils.app_modes import get_domains
        code = (Path(settings.BASE_DIR) / 'wama' / 'anonymizer' / 'static' / 'anonymizer' / 'js'
                / 'queue.js').read_text(encoding='utf-8')
        for domain in get_domains('anonymizer'):
            with self.subTest(domain=domain['id']):
                self.assertIn(f"{{ domain: '{domain['id']}' }}", code)
        self.assertNotIn("closest('[data-domain]')", code)


class DocumentBirthTest(TestCase):
    """A deposited document is BORN in its domain, with its domain's schema — and the file
    proposes the OCR (`Param.default_from`, `needs_ocr`): a scan ticks it, a native PDF does not."""

    #: The work port as production derives it (measured 2026-11-02, `file_ports_for('anonymizer',
    #: 'document')`): the ports come from the catalogue's models, which the test base lacks — it
    #: falls back on a port named `work`, that no `default_from` names.
    WORK_PORT = [{'id': 'work_file', 'group': 'travail', 'types': ['image', 'video', 'document']}]

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.enterContext(override_settings(MEDIA_ROOT=self.root))
        self.enterContext(mock.patch('wama.common.app_registry.file_ports_for',
                                     return_value=self.WORK_PORT))
        self.user = User.objects.create_user('doc_birth', password='x')

    def _born(self, name, write):
        from wama.anonymizer.models import Media
        from wama.anonymizer.views import process_media
        folder = os.path.join(self.root, 'in')
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        write(path)
        result = process_media(path, self.user)
        self.assertIsInstance(result, dict, result)
        return Media.objects.get(pk=result['id'])

    def test_a_scan_is_born_a_document_with_its_ocr_ticked(self):
        media = self._born('scan.pdf', _scanned_pdf)
        self.assertEqual('document', media.media_type)
        self.assertTrue(media.ocr_scanned_pages)

    def test_a_native_pdf_is_born_a_document_without_ocr(self):
        media = self._born('lettre.pdf', _native_pdf)
        self.assertEqual('document', media.media_type)
        self.assertFalse(media.ocr_scanned_pages)

    def _upload(self, name):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse
        path = os.path.join(self.root, 'source.pdf')
        _native_pdf(path)
        with open(path, 'rb') as fh:
            upload = SimpleUploadedFile(name, fh.read(), content_type='application/pdf')
        # An account that may open the Anonymizer (a plain one is redirected by its gate).
        self.uploader = User.objects.create_user('doc_upload', password='x', is_staff=True,
                                                 is_superuser=True)
        self.client.force_login(self.uploader)
        return self.client.post(reverse('anonymizer:upload'), {'file': upload})

    def _inputs(self):
        folder = os.path.join(self.root, 'users', str(self.uploader.id), 'anonymizer', 'input')
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    def test_a_long_file_name_is_imported_whole(self):
        # 91 characters (#2297's neighbour, 2026-11-03): the path did not fit in 100.
        name = ('Can_Iron_Replace_Natural_Gas_Driss_Laraqui_Fenix_Energy_youtube_transcript_'
                'whisper_172.pdf')
        response = self._upload(name)
        self.assertEqual(200, response.status_code, response.content)
        from wama.anonymizer.models import Media
        self.assertEqual(name, os.path.basename(Media.objects.get(user=self.uploader).file.name))

    def test_a_rejected_upload_leaves_no_copy_on_disk(self):
        with mock.patch('wama.anonymizer.views.process_media', return_value='rejected'):
            response = self._upload('rejected.pdf')
        self.assertEqual(400, response.status_code)
        self.assertEqual([], self._inputs())


class DocumentGluesTest(TestCase):
    """The two glues of the document, end to end on a real file — the detection by the PATTERN
    detectors only (no model loaded here): the e-mail address is found, then blacked out in the
    file itself, which is re-read."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.enterContext(override_settings(MEDIA_ROOT=self.root))
        self.user = User.objects.create_user('doc_glue', password='x')

    def test_the_address_is_detected_then_blacked_out_in_the_pdf(self):
        import fitz
        from wama.anonymizer import tasks
        from wama.anonymizer.models import Media
        from wama.common.privacy import engine
        from wama.common.utils.task_skeleton import TaskContext
        os.makedirs(os.path.join(self.root, 'in'))
        _native_pdf(os.path.join(self.root, 'in', 'lettre.pdf'))
        media = Media.objects.create(user=self.user, file='in/lettre.pdf', file_ext='.pdf',
                                     media_type='document')
        ctx = TaskContext('anonymizer', Media, media)
        patterns_only = lambda path, language='', ocr=None, **kw: engine.detect_file(   # noqa: E731
            path, language, ocr=ocr, detectors=())
        with mock.patch('wama.common.privacy.service_client.detect_file', patterns_only):
            found = tasks._detect_text(media, ctx)
        self.assertEqual('1 passage(s)', found['label'])
        media.detections_file.name = found['fields']['detections_file']
        done = tasks._occult_text(media, ctx)
        self.assertTrue(done['fields']['output_file'].endswith('.pdf'), done)
        with fitz.open(os.path.join(self.root, done['fields']['output_file'])) as pdf:
            text = pdf[0].get_text()
        self.assertNotIn('anne.martin@exemple.fr', text)
        self.assertIn('Écrire à', text)                    # the rest of the text is kept


class AStartingPrivacyServiceIsWaitedForTest(SimpleTestCase):
    """2026-11-02, document #2297 : the privacy service was loading its detectors after a restart,
    and the task failed « délai dépassé (180 s) ». A service that says it is loading makes the task
    WAIT (`ServiceNotReady`, re-delivered by the common skeleton) — the TTS service's policy."""

    def test_the_detection_glue_waits_for_a_loading_service(self):
        from wama.anonymizer import tasks
        from wama.anonymizer.models import Media
        from wama.common.privacy.service_client import PrivacyServiceLoading
        from wama.common.utils.task_skeleton import ServiceNotReady
        media = Media(media_type='document', file='in/lettre.pdf', user=User(pk=1, username='x'))
        with mock.patch('wama.common.privacy.service_client.detect_file',
                        side_effect=PrivacyServiceLoading('loading')),                 mock.patch('wama.common.services.ocr_process.read_ocr_file', return_value=None),                 mock.patch.object(type(media.file), 'path', new_callable=mock.PropertyMock,
                                  return_value='/x/lettre.pdf'),                 mock.patch.object(tasks, '_console'):
            with self.assertRaises(ServiceNotReady) as caught:
                tasks._detect_text(media, mock.Mock())
        self.assertGreaterEqual(caught.exception.countdown * caught.exception.max_attempts, 300)

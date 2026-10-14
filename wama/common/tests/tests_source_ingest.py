"""L'entrée d'une card créée avec une URL — téléchargée DÈS LA CRÉATION, hors requête.

Décision de Fabien du 2026-10-13, après le constat Describer #1923 (une page GitHub ajoutée par
URL : « le fichier d'entrée n'a pas été généré » — il ne l'était qu'au lancement) :
  - UN fonctionnement pour toutes les apps, sans seuil de taille : le récepteur commun met en
    file `common.ingest_source` à la création ; le lancement rattrape ou attend ;
  - une page web est gardée en `.html` ;
  - la nature d'une URL AVANT téléchargement vient de la table de décision existante
    (`url_ingest` : plateformes, extension) — réutilisée, pas réécrite.
Cartographie et mesures : `MEDIA_STORAGE_TIERING §8.2` note 7, `§8.3`.
"""
import os
import shutil
import tempfile
from unittest import mock

from django.apps import apps as django_apps
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from wama.common.utils import source_ingest, url_ingest
from wama.common.utils.url_guard import UrlRefusee


class _Hop:
    def __init__(self, url):
        self.url = url


class _Response:
    def __init__(self, url, content=b'', headers=None, history=()):
        self.url = url
        self.content = content
        self.text = content.decode('utf-8', 'replace')
        self.headers = headers or {}
        self.history = [_Hop(u) for u in history]

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=8192):
        yield self.content


def _refuse_private(url):
    """Garde de test : refuse le réseau interne sans résoudre de DNS (aucune sortie réseau)."""
    if '://10.' in url or '://127.' in url:
        raise UrlRefusee(f"Cible interdite (adresse privée (réseau interne)) : {url}")
    return url


class UrlNatureTest(SimpleTestCase):
    """La nature d'une URL connaissable AVANT de la télécharger."""

    def test_a_video_platform_is_a_video_and_a_sound_platform_is_audio(self):
        self.assertEqual(url_ingest.url_nature('https://www.youtube.com/watch?v=abc'), 'video')
        self.assertEqual(url_ingest.url_nature('https://youtu.be/abc'), 'video')
        self.assertEqual(url_ingest.url_nature('https://soundcloud.com/a/b'), 'audio')

    def test_an_extension_gives_the_common_category(self):
        self.assertEqual(url_ingest.url_nature('https://x.org/a/film.MP4?t=3'), 'video')
        self.assertEqual(url_ingest.url_nature('https://x.org/page.html'), 'document')

    def test_a_path_without_extension_is_unknown_until_downloaded(self):
        self.assertEqual(url_ingest.url_nature('https://github.com/turgu1/uPDF'), '')

    def test_the_platform_is_read_on_the_host_not_anywhere_in_the_url(self):
        self.assertFalse(url_ingest.is_media_platform('https://example.org/?ref=youtube.com'))
        self.assertTrue(url_ingest.is_media_platform('https://m.youtube.com/watch?v=abc'))


class WebPageIsKeptAsHtmlTest(SimpleTestCase):
    """Une page web est gardée TELLE QUELLE — plus convertie en texte à l'import."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_a_github_page_lands_as_its_original_html(self):
        page = b'<!DOCTYPE html><html><head><title>uPDF</title></head><body>README</body></html>'
        head = _Response('https://github.com/turgu1/uPDF', headers={'Content-Type': 'text/html'})
        get = _Response('https://github.com/turgu1/uPDF', content=page)
        with mock.patch('wama.common.utils.url_guard.verifier_url', side_effect=_refuse_private), \
                mock.patch('requests.head', return_value=head), \
                mock.patch('requests.get', return_value=get):
            path = url_ingest.fetch_url_content('https://github.com/turgu1/uPDF', self.dir)
        self.assertEqual(os.path.basename(path), 'turgu1_uPDF.html')
        with open(path, 'rb') as fh:
            self.assertEqual(fh.read(), page)

    def test_a_download_without_extension_that_is_a_page_is_named_html(self):
        raw = os.path.join(self.dir, 'download')
        with open(raw, 'wb') as fh:
            fh.write(b'<!doctype html><html><body>x</body></html>')
        with mock.patch('wama.common.utils.url_guard.verifier_url', side_effect=_refuse_private), \
                mock.patch('requests.head', side_effect=OSError('pas de HEAD')), \
                mock.patch('wama.common.utils.video_utils.upload_media_from_url', return_value=raw):
            path = url_ingest.fetch_url_content('https://example.org/a/page', self.dir)
        self.assertEqual(os.path.basename(path), 'a_page.html')


class GenericDownloadRevalidatesRedirectsTest(SimpleTestCase):
    """Le téléchargement générique re-valide chaque redirection — comme la lecture de page.
    Avant le 2026-10-13, une adresse publique pouvait y rediriger le serveur vers l'interne."""

    def test_a_redirect_to_the_internal_network_is_refused_as_such(self):
        from wama.common.utils.video_utils import upload_media_from_url
        hijacked = _Response('http://10.0.0.5/secret', content=b'x',
                             history=['https://example.org/file.bin'])
        with mock.patch('wama.common.utils.url_guard.verifier_url', side_effect=_refuse_private), \
                mock.patch('requests.get', return_value=hijacked):
            with self.assertRaises(UrlRefusee):
                upload_media_from_url('https://example.org/file.bin', tempfile.gettempdir())

    def test_public_redirects_still_download(self):
        from wama.common.utils.video_utils import upload_media_from_url
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        ok = _Response('https://cdn.example.org/file.bin', content=b'abc',
                       history=['https://example.org/file.bin'])
        with mock.patch('wama.common.utils.url_guard.verifier_url', side_effect=_refuse_private), \
                mock.patch('requests.get', return_value=ok):
            path = upload_media_from_url('https://example.org/file.bin', d)
        with open(path, 'rb') as fh:
            self.assertEqual(fh.read(), b'abc')


class EveryIngestingModelIsWiredTest(SimpleTestCase):
    """Le récepteur est branché sur TOUT modèle qui déclare `WAMA_INGEST` — aucune app n'écrit
    rien. Et un `derive` déclaré se résout (sinon la nature ne serait jamais posée)."""

    def _models(self):
        return [m for m in django_apps.get_models() if getattr(m, 'WAMA_INGEST', None)]

    def test_each_model_declaring_an_ingest_receives_the_receiver(self):
        from django.db.models.signals import post_save
        for model in self._models():
            spec = model.WAMA_INGEST
            if not any(f.name == spec.get('source', 'source_url') for f in model._meta.get_fields()):
                continue
            with self.subTest(model=model._meta.label):
                self.assertTrue(post_save.has_listeners(model))
                self.assertIn(model, source_ingest._connected)

    def test_each_declared_derive_resolves_to_a_function(self):
        for model in self._models():
            path = model.WAMA_INGEST.get('derive')
            if path:
                with self.subTest(model=model._meta.label):
                    self.assertTrue(callable(source_ingest._declared_derive(model.WAMA_INGEST)))

    def test_the_four_apps_with_their_own_fields_declare_their_derive(self):
        from wama.anonymizer.models import Media
        from wama.converter.models import ConversionJob
        from wama.describer.models import Description
        from wama.enhancer.models import Enhancement
        for model in (Media, ConversionJob, Description, Enhancement):
            with self.subTest(model=model._meta.label):
                self.assertIn('derive', model.WAMA_INGEST)


class _UserCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        cls.user = get_user_model().objects.create_superuser(
            username='source_ingest_test', email='si@test.local', password='x')

    def setUp(self):
        cache.clear()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, True)
        over = override_settings(MEDIA_ROOT=self.media)
        over.enable()
        self.addCleanup(over.disable)
        # La console de l'utilisateur écrit aussi `logs/wama-console.log` : hors des tests.
        quiet = mock.patch('wama.common.utils.console_utils.push_console_line')
        quiet.start()
        self.addCleanup(quiet.stop)

    def _description(self, url):
        from wama.describer.models import Description
        return Description.objects.create(user=self.user, source_url=url, filename='x')


class CreationSchedulesTheDownloadTest(_UserCase):
    """Une card qui NAÎT avec une URL voit son téléchargement mis en file, une seule fois."""

    def test_a_card_born_with_an_url_is_queued_once_after_commit(self):
        with mock.patch('wama.common.tasks.ingest_source_task.delay') as delay, \
                self.captureOnCommitCallbacks(execute=True):
            d = self._description('https://github.com/turgu1/uPDF')
            d.status = 'PENDING'
            d.save(update_fields=['status'])
            d.save()
        delay.assert_called_once_with('describer', 'description', d.pk)

    def test_a_server_path_is_not_a_download(self):
        with mock.patch('wama.common.tasks.ingest_source_task.delay') as delay, \
                self.captureOnCommitCallbacks(execute=True):
            self._description('users/1/temp/a.mp4')
        delay.assert_not_called()


class CreationDownloadTest(_UserCase):
    """Le téléchargement de création : fichier posé, champs de l'app par le `derive` DÉCLARÉ."""

    def _fake_download(self, name, content=b'<!DOCTYPE html><html></html>'):
        def download(url, mode, dest_dir):
            path = os.path.join(dest_dir, name)
            with open(path, 'wb') as fh:
                fh.write(content)
            return path, ''
        return download

    def test_a_web_page_becomes_an_html_input_typed_document(self):
        d = self._description('https://github.com/turgu1/uPDF')
        with mock.patch.object(source_ingest, '_download', self._fake_download('turgu1_uPDF.html')):
            name = source_ingest.ingest_now(d)
        d.refresh_from_db()
        self.assertEqual(name, 'turgu1_uPDF.html')
        self.assertTrue(d.input_file.name.endswith('.html'))
        self.assertEqual(d.detected_type, 'document')
        self.assertGreater(d.file_size, 0)
        self.assertIsNone(source_ingest.ingest_state(d))

    def test_a_video_url_gets_its_video_nature_from_the_declared_derive(self):
        d = self._description('https://www.youtube.com/watch?v=abc')
        with mock.patch.object(source_ingest, '_download', self._fake_download('clip.mp4', b'0')):
            source_ingest.ingest_now(d)
        d.refresh_from_db()
        self.assertEqual(d.detected_type, 'video')

    def test_a_refused_url_is_remembered_and_said_on_the_card_entry(self):
        from wama.common.utils import preview_utils
        d = self._description('http://127.0.0.1/temoin.html')
        pending = preview_utils._input_preview('describer', d, RequestFactory().get('/'))
        self.assertIn('Téléchargement en cours', pending['content'])
        refused = UrlRefusee('Cible interdite (adresse de bouclage) : 127.0.0.1')
        with mock.patch.object(source_ingest, '_download', side_effect=refused):
            self.assertIsNone(source_ingest.ingest_now(d))
        self.assertEqual(source_ingest.ingest_state(d)['state'], 'failed')
        face = preview_utils._input_preview('describer', d, RequestFactory().get('/'))
        self.assertIn('Échec du téléchargement', face['content'])
        self.assertIn('http://127.0.0.1/temoin.html', face['content'])

    def test_the_launch_waits_for_a_running_download_instead_of_doing_it_twice(self):
        from wama.describer.models import Description
        d = self._description('https://github.com/turgu1/uPDF')
        cache.add(source_ingest._key(d), 1, 60)

        def other_process_finishes(_seconds):
            Description.objects.filter(pk=d.pk).update(input_file='users/x/describer/input/p.html')
            cache.delete(source_ingest._key(d))

        with mock.patch.object(source_ingest, '_download') as download, \
                mock.patch.object(source_ingest.time, 'sleep', side_effect=other_process_finishes):
            name = source_ingest.ensure_local_input(d)
        download.assert_not_called()
        self.assertEqual(name, 'users/x/describer/input/p.html')


class CardFollowsTheDownloadTest(_UserCase):
    """La card SAIT que son entrée se télécharge : le marqueur que `wama-app-base.js` suit pour
    la redemander à l'arrivée du fichier (avant le 2026-10-14, il fallait recharger la page)."""

    MARKER = 'data-ingest-pending="downloading"'

    def test_the_card_carries_the_marker_until_the_file_arrives(self):
        self.client.force_login(self.user)
        d = self._description('https://github.com/turgu1/uPDF')
        url = reverse('describer:card_html', args=[d.pk])
        self.assertContains(self.client.get(url), self.MARKER)
        with mock.patch.object(source_ingest, '_download',
                               CreationDownloadTest._fake_download(None, 'turgu1_uPDF.html')):
            source_ingest.ingest_now(d)
        self.assertNotContains(self.client.get(url), 'data-ingest-pending')

    def test_every_card_includes_the_common_band_that_carries_the_marker(self):
        """Le marqueur vit dans `_card_processes.html` : une card qui ne l'inclut pas (ou pas avec
        `elem`) ne serait jamais suivie — sans erreur."""
        from pathlib import Path

        from django.conf import settings
        cards = [p for p in Path(settings.BASE_DIR, 'wama').glob('*/templates/*/_*card.html')
                 if p.parts[-4] != 'common' and not p.parts[-4].endswith('_01')]
        self.assertGreaterEqual(len(cards), 11)
        for card in cards:
            with self.subTest(card=str(card)):
                self.assertIn("include 'common/_card_processes.html' with processes=elem.processes",
                              card.read_text(encoding='utf-8'))


class UserGesturesTest(_UserCase):
    """Les gestes : coller une URL (lot d'une ligne) dans le Describer et le converter, et la
    route `upload_youtube` du transcriber. Aucune requête ne télécharge — la source part en file."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        no_network = mock.patch('wama.common.utils.video_utils.upload_media_from_url',
                                side_effect=AssertionError('téléchargement DANS la requête'))
        no_network.start()
        self.addCleanup(no_network.stop)

    def _post_batch(self, route, url):
        batch = SimpleUploadedFile('url.txt', (url + '\n').encode('utf-8'), content_type='text/plain')
        with mock.patch('wama.common.tasks.ingest_source_task.delay') as delay, \
                self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse(route), {'batch_file': batch})
        return response, delay

    def test_describer_a_youtube_url_is_a_video_card_queued_for_download(self):
        from wama.describer.models import Description
        response, delay = self._post_batch('describer:batch_create',
                                         'https://www.youtube.com/watch?v=abc')
        self.assertEqual(response.status_code, 200, response.content[:300])
        d = Description.objects.get(pk=response.json()['description_ids'][0])
        self.assertEqual(d.detected_type, 'video')
        self.assertFalse(d.input_file)
        delay.assert_called_once_with('describer', 'description', d.pk)

    def test_describer_accepts_a_deposited_html_page(self):
        from wama.common.app_registry import accepts_file
        self.assertTrue(accepts_file('describer', 'page.html'))

    def test_converter_no_longer_downloads_in_the_request(self):
        from wama.converter.models import ConversionJob
        response, delay = self._post_batch('converter:batch_create',
                                         'https://www.youtube.com/watch?v=abc')
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json().get('count'), 1, response.json())
        job = ConversionJob.objects.filter(user=self.user).latest('pk')
        self.assertEqual(job.source_url, 'https://www.youtube.com/watch?v=abc')
        self.assertEqual(job.media_type, 'video')
        self.assertFalse(job.input_file)
        delay.assert_called_once_with('converter', 'conversionjob', job.pk)

    def test_transcriber_upload_youtube_records_the_source(self):
        from wama.transcriber.models import Transcript
        with mock.patch('wama.common.tasks.ingest_source_task.delay') as delay, \
                mock.patch('wama.common.utils.video_utils.download_youtube_audio',
                           side_effect=AssertionError('téléchargement DANS la requête')), \
                self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('transcriber:upload_youtube'),
                                        {'youtube_url': 'https://www.youtube.com/watch?v=abc'})
        self.assertEqual(response.status_code, 200, response.content[:300])
        t = Transcript.objects.get(pk=response.json()['id'])
        self.assertEqual(t.status, 'DRAFT')
        delay.assert_called_once_with('transcriber', 'transcript', t.pk)

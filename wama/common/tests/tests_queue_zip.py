"""Le ZIP de FILE et le ZIP de LOT : un écrivain, la file déclarée, les sorties déclarées (2026-10-17).

Onze vues `download_all` étaient écrites dans les dix apps, chacune avec son nom d'archive, son
nommage d'entrées, son périmètre, sa réponse « vide » et — pour trois d'entre elles — sa recopie
du rendu des formats déclarés. Celle de l'imager ne zippait que `generated_images` : les VIDÉOS
(`output_video`) n'entraient pas dans le ZIP, et l'imager n'avait pas de ZIP de lot du tout,
l'écrivain du lot lisant un NOM de champ (`output_file`) au lieu des sorties déclarées.

Ce que ces tests tiennent :
  * les onze routes de ZIP de file sont la vue de la fabrique (`make_progress_views`) ;
  * le ZIP d'une file de domaine ne contient QUE sa file (images / vidéos de l'imager) ;
  * le ZIP de lot de l'imager existe et sert ses sorties déclarées ;
  * un rendu late-binding qui échoue retombe sur le premier format déclaré ;
  * file vide → 404, domaine inconnu → 400.
"""
import io
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings
from django.urls import resolve, reverse

from wama.common import app_registry

REAL_APPS = sorted(a for a, s in app_registry.APP_CATALOG.items() if not s.get('sandbox'))
QUEUE_ZIP_ROUTES = ('download_all', 'download_all_media', 'audio_download_all')


def _names(response):
    blob = b''.join(response.streaming_content) if response.streaming else response.content
    return sorted(zipfile.ZipFile(io.BytesIO(blob)).namelist())


class EveryQueueZipIsTheFactoryViewTest(TestCase):

    def test_the_eleven_queue_zip_routes_are_the_factory_view(self):
        seen, wrong = [], []
        for app in REAL_APPS:
            for route in QUEUE_ZIP_ROUTES:
                try:
                    func = resolve(reverse(f'{app}:{route}')).func
                except Exception:
                    continue
                while hasattr(func, '__wrapped__'):
                    func = func.__wrapped__
                seen.append(f'{app}:{route}')
                if (func.__module__, func.__name__) != ('wama.common.utils.progress_views', 'download_all'):
                    wrong.append(f'{app}:{route} → {func.__module__}.{func.__name__}')
        self.assertEqual(11, len(seen), seen)
        self.assertEqual([], wrong)


class ImagerZipTest(TestCase):
    """L'imager : deux files (images, vidéos) dans un modèle, des images en LISTE de chemins."""

    def setUp(self):
        self.media = tempfile.mkdtemp(prefix='wama_zip_')
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        from wama.common.services.nightly_tests import get_test_user
        self.user = get_test_user()
        self.client = Client()
        self.client.force_login(self.user)
        from wama.imager.models import ImageGeneration
        self.image = ImageGeneration.objects.create(user=self.user, prompt='un chat', status='SUCCESS',
                                                    generation_mode='txt2img')
        img_dir = Path(self.media) / 'imager' / 'out'
        img_dir.mkdir(parents=True)
        paths = []
        for i in (1, 2):
            p = img_dir / f'chat_{i}.png'
            p.write_bytes(b'PNG%d' % i)
            paths.append(str(p))
        self.image.generated_images = paths
        self.image.save(update_fields=['generated_images'])
        self.video = ImageGeneration.objects.create(user=self.user, prompt='un chien', status='SUCCESS',
                                                    generation_mode='txt2vid')
        self.video.output_video.save('chien.mp4', ContentFile(b'MP4'))

    def test_each_queue_zip_holds_only_its_own_results(self):
        url = reverse('imager:download_all')
        images = _names(self.client.get(url, {'domain': 'image'}))
        videos = _names(self.client.get(url, {'domain': 'video'}))
        self.assertEqual(['chat_1.png', 'chat_2.png'], images)
        self.assertEqual(1, len(videos), videos)
        self.assertTrue(videos[0].endswith('.mp4'), 'the videos queue ZIP lost its video')

    def test_an_unknown_queue_is_refused_and_an_empty_one_says_so(self):
        url = reverse('imager:download_all')
        self.assertEqual(400, self.client.get(url, {'domain': 'audio'}).status_code)
        type(self.image).objects.filter(user=self.user).update(status='FAILURE')
        self.assertEqual(404, self.client.get(url).status_code)

    def test_the_imager_lot_zip_serves_its_declared_outputs(self):
        from wama.common.utils.batch_common import attach_to_batch
        from wama.imager.models import GenerationBatch, GenerationBatchItem
        lot = GenerationBatch.objects.create(user=self.user, total=2, domain='image')
        for row, gen in enumerate((self.image, self.video)):
            attach_to_batch(gen, lot, row, item_model=GenerationBatchItem, fk_name='generation')
        response = self.client.get(reverse('imager:batch_download', args=[lot.pk]))
        self.assertEqual(200, response.status_code)
        names = _names(response)
        self.assertEqual(3, len(names), names)
        # …et la PAGE l'offre : la card de lot porte le lien (le ⬇ de lot n'avait pas d'adresse).
        page = self.client.get(reverse('imager:index')).content.decode('utf-8', errors='replace')
        self.assertIn(reverse('imager:batch_download', args=[lot.pk]), page)


class LateBindingFallbackTest(TestCase):

    def setUp(self):
        from wama.common.services.nightly_tests import get_test_user
        self.user = get_test_user()
        self.client = Client()
        self.client.force_login(self.user)

    def test_a_render_that_fails_falls_back_to_the_first_declared_format(self):
        from wama.describer.models import Description
        Description.objects.create(user=self.user, filename='photo.jpg', status='SUCCESS',
                                   result_text='une description')
        from wama.common.utils import export_formats
        real = export_formats.export_builder_for('describer')

        def broken(item, fmt):
            if fmt == 'pdf':
                raise RuntimeError('rendu indisponible')
            return real(item, fmt)

        with mock.patch.object(export_formats, 'export_builder_for', lambda app: broken):
            response = self.client.get(reverse('describer:download_all'), {'format': 'pdf'})
        self.assertEqual(200, response.status_code)
        names = _names(response)
        self.assertEqual(1, len(names), names)
        self.assertEqual('.txt', os.path.splitext(names[0])[1])

"""The blurred output belongs to the CARD, not to its input file (2026-09-27).

Measured before the fix: the output path was derived from the INPUT's name. `Dupliquer` shares
the input by contract, so duplicated cards wrote — and read — the same output file: the last run
overwrote the others and every card showed its result. Fabien's report, « la quantité de flou ne
change rien pour SAM3 », was exactly that (media 215/217/218/219: blur 25 and 49, ONE output
written at the same minute). The blur itself was measured fine (a kernel of 5 → 99 on a real
SAM3 mask). Three more defects came from the same root: the download served a stale exact
`<input>_blurred` file first (media 183), « download all » and the batch ZIP looked only for that
name (empty archives), and deleting a card never reached its output.
"""
import os
import shutil
import tempfile
import zipfile
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase, override_settings

User = get_user_model()


class EngineOutputNameTest(SimpleTestCase):
    """The blurred output and the detection document are named through the common brick, WITH
    the card id — by the TASK since 2026-10-04 (the engines only detect)."""

    def test_two_cards_on_the_same_input_get_their_own_output_and_document(self):
        from wama.common.utils.output_naming import compose_output_name
        names = set()
        for card in (215, 217):
            names.add(compose_output_name(app='anonymizer', model='sam3',
                                          source_name='/in/shared.png', item_id=card))
            names.add(compose_output_name(app='anonymizer', model='sam3',
                                          source_name='/in/shared.png', item_id=card,
                                          nature='detections', ext='.json'))
        self.assertEqual({'shared_blurred_sam3_215.png', 'shared_blurred_sam3_217.png',
                          'shared_detections_sam3_215.json', 'shared_detections_sam3_217.json'},
                         names)


class PreviewVersionTest(SimpleTestCase):
    """A card relaunched rewrites its output under the SAME name: the preview URL must change,
    or the browser shows its cached image and the new setting looks ineffective."""

    def test_a_media_file_url_carries_its_modification_time(self):
        from wama.common.utils.preview_utils import _versioned
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, 'out.png'), 'wb') as f:
            f.write(b'x')
        os.utime(os.path.join(root, 'out.png'), (1_700_000_000, 1_700_000_000))
        with override_settings(MEDIA_ROOT=root, MEDIA_URL='/media/'):
            self.assertEqual('/media/out.png?v=1700000000', _versioned('/media/out.png'))
            # counter-checks: a URL with a query, a foreign URL, a missing file pass unchanged
            self.assertEqual('/media/out.png?x=1', _versioned('/media/out.png?x=1'))
            self.assertEqual('https://h/o.png', _versioned('https://h/o.png'))
            self.assertEqual('/media/none.png', _versioned('/media/none.png'))


class CardOutputTest(TestCase):

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.settings_override = override_settings(MEDIA_ROOT=self.root)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.user = User.objects.create_user('anon_output', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)

    def _file(self, sub, name, data=b'img'):
        from wama.common.utils.media_paths import get_app_media_path
        folder = get_app_media_path('anonymizer', self.user.id, sub)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(data)
        return str(path)

    def _media(self, **kw):
        from wama.anonymizer.models import Media
        from wama.common.utils.media_paths import app_media_dir
        self._file('input', 'shared.png')
        return Media.objects.create(user=self.user, file_ext='.png',
                                    file=f"{app_media_dir('anonymizer', self.user.id, 'input')}/shared.png",
                                    **kw)

    def test_the_task_records_what_the_engine_wrote_and_drops_its_previous_output(self):
        from wama.anonymizer.tasks import _record_output
        media = self._media()
        yolo = self._file('output', 'shared_blurred_yolo11n_1.png')
        _record_output(media, yolo)
        media.save()
        sam3 = self._file('output', 'shared_blurred_sam3_1.png')
        _record_output(media, sam3)                      # engine switched: the old output goes
        self.assertTrue(media.output_file.name.endswith('shared_blurred_sam3_1.png'))
        self.assertFalse(os.path.exists(yolo))
        self.assertTrue(os.path.exists(sam3))

    def test_a_previous_output_still_designated_by_another_card_is_kept(self):
        from wama.anonymizer.models import Media
        from wama.anonymizer.tasks import _record_output
        legacy = self._file('output', 'shared_blurred_sam3.png')     # the old shared name
        rel = os.path.relpath(legacy, self.root).replace(os.sep, '/')
        first, second = self._media(output_file=rel), self._media(output_file=rel)
        _record_output(first, self._file('output', 'shared_blurred_sam3_9.png'))
        self.assertTrue(os.path.exists(legacy), 'the duplicate still shows it')
        self.assertEqual(rel, Media.objects.get(pk=second.pk).output_file.name)

    def test_download_serves_the_card_output_not_a_stale_derived_name(self):
        own = self._file('output', 'shared_blurred_sam3_5.png', b'mine')
        self._file('output', 'shared_blurred.png', b'stale')            # media 183's trap
        media = self._media(status='SUCCESS',
                            output_file=os.path.relpath(own, self.root).replace(os.sep, '/'))
        body = b''.join(self.client.get(f'/anonymizer/download/{media.pk}/').streaming_content)
        self.assertEqual(b'mine', body)

    def test_a_duplicate_shares_the_input_never_the_output(self):
        from wama.anonymizer.models import Media
        own = self._file('output', 'shared_blurred_sam3_5.png')
        found = self._file('output', 'shared_detections_sam3_5.json', b'{}')
        media = self._media(status='SUCCESS',
                            output_file=os.path.relpath(own, self.root).replace(os.sep, '/'),
                            detections_file=os.path.relpath(found, self.root).replace(os.sep, '/'))
        new_id = self.client.post(f'/anonymizer/duplicate/{media.pk}/').json()['duplicated']
        copy = Media.objects.get(pk=new_id)
        self.assertEqual(media.file.name, copy.file.name)
        self.assertFalse(copy.output_file)
        self.assertFalse(copy.detections_file, 'nor its detections (2026-10-04)')

    def test_deleting_a_card_releases_its_own_output(self):
        """Depuis le 2026-09-30 (`MEDIA_STORAGE_TIERING` D34) la card part, sa sortie RESTE et
        devient un fichier libéré — l'utilisateur est prévenu et la supprime lui-même."""
        from wama.common.models import ReleasedFile
        own = self._file('output', 'shared_blurred_sam3_5.png')
        rel = os.path.relpath(own, self.root).replace(os.sep, '/')
        media = self._media(status='SUCCESS', output_file=rel)
        self.client.post(f'/anonymizer/delete/{media.pk}/')
        self.assertTrue(os.path.exists(own))
        self.assertTrue(ReleasedFile.objects.filter(path=rel).exists())

    def test_download_all_zips_each_card_output(self):
        a = self._file('output', 'shared_blurred_sam3_1.png', b'a')
        b = self._file('output', 'shared_blurred_sam3_2.png', b'b')
        for path in (a, b):
            self._media(status='SUCCESS', output_file=os.path.relpath(path, self.root).replace(os.sep, '/'))
        response = self.client.post('/anonymizer/download_all_media/')
        archive = zipfile.ZipFile(BytesIO(b''.join(response.streaming_content)))
        self.assertEqual(['shared_blurred_sam3_1.png', 'shared_blurred_sam3_2.png'],
                         sorted(archive.namelist()))

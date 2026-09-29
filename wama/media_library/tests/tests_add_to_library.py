"""La card d'entrée de la médiathèque — `api_upload` sur LA brique `add_file_to_library` (2026-09-29).

Mêmes gestes que les apps : un fichier TÉLÉVERSÉ, ou DÉSIGNÉ (glissé depuis l'arbre). La nature
est celle de l'onglet ; le nom est facultatif (celui du fichier). Un fichier désigné est DÉPLACÉ
dans la médiathèque (D24) — ce qui n'a de sens que pour un fichier de l'espace de l'utilisateur.
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from wama.media_library.models import SystemAsset, UserAsset

User = get_user_model()
PNG = b'\x89PNG\r\n\x1a\nwitness'


class AddToLibraryTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('ml_adder', password='x')
        self.other = User.objects.create_user('ml_other', password='x')
        self.client.force_login(self.user)

    def _write(self, rel):
        path = Path(settings.MEDIA_ROOT) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG)
        return rel

    def _post(self, **data):
        return self.client.post(reverse('media_library:api_upload'), data)

    def test_an_upload_without_name_takes_the_file_name(self):
        response = self._post(asset_type='avatar',
                              file=SimpleUploadedFile('portrait.png', PNG, content_type='image/png'))
        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual('portrait', response.json()['name'])

    def test_a_file_of_my_space_is_moved_into_the_library(self):
        rel = self._write(f'users/{self.user.id}/temp/face.png')
        response = self._post(asset_type='avatar', file__designated=rel)
        self.assertEqual(200, response.status_code, response.content)
        asset = UserAsset.objects.get(pk=response.json()['id'])
        self.assertNotEqual(rel, asset.file.name)
        self.assertTrue((Path(settings.MEDIA_ROOT) / asset.file.name).is_file())
        self.assertFalse((Path(settings.MEDIA_ROOT) / rel).exists(), 'DÉPLACÉ, pas copié (D24)')

    def test_someone_elses_or_a_system_file_is_refused(self):
        theirs = self._write(f'users/{self.other.id}/temp/theirs.png')
        system = self._write('media_library/system/avatar/gallery.png')
        SystemAsset.objects.create(name='gallery.png', asset_type='avatar', file=system)
        for rel in (theirs, system):
            with self.subTest(rel=rel):
                response = self._post(asset_type='avatar', file__designated=rel)
                self.assertEqual(400, response.status_code)
                self.assertTrue((Path(settings.MEDIA_ROOT) / rel).is_file(), 'rien ne bouge')

    def test_a_name_already_taken_is_a_conflict(self):
        UserAsset.objects.create(user=self.user, name='portrait', asset_type='avatar',
                                 file=self._write(f'users/{self.user.id}/media_library/assets/p.png'))
        response = self._post(asset_type='avatar',
                              file=SimpleUploadedFile('portrait.png', PNG, content_type='image/png'))
        self.assertEqual(409, response.status_code)

    def test_the_nature_is_never_guessed(self):
        response = self._post(file=SimpleUploadedFile('portrait.png', PNG, content_type='image/png'))
        self.assertEqual(400, response.status_code)

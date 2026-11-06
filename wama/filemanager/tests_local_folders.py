"""Les dossiers du SERVEUR et les frontières d'écriture du gestionnaire de fichiers (2026-11-06,
audit de sécurité — chaque garde a été rouge avant son correctif, en base de test) :

  - un dossier LOCAL se connecte, se parcourt et se cherche par un ADMINISTRATEUR seul
    (`local_folder_allowed`) ; un membre garde les partages réseau et les nuages ;
  - un sous-chemin ABSOLU ou un lien hors du dossier connecté ne désigne rien (`resolve_mount_path`) ;
  - une écriture dans le dossier temporaire se juge sur le chemin RÉSOLU (`user_temp_path`) :
    l'assainisseur ne fabrique plus de `..`, le déplacement ne sort plus du dossier.
"""
import json
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from wama.filemanager.models import MountedFolder
from wama.filemanager.views import resolve_mount_path, sanitize_relative_path, user_temp_path

User = get_user_model()


class _Accounts(TestCase):

    def setUp(self):
        from wama.accounts.permissions import set_account_tier
        self.member = User.objects.create_user('wama_member_folders')
        self.admin = User.objects.create_user('wama_admin_folders')
        set_account_tier(self.admin, 'admin')
        self.folder = tempfile.mkdtemp(prefix='wama_local_folder_')
        self.addCleanup(__import__('shutil').rmtree, self.folder, True)

    def _as(self, user):
        self.client.force_login(user, backend='django.contrib.auth.backends.ModelBackend')
        return self.client

    def _connect(self, user, path):
        return self._as(user).post(reverse('filemanager:api_mounts'),
                                   data=json.dumps({'name': 'local', 'local_path': path}),
                                   content_type='application/json')


class LocalFoldersAreForAdministratorsTest(_Accounts):

    def test_a_member_cannot_connect_a_local_folder_of_the_server(self):
        reply = self._connect(self.member, self.folder)
        self.assertEqual(reply.status_code, 403)
        self.assertIn('administrateur', reply.json()['error'])
        self.assertFalse(MountedFolder.objects.filter(user=self.member).exists())

    def test_an_administrator_still_connects_one(self):
        reply = self._connect(self.admin, self.folder)
        self.assertEqual(reply.status_code, 200, reply.content)
        self.assertTrue(MountedFolder.objects.filter(user=self.admin, local_path=self.folder).exists())

    def test_a_member_neither_browses_nor_searches_nor_probes_the_server_tree(self):
        client = self._as(self.member)
        self.assertEqual(client.get(reverse('filemanager:api_browse_fs'),
                                    {'path': str(settings.BASE_DIR)}).status_code, 403)
        self.assertEqual(client.get(reverse('filemanager:api_find_folder'),
                                    {'name': 'media'}).status_code, 403)
        probe = client.get(reverse('filemanager:api_validate_path'), {'path': self.folder})
        self.assertEqual(probe.status_code, 403)
        self.assertFalse(probe.json()['accessible'])

    def test_a_member_still_names_a_network_share(self):
        probe = self._as(self.member).get(reverse('filemanager:api_validate_path'),
                                           {'path': r'\\files\saves'})
        self.assertEqual(probe.status_code, 200)
        self.assertTrue(probe.json().get('is_smb'))

    def test_an_administrator_browses_the_tree(self):
        reply = self._as(self.admin).get(reverse('filemanager:api_browse_fs'), {'path': self.folder})
        self.assertEqual(reply.status_code, 200)


class MountSubpathsStayInsideTest(_Accounts):

    def setUp(self):
        super().setUp()
        self.mount = MountedFolder.objects.create(user=self.admin, name='m', local_path=self.folder)
        Path(self.folder, 'inside.txt').write_text('inside', encoding='utf-8')
        self.outside = tempfile.mkdtemp(prefix='wama_outside_')
        self.addCleanup(__import__('shutil').rmtree, self.outside, True)
        Path(self.outside, 'secret.txt').write_text('OUTSIDE', encoding='utf-8')

    def test_an_absolute_subpath_designates_nothing(self):
        target, mount = resolve_mount_path(f'mounts/{self.mount.pk}//{self.outside}/secret.txt',
                                           self.admin)
        self.assertIsNone(target)
        self.assertIsNone(mount)

    def test_a_relative_subpath_is_served(self):
        target, _mount = resolve_mount_path(f'mounts/{self.mount.pk}/inside.txt', self.admin)
        self.assertEqual(Path(target).read_text(encoding='utf-8'), 'inside')

    def test_a_link_pointing_outside_the_folder_designates_nothing(self):
        link = Path(self.folder, 'link.txt')
        try:
            os.symlink(Path(self.outside, 'secret.txt'), link)
        except (OSError, NotImplementedError):
            self.skipTest('liens symboliques indisponibles ici')
        target, _mount = resolve_mount_path(f'mounts/{self.mount.pk}/link.txt', self.admin)
        self.assertIsNone(target)

    def test_the_file_route_rejects_an_absolute_path(self):
        url = reverse('filemanager:api_mount_serve', args=[self.mount.pk, 'x']).rsplit('x', 1)[0]
        reply = self._as(self.admin).get(url + self.outside + '/secret.txt')
        self.assertEqual(reply.status_code, 403)
        served = self._as(self.admin).get(url + 'inside.txt')
        self.assertEqual(served.status_code, 200)
        self.assertEqual(b''.join(served.streaming_content), b'inside')


class WritesStayInTheTempFolderTest(_Accounts):

    def setUp(self):
        super().setUp()
        if 'media_tests' not in str(settings.MEDIA_ROOT).replace('\\', '/'):
            self.skipTest('MEDIA_ROOT non redirigé : rien n’est écrit')
        self.other = User.objects.create_user('wama_other_folders')

    def test_the_sanitizer_no_longer_builds_parent_segments(self):
        self.assertEqual(sanitize_relative_path('a/.*./.*./x.txt'), 'a/x.txt')
        self.assertEqual(sanitize_relative_path('a/../b/./c.txt'), 'a/b/c.txt')
        self.assertIsNone(sanitize_relative_path('../..'))

    def test_the_temp_boundary_is_judged_on_the_resolved_path(self):
        uid = self.member.id
        self.assertIsNotNone(user_temp_path(self.member, f'users/{uid}/temp/a/b.txt'))
        self.assertIsNone(user_temp_path(self.member, f'users/{uid}/temp/../../{self.other.id}/temp'))
        self.assertIsNone(user_temp_path(self.member, f'users/{uid}/temp2/x'))
        self.assertIsNone(user_temp_path(self.member, f'users/{self.other.id}/temp/x'))

    def test_a_move_cannot_leave_the_temp_folder(self):
        client = self._as(self.member)
        up = client.post(reverse('filemanager:api_upload'),
                         {'files': SimpleUploadedFile('depot.txt', b'mine')})
        path = up.json()['uploaded'][0]['path']
        escape = f'users/{self.member.id}/temp/../../{self.other.id}/temp'
        moved = client.post(reverse('filemanager:api_move'),
                            data=json.dumps({'source': path, 'destination': escape}),
                            content_type='application/json')
        self.assertEqual(moved.status_code, 403)
        self.assertTrue((Path(settings.MEDIA_ROOT) / path).exists(), 'le fichier n’a pas bougé')
        inside = f'users/{self.member.id}/temp/sub'
        moved = client.post(reverse('filemanager:api_move'),
                            data=json.dumps({'source': path, 'destination': inside}),
                            content_type='application/json')
        self.assertEqual(moved.status_code, 200, moved.content)
        self.assertEqual(moved.json()['new_path'], f'{inside}/depot.txt')

    def test_a_folder_upload_with_a_forged_path_stays_in_the_temp_folder(self):
        client = self._as(self.member)
        up = client.post(reverse('filemanager:api_upload'), {
            'files': SimpleUploadedFile('note.txt', b'mine'),
            'paths': json.dumps([f'x/.*./.*./.*./{self.other.id}/temp/note.txt'])})
        self.assertEqual(up.status_code, 200)
        landed = up.json()['uploaded'][0]['path']
        self.assertTrue(landed.startswith(f'users/{self.member.id}/temp/'), landed)
        self.assertNotIn('..', landed)
        self.assertFalse((Path(settings.MEDIA_ROOT) / f'users/{self.other.id}/temp/note.txt').exists())

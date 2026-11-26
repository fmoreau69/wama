"""Un avatar NOMMÉ se résout dans la médiathèque et se DÉSIGNE, comme depuis la card (2026-09-29).

Un lot (`-r avatar1.png`), un nœud du Studio et l'assistant citent un avatar par son nom. Ce nom
ne se cherchait que dans la galerie SYSTÈME et restait stocké tel quel : les avatars de
l'utilisateur et ceux qu'on lui partage étaient introuvables par ces voies, et un nom inconnu ne
se révélait qu'au lancement. Désormais le nom se résout parmi ce que l'utilisateur VOIT (les
siens, les partagés, le système) et le job reçoit le FICHIER (`avatar_upload`).
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.media_library.models import SystemAsset, UserAsset
from wama.media_library.services import resolve_visible_asset, visible_asset_names

User = get_user_model()
PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00'
       b'\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N'
       b'\x00\x00\x00\x00IEND\xaeB`\x82')


def _file(rel):
    path = Path(settings.MEDIA_ROOT) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG)
    return rel


class NamedAvatarTest(TestCase):

    def setUp(self):
        self.me = User.objects.create_user('named_me', password='x')
        self.other = User.objects.create_user('named_other', password='x')
        self.system = _file('media_library/system/avatar/face.png')
        SystemAsset.objects.create(name='face.png', asset_type='avatar', file=self.system)
        self.mine = _file(f'users/{self.me.id}/media_library/assets/face.png')
        UserAsset.objects.create(user=self.me, name='face.png', asset_type='avatar', file=self.mine)
        self.shared = _file(f'users/{self.other.id}/media_library/assets/colleague.png')
        UserAsset.objects.create(user=self.other, name='colleague', asset_type='avatar',
                                 file=self.shared, visibility='public')
        self.private = _file(f'users/{self.other.id}/media_library/assets/secret.png')
        UserAsset.objects.create(user=self.other, name='secret', asset_type='avatar', file=self.private)

    # ── la brique ──

    def test_the_users_own_avatar_comes_before_the_system_one(self):
        self.assertEqual(self.mine, resolve_visible_asset(self.me, 'avatar', 'face.png'))

    def test_the_system_avatar_is_found_by_a_user_who_has_none(self):
        self.assertEqual(self.system, resolve_visible_asset(self.other, 'avatar', 'face.png'))

    def test_a_shared_avatar_is_found_by_its_name_or_its_file(self):
        self.assertEqual(self.shared, resolve_visible_asset(self.me, 'avatar', 'colleague'))
        self.assertEqual(self.shared, resolve_visible_asset(self.me, 'avatar', 'colleague.png'))

    def test_someone_elses_private_avatar_is_never_found(self):
        self.assertEqual('', resolve_visible_asset(self.me, 'avatar', 'secret'))

    def test_the_selector_lists_what_the_user_sees_once(self):
        self.assertEqual(['colleague', 'face.png'], sorted(visible_asset_names(self.me, 'avatar')))

    # ── les trois voies ──

    def _grant_the_app(self):
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        for role in (DEFAULT_APP_ACCESS.get('avatarizer') or {}).get('roles', []):
            self.me.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])

    def _tool(self):
        """L'outil d'ajout, DÉRIVÉ de la card (2026-11-26) : le texte à dire sur son port texte,
        l'avatar NOMMÉ sur son port image — un nom d'asset de la médiathèque, comme un chemin."""
        from wama import tool_api
        from wama.common.utils.app_modes import INPUT_TYPES
        args = tool_api.tool_arg_names('add_to_avatarizer')
        if 'work_image' not in args:
            self.skipTest("l'avatar vient des modèles du catalogue (MuseTalk) : aucun ici")
        text = next(a for a in args if (INPUT_TYPES.get(a) or {}).get('kind') == 'text')
        self._grant_the_app()
        return lambda name: tool_api.TOOL_REGISTRY['add_to_avatarizer'](
            self.me, **{text: 'Bonjour.', 'work_image': name})

    def test_the_assistant_tool_points_the_named_avatar(self):
        from wama.avatarizer.models import AvatarJob
        result = self._tool()('colleague')
        self.assertNotIn('error', result, result)
        job = AvatarJob.objects.get(pk=result['item_id'])
        # L'avatar se lit au lecteur commun des entrées (table, 2026-11-25), plus à sa colonne.
        self.assertEqual(('upload', self.shared, ''),
                         (job.avatar_source, job.avatar_file.name, job.avatar_gallery_name))

    def test_the_assistant_tool_rejects_an_unknown_name_before_creating(self):
        from wama.avatarizer.models import AvatarJob
        result = self._tool()('secret')
        self.assertIn('introuvable', result.get('error', ''))
        self.assertFalse(AvatarJob.objects.filter(user=self.me).exists())

    def test_the_create_view_points_a_posted_name(self):
        from wama.avatarizer.models import AvatarJob
        self._grant_the_app()
        self.client.force_login(self.me)
        response = self.client.post('/avatarizer/create/', {'text_content': 'Bonjour.',
                                                            'avatar_gallery_name': 'face.png'})
        self.assertEqual(200, response.status_code, response.content[:300])
        job = AvatarJob.objects.get(pk=response.json()['id'])
        self.assertEqual(('upload', self.mine), (job.avatar_source, job.avatar_file.name))

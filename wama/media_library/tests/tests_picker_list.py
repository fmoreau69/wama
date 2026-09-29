"""La liste que lit la fenêtre de sélection (`api_list`) — onglets et provenances (2026-09-29).

La fenêtre médiathèque universelle (`CARD_DESIGN §11.11` étape 3 (d)) montre, pour une
DÉSIGNATION, les miens, ceux qu'on me partage et ceux du système (la galerie d'avatars), avec des
onglets par nature. Ces options se DEMANDENT : sans elles la réponse est celle d'avant.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wama.media_library.models import SystemAsset, UserAsset

User = get_user_model()


class PickerListTest(TestCase):

    def setUp(self):
        self.me = User.objects.create_user('picker_me', password='x')
        self.other = User.objects.create_user('picker_other', password='x')
        UserAsset.objects.create(user=self.me, name='my_face', asset_type='avatar',
                                 file='users/1/media_library/assets/my_face.png')
        UserAsset.objects.create(user=self.other, name='their_face', asset_type='avatar',
                                 file='users/2/media_library/assets/their_face.png',
                                 visibility='public')
        UserAsset.objects.create(user=self.other, name='their_secret', asset_type='avatar',
                                 file='users/2/media_library/assets/their_secret.png')
        UserAsset.objects.create(user=self.me, name='my_photo', asset_type='image',
                                 file='users/1/media_library/assets/my_photo.png')
        SystemAsset.objects.create(name='gallery_face', asset_type='avatar',
                                   file='media_library/system/avatar/gallery_face.png')
        self.client.force_login(self.me)

    def _get(self, **params):
        response = self.client.get(reverse('media_library:api_list'), params)
        self.assertEqual(200, response.status_code)
        return response.json()

    def test_without_options_the_answer_is_unchanged(self):
        data = self._get(type='avatar')
        self.assertEqual(['my_face'], [a['name'] for a in data['assets']])
        self.assertNotIn('tabs', data)

    def test_the_three_origins_in_order_of_trust(self):
        data = self._get(type='avatar', scope='visible', with_system='1')
        self.assertEqual([('my_face', 'mine'), ('their_face', 'shared'), ('gallery_face', 'system')],
                         [(a['name'], a['origin']) for a in data['assets']])
        self.assertNotIn('their_secret', [a['name'] for a in data['assets']],
                         "le privé d'autrui ne s'affiche jamais")

    def test_an_exact_nature_opens_the_tabs_of_its_category(self):
        data = self._get(type='avatar', scope='visible', with_system='1', tabs='1')
        tabs = [(t['key'], t['exact'], t['count']) for t in data['tabs']]
        # « Tous » = la catégorie image (1 image + 3 avatars visibles), puis chaque nature.
        self.assertEqual([('image', False, 4), ('image', True, 1), ('avatar', True, 3)], tabs)

    def test_a_nature_named_like_its_category_is_filtered_exactly(self):
        """`image` est une catégorie ET une nature : sans `exact`, l'onglet « Image » montrerait
        les avatars."""
        grouped = self._get(type='image', scope='visible', with_system='1')
        exact = self._get(type='image', exact='1', scope='visible', with_system='1')
        self.assertEqual(4, grouped['total'])
        self.assertEqual(['my_photo'], [a['name'] for a in exact['assets']])


class PreviewMimeForThePickerTest(TestCase):
    """La fenêtre de sélection MONTRE l'asset avant le choix (2026-09-29) : elle a besoin d'un type
    même quand celui stocké manque ou ne dit rien — le serveur le résout du FICHIER."""

    def setUp(self):
        self.me = User.objects.create_user('picker_mime', password='x')
        self.client.force_login(self.me)

    def _preview_mime(self, name, stored):
        UserAsset.objects.create(user=self.me, name=name, asset_type='audio_music',
                                 file=f'users/1/media_library/assets/{name}', mime_type=stored)
        data = self.client.get(reverse('media_library:api_list'), {'type': 'all'}).json()
        return next(a for a in data['assets'] if a['name'] == name)

    def test_an_empty_stored_type_is_resolved_from_the_file(self):
        asset = self._preview_mime('track.mp3', '')
        self.assertEqual('audio/mpeg', asset['preview_mime'])
        self.assertEqual('', asset['mime_type'], 'la donnée stockée ne change pas')

    def test_a_generic_stored_type_is_resolved_from_the_file(self):
        self.assertEqual('audio/wav', self._preview_mime('voice.wav', 'application/octet-stream')['preview_mime'])

    def test_a_meaningful_stored_type_is_kept(self):
        """Contre-épreuve : un type stocké qui dit quelque chose prime sur l'extension."""
        self.assertEqual('audio/ogg', self._preview_mime('odd.mp3', 'audio/ogg')['preview_mime'])

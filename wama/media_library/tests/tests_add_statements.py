"""Ce que la personne DIT d'un fichier à l'ajout (2026-09-30, décision de Fabien) : les attributs
que sa nature demande (`Attr.on_add` — langue, âge, genre d'une voix) et la PROVENANCE d'un extrait
qui n'est pas d'elle (licence, auteur, page d'origine). Testé par la route réelle de la card
d'ajout commune (`api_upload`), page médiathèque et fenêtre commune confondues.
"""
import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from wama.media_library.models import UserAsset
from wama.media_library.natures import ASSET_NATURES, natures_as_json


def _wav(name='v.wav'):
    return SimpleUploadedFile(name, b'RIFF0000WAVE', content_type='audio/wav')


class AskedOnAddDeclarationTest(TestCase):
    def test_a_voice_asks_its_language_age_and_gender_and_nothing_measured(self):
        asked = {k for k, a in ASSET_NATURES['voice'].attributes.items() if a.on_add}
        self.assertEqual({'language', 'age', 'gender'}, asked)
        self.assertFalse(any(a.on_add for a in ASSET_NATURES['object3d'].attributes.values()),
                         'un attribut MESURÉ dans le fichier ne se demande jamais')
        self.assertTrue(natures_as_json()['voice']['attributes']['gender']['on_add'])


class AddStatementsRouteTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('add_statements', password='x')
        self.client.force_login(self.user)
        self.url = reverse('media_library:api_upload')

    def _post(self, **fields):
        return self.client.post(self.url, {'asset_type': 'voice', 'file': _wav(), **fields})

    def test_stated_attributes_and_provenance_are_stored(self):
        response = self._post(name='Narrator', license='CC-BY-4.0', author='Jane Doe',
                              source_url='https://example.org/podcast/12',
                              attributes=json.dumps({'language': 'fr', 'age': 'adult',
                                                     'gender': 'female'}))
        self.assertEqual(200, response.status_code, response.content[:200])
        asset = UserAsset.objects.get(pk=response.json()['id'])
        self.assertEqual({'language': 'fr', 'age': 'adult', 'gender': 'female'},
                         {k: asset.attributes.get(k) for k in ('language', 'age', 'gender')})
        self.assertEqual(('CC-BY-4.0', 'Jane Doe', 'https://example.org/podcast/12'),
                         (asset.license, asset.author, asset.source_url))

    def test_a_value_outside_the_declared_vocabulary_is_refused_and_nothing_is_created(self):
        response = self._post(attributes=json.dumps({'gender': 'robot'}))
        self.assertEqual(400, response.status_code)
        self.assertFalse(UserAsset.objects.filter(user=self.user).exists())

    def test_an_attribute_not_asked_on_add_is_ignored(self):
        response = self._post(attributes=json.dumps({'variant': 3, 'language': 'en'}))
        asset = UserAsset.objects.get(pk=response.json()['id'])
        self.assertNotIn('variant', asset.attributes)
        self.assertEqual('en', asset.attributes.get('language'))

    def test_an_invalid_origin_address_is_refused(self):
        response = self._post(source_url='javascript:alert(1)')
        self.assertEqual(400, response.status_code)
        self.assertFalse(UserAsset.objects.filter(user=self.user).exists())

    def test_nothing_stated_still_adds_as_before(self):
        response = self._post()
        self.assertEqual(200, response.status_code, response.content[:200])

    def test_the_picker_tabs_carry_the_declaration(self):
        tabs = self.client.get(reverse('media_library:api_list'),
                               {'type': 'voice', 'exact': '1', 'tabs': '1'}).json()['tabs']
        voice = next(t for t in tabs if t['key'] == 'voice')
        self.assertTrue(voice['attributes']['language']['on_add'])

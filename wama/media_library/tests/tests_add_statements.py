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


class EstimateProposalsTest(TestCase):
    """PROPOSER les attributs en écoutant le fichier (2026-09-30, demande de Fabien : « le déterminer
    et le proposer, pour que ce soit proche des infos qu'il rentrera »)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('estimate_user', password='x')
        self.client.force_login(self.user)

    def test_the_voice_declares_what_can_be_estimated_and_age_is_not(self):
        voice = ASSET_NATURES['voice'].attributes
        self.assertEqual('spoken_language', voice['language'].estimate)
        self.assertEqual('voice_gender', voice['gender'].estimate)
        self.assertEqual('', voice['age'].estimate, "la hauteur de voix ne dit pas l'âge")
        from wama.media_library.services import ATTRIBUTE_ESTIMATORS
        for nature in ASSET_NATURES.values():
            for attr in nature.attributes.values():
                if attr.estimate:
                    self.assertIn(attr.estimate, ATTRIBUTE_ESTIMATORS)

    def test_proposals_keep_the_vocabulary_and_drop_failures(self):
        from unittest.mock import patch
        from wama.media_library import services
        fake = {'spoken_language': lambda p: ('fr', 0.97),
                'voice_gender': lambda p: (_ for _ in ()).throw(RuntimeError('no instrument'))}
        with patch.dict(services.ATTRIBUTE_ESTIMATORS, fake):
            proposals = services.estimate_attributes('voice', '/tmp/x.wav')
        self.assertEqual({'language': {'value': 'fr', 'label': 'Français', 'confidence': 0.97}}, proposals)
        with patch.dict(services.ATTRIBUTE_ESTIMATORS, {'spoken_language': lambda p: ('xx', 0.9)}):
            self.assertNotIn('language', services.estimate_attributes('voice', '/tmp/x.wav'),
                             'une langue hors vocabulaire ne se propose pas')
        with patch.dict(services.ATTRIBUTE_ESTIMATORS, {'spoken_language': lambda p: ('ru', 0.43)}):
            self.assertNotIn('language', services.estimate_attributes('voice', '/tmp/x.wav'),
                             'une estimation peu sûre ne se propose pas (cas mesuré)')

    def test_the_route_listens_without_storing_anything(self):
        from unittest.mock import patch
        with patch('wama.media_library.services.estimate_attributes',
                   return_value={'gender': {'value': 'female', 'label': 'Femme', 'confidence': None}}):
            response = self.client.post(reverse('media_library:api_estimate'),
                                        {'asset_type': 'voice', 'file': _wav()})
        self.assertEqual(200, response.status_code, response.content[:200])
        self.assertEqual('female', response.json()['proposals']['gender']['value'])
        self.assertFalse(UserAsset.objects.filter(user=self.user).exists())

    def test_a_file_of_someone_else_cannot_be_listened_to(self):
        response = self.client.post(reverse('media_library:api_estimate'),
                                    {'asset_type': 'voice', 'file__designated': '../manage.py'})
        self.assertIn(response.status_code, (400, 403))

    def test_the_pitch_of_a_low_voice_proposes_male(self):
        """La vraie mesure (librosa pYIN), sur un son synthétique de 120 Hz."""
        import os
        import tempfile
        try:
            import numpy as np
            import soundfile as sf
            import librosa  # noqa: F401
        except ImportError:
            self.skipTest('librosa / soundfile absents')
        from unittest.mock import patch
        from wama.media_library import services
        sr = 16000
        t = np.arange(sr * 2) / sr
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'low.wav')
            sf.write(path, 0.5 * np.sin(2 * np.pi * 120 * t), sr)
            # La langue d'un son pur ne veut rien dire : seul le GENRE est mesuré ici, pour de vrai.
            def no_language(p):
                raise RuntimeError('pas de langue dans un son pur')
            with patch.dict(services.ATTRIBUTE_ESTIMATORS, {'spoken_language': no_language}):
                proposals = services.estimate_attributes('voice', path)
        self.assertEqual('male', proposals.get('gender', {}).get('value'))
        self.assertNotIn('language', proposals)

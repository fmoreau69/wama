"""La BARRE COMMUNE de la médiathèque — recherche, origine, attributs, tri (2026-10-01).

Demande de Fabien : « dans la médiathèque on n'a que la recherche ; réutiliser la barre de
filtrage/tri/recherche commune ». La page charge sa grille elle-même (`api_list` +
`api_system_list`, paginées) ; la barre (`wama-filter-bar.js`, mode `remote`) lui dit quoi
demander. Ces tests tiennent le contrat SERVEUR des paramètres, et la DÉRIVATION des filtres
depuis les natures (rien n'est écrit par onglet).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wama.media_library.models import SystemAsset, UserAsset

User = get_user_model()


class LibraryListFiltersTest(TestCase):

    def setUp(self):
        self.me = User.objects.create_user('filters_me', password='x')
        self.other = User.objects.create_user('filters_other', password='x')
        UserAsset.objects.create(user=self.me, name='b_voice', asset_type='voice', file_size=10,
                                 file='users/1/media_library/assets/b.wav',
                                 attributes={'gender': 'female', 'language': 'fr'})
        UserAsset.objects.create(user=self.me, name='a_voice', asset_type='voice', file_size=30,
                                 file='users/1/media_library/assets/a.wav',
                                 attributes={'gender': 'male', 'language': 'en'})
        UserAsset.objects.create(user=self.other, name='c_shared', asset_type='voice',
                                 file='users/2/media_library/assets/c.wav', visibility='public',
                                 attributes={'gender': 'female', 'language': 'fr'})
        SystemAsset.objects.create(name='d_system', asset_type='voice',
                                   file='media_library/system/voice/d.wav',
                                   attributes={'gender': 'male', 'language': 'de'})
        self.client.force_login(self.me)

    def _names(self, url_name='media_library:api_list', **params):
        params = {'type': 'voice', 'scope': 'visible', **params}
        response = self.client.get(reverse(url_name), params)
        self.assertEqual(200, response.status_code)
        return [a['name'] for a in response.json()['assets']]

    def test_origin_mine_shared_system(self):
        self.assertEqual({'a_voice', 'b_voice'}, set(self._names(origin='mine')))
        self.assertEqual(['c_shared'], self._names(origin='shared'))
        self.assertEqual([], self._names(origin='system'))
        self.assertEqual(['d_system'], self._names('media_library:api_system_list', origin='system'))
        self.assertEqual([], self._names('media_library:api_system_list', origin='mine'))

    def test_a_declared_attribute_filters_users_and_system_assets(self):
        self.assertEqual({'b_voice', 'c_shared'},
                         set(self._names(**{'attr__voice__gender': 'female'})))
        self.assertEqual(['d_system'],
                         self._names('media_library:api_system_list', **{'attr__voice__gender': 'male'}))

    def test_an_undeclared_or_foreign_attribute_is_ignored(self):
        everything = set(self._names())
        self.assertEqual(everything, set(self._names(**{'attr__voice__not_declared': 'x'})))
        self.assertEqual(everything, set(self._names(**{'attr__object3d__units': 'm'})),
                         'un filtre d’une autre nature (onglet changé) ne restreint rien')

    def test_sorts(self):
        self.assertEqual(['a_voice', 'b_voice', 'c_shared'], self._names(sort='name'))
        self.assertEqual(['a_voice', 'b_voice'], self._names(sort='size', origin='mine'))

    def test_without_the_new_parameters_the_answer_is_unchanged(self):
        """La fenêtre de sélection des apps ne passe rien de tout cela."""
        response = self.client.get(reverse('media_library:api_list'), {'type': 'voice'})
        self.assertEqual({'a_voice', 'b_voice'}, {a['name'] for a in response.json()['assets']})


class LibraryFacetsAreDerivedTest(TestCase):

    def test_facets_come_from_the_natures(self):
        from wama.media_library.views import _attribute_facets
        user = User.objects.create_user('facets_me', password='x')
        UserAsset.objects.create(user=user, name='v', asset_type='voice',
                                 file='users/1/media_library/assets/v.wav',
                                 attributes={'language': 'fr'})
        facets = {f['cle']: f for f in _attribute_facets(user)}
        # Vocabulaire DÉCLARÉ : ses valeurs, toutes.
        self.assertEqual('voice', facets['attr__voice__gender']['nature'])
        self.assertEqual(2, len(facets['attr__voice__gender']['options']))
        # Texte LIBRE : les valeurs PRÉSENTES.
        self.assertEqual({'fr': 'fr'}, facets['attr__voice__language']['options'])
        # Un vocabulaire d'une seule valeur n'est pas un filtre.
        self.assertNotIn('attr__object3d__face_rig', facets)

    def test_the_page_mounts_the_common_bar_in_remote_mode(self):
        user = User.objects.create_user('facets_page', password='x', is_superuser=True)
        self.client.force_login(user)
        html = self.client.get(reverse('media_library:index')).content.decode()
        self.assertIn('data-mode="remote"', html)
        self.assertIn('data-f-role="sort"', html)
        self.assertIn('data-f-facette="origin"', html)
        self.assertIn('data-f-nature="voice"', html)
        self.assertNotIn('id="searchInput"', html, 'la recherche propre à la page est remplacée')

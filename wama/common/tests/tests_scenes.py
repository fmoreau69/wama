"""Les SCÈNES 3D déclarées (`common/scenes.py`) — le registre, les droits, les contrats des scènes
des licences et des modèles, et le bouton que reçoit la page d'un registre qui déclare sa scène.

Ce que ces tests tiennent, et qu'aucun navigateur ne verrait seul : une déclaration incohérente
(une couche au rôle inconnu, un facteur d'une famille inconnue) est refusée À LA DÉCLARATION ; les
pages des scènes passent par la garde des Registres ; les faits viennent de leur brique — la
qualification des licences, le catalogue VISIBLE du demandeur, propositions exclues.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wama.common.scenes import SCENES, Scene, register_scene, scene_for_registry, scene_spec

User = get_user_model()


def _admin(username):
    from wama.accounts.permissions import set_account_tier
    user = User.objects.create_user(username, password='x')
    set_account_tier(user, 'admin')
    return user


class SceneRegistryTest(TestCase):

    def test_the_three_scenes_are_declared_by_their_domains(self):
        self.assertEqual(SCENES['users'].page_url_name, 'accounts:user-constellation')
        self.assertEqual(scene_for_registry('licenses').key, 'licenses')
        self.assertEqual(scene_for_registry('models').key, 'models')
        self.assertIsNone(scene_for_registry('docs'))

    def test_an_inconsistent_declaration_is_refused_when_declared(self):
        base = dict(key='bad', page_title='x', kicker='x', data='x:y')
        cases = (
            dict(layers=({'key': 'l', 'role': 'colour'},)),
            dict(factors=({'key': 'f', 'kind': 'semantic'},)),
            dict(permission='staff'),
            dict(group_kinds={'k': {'layer': 'absent'}}),
            dict(data=''),
        )
        for extra in cases:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                register_scene(Scene(**{**base, **extra}))
        self.assertNotIn('bad', SCENES)

    def test_the_served_declaration_hides_the_server_side_fields(self):
        spec = scene_spec(SCENES['licenses'])
        for private in ('data', 'permission', 'page_url_name', 'data_url_name', 'back_url_name'):
            self.assertNotIn(private, spec)
        self.assertEqual(spec['key'], 'licenses')
        self.assertTrue(spec['factors'])


class ScenePagesTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = _admin('scene_admin')

    def test_the_scene_pages_are_read_under_the_registries_right(self):
        from wama.accounts.permissions import app_id_for_path
        self.assertEqual(app_id_for_path('/common/scenes/licenses/'), 'registries')
        self.assertEqual(app_id_for_path('/common/scenes/models/data/'), 'registries')

    def test_an_anonymous_visitor_is_sent_to_the_login(self):
        from django.conf import settings
        for name in ('common:scene', 'common:scene_data'):
            response = self.client.get(reverse(name, args=['licenses']))
            self.assertEqual(response.status_code, 302, name)
            self.assertTrue(response.url.startswith(str(settings.LOGIN_URL)) or '/login' in response.url,
                            response.url)

    def test_a_scene_reserved_to_administrators_refuses_a_member(self):
        # La garde DÉCLARÉE par la scène est celle des pages d'administration (`admin_required`).
        member = User.objects.create_user('scene_member', password='x')
        register_scene(Scene(key='admin_only', page_title='x', kicker='x', data='x:y', permission='admin'))
        try:
            self.client.force_login(member)
            response = self.client.get(reverse('common:scene_data', args=['admin_only']))
            self.assertEqual(response.status_code, 302)
            self.assertNotIn('/scenes/', response.url)
        finally:
            SCENES.pop('admin_only', None)

    def test_a_scene_page_carries_its_declaration_and_the_address_of_its_data(self):
        self.client.force_login(self.admin)
        for key in ('licenses', 'models'):
            html = self.client.get(reverse('common:scene', args=[key])).content.decode()
            self.assertIn(f'id="wc-{key}-spec"', html)
            self.assertIn(reverse('common:scene_data', args=[key]), html)
            self.assertIn('data-generic', html)                 # pas d'adaptateur : le contrat direct
            self.assertIn("from 'wama/constellation'", html)
            data = self.client.get(reverse('common:scene_data', args=[key])).json()
            for part in ('nodes', 'groups', 'links', 'colorings'):
                self.assertIn(part, data, key)

    def test_a_scene_that_keeps_its_own_address_is_sent_there(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('common:scene', args=['users']))
        self.assertRedirects(response, reverse('accounts:user-constellation'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('common:scene', args=['nothing'])).status_code, 404)

    def test_a_registry_page_receives_the_button_of_its_scene(self):
        self.client.force_login(self.admin)
        scene_url = reverse('common:scene', args=['licenses'])
        self.assertIn(f'href="{scene_url}"', self.client.get(reverse('common:licenses_catalog')).content.decode())
        self.assertIn(f'href="{reverse("common:scene", args=["models"])}"',
                      self.client.get(reverse('model_manager:index')).content.decode())
        # Un registre sans scène n'a pas de bouton.
        self.assertNotIn('fa-circle-nodes', self.client.get(reverse('common:docs_catalog')).content.decode())


class LicenseSceneTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        from wama.common.models import Library
        from wama.model_manager.models import AIModel
        Library.objects.create(key='lib-a', name='Lib A', license='MIT License', author='A')
        Library.objects.create(key='lib-b', name='Lib B', license='mit')
        AIModel.objects.create(model_key='imager:nc', name='NC', model_type='diffusion', source='imager',
                               license='cc-by-nc-4.0')

    def test_one_star_per_licence_grouped_by_family_sized_by_what_it_covers(self):
        from wama.common.services.license_scene import license_scene
        data = license_scene(None)
        nodes = {n['id']: n for n in data['nodes']}
        mit, nc = nodes['lic:mit'], nodes['lic:cc-by-nc-4.0']
        # « MIT License » et « mit » sont UNE licence : la normalisation de l'audit, pas une copie.
        self.assertEqual(mit['size'], 2)
        self.assertEqual(len(mit['sats']), 2)
        self.assertEqual(mit['groups'], ['fam:0'])
        self.assertEqual(nc['groups'], ['fam:3'])
        self.assertEqual((mit['attrs']['rank'], nc['attrs']['rank']), (0, 3))
        families = {g['id'] for g in data['groups']}
        self.assertEqual(families, {'fam:0', 'fam:3'})           # seules les familles présentes
        for n in data['nodes']:
            for gid in n.get('groups', []):
                self.assertIn(gid, families)
        # Une app relie ce que sa composition traverse : chaque lien part d'une app, vers une licence.
        for link in data['links']:
            self.assertTrue(link['from'].startswith('app:') and link['to'].startswith('lic:'), link)
            self.assertIn(link['to'], nodes)


class ModelSceneTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        from wama.model_manager.models import AIModel
        cls.dev = User.objects.create_user('scene_dev', password='x')
        cls.other = User.objects.create_user('scene_other', password='x')
        AIModel.objects.create(model_key='imager:big', name='Big', model_type='diffusion', source='imager',
                               vram_gb=12, is_downloaded=True, backend_ref='diffusers',
                               capabilities={'task': 'text-to-image', 'modalities': ['image']})
        AIModel.objects.create(model_key='albert:chat', name='Chat', model_type='llm', source='albert',
                               execution='cloud')
        AIModel.objects.create(model_key='imager:proposed', name='Proposed', model_type='diffusion',
                               source='imager', is_proposed=True)
        AIModel.objects.create(model_key='imager:private', name='Private', model_type='diffusion',
                               source='imager', owner=cls.other, visibility='private')

    def test_the_scene_shows_the_catalogue_its_reader_sees(self):
        from wama.model_manager.services.model_scene import model_scene
        nodes = {n['id']: n for n in model_scene(self.dev)['nodes']}
        self.assertIn('imager:big', nodes)
        self.assertNotIn('imager:proposed', nodes)           # les propositions ont leur file
        self.assertNotIn('imager:private', nodes)            # le modèle privé d'un autre
        self.assertIn('imager:private', {n['id'] for n in model_scene(self.other)['nodes']})

    def test_a_local_model_is_sized_by_its_vram_and_a_remote_one_waits_in_its_layer(self):
        from wama.model_manager.services.model_scene import model_scene
        data = model_scene(self.dev)
        nodes = {n['id']: n for n in data['nodes']}
        big, chat = nodes['imager:big'], nodes['albert:chat']
        self.assertEqual((big['size'], big['layer']), (12, None))
        self.assertEqual((chat['size'], chat['layer']), (0, 'cloud'))
        self.assertEqual(big['sets'], {'tasks': ['text-to-image'], 'modalities': ['image']})
        self.assertEqual(big['attrs']['engine'], 'diffusers')
        self.assertEqual(big['cats']['state'], 'installed')
        groups = {g['id'] for g in data['groups']}
        for n in data['nodes']:
            for gid in n['groups']:
                self.assertIn(gid, groups)
        # La couche des distants existe, éteinte au départ.
        cloud = next(l for l in SCENES['models'].layers if l['key'] == 'cloud')
        self.assertEqual((cloud['role'], cloud['on']), ('nodes', False))

"""Le volet de l'enhancer MÉMORISE ses réglages par la brique commune (2026-09-29).

La table `UserSettings` propre à l'enhancer n'était jamais écrite : ses « défauts » étaient ceux
du modèle pour tout le monde, et le modèle, le débruitage et le blend du volet ne partaient
qu'avec « Tout démarrer » — un élément déposé naissait sur les défauts. Désormais le dépôt
poste le volet, l'élément naît complet, et ce qui a été posté devient la mémoire du volet
(`save_panel_settings` → `UserAppSetting`).
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from wama.common.tests_import_contract import _WITNESSES
from wama.common.utils.user_settings import read_panel_settings
from wama.enhancer.models import Enhancement
from wama.enhancer.params import MEDIA_PARAMS

User = get_user_model()


class PanelMemoryTest(TestCase):

    def _user(self, name):
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        user = User.objects.create_user(name, password='x')
        for role in (DEFAULT_APP_ACCESS.get('enhancer') or {}).get('roles', []):
            user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        return user

    def _deposit(self, **panel):
        ext, content = _WITNESSES['image']
        data = {'file': SimpleUploadedFile('witness' + ext, content(), content_type='image/png'),
                **panel}
        return self.client.post(reverse('enhancer:upload'), data)

    def setUp(self):
        self.me = self._user('enhancer_panel_me')
        self.client.force_login(self.me)

    def test_the_element_is_born_with_the_panel_settings(self):
        response = self._deposit(ai_model='BSRGANx2', denoise='true', blend_factor='0.3')
        self.assertLess(response.status_code, 400, response.content[:300])
        item = Enhancement.objects.filter(user=self.me).latest('id')
        self.assertEqual(('BSRGANx2', True, 0.3), (item.ai_model, item.denoise, item.blend_factor))

    def test_the_deposit_is_remembered_and_the_page_shows_it(self):
        self._deposit(ai_model='BSRGANx2', denoise='true', blend_factor='0.3')
        memory = read_panel_settings(self.me, 'enhancer', MEDIA_PARAMS)
        self.assertEqual(('BSRGANx2', True, 0.3),
                         (memory['ai_model'], memory['denoise'], memory['blend_factor']))
        page = self.client.get(reverse('enhancer:index')).content.decode()
        self.assertIn('value="BSRGANx2" selected', page)

    def test_another_user_does_not_inherit_it(self):
        """Contre-épreuve : la mémoire est celle de l'auteur, un autre repart des défauts."""
        self._deposit(ai_model='BSRGANx2', denoise='true', blend_factor='0.3')
        other = self._user('enhancer_panel_other')
        memory = read_panel_settings(other, 'enhancer', MEDIA_PARAMS)
        self.assertNotEqual('BSRGANx2', memory['ai_model'])
        self.assertFalse(memory['denoise'])

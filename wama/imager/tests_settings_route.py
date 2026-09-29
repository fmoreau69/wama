"""Les réglages d'UNE génération à l'adresse conventionnelle `settings/<pk>/` (2026-09-29).

La lecture (GET) occupait `settings/<id>/`, l'écriture avait dû prendre `settings/<pk>/save/` : le
seul écart de l'imager au chemin de `WAMA_APP_CONVENTIONS §3.1`. Les deux vues sont aiguillées
par `generation_settings` ; l'enregistrement reste couvert par le contrat générique
`common/tests_item_settings_contract`, ce fichier tient la LECTURE et la frontière d'accès.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from wama.imager.models import ImageGeneration

User = get_user_model()


class SettingsRouteTest(TestCase):

    def setUp(self):
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        self.me = User.objects.create_user('imager_settings_me', password='x')
        self.other = User.objects.create_user('imager_settings_other', password='x')
        for user in (self.me, self.other):
            for role in (DEFAULT_APP_ACCESS.get('imager') or {}).get('roles', []):
                user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.gen = ImageGeneration.objects.create(user=self.me, generation_mode='txt2img',
                                                  prompt='a lighthouse', steps=12)
        self.url = reverse('imager:update_settings', args=[self.gen.id])

    def test_the_conventional_address_reads_the_settings_on_get(self):
        self.client.force_login(self.me)
        response = self.client.get(self.url)
        self.assertEqual(200, response.status_code)
        self.assertEqual((self.gen.id, 'a lighthouse', 12),
                         (response.json()['id'], response.json()['prompt'], response.json()['steps']))

    def test_the_same_address_saves_on_post(self):
        self.client.force_login(self.me)
        response = self.client.post(self.url, {'steps': '20'})
        self.assertLess(response.status_code, 400, response.content[:200])
        self.gen.refresh_from_db()
        self.assertEqual(20, self.gen.steps)

    def test_another_user_can_neither_change_them_nor_use_another_method(self):
        """Contre-épreuve : la fusion n'ouvre rien — un autre utilisateur ne modifie pas, et une
        méthode autre que GET/POST est refusée."""
        self.client.force_login(self.other)
        self.assertEqual(404, self.client.post(self.url, {'steps': '30'}).status_code)
        self.gen.refresh_from_db()
        self.assertEqual(12, self.gen.steps)
        self.client.force_login(self.me)
        self.assertEqual(405, self.client.put(self.url).status_code)

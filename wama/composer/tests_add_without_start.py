"""Le bouton primaire du composer AJOUTE à la file, il ne lance rien (2026-09-29).

Règle des deux temps (`CARD_DESIGN §11.11` Étape 3, point 3 : « on ajoute, on règle, puis on
lance ») : la vue `generate` expédiait `compose_task` à la création. L'élément naît désormais en
attente ; le ▶ de sa card (`start`, `begin_processing`) le lance.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from wama.composer.models import ComposerGeneration

User = get_user_model()


class AddWithoutStartTest(TestCase):

    def setUp(self):
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        self.user = User.objects.create_user('composer_add_only', password='x')
        for role in (DEFAULT_APP_ACCESS.get('composer') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(self.user)

    def test_the_primary_button_queues_and_dispatches_nothing(self):
        with mock.patch('wama.composer.tasks.compose_task.apply_async') as dispatch:
            response = self.client.post(reverse('composer:generate'),
                                        {'prompt': 'a calm piano', 'model': 'musicgen-small',
                                         'duration': '5'})
        self.assertEqual(200, response.status_code, response.content[:300])
        dispatch.assert_not_called()
        gen = ComposerGeneration.objects.get(pk=response.json()['id'])
        self.assertEqual(('PENDING', ''), (gen.status, gen.task_id or ''))

    def test_the_start_view_still_launches(self):
        """Contre-épreuve : le ▶ de la card, lui, lance bien."""
        with mock.patch('wama.composer.tasks.compose_task.apply_async') as dispatch:
            gen_id = self.client.post(reverse('composer:generate'),
                                      {'prompt': 'x', 'model': 'musicgen-small',
                                       'duration': '5'}).json()['id']
            dispatch.return_value.id = 'no-task'
            self.client.post(reverse('composer:start', args=[gen_id]))
        dispatch.assert_called_once()

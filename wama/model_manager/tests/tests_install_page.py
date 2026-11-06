"""La page du model manager suit les installations sur la card de leur modèle (2026-11-06).

Le gabarit est RENDU (un gabarit neuf qui ne se compile pas sert un 500 à chaud) et la route qu'il
interroge rend les installations en cours et celles finies depuis le passage précédent, avec
l'heure du serveur — celle que la page renvoie au passage suivant.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from wama.model_manager.models import InstallEvent


class TheInstallPageTest(TestCase):

    def setUp(self):
        self.client.force_login(User.objects.create_superuser('install_page', 'p@x.fr', 'x'))

    def test_the_page_renders_the_common_block_on_the_card_and_no_veil(self):
        page = self.client.get(reverse('model_manager:index'))
        self.assertEqual(200, page.status_code)
        html = page.content.decode()
        for piece in ('function mmInstallSlot(', 'data-install-for=', 'WamaApp.paintProgress(',
                      'if (CAN_MANAGE) mmFollowInstalls();'):
            self.assertIn(piece, html)
        self.assertNotIn('mmProspectPoll', html, 'the veil that followed one install is gone')

    def test_the_route_gives_what_runs_and_what_ended_since_with_the_server_clock(self):
        now = timezone.now()
        InstallEvent.objects.create(kind='model', key='page:running', name='En cours',
                                    started_at=now)
        InstallEvent.objects.create(kind='model', key='page:ended', name='Fini', status='SUCCESS',
                                    started_at=now - timedelta(minutes=5), finished_at=now)
        url = reverse('model_manager:api_prospect_install_progress')
        first = self.client.get(url).json()
        self.assertEqual({'page:running'}, {r['model_key'] for r in first['installs']})
        since = (now - timedelta(seconds=1)).isoformat()
        second = self.client.get(url, {'since': since}).json()
        self.assertEqual({'page:running', 'page:ended'},
                         {r['model_key'] for r in second['installs']})
        self.assertTrue(second['now'])

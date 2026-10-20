"""Le VISITEUR sans compte dans l'app d'essai : une identité éphémère PAR SESSION (2026-10-04).

Décision de Fabien : le visiteur ne lance rien, sauf dans le converter — avec une persistance
par session, le compte `anonymous` étant unique (ses fichiers seraient vus de tous). Ce que ces
gardes tiennent : chaque visiteur possède ses éléments et ne voit pas ceux d'un autre ; le
compte partagé ne reçoit rien ; les bornes mordent ; l'identité part avec ses fichiers ; les
autres apps restent fermées ; un membre connecté n'est pas concerné.
"""
import json
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from wama.accounts import visitors
from wama.accounts.models import AppAccessPolicy
from wama.accounts.permissions import (ANONYMOUS_USERNAME, VISITOR_ACCOUNT_PREFIX, accessible,
                                       is_guest_account, user_tier)
from wama.converter.models import ConversionJob

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00'
       b'\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\x9d'
       b'\x16\x00\x00\x00\x00IEND\xaeB`\x82')


def _upload(client, name='photo.png'):
    return client.post(reverse('converter:upload'),
                       {'file': SimpleUploadedFile(name, PNG, 'image/png'), 'output_format': 'jpg'})


class VisitorSessionIdentityTests(TestCase):

    def setUp(self):
        cache.clear()
        # La politique se DÉCLARE : la ligne en base prime sur le défaut du code.
        AppAccessPolicy.objects.update_or_create(app_id='converter', defaults={'public': True})
        self.addCleanup(self._remove_visitor_files)

    def _remove_visitor_files(self):
        import shutil
        for user in User.objects.filter(username__startswith=VISITOR_ACCOUNT_PREFIX):
            shutil.rmtree(Path(settings.MEDIA_ROOT) / 'users' / str(user.pk), ignore_errors=True)

    def test_the_converter_is_the_declared_trial_app(self):
        from django.contrib.auth.models import AnonymousUser
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, all_gated_apps
        self.assertTrue(DEFAULT_APP_ACCESS['converter']['public'])
        self.assertEqual(['converter'],
                         [a for a in sorted(all_gated_apps()) if accessible(AnonymousUser(), 'app', a)])

    def test_a_first_gesture_gives_the_visitor_an_identity_of_its_own(self):
        response = _upload(self.client)
        self.assertEqual(200, response.status_code, response.content)
        job = ConversionJob.objects.get(pk=response.json()['id'])
        self.assertTrue(job.user.username.startswith(VISITOR_ACCOUNT_PREFIX))
        self.assertEqual(('anonymous', False, []),
                         (user_tier(job.user), job.user.is_active, list(job.user.groups.all())))
        self.assertTrue(is_guest_account(job.user))
        self.assertEqual(job.user.pk, self.client.session[visitors.SESSION_KEY])
        self.assertTrue(job.input_file.name.startswith(f'users/{job.user.pk}/'), job.input_file.name)
        # Le même visiteur garde la MÊME identité au geste suivant.
        again = ConversionJob.objects.get(pk=_upload(self.client, 'second.png').json()['id'])
        self.assertEqual(job.user, again.user)

    def test_the_shared_anonymous_account_receives_nothing(self):
        _upload(self.client)
        self.assertEqual(0, ConversionJob.objects.filter(user__username=ANONYMOUS_USERNAME).count())

    def test_two_visitors_never_see_each_other(self):
        first, second = Client(), Client()
        mine = _upload(first, 'first_visitor.png').json()['id']
        theirs = _upload(second, 'second_visitor.png').json()['id']
        self.assertNotEqual(ConversionJob.objects.get(pk=mine).user,
                            ConversionJob.objects.get(pk=theirs).user)
        page = first.get(reverse('converter:index')).content.decode()
        self.assertIn('first_visitor.png', page)
        self.assertNotIn('second_visitor.png', page)
        # Ni lecture, ni téléchargement, ni réglage, ni suppression de l'élément d'un autre.
        self.assertEqual(404, first.get(reverse('converter:status', args=[theirs])).status_code)
        self.assertEqual(404, first.get(reverse('converter:download', args=[theirs])).status_code)
        self.assertEqual(404, first.post(reverse('converter:update_settings', args=[theirs]),
                                         {'output_format': 'webp'}).status_code)
        self.assertEqual(404, first.post(reverse('converter:delete', args=[theirs])).status_code)
        self.assertTrue(ConversionJob.objects.filter(pk=theirs).exists())
        # Contre-épreuve : sur le SIEN, les mêmes routes répondent.
        self.assertEqual(200, first.get(reverse('converter:status', args=[mine])).status_code)

    def test_the_page_keeps_showing_a_visitor_not_a_member(self):
        """Les gabarits communs lisent `user.is_authenticated` : la PAGE garde un `AnonymousUser`
        (en-tête de visiteur, pas de menu de membre), l'identité vit dans `request.wama_visitor`."""
        _upload(self.client)
        response = self.client.get(reverse('converter:index'))
        self.assertEqual(200, response.status_code)
        self.assertFalse(response.context['user'].is_authenticated)

    def test_a_read_before_any_gesture_creates_no_identity(self):
        self.assertEqual(200, self.client.get(reverse('converter:index')).status_code)
        self.assertEqual(200, self.client.get(reverse('converter:global_progress')).status_code)
        self.assertFalse(User.objects.filter(username__startswith=VISITOR_ACCOUNT_PREFIX).exists())

    def test_the_other_apps_stay_closed_to_the_visitor(self):
        _upload(self.client)                                    # même AVEC une identité
        response = self.client.post(reverse('avatarizer:create'), {'text_content': 'bonjour'})
        self.assertEqual(403, response.status_code)
        self.assertTrue(response.json()['login_required'])

    def test_routes_that_make_the_server_fetch_stay_closed(self):
        for route in ('converter:batch_create', 'converter:batch_preview', 'converter:quick_convert'):
            response = self.client.post(reverse(route), {})
            self.assertEqual(403, response.status_code, route)
            self.assertTrue(response.json()['visitor'], route)

    @override_settings(WAMA_VISITOR_MAX_ITEMS=1)
    def test_the_item_limit_bites(self):
        self.assertEqual(200, _upload(self.client).status_code)
        refused = _upload(self.client, 'trop.png')
        self.assertEqual(429, refused.status_code)
        self.assertIn('Limite', refused.json()['error'])

    @override_settings(WAMA_VISITOR_MAX_UPLOAD_MB=0)
    def test_the_size_limit_bites_before_anything_is_created(self):
        self.assertEqual(413, _upload(self.client).status_code)
        self.assertFalse(User.objects.filter(username__startswith=VISITOR_ACCOUNT_PREFIX).exists())

    @override_settings(WAMA_VISITOR_NEW_PER_ADDRESS_HOUR=1)
    def test_new_identities_are_rate_limited_per_address(self):
        self.assertEqual(200, _upload(Client()).status_code)
        self.assertEqual(429, _upload(Client()).status_code)

    def test_an_idle_identity_is_purged_with_its_items_and_files(self):
        job = ConversionJob.objects.get(pk=_upload(self.client).json()['id'])
        visitor, home = job.user, Path(settings.MEDIA_ROOT) / 'users' / str(job.user.pk)
        self.assertTrue(home.is_dir())
        # Contre-épreuve : une identité ACTIVE n'est pas touchée.
        self.assertEqual(0, visitors.purge_expired()['purged'])
        User.objects.filter(pk=visitor.pk).update(last_login=timezone.now() - timedelta(hours=25))
        self.assertEqual(1, visitors.purge_expired(dry_run=True)['purged'])
        self.assertTrue(User.objects.filter(pk=visitor.pk).exists(), 'un essai à blanc ne purge pas')
        self.assertEqual(1, visitors.purge_expired()['purged'])
        self.assertFalse(User.objects.filter(pk=visitor.pk).exists())
        self.assertFalse(ConversionJob.objects.filter(pk=job.pk).exists())
        self.assertFalse(home.exists())
        # La session qui portait l'identité repart à neuf, sans erreur.
        self.assertEqual(200, self.client.get(reverse('converter:global_progress')).status_code)

    def test_the_purge_never_touches_a_member_or_the_shared_account(self):
        member = User.objects.create_user('visitor_purge_member', password='x')
        User.objects.filter(pk=member.pk).update(last_login=timezone.now() - timedelta(days=400))
        from wama.accounts.views import get_or_create_anonymous_user
        shared = get_or_create_anonymous_user()
        visitors.purge_expired()
        self.assertTrue(User.objects.filter(pk__in=[member.pk, shared.pk]).count() == 2)

    def test_a_logged_in_member_is_not_given_a_visitor_identity(self):
        member = User.objects.create_user('visitor_member', password='x')
        self.client.force_login(member)
        job = ConversionJob.objects.get(pk=_upload(self.client).json()['id'])
        self.assertEqual(member, job.user)
        self.assertNotIn(visitors.SESSION_KEY, self.client.session)

    def test_a_closed_converter_rejects_the_visitor_again(self):
        """Contre-épreuve de la DÉCLARATION : sans `public`, la garde commune reprend la main."""
        AppAccessPolicy.objects.filter(app_id='converter').update(public=False)
        response = _upload(self.client)
        self.assertEqual(403, response.status_code)
        self.assertTrue(json.loads(response.content)['login_required'])


class VisitorNoticeTests(TestCase):
    """La page DIT au visiteur que son essai est temporaire et borné — et ne le dit pas à un membre."""

    def setUp(self):
        AppAccessPolicy.objects.update_or_create(app_id='converter', defaults={'public': True})

    @override_settings(WAMA_VISITOR_TTL_HOURS=6, WAMA_VISITOR_MAX_UPLOAD_MB=50, WAMA_VISITOR_MAX_ITEMS=3)
    def test_the_page_tells_the_visitor_the_limits_read_from_the_settings(self):
        page = self.client.get(reverse('converter:index')).content.decode()
        self.assertIn('converterVisitorNotice', page)
        for expected in ('6 h', '50 Mo', '3 éléments'):
            self.assertIn(expected, page)

    def test_a_member_sees_no_trial_notice(self):
        self.client.force_login(User.objects.create_user('notice_member', password='x'))
        self.assertNotIn('converterVisitorNotice', self.client.get(reverse('converter:index')).content.decode())

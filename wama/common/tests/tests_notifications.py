"""Notifications IN WAMA — `WAMA_COLLABORATION.md §2.3` (first slice, 2026-09-24).

First event type: a Celery worker died (Fabien: « il me faudrait aussi une notification dans
wama lui-même »). The brick: recipient, kind, link, read / unread ; a header badge and a page.
Email and in-app go together through `notify_admins`.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from wama.common.models import Notification
from wama.common.utils.notifications import infrastructure_admins, notify_admins, notify_in_app


class NotificationBrickTest(TestCase):

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser('notif_admin', 'admin@test.local', 'x')
        self.member = User.objects.create_user('notif_member', 'member@test.local', 'x')

    def test_in_app_notifications_are_created_unread_for_each_recipient(self):
        self.assertEqual(2, notify_in_app([self.admin, self.member], 'test', 'Title', 'Body'))
        self.assertEqual(2, Notification.objects.filter(kind='test', read_at__isnull=True).count())

    def test_infrastructure_admins_are_those_the_model_manager_lets_in(self):
        admins = infrastructure_admins()
        self.assertIn(self.admin, admins)
        self.assertNotIn(self.member, admins)

    # Sans alias déclarés : le test parle des adresses PERSONNELLES. Il lisait ceux du `.env` de la
    # machine, et rougissait dès qu'on y déclarait `wama-admin@` (relevé le 2026-10-06).
    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                       WAMA_ADMIN_EMAILS=[], WAMA_DEV_EMAILS=[])
    def test_notify_admins_writes_in_wama_and_by_email(self):
        created, sent = notify_admins('worker_died', 'Worker gpu arrêté', 'détail')
        self.assertGreaterEqual(created, 1)
        self.assertTrue(sent)
        self.assertTrue(Notification.objects.filter(recipient=self.admin, kind='worker_died').exists())
        self.assertFalse(Notification.objects.filter(recipient=self.member).exists())
        self.assertIn('admin@test.local', mail.outbox[0].to)

    def test_the_header_badge_counts_unread_and_the_page_marks_them_read(self):
        notify_in_app([self.admin], 'test', 'Unread one')
        self.client.force_login(self.admin)
        page = self.client.get(reverse('common:notifications'))
        self.assertEqual(200, page.status_code)
        self.assertContains(page, 'Unread one')
        self.assertEqual(1, page.context['unread_notifications'])     # header badge
        self.client.post(reverse('common:notifications_mark_read'))
        self.assertFalse(Notification.objects.filter(recipient=self.admin,
                                                     read_at__isnull=True).exists())

    def test_one_can_only_mark_ones_own_notifications(self):
        notify_in_app([self.admin], 'test', 'Not yours')
        other = Notification.objects.get(recipient=self.admin)
        self.client.force_login(self.member)
        self.client.post(reverse('common:notifications_mark_read'), {'id': other.pk})
        other.refresh_from_db()
        self.assertIsNone(other.read_at)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   WAMA_ADMIN_EMAILS=[], WAMA_DEV_EMAILS=[], WAMA_SUPPORT_EMAIL='')
class StaffAddressesTest(TestCase):
    """Functional staff addresses (2026-09-26, Fabien: aliases wama-admin@ / wama-dev@ /
    wama-support@): mails go to the declared alias, else to each account of the tier.

    ⚠ HERMETIC since 2026-10-06 : without the class-level settings above, these tests read the
    aliases of the machine's `.env` and turned red as soon as `wama-admin@` was declared there.
    The tests that need an alias declare it themselves."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser('staff_admin', 'boss@test.local', 'x')
        self.dev = User.objects.create_user('staff_dev', 'dev@test.local', 'x')
        self.dev.profile.account_tier = 'developpeur'
        self.dev.profile.save()
        User.objects.create_user('staff_member', 'member@test.local', 'x')

    def test_without_aliases_each_account_of_the_tier_is_written_to(self):
        from wama.common.utils.notifications import staff_emails
        self.assertEqual(['boss@test.local'], staff_emails(('admin',)))
        self.assertEqual(['dev@test.local'], staff_emails(('dev',)))

    @override_settings(WAMA_ADMIN_EMAILS=['wama-admin@test.local'],
                       WAMA_DEV_EMAILS=['wama-dev@test.local'])
    def test_declared_aliases_replace_the_personal_addresses(self):
        notify_admins('worker_died', 'Worker gpu arrêté', 'détail')
        self.assertEqual(['wama-admin@test.local', 'wama-dev@test.local'], mail.outbox[0].to)
        # In-app notifications still reach each ACCOUNT: an alias has no inbox in WAMA.
        self.assertTrue(Notification.objects.filter(recipient=self.admin).exists())

    @override_settings(WAMA_SUPPORT_EMAIL='wama-support@test.local')
    def test_replies_go_to_support(self):
        from wama.common.utils.notifications import notify_emails
        notify_emails(['someone@test.local', 'someone@test.local'], 'Sujet', 'Corps')
        self.assertEqual(['wama-support@test.local'], mail.outbox[0].reply_to)
        self.assertEqual(['someone@test.local'], mail.outbox[0].to)   # no duplicate

    def test_no_support_address_means_no_reply_to(self):
        from wama.common.utils.notifications import notify_emails
        notify_emails(['someone@test.local'], 'Sujet', 'Corps')
        self.assertEqual([], mail.outbox[0].reply_to)


class WorkerDiedCommandTest(TestCase):
    """`manage.py worker_died`, called by `scripts/worker_watchdog.sh` after a death."""

    def setUp(self):
        get_user_model().objects.create_superuser('wd_admin', 'wd@test.local', 'x')

    def test_it_settles_the_dead_process_tasks_and_warns_the_admins(self):
        with mock.patch('wama.common.utils.process_control.reconcile_dead_worker_tasks',
                        return_value=[('converter', 'ConversionJob', 7)]) as settle:
            call_command('worker_died', '--node', 'gpu@host', '--outcome', 'restarted',
                         '--restarts', '1', stdout=mock.MagicMock())
        settle.assert_called_once_with('gpu@host')
        note = Notification.objects.get(kind='worker_died')
        self.assertIn('gpu@host', note.title)
        self.assertIn('converter #7', note.body)

    def test_a_suspended_restart_says_so(self):
        with mock.patch('wama.common.utils.process_control.reconcile_dead_worker_tasks',
                        return_value=[]):
            call_command('worker_died', '--node', 'gpu@host', '--outcome', 'gave_up',
                         '--restarts', '3', stdout=mock.MagicMock())
        self.assertIn('SUSPENDUES', Notification.objects.get(kind='worker_died').body)


class JobEndNotificationTest(TestCase):
    """The end of a task — `notify_job_end`, the ONE end point of the tasks (2026-10-06).

    Until then the OWNER only got the e-mail (and without SMTP, nothing): the in-app
    notification went to collaborators alone. It now reaches the owner too, by `notify_on`
    only (the e-mail is a channel, the notification in WAMA another — `WAMA_COLLABORATION
    §5.2`), and it DESIGNATES its element: that is what the channel gateway reads to post the
    result in the thread the task was asked from.
    """

    def setUp(self):
        import shutil
        import tempfile

        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.describer.models import Description
        root = tempfile.mkdtemp()
        media_root = override_settings(MEDIA_ROOT=root)
        media_root.enable()
        self.addCleanup(media_root.disable)
        self.addCleanup(shutil.rmtree, root, True)
        self.owner = get_user_model().objects.create_user('job_end_owner', password='x')
        _lot, (self.card,) = _lot_de(Description, self.owner, 1)

    def _end(self, success=True, detail=''):
        from wama.common.utils.notifications import notify_job_end
        notify_job_end(self.card, 'describer', 'Describer', 'témoin', success, detail=detail)
        return Notification.objects.filter(recipient=self.owner)

    def _prefer(self, **prefs):
        profile = self.owner.profile
        for field, value in prefs.items():
            setattr(profile, field, value)
        profile.save()

    def test_the_owner_is_notified_in_wama_and_the_notification_names_the_element(self):
        from wama.common.services.journal import app_queue_url
        note = self._end().get()
        self.assertEqual('job_done', note.kind)
        self.assertEqual('Describer — « témoin » terminé', note.title)
        self.assertEqual(('describer', 'Description', str(self.card.pk)),
                         (note.app, note.object_type, note.object_id))
        self.assertEqual(app_queue_url('describer'), note.url)
        self.assertTrue(note.url, 'the queue page of the app, from the common resolver')

    def test_a_failure_is_notified_with_its_cause(self):
        note = self._end(success=False, detail='modèle introuvable').get()
        self.assertEqual(('job_failed', 'modèle introuvable'), (note.kind, note.body))
        self.assertIn('a échoué', note.title)

    def test_cutting_the_email_does_not_cut_the_notification_in_wama(self):
        self._prefer(notify_email=False)
        self.assertEqual(1, self._end().count())

    def test_the_notification_in_wama_follows_notify_on(self):
        self._prefer(notify_on='failure')
        self.assertFalse(self._end(success=True).exists(), 'a success the user did not ask for')
        self.assertEqual(1, self._end(success=False).count())
        self._prefer(notify_on='none')
        self.assertEqual(1, self._end(success=False).count(), 'nothing more once « Aucune »')

    def test_the_email_keeps_its_two_preferences(self):
        """Counter-check: `wants_notification` (e-mail) still needs `notify_email` AND
        `notify_on` — only the in-app channel was freed from the e-mail switch."""
        profile = self.owner.profile
        self.assertTrue(profile.wants_notification(True))
        profile.notify_email = False
        self.assertFalse(profile.wants_notification(True))
        self.assertTrue(profile.wants_in_app_notification(True))

    def test_the_task_skeleton_end_designates_the_element(self):
        """Wiring: the common skeleton passes its `app_id` — the family the gateway reads."""
        from wama.common.utils.task_skeleton import _notify
        _notify(self.card, 'Describer', 'témoin', True, app_id='describer')
        note = Notification.objects.get(recipient=self.owner)
        self.assertEqual(('describer', str(self.card.pk)), (note.app, note.object_id))

    def test_a_collaborator_is_notified_with_the_element_too(self):
        collaborator = get_user_model().objects.create_user('job_end_collab', password='x')
        with mock.patch('wama.common.services.access_requests.collaborators_of',
                        return_value=[collaborator]):
            self._end()
        note = Notification.objects.get(recipient=collaborator)
        self.assertEqual(('describer', str(self.card.pk)), (note.app, note.object_id))
        self.assertIn('collaboration', note.body)


class NotificationSoundTest(TestCase):
    """The sound of a notification in WAMA (2026-10-06, Fabien's request: the main benefit he
    saw in a Discord ping was its SOUND). The SERVER decides — sounding kind + the profile's
    switch — and the page only plays what it is told (`notifications.SOUND_BY_KIND`)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('sound_owner', password='x')
        self.client.force_login(self.user)

    def _recent(self):
        seen = Notification.objects.filter(recipient=self.user).order_by('pk').first()
        after = (seen.pk - 1) if seen else 0
        return self.client.get(reverse('common:api_notifications_recent'), {'after': after}).json()

    def test_the_end_of_a_task_sounds_and_says_how_it_ended(self):
        notify_in_app([self.user], 'job_done', 'Describer — « a » terminé')
        notify_in_app([self.user], 'job_failed', 'Describer — « b » a échoué')
        self.assertEqual(['done', 'failed'], [item['sound'] for item in self._recent()['items']])

    def test_other_notifications_stay_silent(self):
        notify_in_app([self.user], 'access_request', 'Demande d’accès')
        notify_in_app([self.user], 'worker_died', 'Worker arrêté')
        self.assertEqual(['', ''], [item['sound'] for item in self._recent()['items']])

    def test_the_sound_is_on_by_default_and_can_be_cut(self):
        self.assertTrue(self.user.profile.notify_sound, 'a sound on nowhere is never discovered')
        profile = self.user.profile
        profile.notify_sound = False
        profile.save()
        notify_in_app([self.user], 'job_done', 'x')
        self.assertEqual([''], [item['sound'] for item in self._recent()['items']])

    def test_the_profile_saves_the_switch_and_keeps_it_when_absent(self):
        import json
        url = reverse('accounts:profile-notifications')
        body = {'notify_email': True, 'notify_on': 'both', 'notify_sound': False}
        self.client.post(url, json.dumps(body), content_type='application/json')
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.notify_sound)
        del body['notify_sound']                     # an older page that does not send it
        self.client.post(url, json.dumps(body), content_type='application/json')
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.notify_sound, 'an absent preference keeps its value')

    def test_the_profile_page_offers_the_switch(self):
        page = self.client.get(reverse('accounts:profile'))
        self.assertContains(page, 'id="notifySound"')
        self.assertContains(page, "WamaApp.playNotificationSound('done')")

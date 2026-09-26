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

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
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


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class StaffAddressesTest(TestCase):
    """Functional staff addresses (2026-09-26, Fabien: aliases wama-admin@ / wama-dev@ /
    wama-support@): mails go to the declared alias, else to each account of the tier."""

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

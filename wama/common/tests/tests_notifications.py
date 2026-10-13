"""Notifications IN WAMA — `WAMA_COLLABORATION.md §2.3` (first slice, 2026-09-24).

First event type: a Celery worker died (Fabien: « il me faudrait aussi une notification dans
wama lui-même »). The brick: recipient, kind, link, read / unread ; a header badge and a page.
Email and in-app go together through `notify_admins`.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
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


class OpeningANotificationMarksItReadTest(TestCase):
    """« Ouvrir » marque la notification lue, puis mène à son lien (2026-10-07, remarque de
    Fabien : il fallait cliquer « Marquer comme lu » en plus)."""

    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user('notif_open_member', 'open@test.local', 'x')
        self.client.force_login(self.member)

    def _note(self, url, recipient=None):
        notify_in_app([recipient or self.member], 'test', 'Title', url=url)
        return Notification.objects.filter(kind='test').latest('pk')

    def test_opening_marks_read_and_follows_the_link(self):
        note = self._note('/describer/')
        rep = self.client.get(reverse('common:notification_open', args=[note.pk]))
        self.assertRedirects(rep, '/describer/', fetch_redirect_response=False)
        note.refresh_from_db()
        self.assertIsNotNone(note.read_at)

    def test_a_link_outside_wama_is_not_followed(self):
        note = self._note('https://example.org/phishing')
        rep = self.client.get(reverse('common:notification_open', args=[note.pk]))
        self.assertRedirects(rep, reverse('common:notifications'), fetch_redirect_response=False)

    def test_someone_elses_notification_cannot_be_opened(self):
        other = get_user_model().objects.create_user('notif_open_other', 'o@test.local', 'x')
        note = self._note('/describer/', recipient=other)
        self.assertEqual(404, self.client.get(
            reverse('common:notification_open', args=[note.pk])).status_code)
        note.refresh_from_db()
        self.assertIsNone(note.read_at)

    def test_the_page_and_the_popup_open_through_this_route(self):
        note = self._note('/describer/')
        page = self.client.get(reverse('common:notifications')).content.decode()
        self.assertIn(f'/common/notifications/{note.pk}/open/', page)
        from pathlib import Path
        from django.conf import settings
        js = (Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-app-base.js').read_text(
            encoding='utf-8')
        self.assertIn("/common/notifications/' + encodeURIComponent(item.id) +", js)


class BellPanelRoutesTest(TestCase):
    """The PANEL of the bell (2026-10-13, Fabien: « je veux pouvoir interagir avec les
    notifications directement dans la petite fenêtre ») — its routes: the list, then read / unread
    / delete one, read all. Each touches the caller's own notifications only."""

    def setUp(self):
        User = get_user_model()
        self.me = User.objects.create_user('panel_me', password='x')
        self.other = User.objects.create_user('panel_other', password='x')
        self.client.force_login(self.me)

    def _note(self, user=None, kind='job_done', title='Done', url='/describer/', read=False):
        from django.utils import timezone
        return Notification.objects.create(recipient=user or self.me, kind=kind, title=title,
                                           url=url, read_at=timezone.now() if read else None)

    def _list(self, **params):
        return self.client.get(reverse('common:api_notifications_list'), params).json()

    def _act(self, note, action):
        return self.client.post(reverse('common:api_notification_act', args=[note.pk, action]))

    def test_the_panel_lists_ones_own_notifications_newest_first_with_their_style(self):
        old = self._note(title='old', read=True)
        new = self._note(kind='job_failed', title='new')
        self._note(user=self.other, title='not mine')
        data = self._list()
        self.assertEqual([new.pk, old.pk], [n['id'] for n in data['items']])
        self.assertEqual(1, data['unread'])
        first = data['items'][0]
        self.assertEqual(('fa-times-circle', 'danger', False), (first['icon'], first['tone'], first['read']))
        # « Ouvrir » goes through the route that marks it read (2026-10-07).
        self.assertEqual(reverse('common:notification_open', args=[new.pk]), first['open_url'])
        self.assertEqual([], first['actions'])

    def test_the_unread_filter_and_the_limit(self):
        self._note(read=True)
        unread = [self._note(title=f'u{i}') for i in range(3)]
        self.assertEqual({n.pk for n in unread}, {n['id'] for n in self._list(filter='unread')['items']})
        self.assertEqual(2, len(self._list(limit=2)['items']))
        self.assertEqual(4, self._list(limit='nope')['total'])

    def test_read_unread_and_delete_act_on_ones_own_notification(self):
        note = self._note()
        self.assertEqual({'done': True, 'unread': 0}, self._act(note, 'read').json())
        self.assertEqual(1, self._act(note, 'unread').json()['unread'])
        note.refresh_from_db()
        self.assertIsNone(note.read_at)
        self.assertTrue(self._act(note, 'delete').json()['done'])
        self.assertFalse(Notification.objects.filter(pk=note.pk).exists())

    def test_someone_elses_notification_is_out_of_reach(self):
        theirs = self._note(user=self.other)
        for action in ('read', 'delete'):
            self.assertEqual(404, self._act(theirs, action).status_code)
        theirs.refresh_from_db()
        self.assertIsNone(theirs.read_at)

    def test_an_unknown_gesture_is_refused(self):
        self.assertEqual(400, self._act(self._note(), 'archive').status_code)

    def test_read_all_marks_every_unread_of_ones_own_only(self):
        self._note(); self._note()
        theirs = self._note(user=self.other)
        rep = self.client.post(reverse('common:api_notifications_read_all')).json()
        self.assertEqual((True, 2, 0), (rep['done'], rep['marked'], rep['unread']))
        theirs.refresh_from_db()
        self.assertIsNone(theirs.read_at)


class BellPanelAccessRequestTest(TestCase):
    """A gesture PROPER to a kind, declared by the server (`notification_panel.ACTIONS_BY_KIND`):
    « Accorder / Refuser » an access request — for the OWNER, while the request waits."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp()
        setting = override_settings(MEDIA_ROOT=self.tmp)
        setting.enable()
        self.addCleanup(setting.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from wama.common.services.access_requests import request_access
        from wama.common.services.sharing import partager
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.describer.models import Description
        User = get_user_model()
        self.owner = User.objects.create_user('panel_owner', password='x')
        self.requester = User.objects.create_user('panel_requester', password='x')
        _lot, (card,) = _lot_de(Description, self.owner, 1)
        partager(self.owner, card, 'public')
        self.grant = request_access(self.requester, card, 'own', surface='describer')

    def _items(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('common:api_notifications_list')).json()['items']

    def test_the_owner_gets_accept_and_refuse_while_the_request_waits(self):
        (item,) = [n for n in self._items(self.owner) if n['kind'] == 'access_request']
        answer = reverse('common:access_request_answer', args=[self.grant.pk])
        self.assertEqual([('Accorder', answer, {'accept': '1'}), ('Refuser', answer, {'accept': '0'})],
                         [(a['label'], a['post'], a['data']) for a in item['actions']])
        # Refused from the panel's own gesture: the request no longer waits, the gestures go.
        self.assertTrue(self.client.post(answer, item['actions'][1]['data']).json()['done'])
        (item,) = [n for n in self._items(self.owner) if n['kind'] == 'access_request']
        self.assertEqual([], item['actions'])

    def test_a_recipient_who_does_not_own_the_element_is_offered_nothing_to_answer(self):
        # The request's notification held by someone who is NOT the owner (ownership moved since,
        # or a copy): the gestures are computed from who owns the element NOW, never from who
        # received the notification. (A first version looped over the requester's items — who
        # never receives this kind: it passed with the check removed. Counter-proof, 2026-10-13.)
        Notification.objects.create(recipient=self.requester, kind='access_request', title='copy',
                                    url=f'/common/requests/{self.grant.pk}/')
        (item,) = [n for n in self._items(self.requester) if n['kind'] == 'access_request']
        self.assertEqual([], item['actions'])


class ArrivalWhileTheBellPanelIsOpenTest(SimpleTestCase):
    """A NEW notification reaches the page through the relève of `wama-app-base.js` (every 60 s):
    with the panel closed it pops up bottom right; with the panel OPEN it is listed there instead
    — a pop-up would say it twice. Either way the relève announces `wama:notifications`, which the
    open panel reloads on (2026-10-13). Run in V8 on the real file."""

    STUBS = """
    var events = [], popups = 0;
    function fakeEl() {
      return {style: {}, className: '', setAttribute: function () {}, addEventListener: function () {},
              appendChild: function (c) { if (c.className === 'wama-notif-popup') popups++; },
              querySelector: function () { return {addEventListener: function () {}}; },
              remove: function () {}};
    }
    var bell = fakeEl();
    document.getElementById = function (id) { return id === 'wamaNotificationsLink' ? bell : null; };
    document.createElement = function () { return fakeEl(); };
    document.body = fakeEl();
    document.dispatchEvent = function (e) { events.push(e.type); };
    window.CustomEvent = function (type, init) { this.type = type; this.detail = init && init.detail; };
    var CustomEvent = window.CustomEvent;
    localStorage.getItem = function (k) { return k === 'wama.notifications.lastSeen' ? '5' : null; };
    // Le `fetch` GLOBAL (celui que le code appelle) remplace celui du harnais, qui ne répond
    // jamais ; `window.fetch` est ce que la relève vérifie avant de partir.
    fetch = window.fetch = function () {
      return Promise.resolve({ok: true, headers: {get: function () { return 'application/json'; }},
        json: function () { return {unread: 1, last_id: 6,
                                    items: [{id: 6, title: 'Fini', body: '', url: '', sound: ''}]}; }});
    };
    """

    def _arrive(self, panel_open):
        import importlib.util
        if importlib.util.find_spec('py_mini_racer') is None:
            self.skipTest('py_mini_racer absent de ce venv')
        from py_mini_racer import MiniRacer
        from wama.common.tests.tests_cap_from_js import FAKE_DOM
        from wama.common.tests.tests_poller_js import HARNESS, JS
        v8 = MiniRacer()
        v8.eval(FAKE_DOM + HARNESS)
        v8.eval((JS / 'wama-app-base.js').read_text(encoding='utf-8'))
        v8.eval(self.STUBS)
        v8.eval('window.WamaNotifications = {isOpen: function () { return %s; }};'
                % ('true' if panel_open else 'false'))
        v8.eval('window.WamaApp.checkNotifications();')
        v8.eval('1')                                  # la réponse se règle entre deux `eval`
        return v8.eval('popups'), list(v8.eval('JSON.parse(JSON.stringify(events))'))

    def test_closed_panel_the_arrival_pops_up_bottom_right(self):
        self.assertEqual((1, ['wama:notifications']), self._arrive(panel_open=False))

    def test_open_panel_the_arrival_is_not_said_twice(self):
        self.assertEqual((0, ['wama:notifications']), self._arrive(panel_open=True))


class BellPanelRenderingTest(SimpleTestCase):
    """The panel's rendering is PURE (state → HTML), run here in V8: escaping, unread marks, the
    server-declared gestures, the consent step, the undo line, the empty states, the footer."""

    def setUp(self):
        import importlib.util
        if importlib.util.find_spec('py_mini_racer') is None:
            self.skipTest('py_mini_racer absent de ce venv')
        from py_mini_racer import MiniRacer
        from wama.common.tests.tests_cap_from_js import FAKE_DOM
        from wama.common.tests.tests_poller_js import HARNESS, JS
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM + HARNESS)
        # La brique commune d'abord (l'échappement en vient), comme dans `base.html`.
        self.v8.eval((JS / 'wama-app-base.js').read_text(encoding='utf-8'))
        self.v8.eval((JS / 'wama-notifications.js').read_text(encoding='utf-8'))

    def _render(self, **state):
        import json
        base = {'filter': 'all', 'items': [], 'unread': 0, 'loading': False, 'error': False,
                'expanded': {}, 'busy': {}, 'consent': {}, 'pending': {}}
        base.update(state)
        return self.v8.eval(f'window.WamaNotifications._renderPanel({json.dumps(base)}, '
                            f'Date.parse("2026-10-13T12:00:00Z"))')

    @staticmethod
    def _item(**kw):
        item = {'id': 7, 'kind': 'job_done', 'title': 'Fini', 'body': '', 'app': '',
                'open_url': '/common/notifications/7/open/', 'created_at': '2026-10-13T11:55:00Z',
                'read': False, 'icon': 'fa-check-circle', 'tone': 'success', 'actions': []}
        item.update(kw)
        return item

    def test_a_title_is_escaped_and_an_unread_one_is_marked(self):
        html = self._render(items=[self._item(title='<img src=x onerror=alert(1)>')], unread=1)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', html)
        self.assertNotIn('<img src=x', html)
        self.assertIn('wn-item is-unread', html)
        self.assertIn('wn-dot', html)
        self.assertIn('il y a 5 min', html)
        self.assertIn('Non lues <span class="wn-count">1</span>', html)

    def test_a_read_one_offers_to_mark_it_unread_and_read_all_is_off(self):
        html = self._render(items=[self._item(read=True)])
        self.assertNotIn('is-unread', html)
        self.assertIn('Marquer comme non lue', html)
        self.assertIn('data-wn-readall title="Tout marquer comme lu" aria-label="Tout marquer comme lu" disabled', html)

    def test_the_server_declared_gestures_and_their_consent_step(self):
        actions = [{'label': 'Accorder', 'icon': 'fa-check', 'tone': 'success', 'post': '/a/', 'data': {}},
                   {'label': 'Refuser', 'icon': 'fa-times', 'tone': 'danger', 'post': '/a/', 'data': {}}]
        html = self._render(items=[self._item(actions=actions)])
        self.assertIn('class="wn-btn tone-success" data-wn-do="0"', html)
        self.assertIn('class="wn-btn tone-danger" data-wn-do="1"', html)
        busy = self._render(items=[self._item(actions=actions)], busy={'7': True}, unread=1)
        self.assertEqual(2, busy.count(' disabled>'))
        consent = self._render(items=[self._item(actions=actions)],
                               consent={'7': {'statement': 'Je cède <b>tout</b>', 'index': 0, 'label': 'Accorder'}})
        self.assertIn('Je cède &lt;b&gt;tout&lt;/b&gt;', consent)
        self.assertIn('Valider et accorder', consent)
        self.assertNotIn('data-wn-do=', consent)

    def test_a_deletion_waiting_for_undo_and_the_empty_states(self):
        self.assertIn('data-wn-undo="7"', self._render(items=[self._item()], pending={'7': 1}))
        self.assertIn('Tout est lu.', self._render(filter='unread'))
        self.assertIn('Aucune notification.', self._render())
        self.assertIn('Réessayer', self._render(error=True))

    def test_the_footer_leads_to_the_full_page(self):
        self.assertIn('<a class="wn-foot" href="/common/notifications/">Voir toutes les notifications',
                      self._render())

    def test_times_read_as_people_say_them(self):
        now = 'Date.parse("2026-10-13T12:00:00Z")'
        said = self.v8.eval('JSON.stringify(["2026-10-13T11:59:40Z", "2026-10-13T11:55:00Z", '
                            '"2026-10-13T10:00:00Z", "2026-10-12T11:00:00Z", "2026-10-10T12:00:00Z"]'
                            f'.map(function (t) {{ return window.WamaNotifications._relativeTime(t, {now}); }}))')
        import json
        self.assertEqual(['à l’instant', 'il y a 5 min', 'il y a 2 h', 'hier', 'il y a 3 j'],
                         json.loads(said))

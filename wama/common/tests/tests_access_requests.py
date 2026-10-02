"""DEMANDER un accès sur une card reçue, et la PASTILLE de partage (2026-10-03, décision de Fabien).

`WAMA_COLLABORATION §3bis` : le destinataire voit son niveau (coché) et demande un niveau supérieur ;
le propriétaire est prévenu dans WAMA et répond. Seule la PROPRIÉTÉ est honorable aujourd'hui —
l'accepter cède la card (« Transférer à… ») ; modification et collaboration sont refusées avec leur
motif tant que leur mode n'existe pas. La demande et le droit sont la même ligne (`ObjectGrant`).
"""
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

User = get_user_model()


class AccessRequestTest(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        setting = override_settings(MEDIA_ROOT=self.tmp)
        setting.enable()
        self.addCleanup(setting.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from wama.common.services.sharing import partager
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.describer.models import Description
        self.owner = User.objects.create_user('access_owner', password='x')
        self.requester = User.objects.create_user('access_requester', password='x')
        self.lot, (self.card,) = _lot_de(Description, self.owner, 1)
        partager(self.owner, self.card, 'public')

    def _request(self, level='own', user=None):
        from wama.common.services.access_requests import request_access
        return request_access(user or self.requester, self.card, level, surface='describer')

    def test_an_ownership_request_notifies_the_owner_and_is_not_duplicated(self):
        from wama.common.models import Notification, ObjectGrant
        grant = self._request()
        self.assertEqual(ObjectGrant.STATE_REQUESTED, grant.state)
        note = Notification.objects.get(recipient=self.owner, kind='access_request')
        self.assertEqual(f'/common/requests/{grant.pk}/', note.url)
        self.assertEqual(grant.pk, self._request().pk, 'une demande en attente a été recréée')
        self.assertEqual(1, Notification.objects.filter(recipient=self.owner).count())

    def test_a_mode_that_does_not_exist_yet_cannot_be_requested(self):
        from wama.common.services.access_requests import AccessRequestRefused
        for level in ('fork', 'collaborate'):
            with self.subTest(level=level), self.assertRaises(AccessRequestRefused):
                self._request(level)

    def test_only_a_received_card_can_be_requested(self):
        from wama.common.services.access_requests import AccessRequestRefused
        from wama.common.services.sharing import partager
        with self.assertRaises(AccessRequestRefused):
            self._request(user=self.owner)                     # la sienne
        partager(self.owner, self.card, 'private')
        with self.assertRaises(AccessRequestRefused):
            self._request()                                    # plus visible

    def test_accepting_ownership_hands_the_card_over(self):
        from wama.common.models import ObjectGrant
        from wama.common.services.access_requests import answer
        grant = self._request()
        report = answer(self.owner, grant, True)
        self.card.refresh_from_db()
        grant.refresh_from_db()
        self.assertEqual(self.requester.pk, self.card.user_id, 'la card n’a pas changé de main')
        self.assertEqual(ObjectGrant.STATE_GRANTED, grant.state)
        self.assertEqual(self.owner.pk, grant.granted_by_id)
        self.assertEqual(self.requester.username, report.get('to'))

    def test_the_former_owner_still_sees_the_request_he_accepted(self):
        # Mesuré par le geste navigateur le 2026-10-03 : accepter cède la card, et la page de la
        # demande répondait alors 404 à celui qui venait d'accepter.
        from wama.common.services.access_requests import answer
        grant = self._request()
        answer(self.owner, grant, True)
        self.client.force_login(self.owner)
        page = self.client.get(f'/common/requests/{grant.pk}/')
        self.assertEqual(200, page.status_code)
        self.assertIn('Accordé', page.content.decode())

    def test_refusing_tells_the_requester_and_keeps_the_card(self):
        from wama.common.models import Notification, ObjectGrant
        from wama.common.services.access_requests import answer
        grant = self._request()
        answer(self.owner, grant, False)
        self.card.refresh_from_db()
        grant.refresh_from_db()
        self.assertEqual(self.owner.pk, self.card.user_id)
        self.assertEqual(ObjectGrant.STATE_REFUSED, grant.state)
        self.assertTrue(Notification.objects.filter(recipient=self.requester,
                                                    kind='access_request_refused').exists())

    def test_only_the_owner_answers_and_only_once(self):
        from wama.common.services.access_requests import AccessRequestRefused, answer
        grant = self._request()
        with self.assertRaises(AccessRequestRefused):
            answer(self.requester, grant, True)
        answer(self.owner, grant, False)
        with self.assertRaises(AccessRequestRefused):
            answer(self.owner, grant, True)

    def test_the_request_page_is_seen_by_the_two_parties_only(self):
        grant = self._request()
        third = User.objects.create_user('access_third', password='x')
        for user, status in ((self.owner, 200), (self.requester, 200), (third, 404)):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(status, self.client.get(f'/common/requests/{grant.pk}/').status_code)
        self.client.force_login(self.owner)
        html = self.client.get(f'/common/requests/{grant.pk}/').content.decode()
        self.assertIn('data-request-answer="1"', html, 'le propriétaire n’a pas de quoi répondre')

    def test_the_access_menu_shows_the_current_mode_and_the_unbuilt_ones(self):
        self.client.force_login(self.requester)
        data = self.client.get('/common/api/access/', {'surface': 'describer', 'pk': self.card.pk,
                                                       'nature': 'element'}).json()
        self.assertEqual('read', data['mode'])
        self.assertEqual({'read': True, 'fork': False, 'collaborate': False},
                         {m['key']: m['available'] for m in data['modes']})
        self._request()
        data = self.client.get('/common/api/access/', {'surface': 'describer', 'pk': self.card.pk,
                                                       'nature': 'element'}).json()
        self.assertIn('own', data['pending'], 'la demande en attente n’est pas dite')

    def test_recent_notifications_return_only_the_new_unread_ones(self):
        from wama.common.utils.notifications import notify_in_app
        self.client.force_login(self.owner)
        first = self.client.get('/common/api/notifications/recent/').json()
        self.assertEqual([], first['items'], 'sans point de départ, rien n’est à montrer')
        notify_in_app([self.owner], 'test', 'Nouvelle')
        later = self.client.get('/common/api/notifications/recent/',
                                {'after': first['last_id']}).json()
        self.assertEqual(['Nouvelle'], [i['title'] for i in later['items']])
        self.assertEqual(1, later['unread'])


class ShareLabelTest(TestCase):
    """La PASTILLE du niveau de partage, des deux côtés (`reception.entry_arrangement`)."""

    def test_both_sides_carry_the_share_label_and_a_private_entry_none(self):
        from wama.common.services.reception import entry_arrangement, lines_for
        from wama.common.services.sharing import partager
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.describer.models import BatchDescription, Description
        owner = User.objects.create_user('label_owner', password='x')
        other = User.objects.create_user('label_other', password='x')
        lot, (card,) = _lot_de(Description, owner, 1)
        self.assertEqual({}, entry_arrangement(owner, lot, {}), 'une entrée privée porte une pastille')
        partager(owner, card, 'public')
        lot.refresh_from_db()
        mine = entry_arrangement(owner, lot, {})
        self.assertEqual('Partagée · Public · 👁 Lecture seule', mine['share_label'])
        theirs = entry_arrangement(other, lot, lines_for(other, BatchDescription))
        self.assertTrue(theirs['share_label'].startswith('Reçue de label_owner'))
        self.assertTrue(theirs['share_label'].endswith('👁 Lecture seule'))

    def test_the_share_modal_receives_the_declared_modes(self):
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.describer.models import Description
        owner = User.objects.create_user('label_modal', password='x')
        _lot, (card,) = _lot_de(Description, owner, 1)
        self.client.force_login(owner)
        data = self.client.get(f'/common/api/partage/describer/element/{card.pk}/').json()
        self.assertEqual(['read', 'fork', 'collaborate'], [m['key'] for m in data['modes']])

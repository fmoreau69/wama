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
        # La MODIFICATION attend les variantes (marche 8b) ; la collaboration existe depuis le
        # 2026-10-03 (E1-E5) — elle est gardée par `CollaborationTest`.
        from wama.common.services.access_requests import AccessRequestRefused
        with self.assertRaises(AccessRequestRefused):
            self._request('fork')

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
        self.assertEqual({'read': True, 'fork': False, 'collaborate': True},
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


class CollaborationTest(TestCase):
    """La COLLABORATION (2026-10-03, E1-E5 tranchées par Fabien) : accordée à une PERSONNE sur
    demande acceptée, à l'ENTRÉE (le lot) ; elle ouvre l'édition (réglages, lancement, arrêt,
    correction), jamais la suppression ni le partage (E2) ; un retrait a effet immédiat (E5)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        setting = override_settings(MEDIA_ROOT=self.tmp)
        setting.enable()
        self.addCleanup(setting.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from wama.common.services.sharing import partager
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.describer.models import Description
        self.owner = User.objects.create_user('collab_owner', password='x')
        self.collaborator = User.objects.create_user('collab_member', password='x')
        self.reader = User.objects.create_user('collab_reader', password='x')
        self.lot, (self.card,) = _lot_de(Description, self.owner, 1)
        partager(self.owner, self.card, 'public')

    def _grant(self):
        from wama.common.services.access_requests import answer, request_access
        grant = request_access(self.collaborator, self.card, 'collaborate', surface='describer')
        answer(self.owner, grant, True)
        grant.refresh_from_db()
        return grant

    def test_a_collaboration_is_given_to_the_entry_and_announced(self):
        from wama.common.models import Notification, ObjectGrant
        grant = self._grant()
        self.assertEqual((self.lot._meta.label, self.lot.pk), (grant.object_type, grant.object_id),
                         'la collaboration ne vise pas l’entrée (le lot)')
        self.assertEqual(ObjectGrant.STATE_GRANTED, grant.state)
        self.assertTrue(Notification.objects.filter(recipient=self.collaborator,
                                                    kind='access_granted').exists())

    def test_edit_is_open_to_the_collaborator_only_and_closes_on_revoke(self):
        from django.http import Http404
        from wama.common.services.access_requests import revoke
        from wama.common.utils.scoping import editable_or_404
        from wama.describer.models import Description
        grant = self._grant()
        self.assertEqual(self.card.pk, editable_or_404(Description, self.collaborator, pk=self.card.pk).pk)
        with self.assertRaises(Http404):
            editable_or_404(Description, self.reader, pk=self.card.pk)   # simple lecteur
        revoke(self.owner, grant)
        with self.assertRaises(Http404):
            editable_or_404(Description, self.collaborator, pk=self.card.pk)

    def test_start_lock_accepts_the_collaborator_and_turns_a_reader_away(self):
        from wama.common.utils.process_control import begin_processing
        from wama.describer.models import Description
        self._grant()
        self.assertEqual((None, 'not_found'),
                         begin_processing(Description, self.card.pk, user=self.reader))
        item, err = begin_processing(Description, self.card.pk, user=self.collaborator)
        self.assertIsNone(err)
        self.assertEqual(self.owner.pk, item.user_id, 'la tâche n’est plus celle de la card (E3)')

    def test_the_end_of_processing_is_announced_to_the_collaborator(self):
        from wama.common.models import Notification
        from wama.common.utils.notifications import notify_job_collaborators
        self._grant()
        self.assertEqual(1, notify_job_collaborators(self.card, 'Describer', 'témoin', True))
        self.assertTrue(Notification.objects.filter(recipient=self.collaborator, kind='job_done').exists())

    def test_the_owner_label_counts_collaborators_and_the_collaborator_sees_the_mode(self):
        from wama.common.services.reception import entry_arrangement, lines_for
        from wama.describer.models import BatchDescription
        self._grant()
        self.lot.refresh_from_db()
        self.assertIn('1 collaborateur', entry_arrangement(self.owner, self.lot, {})['share_label'])
        theirs = entry_arrangement(self.collaborator, self.lot, lines_for(self.collaborator, BatchDescription))
        self.assertEqual('collaborate', theirs['share_mode'])
        self.assertIn('Collaboration', theirs['share_label'])

    def test_the_soft_lock_tells_who_else_is_editing(self):
        from wama.common.services import edit_lock
        self._grant()
        self.assertFalse(edit_lock.acquire(self.owner, self.card)['held_by_other'])
        other = edit_lock.acquire(self.collaborator, self.card)
        self.assertTrue(other['held_by_other'])
        self.assertEqual('collab_owner', other['name'])
        edit_lock.release(self.owner, self.card)
        self.assertFalse(edit_lock.acquire(self.collaborator, self.card)['held_by_other'])

    def test_the_shares_page_lists_both_sides_and_revokes(self):
        grant = self._grant()
        self.client.force_login(self.owner)
        html = self.client.get('/common/shares/').content.decode()
        self.assertIn(f'data-revoke="{grant.pk}"', html, 'le propriétaire ne peut pas retirer le droit')
        self.assertTrue(self.client.post(f'/common/api/grants/{grant.pk}/revoke/').json()['done'])
        self.client.force_login(self.reader)
        self.assertIn('collab_owner', self.client.get('/common/shares/').content.decode())


class CollaborationAcrossTheFleetTest(TestCase):
    """Sur CHAQUE app : un collaborateur enregistre les réglages d'une card (route de convention
    `update_settings`) ; un simple lecteur ne le peut pas ; personne d'autre que le propriétaire ne
    supprime (E2). Les réglages d'un collaborateur sont tracés au journal (E4)."""

    def test_settings_open_to_collaborators_delete_stays_with_the_owner(self):
        from django.urls import NoReverseMatch, reverse
        from wama.common.models import ObjectGrant, RunOutcome
        from wama.common.services.access_requests import entry_of
        from wama.common.services.sharing import partager
        from wama.common.tests.tests_queue_delete_contract import (SuppressionDansChaqueAppTest,
                                                                   _lot_de, _surfaces)
        from wama.common.utils.preview_registry import PreviewRegistry
        owner = User.objects.create_user('fleet_collab_owner', password='x')
        checked = 0
        for surface, delete_route, card_route in _surfaces():
            model = PreviewRegistry.get_model(surface)
            try:
                settings_url = reverse(card_route.replace('card_html', 'update_settings'), args=[0])
            except NoReverseMatch:
                continue
            with self.subTest(surface=surface):
                account = SuppressionDansChaqueAppTest._compte_pour(self, surface)
                _lot, (card,) = _lot_de(model, owner, 1)
                partager(owner, card, 'public')
                url = settings_url.replace('/0/', f'/{card.pk}/')
                as_reader = self.client.post(url, {}).status_code
                if as_reader == 501:
                    continue           # route non générée (trou de glu d'une jumelle) : rien à mesurer
                self.assertEqual(404, as_reader, 'un simple lecteur enregistre les réglages')
                entry = entry_of(card)
                ObjectGrant.objects.create(object_type=entry._meta.label, object_id=entry.pk,
                                           beneficiary=account, level='collaborate', state='granted')
                as_collaborator = self.client.post(url, {}).status_code
                self.assertNotEqual(404, as_collaborator,
                                    'le collaborateur ne peut pas enregistrer les réglages')
                # Un POST vide peut être REFUSÉ (400) : le journal ne note que ce qui a abouti.
                if as_collaborator < 400:
                    self.assertTrue(RunOutcome.objects.filter(signal='regle', user=account,
                                                              object_id=card.pk).exists(),
                                    'les réglages du collaborateur ne sont pas tracés (E4)')
                self.assertEqual(404, self.client.post(reverse(delete_route, args=[card.pk])).status_code,
                                 'le collaborateur supprime la card (E2)')
                checked += 1
        self.assertGreaterEqual(checked, 6, f'trop peu d’apps mesurées : {checked}')


class GestureJournalAppNameTest(TestCase):
    """Le journal des gestes (`RunOutcome`, middleware) reconnaît une app dont `app_name` est POINTÉ.

    Sonde du 2026-10-03 : reader, composer et transcriber déclarent `app_name = 'wama.reader'` ; le
    middleware cherchait ce nom tel quel au registre de détail et ne captait RIEN pour elles
    (téléchargement, suppression, relance) — depuis la création du middleware, sans rien dire."""

    def test_every_queue_app_route_resolves_to_a_name_the_registry_knows(self):
        from django.urls import resolve, reverse
        from wama.common.middleware import app_of
        from wama.common.tests.tests_queue_delete_contract import _surfaces
        from wama.common.utils.detail_registry import DetailRegistry
        for surface, delete_route, _card in _surfaces():
            with self.subTest(surface=surface):
                match = resolve(reverse(delete_route, args=[1]))
                self.assertIsNotNone(DetailRegistry.get(app_of(match)),
                                     f'{match.app_name!r} / {match.namespace!r} : app inconnue du journal')

    def test_a_dotted_app_name_is_read_on_its_namespace(self):
        from types import SimpleNamespace
        from wama.common.middleware import app_of
        self.assertEqual('reader', app_of(SimpleNamespace(app_name='wama.reader', namespace='reader')))


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

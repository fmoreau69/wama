"""ENREGISTREMENT PRÉPARÉ SUR UN ÉTAT PÉRIMÉ — refusé, jamais écrasé (2026-10-07, marche 1 du conflit).

`WAMA_COLLABORATION §2.4` : *« un enregistrement dit sur quelle version il a été préparé ; si
quelqu'un a enregistré entre-temps, le conflit est montré, jamais écrasé »*. Cas vécu qui l'a
déclenchée : deux personnes corrigent la même transcription ; l'enregistrement automatique de l'une
renvoyait TOUTE la liste des segments et effaçait la correction de l'autre, sans que personne le
sache. Ces tests éprouvent la brique (`edit_lock.state_token` / `stale_edit`) et son premier
consommateur, la page de correction du Transcriber, à deux comptes réels (propriétaire et
collaborateur).
"""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase
from django.urls import reverse

from wama.common.services import edit_lock

User = get_user_model()


class StateTokenTest(TestCase):

    def test_equal_states_have_the_same_token_whatever_the_key_order(self):
        self.assertEqual(edit_lock.state_token([{'a': 1, 'b': 'x'}]),
                         edit_lock.state_token([{'b': 'x', 'a': 1}]))
        self.assertNotEqual(edit_lock.state_token([{'a': 1}]), edit_lock.state_token([{'a': 2}]))

    def test_a_save_from_the_current_state_or_without_a_base_passes(self):
        owner = User.objects.create_user('conflict_token_owner', password='x')
        current = [{'text': 'bonjour'}]
        self.assertIsNone(edit_lock.stale_edit(owner, owner, edit_lock.state_token(current), current))
        self.assertIsNone(edit_lock.stale_edit(owner, owner, '', current),
                          'une page ouverte avant la règle ne dit pas son état : on ne la bloque pas')

    def test_a_save_from_a_stale_state_is_refused_and_names_who_edits(self):
        from wama.transcriber.models import Transcript
        from wama.common.tests.tests_queue_delete_contract import _instance
        owner = User.objects.create_user('conflict_stale_owner', password='x')
        other = User.objects.create_user('conflict_stale_other', password='x')
        card = _instance(Transcript, owner)
        edit_lock.acquire(other, card)
        try:
            res = edit_lock.stale_edit(owner, card, edit_lock.state_token(['avant']), ['après'])
        finally:
            edit_lock.release(other, card)
        self.assertTrue(res['conflict'])
        self.assertEqual('conflict_stale_other', res['by'])
        self.assertEqual(edit_lock.state_token(['après']), res['token'])


class CorrectionPageConflictTest(TestCase):
    """Propriétaire et collaborateur ouvrent la même correction ; le second enregistrement, préparé
    avant le premier, est REFUSÉ — et la correction du premier reste en place."""

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        from wama.common.services.sharing import share_with_person
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.transcriber.models import Transcript
        self.owner = User.objects.create_user('conflict_owner', password='x')
        self.collaborator = User.objects.create_user('conflict_collab', password='x')
        for user in (self.owner, self.collaborator):
            for role in ('communication', 'recherche', 'ingenierie', 'administratif'):
                group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')
                user.groups.add(group)
        _lot, (self.card,) = _lot_de(Transcript, self.owner, 1)
        self.card.status = 'SUCCESS'
        self.card.segments_json = [{'start_time': 0, 'end_time': 1, 'text': 'bonjour'}]
        self.card.save(update_fields=['status', 'segments_json'])
        share_with_person(self.owner, self.card, Transcript, self.collaborator, 'collaborate',
                          surface='transcriber')
        self.as_owner, self.as_collab = Client(), Client()
        self.as_owner.force_login(self.owner)
        self.as_collab.force_login(self.collaborator)

    def _token_of_page(self, client):
        page = client.get(reverse('transcriber:edit', args=[self.card.pk]))
        self.assertEqual(200, page.status_code)
        return page.context['state_token']

    def _save(self, client, text, base):
        return client.post(reverse('transcriber:save_correction', args=[self.card.pk]),
                           data=json.dumps({'segments': [{'start_time': 0, 'end_time': 1,
                                                          'text': text}],
                                            'status': 'draft', 'base': base}),
                           content_type='application/json')

    def test_the_second_save_prepared_before_the_first_is_refused(self):
        owner_base = self._token_of_page(self.as_owner)
        collab_base = self._token_of_page(self.as_collab)
        first = self._save(self.as_owner, 'bonjour à tous', owner_base)
        self.assertEqual(200, first.status_code, first.content[:200])
        late = self._save(self.as_collab, 'bonjour tout le monde', collab_base)
        self.assertEqual(409, late.status_code, 'un état périmé a écrasé la correction de l’autre')
        self.assertIn('rechargez', late.json()['reason'])
        self.card.refresh_from_db()
        self.assertEqual('bonjour à tous', self.card.corrected_segments_json[0]['text'])

    def test_after_reloading_the_collaborator_saves_again(self):
        self._save(self.as_owner, 'bonjour à tous', self._token_of_page(self.as_owner))
        again = self._save(self.as_collab, 'bonjour à toutes et à tous',
                           self._token_of_page(self.as_collab))
        self.assertEqual(200, again.status_code)

    def test_each_save_returns_the_token_the_next_one_starts_from(self):
        res = self._save(self.as_owner, 'un', self._token_of_page(self.as_owner)).json()
        follow = self._save(self.as_owner, 'deux', res['token'])
        self.assertEqual(200, follow.status_code, 'la page ne peut pas enchaîner ses enregistrements')

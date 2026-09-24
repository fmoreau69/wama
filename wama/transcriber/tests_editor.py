"""Correction editor — the « Bornes » tool (`retime_segments`): move a junction, cut a section."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.transcriber.models import Transcript

User = get_user_model()

WORDS = [{'word': ' ' + w, 'start': s, 'end': e, 'probability': 0.9}
         for w, s, e in (('le', 0.0, 0.2), ('chien', 0.2, 0.6), ('dort', 0.6, 1.0),
                         ('sur', 1.2, 1.4), ('le', 1.4, 1.5), ('tapis', 1.5, 1.9))]


class RetimeSegmentsTest(TestCase):

    def setUp(self):
        # `AppAccessMiddleware` redirects any account without the app's role BEFORE the view:
        # a view test goes through the gate, it does not bypass it (cf. tests_import_contract).
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import GROUP_PREFIX
        self.user = User.objects.create_user('transcriber_editor', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)
        self.item = Transcript.objects.create(
            user=self.user, audio='users/0/transcriber/input/fictif.wav', status='SUCCESS',
            text='le chien dort sur le tapis',
            segments_json=[{'speaker_id': 'SPEAKER_00', 'text': 'le chien dort sur le tapis',
                            'start_time': 0.0, 'end_time': 1.9, 'words': WORDS}])

    def _post(self, payload, item=None):
        return self.client.post(f'/transcriber/edit/{(item or self.item).pk}/retime/',
                                json.dumps(payload), content_type='application/json')

    def _sections(self):
        return [{'speaker_id': 'SPEAKER_00', 'text': 'le chien dort', 'start_time': 0.0,
                 'end_time': 1.0, 'words': WORDS[:3], 'reviewed': True},
                {'speaker_id': 'SPEAKER_01', 'text': 'sur le tapis', 'start_time': 1.1,
                 'end_time': 1.9, 'words': WORDS[3:]}]

    def test_moving_a_junction_moves_the_words_and_closes_it_into_one_boundary(self):
        answer = self._post({'op': 'move', 'time': 0.62, 'segments': self._sections()}).json()
        self.assertTrue(answer['ok'], answer)
        left, right = answer['segments']
        self.assertEqual(('le chien', 'dort sur le tapis'), (left['text'], right['text']))
        self.assertEqual(0.6, left['end_time'])
        self.assertEqual(left['end_time'], right['start_time'])
        self.assertTrue(left['reviewed'], 'the other keys of a section are kept')

    def test_the_scissors_cut_a_corrected_section_on_the_asr_words(self):
        """The section says « chat » where the ASR heard « chien »: re-anchored, then cut."""
        section = {'speaker_id': 'SPEAKER_00', 'text': 'le chat dort sur le tapis',
                   'start_time': 0.0, 'end_time': 1.9, 'words': WORDS}
        answer = self._post({'op': 'split', 'time': 1.1, 'segments': [section]}).json()
        self.assertTrue(answer['ok'], answer)
        first, second = answer['segments']
        self.assertEqual(('le chat dort', 'sur le tapis'), (first['text'], second['text']))
        self.assertEqual(1.1, first['end_time'], 'dropped in a silence: the boundary stays there')

    def test_a_refused_gesture_says_why_and_changes_nothing(self):
        answer = self._post({'op': 'split', 'time': 0.1,
                             'segments': [{'text': 'oui', 'start_time': 0, 'end_time': 1}]})
        self.assertEqual(200, answer.status_code)
        self.assertFalse(answer.json()['ok'])
        self.assertIn('au moins un mot', answer.json()['reason'])
        self.item.refresh_from_db()
        self.assertIsNone(self.item.corrected_segments_json, 'the tool never writes: autosave does')

    def test_a_malformed_request_is_refused(self):
        self.assertEqual(400, self._post({'op': 'move', 'time': 'x', 'segments': []}).status_code)
        self.assertEqual(400, self._post({'op': 'swap', 'time': 1, 'segments': [{}]}).status_code)

    def test_another_users_transcript_is_not_reachable(self):
        other = User.objects.create_user('transcriber_editor_other', password='x')
        theirs = Transcript.objects.create(user=other, audio='users/1/x.wav', status='SUCCESS')
        self.assertEqual(404, self._post({'op': 'split', 'time': 1, 'segments': [{}]},
                                         item=theirs).status_code)

    def test_the_editor_page_carries_the_tool_and_its_route(self):
        page = self.client.get(f'/transcriber/edit/{self.item.pk}/').content.decode()
        self.assertIn('id="boundaryToolBtn"', page)
        self.assertIn(f'/transcriber/edit/{self.item.pk}/retime/', page)

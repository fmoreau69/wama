"""The PRIVACY GATE before a remote model (ROADMAP §16.4bis, decisions of 2026-10-28).

What is held here : by default a commercial cloud gets PSEUDONYMS and the answer comes back with
the real values (streamed or not, tool calls staying valid JSON), while the private and sovereign
clouds get the text as is ; the user's choice per hosting level overrides the defaults ; a value
the detector missed elsewhere is replaced too ; the same data keeps the same pseudonym ; when the
detection cannot run, NOTHING is sent (`CloudAccessRefused`, 503) ; the profile shows one row per
hosting level and stores only known levels and gestures.
"""
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

NAMES = ('Marie Dupont', 'anne.leroy@exemple.fr')


def _fake_detect(segments, language='', **kwargs):
    """A deterministic detector : finds the FIRST occurrence of each known value only — so the
    gate's propagation to the other occurrences is what the tests observe."""
    frames = []
    for index, text in enumerate(segments):
        found = []
        for value in NAMES:
            at = text.find(value)
            if at >= 0:
                label = 'EMAIL_ADDRESS' if '@' in value else 'PERSON'
                found.append({'label': label, 'span': [at, at + len(value)], 'conf': 0.9})
        if found:
            frames.append({'i': index, 'd': found})
    return {'frames': frames, 'unavailable': [], 'language': language}


class GateTestCase(SimpleTestCase):

    def setUp(self):
        from wama.common.privacy import gate
        gate._cache.clear()
        patcher = mock.patch('wama.common.privacy.service_client.detect_segments',
                             side_effect=_fake_detect)
        self.detect = patcher.start()
        self.addCleanup(patcher.stop)
        language = mock.patch('wama.common.utils.text_language.detect_text_language',
                              return_value='fr')
        language.start()
        self.addCleanup(language.stop)

    def _gate(self, gesture='pseudonymize'):
        from wama.common.privacy.gate import Gate
        return Gate(gesture, 'Test')


class PseudonymizationTest(GateTestCase):

    def test_values_become_numbered_pseudonyms_and_come_back_in_the_answer(self):
        gate = self._gate()
        sent = gate.outgoing([
            {'role': 'system', 'content': 'Tu es WAMA.'},
            {'role': 'user', 'content': 'Écris à Marie Dupont (anne.leroy@exemple.fr).'},
        ])
        self.assertEqual('Tu es WAMA.', sent[0]['content'])
        self.assertEqual('Écris à [PERSONNE_1] ([EMAIL_1]).', sent[1]['content'])
        answer = gate.incoming('Bonjour [PERSONNE_1], réponse envoyée à personne_1 et [EMAIL_1].')
        self.assertEqual('Bonjour Marie Dupont, réponse envoyée à Marie Dupont et '
                         'anne.leroy@exemple.fr.', answer)

    def test_an_occurrence_the_detector_missed_is_replaced_too(self):
        """The fake detector sees only the first « Marie Dupont » of a text."""
        sent = self._gate().outgoing_texts(['Marie Dupont, puis encore Marie Dupont.'])
        self.assertEqual(['[PERSONNE_1], puis encore [PERSONNE_1].'], sent)

    def test_the_same_data_keeps_its_pseudonym_across_messages_and_turns(self):
        history = ['Marie Dupont a écrit.', 'Bonjour.\n\nMarie Dupont relance.']
        first = self._gate().outgoing_texts(history)
        second = self._gate().outgoing_texts(history + ['Et anne.leroy@exemple.fr ?'])
        self.assertEqual(first, second[:2])
        self.assertIn('[PERSONNE_1]', second[1])

    def test_an_unknown_placeholder_and_ordinary_brackets_are_left_alone(self):
        gate = self._gate()
        gate.outgoing_texts(['Marie Dupont'])
        self.assertEqual('[PERSONNE_2] et [note]', gate.incoming('[PERSONNE_2] et [note]'))

    def test_a_tool_call_comes_back_as_valid_json_with_the_real_values(self):
        import json
        gate = self._gate()
        gate.outgoing_texts(['Envoie à Marie Dupont'])
        gate._backward['PERSONNE_1'] = 'Marie "la" Dupont'      # a value that needs escaping
        call = gate.incoming('{"tool": "send", "args": {"to": "[PERSONNE_1]"}}')
        self.assertEqual({'tool': 'send', 'args': {'to': 'Marie "la" Dupont'}}, json.loads(call))

    def test_occulting_puts_the_bare_label_and_never_restores(self):
        gate = self._gate('occult')
        self.assertEqual(['Écris à [PERSONNE].'], gate.outgoing_texts(['Écris à Marie Dupont.']))
        self.assertEqual('[PERSONNE] a répondu', gate.incoming('[PERSONNE] a répondu'))

    def test_the_cache_spares_a_second_detection_of_the_same_paragraph(self):
        self._gate().outgoing_texts(['Consigne longue.\n\nMarie Dupont'])
        self._gate().outgoing_texts(['Consigne longue.\n\nAutre chose'])
        detected = [seg for call in self.detect.call_args_list for seg in call.args[0]]
        self.assertEqual(1, detected.count('Consigne longue.'))


class StreamTest(GateTestCase):

    def test_a_pseudonym_cut_between_fragments_comes_back_whole(self):
        gate = self._gate()
        gate.outgoing_texts(['Marie Dupont'])
        shown = []
        relay = gate.stream(shown.append)
        for fragment in ('Bonjour [PERS', 'ONNE_', '1], comment ', 'allez-vous ?'):
            relay(fragment)
        gate.flush()
        self.assertEqual('Bonjour Marie Dupont, comment allez-vous ?', ''.join(shown))
        self.assertFalse(any('PERS' in piece for piece in shown), shown)

    def test_occulting_leaves_the_stream_untouched(self):
        gate = self._gate('occult')
        sink = mock.Mock()
        self.assertIs(sink, gate.stream(sink))


class DefaultsAndChoicesTest(SimpleTestCase):

    def _user(self, chosen=None):
        return mock.Mock(is_authenticated=True, profile=mock.Mock(cloud_privacy=chosen or {}))

    def test_by_default_only_a_commercial_cloud_is_gated(self):
        from wama.common.privacy.gate import privacy_gate
        for user in (None, self._user()):
            self.assertIsNone(privacy_gate(user, 'albert'))
            self.assertEqual('pseudonymize', privacy_gate(user, 'anthropic').gesture)
            self.assertEqual('pseudonymize', privacy_gate(user, 'claude_code').gesture)

    def test_the_user_choice_overrides_the_default_per_hosting_level(self):
        from wama.common.privacy.gate import privacy_gate
        user = self._user({'sovereign': 'occult', 'third_party': 'none'})
        self.assertEqual('occult', privacy_gate(user, 'albert').gesture)
        self.assertIsNone(privacy_gate(user, 'anthropic'))

    def test_an_unknown_stored_gesture_falls_back_to_the_default(self):
        from wama.common.privacy.gate import gesture_for
        self.assertEqual('pseudonymize', gesture_for(self._user({'third_party': 'x'}), 'third_party'))


class FailClosedTest(GateTestCase):

    def _call(self):
        from wama.common.utils.llm_utils import chat_with_source
        return chat_with_source('anthropic', 'claude-x',
                                [{'role': 'user', 'content': 'Écris à Marie Dupont.'}])

    def test_the_remote_model_receives_pseudonyms_and_the_caller_gets_real_values(self):
        with mock.patch('wama.common.utils.llm_utils.llm_chat',
                        return_value=('Message pour [PERSONNE_1].', None)) as llm:
            text, err = self._call()
        self.assertEqual('Écris à [PERSONNE_1].', llm.call_args.args[0][0]['content'])
        self.assertEqual(('Message pour Marie Dupont.', None), (text, err))

    def test_nothing_is_sent_when_the_detection_cannot_run(self):
        from wama.common.privacy.service_client import PrivacyUnavailable
        from wama.model_manager.services.cloud_models import CloudAccessRefused
        self.detect.side_effect = PrivacyUnavailable('délai dépassé (180 s)')
        with mock.patch('wama.common.utils.llm_utils.llm_chat') as llm, \
                self.assertRaises(CloudAccessRefused) as refused:
            self._call()
        llm.assert_not_called()
        self.assertEqual(503, refused.exception.status)
        self.assertIn('rien n\'a été envoyé', str(refused.exception))

    def test_nothing_is_sent_when_an_installed_detector_did_not_load(self):
        from wama.model_manager.services.cloud_models import CloudAccessRefused
        self.detect.side_effect = lambda segments, language='', **k: {
            'frames': [], 'unavailable': ['nlp:bardsai'], 'language': language}
        with mock.patch('wama.common.utils.llm_utils.llm_chat') as llm, \
                self.assertRaises(CloudAccessRefused):
            self._call()
        llm.assert_not_called()

    def test_a_sovereign_cloud_is_called_as_is_by_default(self):
        from wama.common.utils.llm_utils import chat_with_source
        with mock.patch('wama.common.utils.llm_utils.llm_chat', return_value=('ok', None)) as llm:
            chat_with_source('albert', 'm', [{'role': 'user', 'content': 'Marie Dupont'}])
        self.assertEqual('Marie Dupont', llm.call_args.args[0][0]['content'])
        self.detect.assert_not_called()


class ProfileSettingTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('gate_user', password='x')
        self.client.force_login(self.user)

    def _post(self, payload):
        import json
        return self.client.post(reverse('accounts:profile-cloud-policy'), json.dumps(payload),
                                content_type='application/json')

    def test_a_choice_per_hosting_level_is_stored(self):
        response = self._post({'cloud_privacy': {'sovereign': 'pseudonymize',
                                                 'third_party': 'occult'}})
        self.assertEqual(200, response.status_code, response.content)
        self.user.profile.refresh_from_db()
        self.assertEqual({'sovereign': 'pseudonymize', 'third_party': 'occult'},
                         self.user.profile.cloud_privacy)

    def test_an_unknown_level_or_gesture_is_refused_and_nothing_stored(self):
        for wrong in ({'third_party_all': 'occult'}, {'third_party': 'send_anyway'}, ['occult']):
            self.assertEqual(400, self._post({'cloud_privacy': wrong}).status_code)
        self.user.profile.refresh_from_db()
        self.assertEqual({}, self.user.profile.cloud_privacy)

    def test_the_profile_page_shows_one_row_per_hosting_level_with_the_defaults(self):
        page = self.client.get(reverse('accounts:profile')).content.decode()
        for level in ('private', 'sovereign', 'third_party'):
            self.assertIn(f'id="cloudPrivacy-{level}"', page)
        third = re.search(r'id="cloudPrivacy-third_party".*?</select>', page, re.S).group(0)
        self.assertRegex(third, r'value="pseudonymize"\s+selected')

"""The transcriber's user settings — what is SPECIFIC to it.

The shared contracts are held for every app in `wama/common/` since 2026-09-26: every panel
setting is a user setting (`tests_panel_user_settings`), a deposit keeps what the panel posts and
takes the default otherwise (`tests_import_contract`). What remains here is the transcriber's own:
two settings were stored under OLD names until 2026-11-12 (`diarization`,
`preprocessing_enabled`) — they now follow the common key, and the preprocessing switch of the
page, a route of its own, writes the SAME setting as the panel.
"""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class TranscriberFormerLegacyKeysTest(TestCase):

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        self.user = User.objects.create_user('transcriber_panel', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)

    def _stored(self):
        from wama.common.models import UserAppSetting
        return dict(UserAppSetting.objects.filter(user=self.user, app='transcriber')
                    .values_list('name', 'value'))

    def test_the_two_former_legacy_settings_follow_the_common_key(self):
        self.client.post('/transcriber/user_settings/save/',  # wama:redondance-ok — les noms postés SONT l'objet du test
                         json.dumps({'enable_diarization': False, 'preprocess_audio': True,
                                     'vad_mode': 'off'}), content_type='application/json')
        stored = self._stored()
        self.assertEqual((False, True, 'off'), (stored['audio.enable_diarization'],
                                                 stored['audio.preprocess_audio'],
                                                 stored['audio.vad_mode']))
        self.assertFalse({'diarization', 'preprocessing_enabled'} & set(stored))
        served = self.client.get('/transcriber/user_settings/').json()
        self.assertEqual((False, True, 'off'), (served['enable_diarization'],
                                                 served['preprocess_audio'], served['vad_mode']))

    def test_the_preprocessing_switch_writes_the_panel_setting(self):
        before = self.client.get('/transcriber/user_settings/').json()['preprocess_audio']
        self.client.post(reverse('transcriber:set_preprocessing'),
                         json.dumps({'enabled': not before}), content_type='application/json')
        self.assertEqual(not before,
                         self.client.get('/transcriber/user_settings/').json()['preprocess_audio'])
        self.assertEqual({'audio.preprocess_audio'}, set(self._stored()))

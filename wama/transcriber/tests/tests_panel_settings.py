"""The transcriber's user settings — what is SPECIFIC to it.

The shared contracts are held for every app in `wama/common/` since 2026-09-26: every panel
setting is a user setting (`tests_panel_user_settings`), a deposit keeps what the panel posts and
takes the default otherwise (`tests_import_contract`). What remains here is the transcriber's own
data boundary: two settings are stored under their OLD names, kept as they are in base.
"""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from wama.transcriber.params import USER_SETTINGS_DEFAULTS

User = get_user_model()


class TranscriberLegacyStoredKeysTest(TestCase):

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        self.user = User.objects.create_user('transcriber_panel', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)

    def test_the_two_legacy_keys_stay_stored_under_their_old_name(self):
        """Data boundary: `diarization` and `preprocessing_enabled` are already in base."""
        from wama.common.utils.user_settings import get_user_app_settings
        self.client.post('/transcriber/user_settings/save/',  # wama:redondance-ok — les noms postés SONT l'objet du test (clés historiques)
                         json.dumps({'enable_diarization': False, 'preprocess_audio': True,
                                     'vad_mode': 'off'}), content_type='application/json')
        stored = get_user_app_settings(self.user, 'transcriber', USER_SETTINGS_DEFAULTS)
        self.assertEqual((False, True, 'off'), (stored['diarization'],
                                                 stored['preprocessing_enabled'],
                                                 stored['vad_mode']))
        served = self.client.get('/transcriber/user_settings/').json()
        self.assertEqual((False, True, 'off'), (served['enable_diarization'],
                                                 served['preprocess_audio'], served['vad_mode']))

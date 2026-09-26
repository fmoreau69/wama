"""The transcriber right panel reads and saves THROUGH THE SCHEMA (port of 2026-09-26): a setting
added to `params.py` reaches the panel, the deposit and the user settings without a view edit."""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from wama.transcriber.models import Transcript
from wama.transcriber.params import PARAMS_JSON, USER_SETTINGS_DEFAULTS, user_setting_key

User = get_user_model()


class TranscriberPanelSettingsTest(TestCase):

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        self.user = User.objects.create_user('transcriber_panel', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)

    def _stored(self):
        from wama.common.utils.user_settings import get_user_app_settings
        return get_user_app_settings(self.user, 'transcriber', USER_SETTINGS_DEFAULTS)

    def test_every_panel_param_of_the_schema_is_a_user_setting(self):
        panel = [p for p in PARAMS_JSON if 'panel' in (p.get('contexts') or ())]
        self.assertIn('vad_mode', [p['name'] for p in panel])
        self.assertEqual({user_setting_key(p) for p in panel}, set(USER_SETTINGS_DEFAULTS))

    def test_the_two_legacy_keys_stay_stored_under_their_old_name(self):
        """Data boundary: `diarization` and `preprocessing_enabled` are already in base."""
        self.client.post('/transcriber/user_settings/save/',
                         json.dumps({'enable_diarization': False, 'preprocess_audio': True,
                                     'vad_mode': 'off'}), content_type='application/json')
        stored = self._stored()
        self.assertEqual((False, True, 'off'), (stored['diarization'],
                                                 stored['preprocessing_enabled'],
                                                 stored['vad_mode']))
        served = self.client.get('/transcriber/user_settings/').json()
        self.assertEqual((False, True, 'off'), (served['enable_diarization'],
                                                 served['preprocess_audio'], served['vad_mode']))

    def test_a_deposit_takes_every_schema_setting_the_panel_posts(self):
        from wama.common.services.ui_smoke import _wav_silence
        resp = self.client.post('/transcriber/upload/', {
            'file': SimpleUploadedFile('panel.wav', _wav_silence(1.0, 8000), 'audio/wav'),
            'vad_mode': 'off', 'enable_diarization': '0', 'generate_summary': '1',
            'summary_type': 'meeting', 'backend': 'whisper'})
        self.assertEqual(200, resp.status_code, resp.content[:300])
        t = Transcript.objects.filter(user=self.user).latest('id')
        self.addCleanup(lambda: t.audio.delete(save=False))
        self.assertEqual(('off', False, True, 'meeting', 'whisper', 'DRAFT'),
                         (t.vad_mode, t.enable_diarization, t.generate_summary,
                          t.summary_type, t.backend, t.status))
        self.assertEqual('off', self._stored()['vad_mode'])   # kept as the next deposit's default

    def test_a_deposit_without_settings_takes_the_model_defaults(self):
        from wama.common.services.ui_smoke import _wav_silence
        self.client.post('/transcriber/upload/', {
            'file': SimpleUploadedFile('bare.wav', _wav_silence(1.0, 8000), 'audio/wav')})
        t = Transcript.objects.filter(user=self.user).latest('id')
        self.addCleanup(lambda: t.audio.delete(save=False))
        self.assertEqual(('auto', True, False), (t.vad_mode, t.enable_diarization,
                                                 t.preprocess_audio))

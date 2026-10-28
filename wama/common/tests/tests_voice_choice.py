"""Le choix de la voix (2026-10-28) : les voix PROPRES des moteurs, sous leur seul modèle, et le
modèle de voix de l'assistant — choisi par le compte ou tiré « auto ».

Trois étages, gardés chacun là où un défaut ne se verrait pas à l'usage :
  • la source commune des voix range les voix d'un moteur sous SON modèle (`data-model`) ;
  • la règle du navigateur (`WamaModelCaps.cloneVoiceFilter`) ne les montre que sous lui ;
  • la vocalisation de l'assistant dit ses réponses avec le modèle et la voix du compte, ou le
    plus rapide en temps réel dans sa langue.
"""
import json
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase

from wama.model_manager.models import AIModel

PHONON = 'huggingface:gradium/phonon-40m-fr'
KOKORO = 'huggingface:onnx-community/Kokoro-82M-v1.0-ONNX'


def _tts_row(key, voices=(), **caps):
    return AIModel.objects.update_or_create(
        model_key=key, defaults=dict(
            name=key.rsplit('/', 1)[-1], model_type='speech', source='huggingface',
            is_available=True, is_downloaded=True,
            capabilities={'task': 'text-to-speech', 'languages': ['fr'],
                          **({'voices': list(voices)} if voices else {}), **caps}))[0]


class EngineVoiceGroupsTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('engine_voices_user', password='x')

    def test_each_model_that_names_voices_gets_a_group_whose_options_carry_the_model(self):
        from wama.common.utils.voice_options import get_voice_groups
        _tts_row(PHONON, voices=[{'value': 'phonon_noemie', 'label': 'Noémie', 'language': 'fr'}])
        _tts_row(KOKORO)                                     # aucune voix propre : aucun groupe
        groups = {g['key']: g for g in get_voice_groups(self.user)}
        group = groups[f'engine:{PHONON}']
        self.assertEqual([('phonon_noemie', 'Noémie')], group['options'])
        self.assertEqual({'phonon_noemie': {'model': PHONON, 'language': 'fr'}}, group['attributes'])
        self.assertNotIn(f'engine:{KOKORO}', groups)

    def test_the_bark_presets_are_no_longer_offered_under_every_engine(self):
        from wama.common.utils.voice_options import get_voice_groups
        values = [v for g in get_voice_groups(self.user) for v, _ in g['options']]
        self.assertFalse([v for v in values if v.startswith('bark_')],
                         "sans ligne Bark qui les porte, aucun préréglage Bark")


class EngineVoiceRuleTest(SimpleTestCase):
    """La règle du navigateur, exécutée par V8 sur le fichier SERVI."""

    BROWSER = """
var window = this;
function Event(t) { this.type = t; }
function option(value, model) {
  return { value: value, textContent: value, hidden: false, disabled: false, selected: false,
           title: '', dataset: model ? { model: model } : {} };
}
function select(values) {
  var opts = values.map(function (v) { return option(v[0], v[1]); });
  opts[0].selected = true;
  return { options: opts, value: opts[0].value, changed: 0,
           dispatchEvent: function () { this.changed++; } };
}
function hidden(sel) { return sel.options.filter(function (o) { return o.hidden; })
                                          .map(function (o) { return o.value; }); }
"""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-model-caps.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval(self.BROWSER + source)
        ctx.eval("var f = WamaModelCaps.cloneVoiceFilter('v');"
                 "var sel = select([['default'], ['ua_3'], ['sa_5'], ['phonon_noemie', '%s'],"
                 " ['ff_siwis', '%s']]);" % (PHONON, KOKORO))
        return ctx

    def _apply(self, ctx, caps, key, loaded='true'):
        ctx.eval("WamaModelCaps.applyOptionFilter(sel, f, %s, %s, %s)"
                 % (json.dumps(caps), json.dumps(key), loaded))
        return list(ctx.eval("hidden(sel)"))

    def test_an_engine_voice_is_shown_under_its_own_model_only(self):
        ctx = self._ctx()
        self.assertEqual(['ua_3', 'sa_5', 'ff_siwis'],
                         self._apply(ctx, {'supports_cloning': False}, PHONON))
        self.assertEqual(['ua_3', 'sa_5', 'phonon_noemie'],
                         self._apply(ctx, {'supports_cloning': False}, KOKORO))

    def test_a_reference_voice_needs_an_engine_that_clones(self):
        """Le serveur ne passe une voix de référence qu'à un moteur qui clone (`speaker_wav_for`) :
        sous un autre, elle n'aurait aucun effet."""
        ctx = self._ctx()
        self.assertEqual(['phonon_noemie', 'ff_siwis'],
                         self._apply(ctx, {'supports_cloning': True}, 'synthesizer:coqui-xtts'))

    def test_under_auto_engine_voices_hide_once_the_catalog_has_answered(self):
        ctx = self._ctx()
        self.assertEqual([], self._apply(ctx, None, 'auto', loaded='false'),
                         "avant la réponse du catalogue, rien ne se juge")
        self.assertEqual(['phonon_noemie', 'ff_siwis'], self._apply(ctx, None, 'auto'))

    def test_a_hidden_selected_voice_moves_to_the_first_visible_one(self):
        ctx = self._ctx()
        ctx.eval("sel.options[0].selected = false; sel.options[3].selected = true;"
                 "sel.value = 'phonon_noemie';")
        self._apply(ctx, {}, KOKORO)
        self.assertEqual('default', ctx.eval("sel.value"))
        self.assertEqual(1, ctx.eval("sel.changed"))


class AssistantVoiceModelTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('assistant_voice_user', password='x')

    def test_auto_takes_the_fastest_realtime_model_that_speaks_the_language(self):
        from wama.common.tts.assistant_voice import voice_model_for
        _tts_row(PHONON, realtime=True, first_audio_s=1.1)
        _tts_row(KOKORO, realtime=True, first_audio_s=0.26)
        _tts_row('huggingface:org/slow-but-unmeasured', realtime=True)
        _tts_row('huggingface:org/not-realtime', realtime=False, first_audio_s=0.1)
        _tts_row('huggingface:org/english-only', realtime=True, first_audio_s=0.05,
                 languages=['en'])
        with mock.patch('wama.model_manager.services.model_selector.full_gpu_budget_gb',
                        return_value=None):
            self.assertEqual(KOKORO, voice_model_for(self.user, 'auto', 'fr'))

    def test_a_chosen_model_is_kept_and_no_realtime_model_means_none(self):
        from wama.common.tts.assistant_voice import voice_model_for
        self.assertEqual(PHONON, voice_model_for(self.user, PHONON, 'fr'))
        self.assertIsNone(voice_model_for(self.user, 'auto', 'fr'))


class AssistantVoiceSettingsTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('assistant_voice_settings', password='x')
        self.client = Client()
        self.client.force_login(self.user)

    def _post(self, **data):
        return self.client.post('/api/ai-chat/settings/', json.dumps(data),
                                content_type='application/json')

    def test_a_synthesis_model_and_one_of_the_offered_voices_are_saved(self):
        from wama.common.services.assistant_engine import assistant_settings
        _tts_row(PHONON, voices=[{'value': 'phonon_lucien', 'label': 'Lucien', 'language': 'fr'}])
        self.assertEqual(200, self._post(voice_model=PHONON, voice_preset='phonon_lucien').status_code)
        saved = assistant_settings(self.user)
        self.assertEqual((PHONON, 'phonon_lucien'), (saved['voice_model'], saved['voice_preset']))

    def test_a_model_outside_the_menu_or_an_unknown_voice_is_refused(self):
        AIModel.objects.update_or_create(model_key='ollama:some-llm', defaults=dict(
            name='some-llm', model_type='llm', source='ollama', is_available=True,
            capabilities={'task': 'text-generation'}))
        self.assertEqual(400, self._post(voice_model='ollama:some-llm').status_code)
        self.assertEqual(400, self._post(voice_preset='phonon_inexistante').status_code)


class AssistantVocalisationTest(TestCase):
    """La vue de vocalisation dit avec le modèle et la voix du COMPTE — le navigateur n'envoie
    que le texte."""

    def setUp(self):
        self.user = User.objects.create_user('assistant_vocalisation', password='x')
        self.client = Client()
        self.client.force_login(self.user)

    def test_the_saved_model_and_voice_reach_the_voice_service(self):
        from wama.common.utils.user_settings import save_user_app_settings
        _tts_row(PHONON, voices=[{'value': 'phonon_augustin', 'label': 'Augustin'}],
                 supports_cloning=False)
        save_user_app_settings(self.user, 'assistant',
                               {'voice_model': PHONON, 'voice_preset': 'phonon_augustin'})
        with mock.patch('wama.common.tts.service_client.tts_via_service',
                        return_value=b'RIFF') as service:
            response = self.client.post('/api/tts-kokoro/', json.dumps({'text': 'Bonjour.'}),
                                        content_type='application/json')
        self.assertEqual(200, response.status_code, response.content)
        args, kwargs = service.call_args
        self.assertEqual(PHONON, args[1])
        self.assertEqual('phonon_augustin', kwargs['voice_preset'])
        self.assertIsNone(kwargs['speaker_wav'], "un moteur qui ne clone pas ne reçoit pas de voix")

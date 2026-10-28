"""Le choix de la voix (2026-10-28) : les voix PROPRES des moteurs, et le modèle de voix de
l'assistant — choisi par le compte ou tiré « auto ».

Quatre étages, gardés chacun là où un défaut ne se verrait pas à l'usage :
  • la source commune des voix range chaque voix de moteur avec les modèles qui la DISENT
    (`data-models`) — deux moteurs aux mêmes voix (les deux Kokoro) partagent un groupe ;
  • la règle du navigateur, dans les deux sens : sous un modèle, ne restent que les voix qu'il dit
    (`WamaModelCaps.cloneVoiceFilter`) ; une voix choisie grise les modèles qui ne la disent pas
    (`WamaInputMatch.voiceSlot`) ; sous « auto », tout reste ;
  • le tirage « auto » reçoit la voix choisie (`auto_model.narrow_by_voice`), au lancement comme
    pour la prévision ;
  • la vocalisation de l'assistant dit ses réponses avec le modèle et la voix du compte, ou le
    plus rapide en temps réel dans sa langue — sauf voix choisie, qui l'emporte.
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
KOKORO_PT = 'synthesizer:kokoro'
XTTS = 'synthesizer:coqui-xtts'
CLONER = 'huggingface:org/cloning-engine'

NOEMIE = {'value': 'phonon_noemie', 'label': 'Noémie', 'language': 'fr'}
SIWIS = {'value': 'ff_siwis', 'label': 'Français féminin', 'language': 'fr'}


def _tts_row(key, voices=(), downloaded=True, engine=None, **caps):
    return AIModel.objects.update_or_create(
        model_key=key, defaults=dict(
            name=key.rsplit('/', 1)[-1], model_type='speech', source='huggingface',
            is_available=True, is_downloaded=downloaded, vram_gb=0.5,
            composition={'runtime': {'engine': engine}} if engine else {},
            capabilities={'task': 'text-to-speech', 'languages': ['fr'],
                          **({'voices': list(voices)} if voices else {}), **caps}))[0]


class EngineVoiceGroupsTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('engine_voices_user', password='x')

    def test_each_voice_carries_the_models_that_name_it(self):
        from wama.common.utils.voice_options import get_voice_groups
        _tts_row(PHONON, voices=[NOEMIE])
        _tts_row('huggingface:org/silent-engine')            # aucune voix propre : aucun groupe
        groups = {g['key']: g for g in get_voice_groups(self.user)}
        group = groups[f'engine:{PHONON}']
        self.assertEqual([('phonon_noemie', 'Noémie')], group['options'])
        self.assertEqual({'phonon_noemie': {'models': PHONON, 'language': 'fr'}}, group['attributes'])
        self.assertFalse([k for k in groups if 'silent-engine' in k])

    def test_two_engines_with_the_same_voices_share_one_group(self):
        """Sous « auto » toutes les voix restent offertes : deux groupes identiques mettraient deux
        fois la même valeur dans le select."""
        from wama.common.utils.voice_options import get_voice_groups
        _tts_row(KOKORO, voices=[SIWIS])
        _tts_row(KOKORO_PT, voices=[SIWIS])
        engine = [g for g in get_voice_groups(self.user) if g['key'].startswith('engine:')]
        self.assertEqual(1, len(engine), engine)
        self.assertEqual({KOKORO, KOKORO_PT},
                         set(engine[0]['attributes']['ff_siwis']['models'].split(' ')))

    def test_the_bark_presets_are_no_longer_offered_under_every_engine(self):
        from wama.common.utils.voice_options import get_voice_groups
        values = [v for g in get_voice_groups(self.user) for v, _ in g['options']]
        self.assertFalse([v for v in values if v.startswith('bark_')],
                         "sans ligne Bark qui les porte, aucun préréglage Bark")


class VoiceRuleTest(SimpleTestCase):
    """La règle du navigateur, exécutée par V8 sur les fichiers SERVIS, dans les deux sens."""

    BROWSER = """
var window = this;
function Event(t) { this.type = t; }
function option(value, models) {
  return { value: value, textContent: value, hidden: false, disabled: false, selected: false,
           title: '', dataset: models ? { models: models } : {} };
}
function select(values) {
  var opts = values.map(function (v) { return option(v[0], v[1]); });
  opts[0].selected = true;
  return { options: opts, value: opts[0].value, changed: 0, selectedOptions: [opts[0]],
           dispatchEvent: function () { this.changed++; } };
}
function choose(sel, i) {
  sel.options.forEach(function (o) { o.selected = false; });
  sel.options[i].selected = true; sel.value = sel.options[i].value; sel.selectedOptions = [sel.options[i]];
}
function hidden(sel) { return sel.options.filter(function (o) { return o.hidden; })
                                          .map(function (o) { return o.value; }); }
"""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        js = Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
        ctx = MiniRacer()
        ctx.eval(self.BROWSER + (js / 'wama-model-caps.js').read_text(encoding='utf-8')
                 + (js / 'wama-input-match.js').read_text(encoding='utf-8'))
        ctx.eval("var f = WamaModelCaps.cloneVoiceFilter('v');"
                 "var sel = select([['default'], ['ua_3'], ['sa_5'], ['phonon_noemie', '%s'],"
                 " ['ff_siwis', '%s %s']]);" % (PHONON, KOKORO, KOKORO_PT))
        return ctx

    CAPS = {
        PHONON: {'supports_cloning': False, 'voices': [NOEMIE]},
        KOKORO: {'supports_cloning': False, 'voices': [SIWIS]},
        XTTS: {'supports_cloning': True, 'inputs_optional': ['reference_voice']},
    }

    def _apply(self, ctx, key):
        ctx.eval("WamaModelCaps.applyOptionFilter(sel, f, %s, %s)"
                 % (json.dumps(self.CAPS.get(key)), json.dumps(key)))
        return list(ctx.eval("hidden(sel)"))

    def test_under_a_model_only_the_voices_it_says_remain(self):
        ctx = self._ctx()
        self.assertEqual(['ua_3', 'sa_5', 'ff_siwis'], self._apply(ctx, PHONON))
        self.assertEqual(['ua_3', 'sa_5', 'phonon_noemie'], self._apply(ctx, KOKORO))
        self.assertEqual(['phonon_noemie', 'ff_siwis'], self._apply(ctx, XTTS),
                         "un moteur qui clone dit les enregistrements, pas les voix d'un autre")

    def test_under_auto_every_voice_stays_offered(self):
        """« auto » est le tirage : c'est lui qui reçoit la voix choisie (`narrow_by_voice`)."""
        ctx = self._ctx()
        self.assertEqual([], self._apply(ctx, 'auto'))

    def test_a_hidden_selected_voice_moves_to_the_first_visible_one(self):
        ctx = self._ctx()
        ctx.eval("choose(sel, 3)")
        self._apply(ctx, KOKORO)
        self.assertEqual('default', ctx.eval("sel.value"))
        self.assertEqual(1, ctx.eval("sel.changed"))

    def _slot(self, ctx, index, key):
        ctx.eval("choose(sel, %d); var slot = WamaInputMatch.voiceSlot('v');" % index)
        return (ctx.eval("slot.isProvided(sel)"),
                ctx.eval("slot.accepts(%s, sel)" % json.dumps(self.CAPS.get(key) or {})))

    def test_a_chosen_engine_voice_greys_the_models_that_do_not_name_it(self):
        ctx = self._ctx()
        self.assertEqual((True, True), self._slot(ctx, 3, PHONON))
        self.assertEqual((True, False), self._slot(ctx, 3, KOKORO))
        self.assertEqual((True, True), self._slot(ctx, 4, KOKORO), "Kokoro dit sa propre voix")
        self.assertEqual('Voix « phonon_noemie »', ctx.eval("choose(sel, 3); slot.label(sel)"),
                         "la raison du grisage nomme la voix, pas « Voix de référence »")

    def test_a_chosen_recording_greys_the_engines_without_a_reference_voice(self):
        ctx = self._ctx()
        for index in (1, 2):                                 # ua_ puis sa_
            self.assertEqual((True, False), self._slot(ctx, index, KOKORO))
            self.assertEqual((True, True), self._slot(ctx, index, XTTS))

    def test_the_default_voice_greys_nothing(self):
        ctx = self._ctx()
        self.assertFalse(self._slot(ctx, 0, KOKORO)[0])


class VoiceDrawTest(TestCase):
    """Le tirage « auto » reçoit la voix choisie — `resolve_model_choice(voice=…)`."""

    def setUp(self):
        # Chaque ligne porte son moteur réel : sans lui, la sélection la sort du tirage et le test
        # ne mesurerait que le repli (vu à la contre-épreuve).
        _tts_row(KOKORO, voices=[SIWIS], supports_cloning=False, engine='kokoro-onnx')
        _tts_row(PHONON, voices=[NOEMIE], supports_cloning=False, engine='phonon')
        # Un modèle FICTIF qui clone, porté par un moteur réel (`coqui`) : sans moteur, la sélection
        # le juge « sans route d'exécution » et le sort du tirage.
        _tts_row(CLONER, supports_cloning=True, engine='coqui')
        # Plus lourd que les autres : sans la voix, le tirage au curseur rapide ne le prend pas.
        AIModel.objects.filter(model_key=CLONER).update(vram_gb=4.0)

    def _draw(self, voice, **kw):
        from wama.common.utils.auto_model import resolve_model_choice
        # Un budget FIXE : la VRAM libre du moment (GPU partagé avec WAMA en service) ne décide pas.
        with mock.patch('wama.model_manager.services.model_selector.full_gpu_budget_gb',
                        return_value=24.0):
            return resolve_model_choice('auto', spec={'task': 'text-to-speech'}, quality_intent=0,
                                        voice=voice, fallback='repli', **kw)

    def test_the_constraint_of_each_kind_of_voice(self):
        from wama.common.tts.voice_refs import voice_draw_constraint
        self.assertEqual({'requires': ['supports_cloning']}, voice_draw_constraint('ua_3'))
        self.assertEqual({'requires': ['supports_cloning']}, voice_draw_constraint('sa_5'))
        self.assertEqual({'candidates': [PHONON]}, voice_draw_constraint('phonon_noemie'))
        self.assertEqual({}, voice_draw_constraint('default'))
        self.assertEqual({}, voice_draw_constraint('female_1'), "un nom hérité ne contraint rien")

    def test_an_engine_voice_draws_a_model_that_names_it(self):
        self.assertEqual(PHONON, self._draw('phonon_noemie'))
        self.assertEqual(KOKORO, self._draw('ff_siwis'))

    def test_a_recording_draws_an_engine_that_clones(self):
        self.assertEqual(CLONER, self._draw('sa_5'))

    def test_an_engine_voice_whose_model_is_not_installed_still_gets_it(self):
        """Sans modèle installé qui la dit, la tâche prend quand même celui qui la nomme — la route
        l'installe (`ensure_model`) — au lieu de tirer un moteur qui dirait une autre voix."""
        AIModel.objects.filter(model_key=PHONON).update(is_downloaded=False)
        self.assertEqual(PHONON, self._draw('phonon_noemie'))

    def test_the_forecast_receives_the_voice_like_the_launch(self):
        from django.urls import reverse
        user = User.objects.create_user('voice_forecast_user', password='x')
        client = Client()
        client.force_login(user)
        with mock.patch('wama.model_manager.services.model_selector.full_gpu_budget_gb',
                        return_value=24.0):
            reply = client.get(reverse('model_manager:api_model_options'),
                               {'task': 'text-to-speech', 'auto': '1', 'voice': 'phonon_noemie'})
        self.assertEqual(PHONON, (reply.json().get('auto_preview') or {}).get('id'), reply.json())

    def test_the_two_apps_hand_the_voice_to_their_draw(self):
        from wama.common.utils.auto_model import declared_resolution
        for app in ('synthesizer', 'avatarizer'):
            self.assertEqual('voice_preset', declared_resolution(app).get('voice'), app)


class AssistantVoiceModelTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('assistant_voice_user', password='x')

    def _for(self, requested, voice=''):
        from wama.common.tts.assistant_voice import voice_model_for
        with mock.patch('wama.model_manager.services.model_selector.full_gpu_budget_gb',
                        return_value=None):
            return voice_model_for(self.user, requested, 'fr', voice)

    def test_auto_takes_the_fastest_realtime_model_that_speaks_the_language(self):
        _tts_row(PHONON, realtime=True, first_audio_s=1.1)
        _tts_row(KOKORO, realtime=True, first_audio_s=0.26)
        _tts_row('huggingface:org/slow-but-unmeasured', realtime=True)
        _tts_row('huggingface:org/not-realtime', realtime=False, first_audio_s=0.1)
        _tts_row('huggingface:org/english-only', realtime=True, first_audio_s=0.05,
                 languages=['en'])
        self.assertEqual(KOKORO, self._for('auto'))

    def test_a_chosen_voice_wins_over_speed(self):
        _tts_row(PHONON, voices=[NOEMIE], realtime=True, first_audio_s=1.1)
        _tts_row(KOKORO, voices=[SIWIS], realtime=True, first_audio_s=0.26)
        self.assertEqual(PHONON, self._for('auto', 'phonon_noemie'))

    def test_a_chosen_model_is_kept_and_no_realtime_model_means_none(self):
        self.assertEqual(PHONON, self._for(PHONON))
        self.assertIsNone(self._for('auto'))


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

"""Le select du transcriber au grain MODÈLE, tiré du CATALOGUE (route F4b ⑦, 2026-09-30).

Décision de Fabien : grain modèle, clés entières, domaine par TÂCHE `transcription`, distants par
`options_cloud`. CE QUE CES GARDES TIENNENT :
- le schéma DÉCLARE la source (plus de liste servie par l'app ni remplie en JS) ;
- toute valeur écrite devient une CLÉ (anciens noms de moteur compris), et la migration 0027 fait
  la même transformation sur les lignes existantes, dans les deux sens ;
- « auto » se tire par la brique commune, dans le domaine du select, Whisper d'abord, et
  n'emporte pas un modèle qui exige une autre entrée qu'un audio ;
- la porte des outils accepte les clés lançables et les anciens noms, refuse un modèle grisé ;
- la card montre le modèle QUI A TOURNÉ, et le dit quand ce n'est pas celui demandé ;
- l'endpoint propre à l'app (`/transcriber/backends/`) n'existe plus.
"""
import importlib
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from wama.transcriber.backends.manager import (
    LEGACY_ENGINE_MODELS, backend_choice_values, catalogue_value, engine_name_for,
    resolve_auto_key,
)
from wama.transcriber.catalogue_fixtures import transcription_catalogue, transcription_row
from wama.transcriber.models import Transcript


def _transcript(user, backend='auto', **fields):
    return Transcript.objects.create(user=user, audio='transcriber/input/a.wav', backend=backend,
                                     **fields)


class TheSchemaDeclaresTheCatalogueTest(TestCase):

    def test_the_model_select_is_a_catalogue_source_by_task_with_auto_and_remote(self):
        from wama.transcriber.params import PARAMS_JSON
        field = next(p for p in PARAMS_JSON if p['name'] == 'backend')
        self.assertEqual('catalog', field['options_source'])
        self.assertEqual({'task': 'transcription'}, field['options_query'])
        self.assertTrue(field['options_auto'])
        self.assertTrue(field['options_cloud'])
        self.assertFalse(field.get('choices'), 'no static list: auto comes with the options')

    def test_serving_auto_brings_the_quality_slider_shown_on_auto_only(self):
        from wama.transcriber.params import PARAMS_JSON
        slider = next(p for p in PARAMS_JSON if p['type'] == 'intent')
        self.assertEqual({'field': 'backend', 'equals': 'auto'}, slider['show_if'])
        self.assertEqual(['panel'], list(slider['contexts']),
                         'an app setting, like the reader: the card has no column for it')

    def test_the_apps_own_engine_endpoint_is_gone(self):
        with self.assertRaises(NoReverseMatch):
            reverse('transcriber:backends')


class EveryWrittenValueIsACatalogueKeyTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('select_keys', password='x')

    def test_old_engine_names_become_the_model_each_engine_loaded_by_default(self):
        for value, key in LEGACY_ENGINE_MODELS.items():
            with self.subTest(value=value):
                self.assertEqual(key, _transcript(self.user, value).backend)

    def test_a_bare_id_joins_the_transcriber_space_and_keys_and_auto_are_kept(self):
        self.assertEqual('transcriber:canary-1b-v2', catalogue_value('canary-1b-v2'))
        for value in ('auto', '', 'albert:whisper-large-v3', 'huggingface:aihpi/FrWhisper'):
            with self.subTest(value=value):
                self.assertEqual(value, catalogue_value(value))

    def test_a_long_repository_key_fits_the_field(self):
        key = 'huggingface:linagora/linto_stt_fr_fastconformer_pc'
        self.assertEqual(key, _transcript(self.user, key).backend)

    def test_the_migration_rekeys_stored_rows_and_reverses_exactly(self):
        migration = importlib.import_module(
            'wama.transcriber.migrations.0027_transcript_backend_catalog_keys')
        rows = {value: _transcript(self.user) for value in ('whisper', 'qwen_asr', 'nemo',
                                                            'qwen3-asr-0.6b', 'auto')}
        for value, row in rows.items():   # `update()` : l'état d'AVANT, sans la normalisation
            Transcript.objects.filter(pk=row.pk).update(backend=value)
        migration.to_catalog_keys(django_apps, None)
        stored = {v: Transcript.objects.get(pk=r.pk).backend for v, r in rows.items()}
        self.assertEqual({'whisper': 'transcriber:whisper',
                          'qwen_asr': 'transcriber:qwen3-asr-1.7b',
                          'nemo': 'transcriber:parakeet-tdt-0.6b-v3',
                          'qwen3-asr-0.6b': 'transcriber:qwen3-asr-0.6b', 'auto': 'auto'}, stored)
        migration.to_engine_names(django_apps, None)
        self.assertEqual({v: v for v in rows},
                         {v: Transcript.objects.get(pk=r.pk).backend for v, r in rows.items()})


class TheAutoDrawTest(TestCase):

    def setUp(self):
        transcription_catalogue('transcriber:whisper', 'transcriber:qwen3-asr-1.7b')

    def test_auto_draws_a_full_key_whisper_first(self):
        self.assertEqual('transcriber:whisper', resolve_auto_key())

    def test_a_model_that_needs_another_input_than_audio_is_not_drawn(self):
        """`describer:whisper` requires `work_file` (a describer's input) and is announced far
        lighter: without the provided inputs it would win the whisper tier."""
        transcription_row('describer:whisper', engine='faster-whisper', vram_gb=0.3,
                          capabilities={'task': 'transcription', 'inputs_required': ['work_file']})
        for intent in (0, 50):
            with self.subTest(intent=intent):
                with mock.patch('wama.common.utils.auto_model.quality_intent_of',
                                return_value=intent):
                    self.assertEqual('transcriber:whisper',
                                     resolve_auto_key(user=get_user_model()(pk=1)))

    def test_an_empty_catalogue_falls_back_without_raising(self):
        from wama.model_manager.models import AIModel
        AIModel.objects.all().delete()
        self.assertEqual('transcriber:whisper', resolve_auto_key())


class ThePreviewSaysWhatTheLaunchDrawsTest(TestCase):
    """2026-10-01, after the restart: the select announced Qwen3-ASR while the launch drew
    Whisper — the whisper-first policy and the provided input lived in the manager, read by the
    launch only. They are declared on the schema now (`options_resolution`) and travel with the
    select's request, built here the way `wama-params.js` builds it."""

    def setUp(self):
        # Ranks as measured in production: without the policy, Qwen3-ASR wins the draw.
        transcription_row('transcriber:whisper', benchmark_index=6.237)
        transcription_row('transcriber:qwen3-asr-1.7b', benchmark_index=5.683)
        self.user = get_user_model().objects.create_user('preview_draw', password='x')
        self.client.force_login(self.user)
        from wama.transcriber.params import PARAMS_JSON
        self.field = next(p for p in PARAMS_JSON if p['name'] == 'backend')

    def _preview(self, with_resolution=True):
        query = dict(self.field['options_query'], auto='1', cloud='1')
        if with_resolution:
            query.update({k: ','.join(v) for k, v in self.field['options_resolution'].items()})
        response = self.client.get('/model-manager/api/models/options/', query)
        return response.json()['auto_preview']['id']

    def test_the_preview_draws_the_model_the_launch_draws(self):
        self.assertEqual('transcriber:whisper', resolve_auto_key(user=self.user))
        self.assertEqual(resolve_auto_key(user=self.user), self._preview())

    def test_without_the_declared_refinements_the_preview_would_differ(self):
        """Counter-proof: the case is one where the refinements change the answer."""
        self.assertEqual('transcriber:qwen3-asr-1.7b', self._preview(with_resolution=False))


class TheToolDoorDomainTest(TestCase):

    def test_launchable_keys_and_old_names_pass_a_greyed_model_does_not(self):
        transcription_catalogue('transcriber:whisper', 'transcriber:qwen3-asr-1.7b')
        transcription_row('huggingface:aihpi/FrWhisper', engine='transformers')
        values = backend_choice_values()
        for value in ('auto', 'transcriber:whisper', 'transcriber:qwen3-asr-1.7b', 'whisper',
                      'qwen_asr'):
            with self.subTest(value=value):
                self.assertIn(value, values)
        self.assertNotIn('huggingface:aihpi/FrWhisper', values,
                         'weights installed without a backend are greyed, not offered')


class TheEstimateLearnsUnderTheEngineTest(TestCase):

    def test_a_model_key_is_read_as_the_engine_it_runs_on(self):
        transcription_catalogue('transcriber:canary-1b-v2')
        self.assertEqual('qwen_asr', engine_name_for('transcriber:qwen3-asr-1.7b'))
        self.assertEqual('nemo', engine_name_for('transcriber:canary-1b-v2'))
        self.assertEqual('albert', engine_name_for('albert:whisper-large-v3'))
        self.assertEqual('whisper', engine_name_for('whisper'))
        self.assertEqual('', engine_name_for('auto'))


class TheCardShowsTheModelThatRanTest(TestCase):

    def setUp(self):
        transcription_catalogue('transcriber:whisper', 'transcriber:qwen3-asr-1.7b')
        self.user = get_user_model().objects.create_user('select_chip', password='x')

    def _chip(self, t):
        from wama.transcriber.views import _decorate_card
        return next(c for c in _decorate_card(t).chips['settings']
                    if c.get('icon') == 'fa-microchip')

    def test_a_request_run_by_another_model_is_flagged(self):
        t = _transcript(self.user, 'transcriber:qwen3-asr-1.7b', model_key='transcriber:whisper')
        chip = self._chip(t)
        self.assertEqual('warn', chip.get('variant'))
        self.assertIn('transcriber:qwen3-asr-1.7b', chip.get('title', ''))

    def test_auto_names_the_model_it_drew(self):
        t = _transcript(self.user, 'auto', model_key='transcriber:qwen3-asr-1.7b')
        self.assertTrue(self._chip(t)['label'].endswith('(auto)'))
        self.assertEqual('auto', self._chip(_transcript(self.user, 'auto'))['label'])

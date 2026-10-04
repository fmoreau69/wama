"""The LLM harness on the composer's prompt (2026-10-04, Fabien: « est-ce que le harnais LLM
s'applique correctement ? Dans la card V4 du composer, il n'y a pas le bouton Traduire et enrichir.
Est-ce que YuE2 utilise bien les skills/prompts ? »).

Measured on card #321: the launch-time pipeline DID run (translated fr→en, enriched 32→287), but:
  * the card had no on-demand trigger — the ✨ button was written inside the imager;
  * the on-demand enrichment never received the target model's CONTRACT (the view did not pass it);
  * under « auto », the pipeline read `auto:text-to-music` — no model, so neither its languages
    nor its contract.
"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock, skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.composer import tasks

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None


class ThePipelineHearsTheModelOfThisLaunchTest(SimpleTestCase):

    def test_under_auto_the_drawn_model_is_passed_not_the_auto_value(self):
        gen = SimpleNamespace(prompt='électro rock', user=None, model='auto:text-to-music')
        ctx = SimpleNamespace(app_id='composer', console=lambda *a, **k: None)
        with mock.patch.object(tasks, '_model_key', return_value='huggingface:m-a-p/YuE2-3B'), \
                mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                           return_value='electro rock') as pipeline:
            self.assertEqual('electro rock', tasks._routed_prompt(gen, ctx))
        self.assertEqual('huggingface:m-a-p/YuE2-3B', pipeline.call_args.kwargs['model_id'])


class TheOnDemandEnrichmentFollowsTheTargetModelTest(TestCase):

    def setUp(self):
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='huggingface:org/Song', name='Song', source='huggingface',
                               prompt_contract='STYLE then [Verse] lyrics')
        self.client.force_login(get_user_model().objects.create_user('enrich_me', password='x'))

    def _post(self, target):
        with mock.patch('wama.common.utils.prompt_enrichment.enrich_on_demand',
                        return_value='rich') as enrich:
            response = self.client.post(reverse('common:enrich_prompt'), data=json.dumps(
                {'prompt': 'électro rock', 'app': 'composer', 'domain': 'music',
                 'target_model': target}), content_type='application/json')
        self.assertEqual(200, response.status_code)
        return enrich.call_args.kwargs['contract']

    def test_the_chosen_model_s_contract_shapes_the_enrichment(self):
        self.assertEqual('STYLE then [Verse] lyrics', self._post('huggingface:org/Song'))

    def test_auto_or_nothing_brings_no_contract(self):
        self.assertIsNone(self._post('auto:text-to-music'))
        self.assertIsNone(self._post(''))


class TheTaskSendsTheEnrichedPromptOnceTest(SimpleTestCase):
    """The imager's route (2026-10-04): what the ingestion enriched — or the user edited in the
    modal — is what leaves; an already enriched prompt is not enriched a second time."""

    def _route(self, **fields):
        gen = SimpleNamespace(prompt='électro rock', user=None, model='composer:musicgen-small',
                              **fields)
        ctx = SimpleNamespace(app_id='composer', console=lambda *a, **k: None)
        with mock.patch.object(tasks, '_model_key', return_value='composer:musicgen-small'), \
                mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                           return_value='routed') as pipeline:
            tasks._routed_prompt(gen, ctx)
        return pipeline.call_args

    def test_the_enriched_prompt_leaves_without_a_second_enrichment(self):
        call = self._route(prompt_processed='driving electro rock, 128 BPM',
                           prompt_keywords=['synthwave'])
        self.assertEqual('driving electro rock, 128 BPM', call.args[2])
        self.assertIs(False, call.kwargs['enrich'])
        self.assertEqual(['synthwave'], call.kwargs['glossary'])

    def test_without_an_enriched_prompt_the_declaration_decides(self):
        call = self._route(prompt_processed='', prompt_keywords=[])
        self.assertEqual('électro rock', call.args[2])
        self.assertIsNone(call.kwargs['enrich'])


SONG = "Chanson pop douce\n[Verse]\nSous la pluie je marche seul\n[Chorus]\nEt je chante"


class TheLyricsNeverGoThroughTheLLMTest(SimpleTestCase):
    """Fabien, 2026-10-04: translation and enrichment touch the DESCRIPTION; the user's lyrics
    come back verbatim — a LLM that « improves » or translates lyrics destroys them."""

    def _pipeline(self, routing=None):
        def fake(prompt, **kw):
            return {'prompt': prompt.upper(), 'original': prompt, 'translated': True,
                    'enriched': True, 'routing': routing or {}, 'reason': 'x'}
        return mock.patch('wama.common.utils.prompt_pipeline.process_prompt', side_effect=fake)

    def test_only_the_description_is_processed_and_the_lyrics_come_back_intact(self):
        from wama.common.utils.app_metadata import process_prompt_for
        with self._pipeline() as pipeline, \
                mock.patch('wama.common.utils.app_metadata._resolve_model',
                           return_value=(None, 'music', None)):
            out = process_prompt_for('composer', 'prompt', SONG, full=True)
        self.assertEqual('Chanson pop douce', pipeline.call_args.args[0])
        self.assertEqual("CHANSON POP DOUCE\n\n[Verse]\nSous la pluie je marche seul\n"
                         "[Chorus]\nEt je chante", out['prompt'])
        self.assertEqual(SONG, out['original'])
        self.assertTrue(out['lyrics_spared'])

    def test_a_model_without_that_language_is_said(self):
        from wama.common.utils.app_metadata import process_prompt_for
        said = []
        with self._pipeline({'input_translate': True, 'model_languages': ['en', 'zh']}), \
                mock.patch('wama.common.utils.app_metadata._resolve_model',
                           return_value=(None, 'music', None)):
            process_prompt_for('composer', 'prompt', SONG, console=said.append)
        self.assertIn('en, zh', said[-1])
        self.assertIn('jamais traduites', said[-1])

    def test_a_prompt_without_tags_goes_through_whole(self):
        from wama.common.utils.app_metadata import process_prompt_for
        with self._pipeline() as pipeline, \
                mock.patch('wama.common.utils.app_metadata._resolve_model',
                           return_value=(None, 'music', None)):
            self.assertEqual('AMBIENT PIANO', process_prompt_for('composer', 'prompt',
                                                                  'ambient piano'))
        self.assertEqual('ambient piano', pipeline.call_args.args[0])

    def test_the_on_demand_enrichment_spares_them_too(self):
        from wama.common.utils.app_metadata import enrich_prompt_value
        with mock.patch('wama.common.utils.prompt_enrichment.enrich_on_demand',
                        return_value='Soft pop, warm female voice') as enrich:
            out = enrich_prompt_value('composer', 'prompt', SONG, domain='music')
        self.assertEqual('Chanson pop douce', enrich.call_args.args[0])
        self.assertTrue(out.startswith('Soft pop, warm female voice\n\n[Verse]\nSous la pluie'))

    def test_lyrics_alone_have_nothing_to_enrich_and_it_is_said(self):
        from wama.common.utils.app_metadata import enrich_prompt_value
        with self.assertRaisesRegex(RuntimeError, 'que des paroles'):
            enrich_prompt_value('composer', 'prompt', "[Verse]\nla la la", domain='music')

    def test_an_app_without_lyrics_is_untouched(self):
        from wama.common.utils.app_metadata import enrich_prompt_value
        with mock.patch('wama.common.utils.prompt_enrichment.enrich_on_demand',
                        return_value='rich') as enrich:
            enrich_prompt_value('imager', 'prompt', "[sic] a cat", domain='image')
        self.assertEqual('[sic] a cat', enrich.call_args.args[0])


class TheIngestionFollowsTheTargetModelTest(TestCase):
    """The ingestion enriched with the app skill alone — MusicGen's 30-80 words for a card bound
    to YuE2. It now passes the chosen model's contract, and under an « auto » whose candidates
    bear one, it leaves the enrichment to the launch (the drawn model is not known before)."""

    def setUp(self):
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='huggingface:org/Song', name='Song', source='huggingface',
                               capabilities={'task': 'text-to-music'},
                               prompt_contract='STYLE then [Verse] lyrics')
        AIModel.objects.create(model_key='composer:musicgen-small', name='MusicGen',
                               source='composer', capabilities={'task': 'text-to-music'})
        self.user = get_user_model().objects.create_user('ingest_me', password='x')

    def _ingest(self, model):
        from wama.common.utils.app_metadata import enrich_instance_prompts
        from wama.composer.models import ComposerGeneration
        # The ingestion receiver queues on COMMIT — never reached inside a TestCase.
        gen = ComposerGeneration.objects.create(user=self.user, prompt='électro rock', model=model)
        with mock.patch('wama.common.utils.prompt_enrichment.enrichment_enabled',
                        return_value=True), \
                mock.patch('wama.common.utils.prompt_enrichment.enrich_on_demand',
                           return_value='driving electro rock') as enrich:
            enrich_instance_prompts('composer', gen, user=self.user)
        gen.refresh_from_db()
        return gen, enrich

    def test_the_chosen_model_s_contract_shapes_the_ingested_enrichment(self):
        gen, enrich = self._ingest('huggingface:org/Song')
        self.assertEqual('STYLE then [Verse] lyrics', enrich.call_args.kwargs['contract'])
        self.assertEqual('driving electro rock', gen.prompt_processed)
        self.assertEqual('électro rock', gen.prompt)

    def test_under_auto_with_a_contract_bearing_candidate_the_launch_decides(self):
        gen, enrich = self._ingest('auto:text-to-music')
        enrich.assert_not_called()
        self.assertEqual('', gen.prompt_processed)


class TheModalWritesTheRightFaceTest(TestCase):
    """`apply_prompt_state` in the composer's settings route: editing the enriched text keeps the
    user's own; taking one's own text back makes the enriched one stale, hence emptied."""

    def setUp(self):
        from wama.composer.models import ComposerGeneration
        user = get_user_model().objects.create_user('modal_me', password='x')
        from django.contrib.auth.models import Group
        user.groups.add(*[Group.objects.get_or_create(name=n)[0]
                          for n in ('user', 'role:communication')])
        self.client.force_login(user)
        self.gen = ComposerGeneration.objects.create(
            user=user, prompt='électro rock', prompt_processed='driving electro rock',
            model='composer:musicgen-small')

    def _save(self, text, state):
        response = self.client.post(reverse('composer:update_settings', args=[self.gen.id]),
                                    {'prompt': text, 'prompt_state': state, 'restart': '0'})
        self.assertEqual(200, response.status_code, response.content[:200])
        self.gen.refresh_from_db()

    def test_editing_the_enriched_face_keeps_the_original(self):
        self._save('driving electro rock, 128 BPM', 'processed')
        self.assertEqual('électro rock', self.gen.prompt)
        self.assertEqual('driving electro rock, 128 BPM', self.gen.prompt_processed)

    def test_taking_one_s_own_text_back_empties_the_enriched_one(self):
        self._save('rock électro lent', 'user')
        self.assertEqual('rock électro lent', self.gen.prompt)
        self.assertEqual('', self.gen.prompt_processed)


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class TheBrickOffersItsTriggerWhenAskedTest(SimpleTestCase):

    def _bar(self, cfg):
        from py_mini_racer import MiniRacer
        v8 = MiniRacer()
        v8.eval("""
            function el() { return {style: {}, dataset: {}, innerHTML: '', textContent: '',
                                    addEventListener: function () {},
                                    insertAdjacentElement: function () {}}; }
            var window = {}; var document = {createElement: function () { return el(); }};
            var field = el(); field.value = 'électro rock'; field.tagName = 'TEXTAREA';
        """)
        v8.eval((Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-prompt-enrich.js')
                .read_text(encoding='utf-8'))
        return v8.eval(f"window.WamaPromptEnrich.attach(field, {json.dumps(cfg)}).bar.innerHTML")

    def test_with_trigger_the_card_can_ask_for_an_enrichment(self):
        self.assertIn('Traduire et enrichir', self._bar({'app': 'composer', 'trigger': True}))

    def test_without_it_nothing_changes_for_the_apps_that_have_their_own_button(self):
        self.assertEqual('', self._bar({'app': 'imager'}))

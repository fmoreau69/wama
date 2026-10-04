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

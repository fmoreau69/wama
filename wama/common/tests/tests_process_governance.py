"""The governor at the grain of the PROCESS, and each process on ITS queue (2026-10-14).

Decision of Fabien, the same day: « declare to the governor the steps of a card's pipeline, not
the whole process of an app's card » — a long CPU conversion must not reserve the GPU queue, an
AI post-processing must not go around it. The route had it written (`ROUTE §10.6` 4.5: « waiting
for resources (governor), ETA per process »; nuance of 15/09: `vram_needed` « at the grain of the
process »); only the ETA had been delivered.

What these guards hold:
- only a process that uses the card (`ProcessSpec.gpu`) is declared running to the governor, and
  only while it runs; a CPU process never waits for VRAM;
- the VRAM need is the declared one, otherwise the one of the card's model in the catalogue,
  minus what THIS worker already holds of it (the composer's render follows its score on the same
  model: without that, it would wait forever for what it holds);
- a process delivered on the wrong queue is handed over to its own (`task.retry(queue=…)`) with
  an explicit priority — never as a failure — and the next delivery resumes there: nothing
  replayed, the bar, the measured seconds and the employed models of the launch carried over;
- the flag is coherent with what the catalogue says of the function (`gpu`, `llm`, `tts` tags),
  for every real app.

No GPU, no Redis: the probe is simulated, the registry is the fake Redis.
"""
import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama.common.models import JOB_PENDING, JOB_SUCCESS, ProcessRun
from wama.common.services import process_runs
from wama.common.services import resource_governor as gov
from wama.common.services.process_pipeline import AppPipeline, ProcessSpec
from wama.common.tests.tests_queue_delete_contract import _instance
from wama.common.tests.tests_task_skeleton_contract import _adopters
from wama.common.tests.tests_vram_ledger import _FauxRedis

#: Catalogue tags that say a function uses the card — directly, or through a local service.
GPU_TAGS = {'gpu', 'llm', 'tts'}


class _Resent(Exception):
    """What a fake `task.retry` returns: the skeleton raises it."""


def _task(queue='', retries=0, priority=None):
    """A bound-task double: its delivery (queue, priority) and the re-deliveries it asked for."""
    sent = []
    info = {'routing_key': queue, 'priority': priority} if queue else {}

    class _T:
        class request:
            id = 'task-governance'
            delivery_info = info
        request.retries = retries

        @staticmethod
        def retry(**options):
            sent.append(options)
            return _Resent(options)
    return _T, sent


class _Base(TestCase):

    def setUp(self):
        self.app, self.model = _adopters()[0]
        self.redis = _FauxRedis()
        for patch in (mock.patch.object(gov, '_redis', return_value=self.redis),
                      mock.patch.object(gov, 'total_vram_gb', return_value=24.0),
                      mock.patch('wama.common.utils.task_skeleton.close_old_connections')):
            patch.start()
            self.addCleanup(patch.stop)
        self.calls, self.seen = [], {}
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('convert', share=1),
            ProcessSpec('enhance', depends_on=('convert',), gpu=True, share=3),
        ), label='Demo')

    def _element(self, name):
        user = get_user_model().objects.create_user(name, password='x')
        item = _instance(self.model, user)
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        return item

    def _glue(self, key):
        def glue(element, ctx):
            self.calls.append(key)
            self.seen[key] = [(t['app'], t.get('process')) for t in gov.running_tasks()]
            return {'models': [f'family:{key}']}
        return glue

    def _run(self, item, task, free=24.0, **kwargs):
        from wama.common.utils.task_skeleton import run_item_task
        processes = {spec.key: self._glue(spec.key) for spec in self.pipeline.specs}
        with mock.patch.object(gov, 'effective_free_gb', return_value=free), \
                mock.patch.object(gov, 'release_granted', return_value=None), \
                mock.patch.object(gov, 'holders_summary', return_value=''):
            run_item_task(task, app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline, processes=processes, **kwargs)
        return self.model.objects.get(pk=item.pk)

    def _states(self, item):
        return {row.node_id: row.status for row in process_runs.lines(item)}


class OnlyTheGpuProcessHoldsTheCardTest(_Base):

    def test_the_conversion_is_not_a_gpu_task_and_the_post_processing_is(self):
        task, _sent = _task()
        item = self._run(self._element('gov_holds'), task)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual([], self.seen['convert'], 'a CPU process does not hold the card')
        self.assertEqual([(self.app, 'enhance')], self.seen['enhance'])
        self.assertEqual([], gov.running_tasks(), 'released when the process returns')

    def test_a_cpu_process_never_waits_for_vram(self):
        self.pipeline = AppPipeline(self.app, (ProcessSpec('convert'),), label='Demo')
        task, sent = _task()
        item = self._run(self._element('gov_cpu_no_wait'), task, free=0.5, vram_needed=8.0)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual([], sent)

    def test_the_line_of_the_gpu_process_is_released_when_it_fails(self):
        def broken(element, ctx):
            raise RuntimeError('out of memory')
        task, _sent = _task()
        item = self._element('gov_fails')
        from wama.common.utils.task_skeleton import run_item_task
        with mock.patch.object(gov, 'effective_free_gb', return_value=24.0):
            run_item_task(task, app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline,
                          processes={'convert': self._glue('convert'), 'enhance': broken})
        self.assertEqual('FAILURE', self.model.objects.get(pk=item.pk).status)
        self.assertEqual([], gov.running_tasks())

    def test_who_holds_the_card_names_the_process(self):
        token = gov.task_started('converter', 12, 2.0, process='enhance')
        self.addCleanup(gov.task_finished, token)
        with mock.patch.object(gov, 'resident_models', return_value={}):
            self.assertIn('converter #12 (enhance)', gov.holders_summary())


class TheNeedOfTheProcessTest(_Base):

    def test_without_a_declared_need_the_model_of_the_card_gives_it(self):
        task, _sent = _task()
        with mock.patch('wama.common.utils.auto_model.vram_needed_gb', return_value=8.0) as need:
            with self.assertRaises(_Resent):
                self._run(self._element('gov_derived'), task, free=1.0, model_key='family:m')
        need.assert_called_with('family:m')
        self.assertEqual(['convert'], self.calls, 'the conversion played, the GPU process waits')

    def test_a_model_this_worker_already_holds_is_not_a_need(self):
        gov.reserve_vram(f'wama.x.Engine:{os.getpid()}#family:m', 8.0, allocated=True)
        task, sent = _task()
        with mock.patch('wama.common.utils.auto_model.vram_needed_gb', return_value=8.0):
            item = self._run(self._element('gov_resident_here'), task, free=0.5,
                             model_key='family:m')
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual([], sent, 'no wait for the model it holds')

    def test_the_same_model_held_by_another_process_is_still_a_need(self):
        gov.reserve_vram('wama.x.Engine:999999#family:m', 8.0, allocated=True)
        self.assertEqual(0.0, gov.resident_here_gb('family:m'))
        task, _sent = _task()
        with mock.patch('wama.common.utils.auto_model.vram_needed_gb', return_value=8.0):
            with self.assertRaises(_Resent):
                self._run(self._element('gov_resident_elsewhere'), task, free=0.5,
                          model_key='family:m')


class EachProcessOnItsQueueTest(_Base):

    def test_a_gpu_process_delivered_on_the_default_queue_is_handed_over_to_the_gpu_queue(self):
        task, sent = _task('default')
        item = self._element('gov_hop_up')
        with self.assertRaises(_Resent):
            self._run(item, task)
        self.assertEqual(['convert'], self.calls)
        self.assertEqual('gpu', sent[0]['queue'])
        self.assertEqual(0, sent[0]['countdown'])
        self.assertEqual(gov.celery_priority_for(self.model._meta.app_label), sent[0]['priority'],
                         'the priority of the app, as its route: a message sent WITHOUT priority '
                         'is delivered as priority 0 (measured) — it would enter the GPU queue '
                         'ahead of everything')
        item = self.model.objects.get(pk=item.pk)
        self.assertEqual('RUNNING', item.status, 'a hand-over is not a failure')
        self.assertEqual({'convert': JOB_SUCCESS, 'enhance': JOB_PENDING}, self._states(item))
        self.assertEqual([], gov.running_tasks())

    def test_a_cpu_process_leaves_the_gpu_queue_and_the_delivered_priority_is_never_reused(self):
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('generate', gpu=True), ProcessSpec('output', depends_on=('generate',)),
        ), label='Demo')
        task, sent = _task('gpu', priority=0)
        with self.assertRaises(_Resent):
            self._run(self._element('gov_hop_down'), task)
        self.assertEqual(['generate'], self.calls)
        self.assertEqual(('default', gov.celery_priority_for(self.model._meta.app_label)),
                         (sent[0]['queue'], sent[0]['priority']))

    def test_the_next_delivery_resumes_there_with_the_bar_the_seconds_and_the_models(self):
        timed = any(f.name == 'processing_seconds' for f in self.model._meta.get_fields())
        item = self._element('gov_resume')
        task, _sent = _task('default')
        with self.assertRaises(_Resent):
            self._run(item, task)
        ProcessRun.objects.filter(object_id=str(item.pk), node_id='convert').update(duration_s=5.0)
        self.calls.clear()
        bar = []

        def enhance(element, ctx):
            self.calls.append('enhance')
            ctx.progress(0)
            return {'models': ['family:enhance']}
        task, sent = _task('gpu', retries=1)
        from wama.common.utils.task_skeleton import run_item_task
        with mock.patch.object(gov, 'effective_free_gb', return_value=24.0), \
                mock.patch('wama.common.utils.task_skeleton._signal') as signal:
            run_item_task(task, app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline,
                          processes={'convert': self._glue('convert'), 'enhance': enhance},
                          progress_fn=lambda element, pct, msg: bar.append(round(pct)))
        item = self.model.objects.get(pk=item.pk)
        self.assertEqual([], sent)
        self.assertEqual(['enhance'], self.calls, 'the conversion is not played again')
        self.assertEqual('SUCCESS', item.status)
        produced = [c for c in signal.call_args_list if c.args[2] == 'produit'][0]
        self.assertEqual(['family:convert', 'family:enhance'], produced.args[3])
        self.assertGreaterEqual(produced.args[4]['secondes'], 5.0)
        self.assertEqual([25, 100], bar,
                         'the bar starts where the conversion left it — never back to zero')
        if timed:
            self.assertGreaterEqual(item.processing_seconds, 5.0)

    def test_outside_a_worker_nothing_moves(self):
        task, sent = _task()
        item = self._run(self._element('gov_no_delivery'), task)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual([], sent)

    def test_the_converter_converts_beside_the_gpu_queue_and_post_processes_on_it(self):
        """Fabien's question (2026-10-14): « a long video conversion runs on the GPU, or on the
        CPU while booking a GPU slot? » — now on the CPU, booking nothing."""
        from wama.common.utils.task_skeleton import queue_of
        from wama.converter.function_specs import PIPELINE
        self.assertEqual({'convert': 'default', 'enhance': 'gpu'},
                         {spec.key: queue_of(spec) for spec in PIPELINE.specs})


class TheDrawDecidesWhoHoldsTheCardTest(_Base):
    """2026-10-14 (ROADMAP §8d step 4, Fabien: « if the task is planned remote, no slot must be
    booked »): a process that uses THE card's model (`ProcessSpec.card_model`) does not hold the
    card when that model was drawn REMOTE — no GPU queue, no VRAM wait, nothing declared. The
    other GPU processes of the card keep the card, without inheriting the remote model's need."""

    REMOTE, LOCAL = 'albert:whisper-test', 'transcriber:whisper-test'

    def setUp(self):
        super().setUp()
        from wama.model_manager.models import AIModel
        for key, execution in ((self.REMOTE, 'cloud'), (self.LOCAL, 'local')):
            AIModel.objects.create(model_key=key, name=key, model_type='speech',
                                   source=key.split(':')[0], execution=execution)
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('transcribe', gpu=True, card_model=True),
            ProcessSpec('summarize', depends_on=('transcribe',), gpu=True),
        ), label='Demo')
        patch = mock.patch('wama.common.utils.auto_model.vram_needed_gb', return_value=8.0)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_remote_draw_leaves_the_gpu_queue_before_the_process_plays(self):
        task, sent = _task('gpu')
        with self.assertRaises(_Resent):
            self._run(self._element('draw_hop_down'), task, free=0.5, model_key=self.REMOTE)
        self.assertEqual([], self.calls)
        self.assertEqual('default', sent[0]['queue'])

    def test_on_the_default_queue_it_plays_without_vram_and_undeclared(self):
        task, sent = _task('default')
        with self.assertRaises(_Resent):
            self._run(self._element('draw_plays'), task, free=0.5, model_key=self.REMOTE)
        self.assertEqual(['transcribe'], self.calls, 'played at once, no VRAM wait')
        self.assertEqual([], self.seen['transcribe'], 'not declared to the governor')
        self.assertEqual('gpu', sent[0]['queue'], 'the local summary goes back to the GPU queue')

    def test_the_other_gpu_process_does_not_inherit_the_remote_models_need(self):
        self.pipeline = AppPipeline(self.app, (ProcessSpec('summarize', gpu=True),), label='Demo')
        task, sent = _task('gpu')
        item = self._run(self._element('draw_foreign'), task, free=0.5, model_key=self.REMOTE)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual([], sent, 'no wait for a model it does not use')
        self.assertEqual([(self.app, 'summarize')], self.seen['summarize'], 'still holds the card')

    def test_counter_test_a_local_draw_keeps_the_card_and_waits(self):
        task, sent = _task('gpu')
        with self.assertRaises(_Resent):
            self._run(self._element('draw_local'), task, free=0.5, model_key=self.LOCAL)
        self.assertEqual([], self.calls)
        self.assertNotEqual('default', (sent[0].get('queue') or 'gpu'),
                            'a local model waits for its VRAM, it does not leave the GPU queue')

    def test_the_transcriber_declares_its_transcription_on_the_cards_model_only(self):
        from wama.common.utils.task_skeleton import queue_of
        from wama.transcriber.function_specs import PIPELINE
        self.assertEqual({'transcribe'}, {s.key for s in PIPELINE.specs if s.card_model})
        spec = next(s for s in PIPELINE.specs if s.key == 'transcribe')
        self.assertEqual(('gpu', 'default'), (queue_of(spec), queue_of(spec, gpu=False)))

    def test_the_declaration_survives_the_manifest_round_trip(self):
        """Exported to the `pipeline` manifest, read back by the generator: a generated twin of the
        transcriber keeps `card_model` (written only when true — pure addition)."""
        from wama.common.manifests.codegen.pipeline_decl import process_specs
        from wama.transcriber.function_specs import PIPELINE
        specs = {s['key']: s for s in process_specs(PIPELINE.manifest())}
        self.assertTrue(specs['transcribe']['card_model'])
        self.assertFalse(specs['summarize']['card_model'])
        declared = {n['id']: n['process'] for n in PIPELINE.graph()['nodes']}
        self.assertNotIn('card_model', declared['summarize'])

    def test_the_generator_writes_it_back(self):
        """On the generator's own case (the Writer draft), its first process declared on the
        card's model: the generated `function_specs.py` carries `card_model=True` there only."""
        import copy
        import json
        from wama.common.manifests.codegen import function_specs_gen
        from wama.common.manifests.codegen.pipeline_decl import declared_pipeline
        from wama.common.tests.tests_codegen_from_scratch import DRAFT, _calls
        pipeline, functions = declared_pipeline('writer')
        pipeline = copy.deepcopy(pipeline)
        pipeline['body']['nodes'][0]['process']['card_model'] = True
        with mock.patch.object(function_specs_gen, 'declared_pipeline',
                               return_value=(pipeline, functions)):
            src, reason = function_specs_gen.render_function_specs(
                json.loads(DRAFT.read_text(encoding='utf-8')))
        self.assertIsNotNone(src, reason)
        flagged = [c.args[0].value for c in _calls(src, 'ProcessSpec')
                   if any(k.arg == 'card_model' for k in c.keywords)]
        self.assertEqual([pipeline['body']['nodes'][0]['id']], flagged)


class TheFlagSaysWhatTheCatalogueSaysTest(SimpleTestCase):
    """`ProcessSpec.gpu` is a GUARD since 2026-10-14: a process wrongly declared CPU would run
    beside the GPU work and hold the card undeclared. What the function does is said by the
    catalogue's tags — a model on the card (`gpu`), a language model of the Ollama host (`llm`),
    the TTS service (`tts`). Measured the day it was written: the two voices disagreed
    (synthesizer `True`, avatarizer `False`) and every `llm` process was `False`."""

    def test_every_process_of_every_real_app_declares_what_its_function_does(self):
        from wama.common.app_registry import APP_CATALOG
        from wama.common.catalog.function_catalog import FUNCTION_CATALOG, load_all
        from wama.common.sandbox import non_sandbox_apps
        from wama.common.services import process_pipeline as pp
        load_all()
        pp._load_declarations()
        real = set(non_sandbox_apps(APP_CATALOG))
        checked = 0
        for app, pipeline in pp.APP_PIPELINES.items():
            if app not in real:
                continue
            for spec in pipeline.specs:
                function = FUNCTION_CATALOG.get(pipeline.function_key(spec))
                with self.subTest(app=app, process=spec.key):
                    self.assertIsNotNone(function)
                    uses_the_card = bool(GPU_TAGS & set(function.tags or ()))
                    self.assertEqual(uses_the_card, spec.gpu)
                checked += 1
        self.assertGreater(checked, 25, 'the ten apps were read')


class TheLaunchRemembersAcrossDeliveriesTest(_Base):
    """2026-10-21, transcriber #2522 — a re-delivered task runs its next process in ANOTHER
    worker: what the launch decided must not be redone there — an « auto » model was drawn at
    every delivery. The skeleton keeps the launch's model and memory under its task id
    (`task.retry` keeps it) and forgets them at its REAL end only. (The audio leveled twice is
    held otherwise since the same day: the leveled audio is the declared output of a process.)"""

    def _deliveries(self, item, first_glue, second_glue, model_key=None):
        from wama.common.utils.task_skeleton import run_item_task
        task, _sent = _task('default')
        with mock.patch.object(gov, 'effective_free_gb', return_value=24.0):
            with self.assertRaises(_Resent):
                run_item_task(task, app_id=self.app, model=self.model, item_id=item.pk,
                              pipeline=self.pipeline, model_key=model_key,
                              processes={'convert': first_glue, 'enhance': second_glue})
            task, _sent = _task('gpu', retries=1)
            run_item_task(task, app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline, model_key=model_key,
                          processes={'convert': first_glue, 'enhance': second_glue})
        return self.model.objects.get(pk=item.pk)

    def test_the_drawn_model_is_not_drawn_again_by_the_next_delivery(self):
        draws, seen = iter(['family:a', 'family:b']), []

        def draw(element):
            return next(draws)

        def glue(element, ctx):
            seen.append(ctx.model_key)
            return {}
        item = self._deliveries(self._element('launch_model'), glue, glue, model_key=draw)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual(['family:a', 'family:a'], seen,
                         'a second draw could decide otherwise about the next processes')

    def test_what_a_process_decided_is_found_by_the_next_one_and_forgotten_at_the_end(self):
        found = []

        def decide(element, ctx):
            ctx.remember('language', 'fr')
            return {}

        def reuse(element, ctx):
            found.append(ctx.recall('language'))
            return {}
        item = self._deliveries(self._element('launch_fact'), decide, reuse)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual(['fr'], found, 'the re-delivery lost what the launch decided')
        from wama.common.utils.task_skeleton import _launch_key
        from django.core.cache import cache
        self.assertIsNone(cache.get(_launch_key(self.app, item.pk)), 'the launch ended: forgotten')

    def test_a_failed_launch_is_forgotten_too(self):
        from django.core.cache import cache
        from wama.common.utils.task_skeleton import _launch_key, run_item_task

        def decide(element, ctx):
            ctx.remember('language', 'fr')
            raise RuntimeError('boom')
        item = self._element('launch_fails')
        task, _sent = _task()
        with mock.patch.object(gov, 'effective_free_gb', return_value=24.0):
            run_item_task(task, app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline,
                          processes={'convert': decide, 'enhance': self._glue('enhance')})
        self.assertEqual('FAILURE', self.model.objects.get(pk=item.pk).status)
        self.assertIsNone(cache.get(_launch_key(self.app, item.pk)))

    def test_a_new_launch_recalls_nothing_and_clears_an_interrupted_one(self):
        from django.core.cache import cache
        from wama.common.utils.task_skeleton import _launch_key, run_item_task
        recalled = []
        item = self._element('launch_stale')
        cache.set(_launch_key(self.app, item.pk),
                  {'task': 'killed-worker', 'facts': {'language': 'de'}})

        def glue(element, ctx):
            recalled.append(ctx.recall('language'))
            return {}
        task, _sent = _task()
        with mock.patch.object(gov, 'effective_free_gb', return_value=24.0):
            run_item_task(task, app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline, processes={'convert': glue, 'enhance': glue})
        self.assertEqual([None, None], recalled, 'another launch reuses nothing')
        self.assertIsNone(cache.get(_launch_key(self.app, item.pk)),
                          'the interrupted launch left its memory behind')

    def test_outside_a_worker_nothing_is_remembered(self):
        from wama.common.utils.task_skeleton import TaskContext
        item = self._element('launch_direct')
        ctx = TaskContext(self.app, self.model, item)
        ctx.remember('x', 1)
        self.assertIsNone(ctx.recall('x'))

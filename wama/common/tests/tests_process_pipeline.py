"""A card that carries SEVERAL processes — `WAMA_APP_GENERATION_ROUTE §10.6`, step P3 stage B.

What is held here, and why each point:

  * an app writes its processes down the way the cam_analyzer writes its passes (a registry in
    code that becomes a `pipeline` manifest with `function` nodes) — the form is the one the
    studio already opens, so nothing new has to learn to read it ;
  * a launch replays ONLY what is no longer valid, plus everything downstream of it — that is
    the whole point of several processes: a setting of the last one must not replay the first ;
  * « no longer valid » has the three causes of point 4.3: a watched setting changed, the output
    of an upstream process was replaced, an upstream process is itself stale ;
  * a card whose processes are all valid, relaunched, replays everything — the user asks for
    another result — even though the launcher already removed the previous output ;
  * the task skeleton runs the retained processes one after the other in ONE task and keeps one
    execution line per process ; a failure closes the line of the process that failed and leaves
    the ones before it valid.
"""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.models import (JOB_FAILURE, JOB_PENDING, JOB_RUNNING, JOB_STALE, JOB_SUCCESS,
                                ProcessRun)
from wama.common.services import process_runs
from wama.common.services.process_pipeline import (APP_PIPELINES, UPSTREAM_KEY, AppPipeline,
                                                   ProcessSpec, register_app_pipeline)
from wama.common.tests.tests_queue_delete_contract import _instance
from wama.common.tests.tests_task_skeleton_contract import _adopters, _task


class _Element:
    """Stand-in element: the lines address it by (app, type, pk) and read its settings."""

    class _meta:
        app_label = 'demo_pipeline'
        object_name = 'Element'

    _next = 0

    def __init__(self, **settings):
        type(self)._next += 1
        self.pk = type(self)._next
        self.prompt, self.duration, self.given_score = 'a calm piano', 30, ''
        self.__dict__.update(settings)


def _two_steps(**plan_options):
    return AppPipeline('demo_pipeline', (
        ProcessSpec('plan', watched=('prompt',), **plan_options),
        ProcessSpec('render', depends_on=('plan',), watched=('prompt', 'duration'), share=3),
    ), label='Demo')


def _keys(steps):
    return [spec.key for spec in steps]


class WritingAPipelineDownTest(SimpleTestCase):

    def test_an_upstream_that_is_not_in_the_pipeline_is_refused(self):
        with self.assertRaisesMessage(ValueError, 'master'):
            AppPipeline('demo', (ProcessSpec('render', depends_on=('master',)),), label='x')

    def test_a_key_written_twice_is_refused(self):
        with self.assertRaises(ValueError):
            AppPipeline('demo', (ProcessSpec('render'), ProcessSpec('render')), label='x')

    def test_a_cycle_is_refused_when_the_pipeline_is_written_not_when_it_runs(self):
        with self.assertRaisesMessage(ValueError, 'cycle'):
            AppPipeline('demo', (ProcessSpec('a', depends_on=('b',)),
                                 ProcessSpec('b', depends_on=('a',))), label='x')

    def test_an_unknown_degree_is_refused(self):
        with self.assertRaises(ValueError):
            AppPipeline('demo', (ProcessSpec('render', degree='sometimes'),), label='x')

    def test_the_order_is_the_order_of_the_graph_whatever_the_writing_order(self):
        pipeline = AppPipeline('demo', (ProcessSpec('render', depends_on=('plan',)),
                                        ProcessSpec('plan')), label='x')
        self.assertEqual(['plan', 'render'], _keys(pipeline.ordered()))
        self.assertEqual(['render'], _keys(pipeline.ordered({'render'})))

    def test_the_graph_is_the_canvas_form_and_makes_a_valid_manifest_body(self):
        """Same form as the cam_analyzer registry: a process = a `function` node, a dependency =
        a link. That is what lets the studio open the pipeline of an app."""
        from wama.common.manifests.builtin.pipeline import (body_to_graph, graph_to_body,
                                                            validate_pipeline_body)
        pipeline = _two_steps()
        graph = pipeline.graph()
        self.assertEqual(['function:demo_pipeline.plan', 'function:demo_pipeline.render'],
                         [node['app'] for node in graph['nodes']])
        self.assertEqual([{'from': 'plan', 'to': 'render', 'to_port': None}], graph['links'])
        # The DECLARATION travels under `process`; `params` (the user's values) stays empty (D1).
        self.assertEqual(['prompt', 'duration'], graph['nodes'][1]['process']['watched'])
        self.assertEqual({}, graph['nodes'][1]['params'])
        body = graph_to_body(graph)
        self.assertEqual(graph['nodes'][1]['process'], body['nodes'][1]['process'])
        self.assertEqual([], validate_pipeline_body(body))
        self.assertEqual(['demo_pipeline.plan', 'demo_pipeline.render'],
                         [node['function'] for node in body['nodes']])
        self.assertEqual(['plan', 'render'], [n['id'] for n in body_to_graph(body)['nodes']])

    def test_a_function_key_can_be_named_when_it_is_not_the_default_one(self):
        pipeline = AppPipeline('demo', (ProcessSpec('render', function='demo.rendering'),),
                               label='x')
        self.assertEqual('demo.rendering', pipeline.function_key(pipeline.spec('render')))

    def test_registering_makes_the_pipeline_a_manifest_source_under_the_app_key(self):
        from wama.common.manifests.builtin.pipeline import PIPELINE_SOURCES
        self.addCleanup(APP_PIPELINES.pop, 'demo_registered', None)
        self.addCleanup(PIPELINE_SOURCES.pop, 'demo_registered', None)
        pipeline = register_app_pipeline('demo_registered', (ProcessSpec('render'),), label='Demo')
        self.assertIs(APP_PIPELINES['demo_registered'], pipeline)
        with mock.patch('wama.common.app_registry.app_world', return_value='media'):
            manifest = PIPELINE_SOURCES['demo_registered']()
        self.assertEqual(('pipeline', 'demo_registered', 'media'),
                         (manifest['manifest_kind'], manifest['key'], manifest['world']))
        self.assertIn('1 process', manifest['name'])


class WhatALaunchReplaysTest(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _output(self, name, text='X:1'):
        (Path(self.tmp) / name).write_text(text, encoding='utf-8')
        return name

    def _played(self, pipeline, item, key, output=''):
        """Plays one process the way the skeleton does: snapshot at the start, output at the end."""
        spec = pipeline.spec(key)
        process_runs.start(item, key, settings_snapshot=pipeline.snapshot(spec, item))
        process_runs.succeed(item, key, output_ref=output)

    def _both_played(self, pipeline, item):
        self._played(pipeline, item, 'plan', self._output(f'score{item.pk}.abc'))
        self._played(pipeline, item, 'render', self._output(f'audio{item.pk}.wav', 'RIFF'))

    def test_a_card_that_never_ran_plays_every_process_in_order(self):
        pipeline, item = _two_steps(), _Element()
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))
        self.assertEqual(JOB_PENDING, pipeline.card_state(item))

    def test_a_process_that_does_not_apply_to_this_element_is_not_played(self):
        pipeline = _two_steps(applies=lambda item, model_key: model_key == 'writes-scores')
        item = _Element()
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item, 'plays-only')))
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item, 'writes-scores')))

    def test_a_failed_last_process_is_replayed_alone(self):
        pipeline, item = _two_steps(), _Element()
        self._played(pipeline, item, 'plan', self._output('score.abc'))
        process_runs.start(item, 'render')
        process_runs.fail(item, 'render', 'out of memory')
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item)))
        self.assertTrue(pipeline.resumes_from(item, 'plan'))
        self.assertEqual(JOB_FAILURE, pipeline.card_state(item))

    def test_a_setting_of_the_last_process_does_not_replay_the_first(self):
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        self.assertEqual(JOB_SUCCESS, pipeline.card_state(item))
        item.duration = 60
        self.assertEqual({'render'}, pipeline.refresh(item))
        self.assertEqual(JOB_STALE, pipeline.card_state(item))
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item)))
        self.assertEqual(JOB_SUCCESS, process_runs.line(item, 'plan').status)

    def test_a_setting_of_the_first_process_replays_everything_downstream(self):
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        item.prompt = 'a fast drum solo'
        self.assertEqual({'plan', 'render'}, pipeline.refresh(item))
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))
        self.assertFalse(pipeline.resumes_from(item, 'plan'))

    def test_an_upstream_output_that_was_replaced_makes_the_downstream_stale(self):
        """The third cause of point 4.3: nobody changed a setting, somebody rewrote the score."""
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        self.assertIn(UPSTREAM_KEY, process_runs.line(item, 'render').settings_snapshot)
        self.assertEqual(set(), pipeline.refresh(item), 'nothing changed, nothing is stale')
        self._output(f'score{item.pk}.abc', 'X:1 corrected by hand')
        self.assertEqual({'render'}, pipeline.refresh(item))
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item)))

    def test_a_valid_card_relaunched_replays_everything(self):
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))
        self.assertFalse(pipeline.resumes_from(item, 'plan'))

    def test_it_still_replays_everything_once_the_launcher_removed_the_last_output(self):
        """The launcher resets the card BEFORE the task asks what to play (`begin_processing`):
        reading the missing file first would turn a full relaunch into a resume of the last
        process."""
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        (Path(self.tmp) / f'audio{item.pk}.wav').unlink()
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))

    def test_a_result_whose_file_is_gone_is_not_resumed_from(self):
        pipeline, item = _two_steps(), _Element()
        self._played(pipeline, item, 'plan', self._output('score.abc'))
        process_runs.start(item, 'render')
        process_runs.fail(item, 'render', 'boom')
        (Path(self.tmp) / 'score.abc').unlink()
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))

    def test_one_process_alone_takes_its_stale_upstreams_and_never_its_downstream(self):
        """▶ par process (P5) : the asked process always runs ; an upstream still valid is
        resumed from, a stale one is replayed first ; the downstream is left alone — it will
        turn stale by itself once its upstream output changed."""
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item, only='render')))
        self.assertEqual(['plan'], _keys(pipeline.steps_to_run(item, only='plan')),
                         'the downstream render must not be dragged along')
        item.prompt = 'a fast drum solo'           # plan stale → render asked alone replays it first
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item, only='render')))

    def test_a_process_asked_alone_must_exist_and_apply(self):
        pipeline, item = _two_steps(applies=lambda item, model_key: False), _Element()
        with self.assertRaisesMessage(ValueError, 'plan'):
            pipeline.steps_to_run(item, only='plan')
        with self.assertRaisesMessage(ValueError, 'master'):
            pipeline.steps_to_run(item, only='master')

    def test_resetting_the_outputs_of_one_process_leaves_the_others(self):
        """Relaunching the score alone must not take the audio away."""
        class _File:
            def __init__(self, name):
                self.name = name
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('plan', outputs=('score_file',)),
            ProcessSpec('render', depends_on=('plan',), outputs=('audio_file',)),
        ), label='Demo')
        item = _Element(score_file=_File('s.abc'), audio_file=_File('a.wav'))
        with mock.patch('wama.common.utils.queue_duplication.safe_delete_file',
                        return_value=True) as deleted:
            self.assertEqual(['score_file'], pipeline.reset_outputs(item, ['plan']))
        deleted.assert_called_once_with(item, 'score_file')
        self.assertIsNone(item.score_file)
        self.assertEqual('a.wav', item.audio_file.name)

    def test_an_upstream_that_never_ran_makes_nobody_stale(self):
        """A process that did not apply (no line) is not a missing upstream."""
        pipeline, item = _two_steps(applies=lambda item, model_key: False), _Element()
        self._played(pipeline, item, 'render', self._output('audio.wav', 'RIFF'))
        self.assertEqual(set(), pipeline.refresh(item))
        self.assertEqual(JOB_SUCCESS, pipeline.card_state(item))

    def test_the_line_of_a_single_process_card_is_not_one_of_the_pipeline(self):
        pipeline, item = _two_steps(), _Element()
        process_runs.start(item)
        process_runs.succeed(item)
        self.assertEqual({}, pipeline.rows(item))
        self.assertEqual(JOB_PENDING, pipeline.card_state(item))

    def test_a_file_setting_is_compared_by_its_path(self):
        """The snapshot is read back from JSON: a file field must be written as its path, or a
        card would be stale the moment it is read."""
        class _File:
            """Like a `FieldFile`: its text form is its path."""

            def __init__(self, name):
                self.name = name

            def __str__(self):
                return self.name
        pipeline = AppPipeline('demo_pipeline', (ProcessSpec('render', watched=('given_score',)),),
                               label='x')
        item = _Element(given_score=_File('users/1/in.abc'))
        self._played(pipeline, item, 'render')
        self.assertEqual({'given_score': 'users/1/in.abc'},
                         process_runs.line(item, 'render').settings_snapshot)
        self.assertEqual(set(), pipeline.refresh(item))
        item.given_score = _File('users/1/other.abc')
        self.assertEqual({'render'}, pipeline.refresh(item))


class AnUpstreamThatNoLongerTakesPlaceTest(WhatALaunchReplaysTest):
    """2026-10-21 — measured before the fix: an upstream that stops taking place for the element
    (the leveling unticked, the cover audio removed) kept its line, made stale by the setting that
    removed it — and its downstream, replayed without it, was stale again at every read (`refresh`
    → {'render'} after the relaunch, the card « stale » for ever). A line counts as long as the
    ELEMENT asks for its process (`still_counts`) ; the downstream that read it is stale ONCE."""

    def _prepared(self):
        return AppPipeline('demo_pipeline', (
            ProcessSpec('prep', watched=('level',), applies=lambda item, mk: bool(item.level)),
            ProcessSpec('render', depends_on=('prep',), watched=('prompt',)),
        ), label='Demo', model_of=lambda item: 'any')

    def test_the_downstream_is_stale_once_and_valid_again_once_replayed_without_it(self):
        pipeline, item = self._prepared(), _Element(level=True)
        self._played(pipeline, item, 'prep', self._output(f'prep{item.pk}.wav', 'RIFF1'))
        self._played(pipeline, item, 'render', self._output(f'out{item.pk}.txt', 'A'))
        item.level = False
        self.assertEqual({'render'}, pipeline.refresh(item), 'it was rendered from the prep')
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item, 'any')))
        self._played(pipeline, item, 'render', self._output(f'out{item.pk}.txt', 'B'))
        self.assertEqual(set(), pipeline.refresh(item))
        self.assertEqual(JOB_SUCCESS, pipeline.card_state(item))
        self.assertEqual(['render'], [row['key'] for row in pipeline.card_rows(item, 'any')],
                         'the strip no longer shows a process the element no longer plays')

    def test_under_a_model_not_drawn_yet_only_the_switch_judges(self):
        """« auto » before the draw : `requested_model` is None — the line is not guessed away."""
        pipeline, item = self._prepared(), _Element(level=True)
        self._played(pipeline, item, 'prep', self._output(f'prep{item.pk}.wav', 'RIFF1'))
        self.assertTrue(pipeline.still_counts(pipeline.spec('prep'), _Element(level=False), None))

    def test_what_is_installed_does_not_judge_a_result(self):
        """Uninstalling a model does not change the card: its results stand."""
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('prep', available=lambda: False),
            ProcessSpec('render', depends_on=('prep',)),
        ), label='Demo')
        self.assertTrue(pipeline.still_counts(pipeline.spec('prep'), _Element(), 'any'))
        self.assertFalse(pipeline.takes_place(pipeline.spec('prep'), _Element(), 'any'))


class WhatADownstreamReadsTest(SimpleTestCase):
    """`AppPipeline.output_of` / `upstream_output` (2026-10-21) : a downstream reads the output of
    its upstream by ONE gesture — the file, while its process takes place — and the data follows
    the declared links: the nearest upstream that rendered the asked type, the one before it when
    it rendered nothing (its process failed), the card's input when none did."""

    class _File:
        def __init__(self, name):
            self.name = name

    def _chain(self):
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('level', applies=lambda item, mk: item.level, outputs=('leveled',)),
            ProcessSpec('denoise', depends_on=('level',), degree='optional', toggle='denoise_on',
                        outputs=('denoised',)),
            ProcessSpec('transcribe', depends_on=('level', 'denoise')),
            ProcessSpec('speakers', depends_on=('transcribe',)),
        ), label='Demo')
        types = {'level': 'audio', 'denoise': 'audio', 'transcribe': 'document'}
        patcher = mock.patch.object(AppPipeline, 'output_type',
                                    lambda self, spec: types.get(spec.key, ''))
        patcher.start()
        self.addCleanup(patcher.stop)
        return pipeline

    def test_the_nearest_upstream_that_rendered_the_type_is_read(self):
        pipeline = self._chain()
        item = _Element(level=True, denoise_on=True, leveled=self._File('l.wav'),
                        denoised=self._File('d.wav'))
        self.assertEqual('d.wav', pipeline.upstream_output(item, 'transcribe', 'audio'))
        self.assertEqual('d.wav', pipeline.upstream_output(item, 'speakers', 'audio'),
                         'through the transcription, which renders no audio')
        item.denoised = None                      # the denoising failed: its field stayed empty
        self.assertEqual('l.wav', pipeline.upstream_output(item, 'transcribe', 'audio'))

    def test_an_upstream_that_does_not_take_place_is_never_read_even_with_its_old_file(self):
        pipeline = self._chain()
        item = _Element(level=False, denoise_on=False, leveled=self._File('old.wav'),
                        denoised=None)
        self.assertEqual('', pipeline.output_of(item, 'level'))
        self.assertEqual('', pipeline.upstream_output(item, 'transcribe', 'audio'),
                         'the card input, then')


class AProcessSplitFromItsDownstreamTest(WhatALaunchReplaysTest):
    """`ProcessSpec.split_from` (2026-10-21, the leveling taken out of the transcription) : a
    downstream line rendered BEFORE the split did the work itself — its photo still holds the
    settings of the split process. It stands for it while they did not change: an old card is
    not transcribed again for a changed kind of summary."""

    def _split(self):
        return AppPipeline('demo_pipeline', (
            ProcessSpec('prep', watched=('level',), split_from='render'),
            ProcessSpec('render', depends_on=('prep',), watched=('prompt',)),
            ProcessSpec('summary', depends_on=('render',), watched=('kind',)),
        ), label='Demo')

    def _old_card(self, pipeline):
        item = _Element(level=True, kind='short')
        before = AppPipeline('demo_pipeline', (
            ProcessSpec('render', watched=('prompt', 'level')),
            ProcessSpec('summary', depends_on=('render',), watched=('kind',)),
        ), label='Demo')
        self._played(before, item, 'render', self._output(f'out{item.pk}.txt', 'A'))
        self._played(before, item, 'summary', self._output(f'sum{item.pk}.txt', 'S'))
        return item

    def test_the_old_line_stands_for_the_split_process(self):
        pipeline = self._split()
        item = self._old_card(pipeline)
        self.assertEqual(set(), pipeline.refresh(item))
        item.kind = 'long'
        self.assertEqual(['summary'], _keys(pipeline.steps_to_run(item, 'any')),
                         'the old render did the prep itself: neither is replayed')
        rows = {row['key']: row for row in pipeline.card_rows(item, 'any')}
        self.assertEqual(JOB_SUCCESS, rows['prep']['status'])
        self.assertIn('« render »', rows['prep']['output_label'], 'the strip says where it was done')

    def test_a_changed_setting_of_the_split_process_stales_the_old_line(self):
        pipeline = self._split()
        item = self._old_card(pipeline)
        item.level = False
        self.assertEqual({'render', 'summary'}, pipeline.refresh(item))
        self.assertEqual(['prep', 'render', 'summary'], _keys(pipeline.steps_to_run(item, 'any')))

    def test_a_line_rendered_after_the_split_holds_nothing(self):
        pipeline, item = self._split(), _Element(level=True, kind='short')
        self._played(pipeline, item, 'render', self._output(f'out{item.pk}.txt', 'A'))
        self.assertEqual(['prep', 'render', 'summary'], _keys(pipeline.steps_to_run(item, 'any')))

    def test_the_split_process_must_be_an_upstream_of_its_origin(self):
        with self.assertRaisesMessage(ValueError, 'split_from'):
            AppPipeline('demo', (ProcessSpec('prep', split_from='render'),
                                 ProcessSpec('render')), label='x')


class AResultOlderThanThePipelineTest(TestCase):
    """2026-10-13 — Fabien's transcript #739 (28/09) predates the transcriber pipeline (03/10): no
    line, so nothing was « up to date » and the ▶ of « Locuteurs » re-listened to the whole audio.
    A SUCCESSFUL element proves its `required` processes rendered: the first read of the element
    (a queue page, `preload`) or its launch (`begin_processing`) BACKFILLS them a line ; an
    `optional` one, unknown, stays to be played. Common to every app with a pipeline."""

    def _pipeline(self):
        return AppPipeline('demo_pipeline', (
            ProcessSpec('transcribe', watched=('prompt',)),
            ProcessSpec('diarize', depends_on=('transcribe',), degree='optional',
                        toggle='wants_speakers'),
        ), label='Demo')

    def test_the_required_process_is_backfilled_and_the_option_alone_is_played(self):
        from wama.common.services import process_pipeline
        pipeline = self._pipeline()
        item = _Element(status=JOB_SUCCESS, wants_speakers=True)
        self.assertEqual(['transcribe', 'diarize'], _keys(pipeline.steps_to_run(item)),
                         'without the backfill, everything is replayed — the defect')
        with mock.patch.dict(APP_PIPELINES, {'demo_pipeline': pipeline}):
            process_pipeline.preload([item])
        process_pipeline.release(item)
        self.assertEqual(JOB_SUCCESS, process_runs.line(item, 'transcribe').status)
        self.assertIsNone(process_runs.line(item, 'diarize'), 'an optional was invented')
        self.assertEqual(['diarize'], _keys(pipeline.steps_to_run(item, only='diarize')))
        self.assertEqual(['diarize'], _keys(pipeline.steps_to_run(item)))

    def test_nothing_is_backfilled_for_an_element_not_successful_or_already_tracked(self):
        pipeline = self._pipeline()
        self.assertEqual({}, pipeline.backfill_prior_runs(_Element(status=JOB_PENDING)))
        self.assertEqual({}, pipeline.backfill_prior_runs(_Element(status=JOB_RUNNING)))
        tracked = _Element(status=JOB_SUCCESS)
        process_runs.fail(tracked, 'transcribe', 'out of memory')
        self.assertEqual({}, pipeline.backfill_prior_runs(tracked))
        self.assertEqual(JOB_FAILURE, process_runs.line(tracked, 'transcribe').status)

    def test_a_setting_changed_after_the_backfill_makes_it_stale(self):
        pipeline = self._pipeline()
        item = _Element(status=JOB_SUCCESS)
        pipeline.backfill_prior_runs(item)
        item.prompt = 'another language'
        self.assertEqual(['transcribe'], _keys(pipeline.steps_to_run(item)))

    def test_a_launch_backfills_a_card_no_page_has_read(self):
        """2026-10-14 — the backfill only ran on a page read: a ▶ from the assistant or a
        scheduled action, on a card never displayed since, replayed everything. The launch
        (`begin_processing`, every app) backfills before RUNNING, while the element is still
        successful."""
        from wama.common.utils.process_control import begin_processing
        item = _Element(status=JOB_SUCCESS, task_id='', save=lambda: None)

        class _Model:
            class objects:
                @staticmethod
                def select_for_update():
                    return mock.Mock(get=lambda pk: item)

        with mock.patch.dict(APP_PIPELINES, {'demo_pipeline': self._pipeline()}):
            obj, err = begin_processing(_Model, item.pk)
        self.assertIsNone(err)
        self.assertEqual('RUNNING', obj.status)
        self.assertEqual(JOB_SUCCESS, process_runs.line(item, 'transcribe').status)
        self.assertEqual({'backfilled': True}, process_runs.line(item, 'transcribe').output_summary)


class WhatTheCardShowsTest(TestCase):
    """P5 — the card shows its processes and ONE state, read through the adapter
    (`shown_state`), never `item.status` alone: a stale render under a « successful » element
    is what the lines know and the element does not."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('plan', label='Partition', watched=('prompt',),
                        applies=lambda item, model_key: model_key == 'writes-scores'),
            ProcessSpec('render', label='Rendu', depends_on=('plan',), watched=('duration',)),
        ), label='Demo')

    def _played(self, item, key, output=''):
        spec = self.pipeline.spec(key)
        process_runs.start(item, key, settings_snapshot=self.pipeline.snapshot(spec, item),
                           model_key='family:m')
        process_runs.succeed(item, key, output_ref=output, output_summary={'label': key + '.out'})

    def test_an_element_in_flight_is_shown_as_the_element_says(self):
        item = _Element(status=JOB_RUNNING)
        self.assertEqual(JOB_RUNNING, self.pipeline.shown_state(item))
        item.status = 'AWAITING_RESOURCES'
        self.assertEqual('AWAITING_RESOURCES', self.pipeline.shown_state(item))

    def test_without_any_line_the_element_alone_is_shown(self):
        item = _Element(status=JOB_PENDING)
        self.assertEqual(JOB_PENDING, self.pipeline.shown_state(item))
        self.assertEqual([], self.pipeline.card_rows(item))

    def test_each_row_says_what_its_process_watches_for_its_own_gear(self):
        """⚙ par process (P5) : the gear of a row shows the settings the process WATCHES — read
        from the declaration, never a list written in a template."""
        item = _Element(status=JOB_SUCCESS)
        self._played(item, 'plan')
        self._played(item, 'render')
        rows = {r['key']: r['watched'] for r in self.pipeline.card_rows(item)}
        self.assertEqual({'plan': ['prompt'], 'render': ['duration']}, rows)

    # ── the switch of an optional process (3.2) and non-file outputs ───────────────────────────
    def _with_an_option(self):
        return AppPipeline('demo_pipeline', (
            ProcessSpec('render', label='Rendu', watched=('duration',)),
            ProcessSpec('summary', label='Résumé', depends_on=('render',), degree='optional',
                        toggle='wants_summary'),
        ), label='Demo')

    def test_a_switch_belongs_to_an_optional_process_only(self):
        with self.assertRaises(ValueError) as refused:
            AppPipeline('demo_pipeline', (ProcessSpec('render', toggle='wants_it'),), label='Demo')
        self.assertIn('optional', str(refused.exception))

    def test_an_option_switched_off_does_not_take_place_and_no_longer_weighs_on_the_card(self):
        """Rule 4.4: « les optional désactivés sont ignorés ». A failed summary keeps the card
        « to be completed » ; switching the summary OFF makes the card successful again, and the
        row stays in the strip — unchecked — so that it can be switched back on."""
        pipeline = self._with_an_option()
        item = _Element(status=JOB_SUCCESS, wants_summary=True)
        process_runs.start(item, 'render', settings_snapshot=pipeline.snapshot(pipeline.spec('render'), item))
        process_runs.succeed(item, 'render')
        process_runs.start(item, 'summary')
        process_runs.fail(item, 'summary', 'model down')
        self.assertEqual(['render', 'summary'], _keys(pipeline.applicable(item)))
        self.assertEqual(JOB_PENDING, pipeline.card_state(item))
        item.wants_summary = False
        self.assertEqual(['render'], _keys(pipeline.applicable(item)))
        self.assertEqual(JOB_SUCCESS, pipeline.card_state(item))
        self.assertEqual(JOB_SUCCESS, pipeline.shown_state(item))
        rows = {r['key']: (r['toggle'], r['enabled']) for r in pipeline.card_rows(item)}
        self.assertEqual({'render': ('', True), 'summary': ('wants_summary', False)}, rows)

    def test_the_strip_gives_an_option_its_checkbox_and_dims_it_when_off(self):
        from django.template.loader import render_to_string
        pipeline = self._with_an_option()
        item = _Element(status=JOB_SUCCESS, wants_summary=False)
        for key in ('render', 'summary'):
            process_runs.start(item, key)
            process_runs.succeed(item, key)
        html = render_to_string('common/_card_processes.html', {
            'processes': pipeline.card_rows(item), 'card_id': 7, 'settings_url': '/demo/settings/7/'})
        self.assertRegex(html, r'wcv3-proc--off"[^>]*data-process="summary"')
        self.assertRegex(html, r'wcv3-proc-toggle"[^>]*data-toggle-field="wants_summary"'
                               r'[^>]*data-settings-url="/demo/settings/7/"')
        self.assertNotRegex(html, r'wcv3-proc-toggle"[^>]*\bchecked\b')
        self.assertNotRegex(html, r'wcv3-proc-run"[^>]*data-process="summary"',
                            'a process switched off has no ▶')
        self.assertRegex(html, r'wcv3-proc-run"[^>]*data-process="render"')

    # ── branches: the strip lays the graph out as the studio does (one column per depth) ───────
    def _branching(self):
        """The composer's shape: two roots, one of them a side output, and two processes that
        read the render. `full` is declared AFTER `render`: the strip still puts it beside the
        other root."""
        return AppPipeline('demo_pipeline', (
            ProcessSpec('score', label='Partition'),
            ProcessSpec('render', label='Rendu', depends_on=('score',)),
            ProcessSpec('full', label='Partition complète'),
            ProcessSpec('output', label='Sortie', depends_on=('render',)),
            ProcessSpec('render_score', label='Partition du rendu', depends_on=('render',)),
        ), label='Demo')

    def test_processes_of_the_same_depth_share_a_column_and_a_side_output_says_so(self):
        pipeline = self._branching()
        item = _Element(status=JOB_SUCCESS)
        for key in ('score', 'render', 'full', 'output', 'render_score'):
            process_runs.start(item, key)
            process_runs.succeed(item, key)
        rows = pipeline.card_rows(item)
        self.assertEqual([('score', 0), ('full', 0), ('render', 1), ('output', 2),
                          ('render_score', 2)], [(r['key'], r['column']) for r in rows])
        by_key = {r['key']: r for r in rows}
        self.assertEqual(['Rendu'], by_key['render_score']['after'])
        self.assertEqual([], by_key['full']['after'])
        self.assertEqual({'full'}, {r['key'] for r in rows if r['branch_end']},
                         'only a process that feeds nothing while a column follows is a side '
                         'output — the last column ends every chain')

        from django.template.loader import render_to_string
        html = render_to_string('common/_card_processes.html', {'processes': rows, 'card_id': 7})
        self.assertEqual(3, html.count('class="wcv3-proc-col'))
        self.assertEqual(2, html.count('wcv3-proc-col--branches'))
        self.assertEqual(2, html.count('wcv3-proc-sep'), 'arrows go between columns only')
        self.assertRegex(html, r'data-process="full"[^>]*title="[^"]*branche')
        self.assertEqual(1, html.count('wcv3-proc-branch"'))

    def test_a_chain_without_branches_keeps_one_line(self):
        pipeline = self._with_an_option()
        item = _Element(status=JOB_SUCCESS, wants_summary=True)
        for key in ('render', 'summary'):
            process_runs.start(item, key)
            process_runs.succeed(item, key)
        from django.template.loader import render_to_string
        html = render_to_string('common/_card_processes.html',
                                {'processes': pipeline.card_rows(item), 'card_id': 7})
        self.assertNotIn('wcv3-proc-col--branches', html)
        self.assertNotIn('wcv3-proc-branch"', html)
        self.assertEqual(1, html.count('wcv3-proc-sep'))

    def test_a_process_that_does_not_take_place_leaves_no_empty_column(self):
        """A → B → C with B absent for this model: C comes right after A, and says it follows A."""
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('first', label='A'),
            ProcessSpec('middle', label='B', depends_on=('first',),
                        applies=lambda item, model_key: False),
            ProcessSpec('last', label='C', depends_on=('middle',)),
        ), label='Demo')
        item = _Element(status=JOB_SUCCESS)
        for key in ('first', 'last'):
            process_runs.start(item, key)
            process_runs.succeed(item, key)
        rows = pipeline.card_rows(item, 'any')
        self.assertEqual([('first', 0, []), ('last', 1, ['A'])],
                         [(r['key'], r['column'], r['after']) for r in rows])

    def test_an_output_that_is_not_a_file_makes_its_downstream_stale_when_it_changes(self):
        """A transcription is text in the base, not a file: its glue DECLARES a fingerprint
        (`output_fingerprint`), kept on the line — replaced, the downstream goes stale."""
        pipeline = self._with_an_option()
        item = _Element(status=JOB_SUCCESS, wants_summary=True)
        process_runs.start(item, 'render',
                           settings_snapshot=pipeline.snapshot(pipeline.spec('render'), item))
        process_runs.succeed(item, 'render', output_summary={'fingerprint': 'text-v1'})
        process_runs.start(item, 'summary',
                           settings_snapshot=pipeline.snapshot(pipeline.spec('summary'), item))
        process_runs.succeed(item, 'summary')
        self.assertEqual(set(), pipeline.refresh(item))
        process_runs.succeed(item, 'render', output_summary={'fingerprint': 'text-v2'})
        self.assertEqual({'summary'}, pipeline.refresh(item))

    def test_a_page_of_cards_reads_its_lines_in_one_query(self):
        """Measured on 2026-10-03: the strip cost six queries PER CARD (the lines were read again
        by `refresh`, `card_rows` and `shown_state`). A page preloads the lines of all its cards
        at once ; a card asked alone reads them once and leaves nothing on the instance."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from wama.common.services.process_pipeline import PRELOADED, card_view, preload
        APP_PIPELINES['demo_pipeline'] = self.pipeline
        self.addCleanup(APP_PIPELINES.pop, 'demo_pipeline', None)
        cards = [_Element(status=JOB_SUCCESS) for _ in range(3)]
        for card in cards:
            self._played(card, 'plan')
            self._played(card, 'render')
        with CaptureQueriesContext(connection) as page:
            preload(cards)
            views = [card_view(card, preloaded=True) for card in cards]
        self.assertEqual(1, len(page), [q['sql'][:80] for q in page])
        self.assertTrue(all(view[1] == JOB_SUCCESS and len(view[0]) == 2 for view in views))
        alone = _Element(status=JOB_SUCCESS)
        self._played(alone, 'render')
        with CaptureQueriesContext(connection) as single:
            card_view(alone)
        self.assertEqual(1, len(single))
        self.assertFalse(hasattr(alone, PRELOADED), 'nothing read stays on a kept instance')

    def test_a_fresh_process_loads_the_declarations_before_saying_there_is_no_pipeline(self):
        """Lived on 2026-10-03, 500 on the live composer page: a web process that had imported
        no `function_specs` yet read an EMPTY registry as « this app has no pipeline ». An
        unknown app makes the registry load the declarations of the installed apps, once."""
        from wama.common.services import process_pipeline
        item = _Element(status=JOB_SUCCESS)
        APP_PIPELINES.pop('demo_pipeline', None)

        def register_now():
            APP_PIPELINES['demo_pipeline'] = self.pipeline

        self.addCleanup(APP_PIPELINES.pop, 'demo_pipeline', None)
        with mock.patch.object(process_pipeline, '_declarations_loaded', False), \
                mock.patch('wama.common.catalog.function_catalog.load_all',
                           side_effect=register_now) as loaded:
            self.assertIs(process_pipeline.pipeline_of(item), self.pipeline)
            process_pipeline.pipeline_of(item)
        self.assertEqual(1, loaded.call_count, 'loaded once per process, not at every card')

    def test_the_common_decoration_sets_the_view_only_for_an_app_with_a_pipeline(self):
        """`decorate` is the single attachment point of the GENERATED apps (5.2) : nothing
        without a declared pipeline (the card reads `status`), the three attributes with one."""
        from wama.common.services.process_pipeline import card_view, decorate
        item = _Element(status=JOB_SUCCESS)
        APP_PIPELINES.pop('demo_pipeline', None)
        self.assertIsNone(card_view(item))
        self.assertIsNone(decorate(item))
        self.assertFalse(hasattr(item, 'shown_state'))
        APP_PIPELINES['demo_pipeline'] = self.pipeline
        self.addCleanup(APP_PIPELINES.pop, 'demo_pipeline', None)
        self._played(item, 'plan')
        self._played(item, 'render')
        rows, state, label = decorate(item)
        self.assertEqual((['plan', 'render'], JOB_SUCCESS), ([r['key'] for r in rows], state))
        self.assertEqual((item.processes, item.shown_state, item.shown_state_label),
                         (rows, state, label))
        self.assertTrue(label)

    def test_the_requested_model_is_declared_once_and_read_by_the_card(self):
        """Each app told the strip, the progress view and the ▶ of a process which model the
        card asks for (2026-10-04). It is declared ONCE (`model_of`) ; `card_view` reads it when
        no key is passed, an explicit key still wins, a declaration that raises says « unknown »."""
        from wama.common.services.process_pipeline import card_view, decorate_cards
        declared = AppPipeline('demo_pipeline', self.pipeline.specs, label='Demo',
                               model_of=lambda item: item.model)
        APP_PIPELINES['demo_pipeline'] = declared
        self.addCleanup(APP_PIPELINES.pop, 'demo_pipeline', None)
        scored = _Element(status=JOB_SUCCESS, model='writes-scores')
        plain = _Element(status=JOB_SUCCESS, model='plain')
        self.assertEqual(['plan', 'render'], [r['key'] for r in card_view(scored)[0]])
        self.assertEqual(['render'], [r['key'] for r in card_view(plain)[0]])
        self.assertEqual(['plan', 'render'],
                         [r['key'] for r in card_view(plain, 'writes-scores')[0]])
        self.assertIsNone(declared.requested_model(_Element(status=JOB_SUCCESS)),
                          'no `model` on the element : unknown, never an error')
        seen = []
        cards = decorate_cards([scored, None, plain],
                               lambda item, preloaded: seen.append((item.pk, preloaded)))
        self.assertEqual([(scored.pk, True), (plain.pk, True)], seen)
        self.assertEqual([scored, plain], cards)
        self.assertEqual(['render'], [r['key'] for r in decorate_cards([plain])[0].processes])

    def test_a_stale_render_is_shown_under_a_successful_element(self):
        item = _Element(status=JOB_SUCCESS)
        (Path(self.tmp) / 'score.abc').write_text('X:1', encoding='utf-8')
        self._played(item, 'plan', 'score.abc')
        self._played(item, 'render')
        self.assertEqual(JOB_SUCCESS, self.pipeline.shown_state(item))
        item.duration = 60
        self.assertEqual(JOB_STALE, self.pipeline.shown_state(item))
        rows = self.pipeline.card_rows(item)
        self.assertEqual([('plan', 'Partition', JOB_SUCCESS), ('render', 'Rendu', JOB_STALE)],
                         [(r['key'], r['label'], r['status']) for r in rows])
        self.assertEqual('plan.out', rows[0]['output_label'])
        self.assertEqual('family:m', rows[0]['model_key'])

    def test_the_rows_show_what_ran_and_what_the_named_model_will_run(self):
        item = _Element(status=JOB_PENDING)
        self.assertEqual(['render'], [r['key'] for r in self.pipeline.card_rows(item, 'plays-only')])
        self.assertEqual(['plan', 'render'],
                         [r['key'] for r in self.pipeline.card_rows(item, 'writes-scores')])
        self.assertTrue(all(r['status'] == JOB_PENDING for r in
                            self.pipeline.card_rows(item, 'writes-scores')))

    def test_the_common_strip_renders_one_line_per_process_and_nothing_without_any(self):
        from django.template.loader import render_to_string
        html = render_to_string('common/_card_processes.html', {'processes': [
            {'key': 'plan', 'label': 'Partition', 'degree': 'required', 'status': JOB_SUCCESS,
             'duration_s': 159.1, 'model_key': 'family:m', 'output_label': 'a.abc', 'error': ''},
            {'key': 'render', 'label': 'Rendu', 'degree': 'required', 'status': JOB_STALE,
             'duration_s': 54.0, 'model_key': '', 'output_label': '', 'error': ''}]})
        self.assertIn('data-processes', html)
        self.assertIn('data-process="plan"', html)
        self.assertIn('data-s="STALE"', html)
        self.assertIn('159 s', html)
        self.assertIn('périmé', html)
        self.assertEqual('', render_to_string('common/_card_processes.html',
                                              {'processes': []}).strip())
        single = render_to_string('common/_card_processes.html', {'processes': [
            {'key': 'render', 'label': 'Rendu', 'degree': 'required', 'status': JOB_SUCCESS,
             'duration_s': 54.0, 'model_key': '', 'output_label': '', 'error': ''}]})
        self.assertEqual('', single.strip(), 'one process is not a pipeline to show')


class SkeletonRunsThePipelineTest(TestCase):
    """The retained processes run one after the other in ONE task, one line each."""

    def setUp(self):
        self.app, self.model = _adopters()[0]
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('plan'), ProcessSpec('render', depends_on=('plan',), share=3),
        ), label='Demo')
        self.calls = []

    def _element(self, name):
        user = get_user_model().objects.create_user(name, password='x')
        item = _instance(self.model, user)
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        return item

    def _run(self, item, **glues):
        from wama.common.utils.task_skeleton import run_item_task

        def default(key):
            def glue(element, ctx):
                self.calls.append((key, ctx.step))
                return {'models': [f'family:{key}'], 'label': f'{key}.out'}
            return glue
        processes = {spec.key: glues.get(spec.key) or default(spec.key)
                     for spec in self.pipeline.specs}
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(), app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline, processes=processes,
                          model_key='family:announced')
        return self.model.objects.get(pk=item.pk)

    def _states(self, item):
        return {row.node_id: row.status for row in process_runs.lines(item)}

    def test_both_processes_run_in_order_and_each_has_its_line(self):
        item = self._run(self._element('pipeline_both'))
        self.assertEqual([('plan', 'plan'), ('render', 'render')], self.calls)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_SUCCESS}, self._states(item))
        plan, render = (process_runs.line(item, key) for key in ('plan', 'render'))
        self.assertEqual((f'{self.app}.plan', 'function', 'family:plan'),
                         (plan.process_key, plan.process_kind, plan.model_key))
        self.assertEqual('family:render', render.model_key)
        self.assertEqual('plan.out', plan.output_summary.get('label'))
        self.assertIsNone(process_runs.line(item), 'a pipeline card has no « main » line')

    def test_the_card_reports_every_model_its_processes_employed(self):
        with mock.patch('wama.common.utils.task_skeleton._signal') as signal:
            self._run(self._element('pipeline_models'))
        produced = [call for call in signal.call_args_list if call.args[2] == 'produit']
        self.assertEqual(['family:plan', 'family:render'], produced[0].args[3])

    def test_a_glue_sees_what_it_watched_at_its_last_render(self):
        """`ctx.snapshot` / `ctx.previous_snapshot` (2026-10-13) : read BEFORE the launch plan sets
        the lines back to pending — what lets the Writer's layout know that only its upstream
        changed, and adjust its result instead of redoing it."""
        seen = []

        def render(element, ctx):
            seen.append((ctx.snapshot, ctx.previous_snapshot))
            return {}
        item = self._run(self._element('pipeline_snapshots'), render=render)
        self.assertIsNone(seen[0][1], 'never rendered : no previous photo')
        self.assertIn('@upstream', seen[0][0], 'the photo carries its upstream fingerprint')
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        self._run(item, render=render)
        self.assertEqual(seen[0][0], seen[1][1], 'the photo of its last render, not the new one')

    def test_a_handed_over_launch_still_sees_the_photo_of_its_last_render(self):
        """The Writer's « Appliquer » on the live (2026-10-14) : the launch plans its lines on the
        default queue, then is handed over to the GPU queue under the SAME task id ; the second
        delivery read the lines after that plan, found no render, and the layout redid it all."""
        seen = []

        def render(element, ctx):
            seen.append(ctx.previous_snapshot)
            return {}
        item = self._run(self._element('pipeline_handed_over'), render=render)
        rendered = dict(process_runs.line(item, 'render').settings_snapshot)
        task_id = _task().request.id
        process_runs.plan(item, [('render', 'render', 'function')], task_id=task_id)
        process_runs.plan(item, [('render', 'render', 'function')], task_id=task_id)
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        self._run(item, render=render)
        self.assertEqual(rendered, seen[-1], 'the second delivery lost the last render')
        # Not a render : a line another launch announced, or one planned over a failure.
        line = process_runs.line(item, 'render')
        self.assertTrue(process_runs.rendered_before(line, task_id))
        process_runs.plan(item, [('render', 'render', 'function')], task_id='another-task')
        self.assertFalse(process_runs.rendered_before(process_runs.line(item, 'render'), task_id))
        # A launch stopped before its turn, then launched again : the line was already PENDING,
        # nothing rendered since — the new launch still sees the last render.
        self.assertTrue(process_runs.rendered_before(process_runs.line(item, 'render'),
                                                     'another-task'))
        ProcessRun.objects.filter(pk=line.pk).update(status=JOB_FAILURE)
        process_runs.plan(item, [('render', 'render', 'function')], task_id=task_id)
        self.assertFalse(process_runs.rendered_before(process_runs.line(item, 'render'), task_id))

    def test_a_failure_closes_the_line_of_the_process_that_failed_only(self):
        def broken(element, ctx):
            raise RuntimeError('render is down')
        item = self._run(self._element('pipeline_fails'), render=broken)
        self.assertEqual('FAILURE', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_FAILURE}, self._states(item))
        self.assertIn('render is down', process_runs.line(item, 'render').error_message)

    def test_an_optional_process_that_fails_does_not_fail_the_card(self):
        """Rule 4.4: only a REQUIRED process in failure fails the card. An optional one says it
        on its own line, the card ends in success for the element and « to be completed » for
        the deduced state — what the transcriber used to swallow (summary failed, nothing shown)."""
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('plan'),
            ProcessSpec('extra', depends_on=('plan',), degree='optional'),
            ProcessSpec('render', depends_on=('plan',)),
        ), label='Demo')

        def broken(element, ctx):
            raise RuntimeError('the summary model is down')
        item = self._run(self._element('pipeline_optional_mid'), extra=broken)
        self.assertEqual([('plan', 'plan'), ('render', 'render')], self.calls,
                         'the processes after the failed option still run')
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'extra': JOB_FAILURE, 'render': JOB_SUCCESS},
                         self._states(item))
        self.assertIn('summary model is down', process_runs.line(item, 'extra').error_message)
        self.assertEqual(JOB_PENDING, self.pipeline.card_state(item), 'the card is to be completed')
        # ▶ again replays ONLY what is missing.
        self.calls.clear()
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        item = self._run(item)
        self.assertEqual([('extra', 'extra')], self.calls)
        self.assertEqual(JOB_SUCCESS, self.pipeline.card_state(item))

    def test_an_optional_process_that_waits_redelivers_the_task_instead_of_failing(self):
        """2026-10-18 : a glue that installs its model (`ctx.ensure_model`) WAITS — even in an
        optional process, that is not a failure : the task is redelivered, the card keeps going."""
        from wama.common.utils.task_skeleton import ServiceNotReady
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('plan'),
            ProcessSpec('extra', depends_on=('plan',), degree='optional'),
        ), label='Demo')

        def waiting(element, ctx):
            raise ServiceNotReady('Installation de « X » en cours', countdown=30, max_attempts=720)
        task = _task()
        task.retry = staticmethod(lambda **kw: RuntimeError(f"re-delivered {kw['countdown']}"))
        item = self._element('pipeline_optional_waits')
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                self.assertRaisesMessage(RuntimeError, 're-delivered 30'):
            from wama.common.utils.task_skeleton import run_item_task
            run_item_task(task, app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline,
                          processes={'plan': lambda element, ctx: {}, 'extra': waiting})
        item = self.model.objects.get(pk=item.pk)
        self.assertEqual('RUNNING', item.status)
        self.assertNotEqual(JOB_FAILURE, process_runs.line(item, 'extra').status)

    def test_a_glue_installs_its_model_through_the_context(self):
        """`ctx.ensure_model(key)` : the common brick with the card's user, console and redelivery
        — and the key back, to be written in line."""
        seen = []

        def render(element, ctx):
            seen.append(ctx.ensure_model('family:secondary'))
            return {}
        with mock.patch('wama.common.utils.model_readiness.ensure_installed') as ensure:
            item = self._run(self._element('pipeline_ensure_model'), render=render)
        self.assertEqual(['family:secondary'], seen)
        keys = [call.args[0] for call in ensure.call_args_list]
        self.assertEqual(['family:announced', 'family:secondary'], keys,
                         'the card model by the skeleton, then the glue its own')
        last = ensure.call_args_list[-1].kwargs
        self.assertEqual(item.user, last['user'])
        self.assertIs(False, last['redelivered'])
        self.assertTrue(callable(last['console']))

    def test_a_last_optional_process_that_fails_leaves_the_card_named_and_successful(self):
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('plan'), ProcessSpec('render', depends_on=('plan',), degree='optional'),
        ), label='Demo')

        def broken(element, ctx):
            raise RuntimeError('render is down')
        with mock.patch('wama.common.utils.task_skeleton._notify') as notify:
            item = self._run(self._element('pipeline_optional_last'), render=broken)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_FAILURE}, self._states(item))
        self.assertEqual(('plan.out', True), notify.call_args.args[2:4],
                         'the card keeps the name its last SUCCESSFUL process gave')

    def test_the_relaunch_after_a_failure_does_not_replay_what_succeeded(self):
        def broken(element, ctx):
            raise RuntimeError('render is down')
        item = self._run(self._element('pipeline_resumes'), render=broken)
        self.calls.clear()
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        item = self._run(item)
        self.assertEqual([('render', 'render')], self.calls)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_SUCCESS}, self._states(item))

    def test_each_process_fills_its_own_share_of_the_bar(self):
        """`plan` weighs 1 and `render` 3: half of `plan` is an eighth of the card."""
        if not any(f.name == 'progress' for f in self.model._meta.get_fields()):
            self.skipTest(f'{self.app} has no progress column')
        seen = {}

        def half(key):
            def glue(element, ctx):
                ctx.progress(50)
                seen[key] = self.model.objects.get(pk=element.pk).progress
                return {}
            return glue
        self._run(self._element('pipeline_bar'), plan=half('plan'), render=half('render'))
        self.assertEqual({'plan': 12, 'render': 62}, seen)

    def test_each_process_learns_its_own_duration(self):
        """Point 4.5: the ETA is per PROCESS — the one of `plan` is recorded when `plan` returns,
        under its own key, not when the card ends."""
        def with_eta(key):
            def glue(element, ctx):
                return {'eta': (f'family:{key}', 2.0, 'audio_sec')}
            return glue
        with mock.patch('wama.model_manager.services.eta_estimator.record_run') as record:
            self._run(self._element('pipeline_eta'), plan=with_eta('plan'),
                      render=with_eta('render'))
        self.assertEqual(['family:plan', 'family:render'],
                         [call.args[0] for call in record.call_args_list])

    def test_the_time_limit_closes_the_line_of_the_process_it_interrupted(self):
        from wama.common.utils.task_skeleton import TaskTimeLimitExceeded

        def too_long(element, ctx):
            raise TaskTimeLimitExceeded(60)
        item = self._run(self._element('pipeline_limit'), render=too_long)
        self.assertEqual('FAILURE', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_FAILURE}, self._states(item))
        self.assertIn('Durée maximale', process_runs.line(item, 'render').error_message)

    def test_the_wait_for_the_graphics_card_is_decided_at_the_gpu_process_on_its_line(self):
        """2026-10-14 (Fabien: the governor at the grain of the PROCESS): a process that does not
        use the card plays without waiting; the GPU process that follows waits, and its OWN line
        says so — no « main » line. Until then the wait was decided before the card, and a
        pipeline card wrote no line at all (« nobody knows which process starts first »)."""
        from wama.common.utils.task_skeleton import run_item_task
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('plan'), ProcessSpec('render', depends_on=('plan',), gpu=True),
        ), label='Demo')

        class Deferred(Exception):
            pass
        task = _task()
        task.retry = staticmethod(lambda **kwargs: Deferred(kwargs))
        item = self._element('pipeline_waits')

        def glue(key):
            def inner(element, ctx):
                self.calls.append(key)
                return {}
            return inner
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                mock.patch('wama.common.services.resource_governor.effective_free_gb',
                           return_value=1.0), \
                mock.patch('wama.common.services.resource_governor.fits_alone',
                           return_value=True), \
                mock.patch('wama.common.services.resource_governor.release_granted',
                           return_value=None), \
                mock.patch('wama.common.services.resource_governor.holders_summary',
                           return_value=''):
            with self.assertRaises(Deferred):
                run_item_task(task, app_id=self.app, model=self.model, item_id=item.pk,
                              pipeline=self.pipeline, vram_needed=8.0,
                              processes={'plan': glue('plan'), 'render': glue('render')})
        item = self.model.objects.get(pk=item.pk)
        self.assertEqual('AWAITING_RESOURCES', item.status)
        self.assertEqual(['plan'], self.calls, 'the process without GPU did not wait')
        self.assertEqual({'plan': JOB_SUCCESS, 'render': 'AWAITING_RESOURCES'}, self._states(item))
        self.assertIsNone(process_runs.line(item), 'still no « main » line')

    def test_the_skeleton_can_be_bounded_to_one_process(self):
        item = self._run(self._element('pipeline_bounded_first'))
        self.calls.clear()
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        from wama.common.utils.task_skeleton import run_item_task

        def glue(key):
            def inner(element, ctx):
                self.calls.append(key)
                return {}
            return inner
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(), app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline, only='plan',
                          processes={'plan': glue('plan'), 'render': glue('render')})
        self.assertEqual(['plan'], self.calls)
        self.assertEqual('SUCCESS', self.model.objects.get(pk=item.pk).status)
        self.assertEqual(JOB_SUCCESS, process_runs.line(item, 'plan').status)

    def test_a_process_without_its_glue_fails_the_card_and_says_so(self):
        from wama.common.utils.task_skeleton import run_item_task
        item = self._element('pipeline_no_glue')
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(), app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline, processes={'render': lambda e, c: {}})
        item = self.model.objects.get(pk=item.pk)
        self.assertEqual('FAILURE', item.status)
        self.assertFalse(process_runs.lines(item).exists(), 'no process started, no line')


class InputsThePipelineBringsTest(SimpleTestCase):
    """EXTENDED inputs (2026-10-03): an upstream process can make one of the model's inputs out of
    another — the composer's `extract_score` turns the audio of a cover into the score YuE2
    follows. Derived from the declarations (port types of the `FunctionSpec`s, `available`), never
    rewritten by an app. A fictitious pipeline: extract (audio → score), plan (prompt → score),
    render (prompt + score)."""

    KEYS = ('demo_bridge.extract', 'demo_bridge.plan', 'demo_bridge.render', 'demo_bridge.output')

    def setUp(self):
        from wama.common.catalog.function_catalog import (FUNCTION_CATALOG, Binding, FunctionSpec,
                                                          PortSpec)

        def declare(key, inputs, outputs):
            FUNCTION_CATALOG[key] = FunctionSpec(
                key=key, name=key, description='', category='transform', binding=Binding.APP,
                app='demo_bridge', inputs=[PortSpec(k, t, optional=True) for k, t in inputs],
                outputs=[PortSpec(k, t) for k, t in outputs])
        declare(self.KEYS[0], [('work_audio', 'audio')], [('score', 'score')])
        declare(self.KEYS[1], [('prompt', 'prompt')], [('score', 'score')])
        declare(self.KEYS[2], [('prompt', 'prompt'), ('work_score', 'score')], [('audio', 'audio')])
        declare(self.KEYS[3], [('rendered', 'audio')], [('audio', 'audio')])
        self.addCleanup(lambda: [FUNCTION_CATALOG.pop(k, None) for k in self.KEYS])
        self.installed = True

    def _pipeline(self, extract_function='demo_bridge.extract', with_output=False):
        specs = [
            ProcessSpec('extract', function=extract_function, available=lambda: self.installed,
                        applies=lambda item, model: True),
            ProcessSpec('plan', function='demo_bridge.plan'),
            ProcessSpec('render', function='demo_bridge.render', depends_on=('extract', 'plan')),
        ]
        if with_output:
            specs.append(ProcessSpec('output', function='demo_bridge.output',
                                     depends_on=('render',)))
        return AppPipeline('demo_bridge', tuple(specs), label='Demo')

    def test_a_process_downstream_of_the_model_s_one_changes_nothing(self):
        """The composer's `output` process (format, quality) comes after the render: the model's
        process is no longer the last one, and the extended inputs must not move."""
        pipeline = self._pipeline(with_output=True)
        self.assertTrue({'work_audio', 'work_score'} <= pipeline.covering_inputs('work_audio'))
        self.assertEqual({'prompt', 'work_score', 'work_audio'},
                         pipeline.extended_inputs({'prompt', 'work_score'}))

    def test_a_model_that_follows_a_score_takes_the_audio_the_score_is_extracted_from(self):
        pipeline = self._pipeline()
        self.assertEqual({'work_audio', 'work_score'}, pipeline.covering_inputs('work_audio'))
        self.assertEqual({'prompt', 'work_score', 'work_audio'},
                         pipeline.extended_inputs({'prompt', 'work_score'}))

    def test_a_model_without_the_bridged_port_gains_nothing(self):
        self.assertEqual({'prompt'}, self._pipeline().extended_inputs({'prompt'}))

    def test_an_unavailable_upstream_extends_nothing_and_does_not_take_place(self):
        self.installed = False
        pipeline = self._pipeline()
        self.assertEqual({'work_audio'}, pipeline.covering_inputs('work_audio'))
        self.assertNotIn('work_audio', pipeline.extended_inputs({'prompt', 'work_score'}))
        self.assertEqual(['plan', 'render'], _keys(pipeline.applicable(_Element(), 'any')))

    def test_an_availability_that_cannot_be_read_counts_as_no(self):
        def broken():
            raise RuntimeError('catalogue down')
        spec = ProcessSpec('extract', available=broken)
        self.assertFalse(AppPipeline.can_run(spec))

    def test_a_process_whose_function_is_not_declared_yields_the_port_alone(self):
        pipeline = self._pipeline(extract_function='demo_bridge.nowhere')
        self.assertEqual({'work_audio'}, pipeline.covering_inputs('work_audio'))

    def test_availability_never_reaches_the_manifest(self):
        declared = [node['process'] for node in self._pipeline().graph()['nodes']]
        self.assertTrue(all('available' not in p for p in declared), declared)


class ADuplicateStartsWithoutWhatItsProcessesWroteTest(TestCase):
    """`duplicate_instance` + `AppPipeline.produced_fields` (2026-10-21) : a copy SHARES what the
    user gave (the brick's contract) and starts without what the source's processes WROTE — the
    declared output of a process that takes place, or that one of its lines rendered. Every app's
    views copied these lists by hand, twice (card view, batch factory), and they had drifted
    (`parts_score`). A declared output is not always a result: the audio of an avatarizer job is
    `speak`'s output in « pipeline » mode, and the user's own audio in « standalone » mode."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from wama.common.catalog.function_catalog import load_all
        load_all()
        self.user = get_user_model().objects.create_user('duplicate_produced', password='x')

    def _filled(self, model, **fields):
        item = _instance(model, self.user)
        names = [f.name for f in model._meta.concrete_fields
                 if f.get_internal_type() in ('FileField', 'ImageField')]
        model.objects.filter(pk=item.pk).update(
            **{n: f'users/{self.user.pk}/{n}_{item.pk}.bin' for n in names}, **fields)
        item.refresh_from_db()
        return item, names

    def test_every_app_with_a_pipeline_drops_what_it_produced_and_shares_the_rest(self):
        from wama.common.utils.preview_registry import PreviewRegistry
        from wama.common.utils.queue_duplication import duplicate_instance
        produced_somewhere = []
        for app, pipeline in APP_PIPELINES.items():
            model = PreviewRegistry.get_model(app)
            if model is None:
                continue
            with self.subTest(app=app):
                item, names = self._filled(model)
                produced = pipeline.produced_fields(item)
                copy = duplicate_instance(item)
                self.assertEqual([], [n for n in produced if getattr(copy, n)],
                                 'the copy keeps a result of the source')
                self.assertEqual([], [n for n in names if n not in produced
                                      and getattr(copy, n).name != getattr(item, n).name],
                                 'the copy lost something the user gave')
                produced_somewhere += produced
        self.assertTrue(produced_somewhere, 'nothing produced anywhere: the guard measures nothing')

    def test_the_avatar_s_audio_goes_when_spoken_and_stays_when_given(self):
        from wama.avatarizer.models import AvatarJob
        from wama.common.utils.queue_duplication import duplicate_instance
        spoken, _ = self._filled(AvatarJob, mode='pipeline')
        given, _ = self._filled(AvatarJob, mode='standalone')
        self.assertFalse(duplicate_instance(spoken).audio_input, 'the TTS audio is a result')
        self.assertEqual(given.audio_input.name, duplicate_instance(given).audio_input.name,
                         "the user's own audio is an input: the copy keeps it")

    def test_an_old_result_goes_even_when_its_process_no_longer_takes_place(self):
        from wama.common.utils.queue_duplication import duplicate_instance
        from wama.transcriber.models import Transcript
        item, _ = self._filled(Transcript, level_speech=False, preprocess_audio=False)
        process_runs.succeed(item, 'level', output_ref=item.leveled_audio.name)
        self.assertIn('leveled_audio', APP_PIPELINES['transcriber'].produced_fields(item))
        self.assertFalse(duplicate_instance(item).leveled_audio)

    def test_no_duplicate_list_names_a_field_the_pipeline_derives(self):
        """One path: a view's `clear_fields` / `output_fields` names only what no process declares
        (a text, an error message) — never a declared output, which the brick derives. Held on the
        app's views AND on the views the GENERATOR renders from its manifest (the sandbox twins) :
        `views_gen.champs_sortie` derived its own list until 2026-10-22."""
        import ast
        from pathlib import Path
        from django.conf import settings
        from wama.common.manifests.codegen.views_gen import render_views
        from wama.common.manifests.ingest import extract
        from wama.common.sandbox import sandbox_labels
        twins = set(sandbox_labels())
        found, generated = [], 0
        for app, pipeline in APP_PIPELINES.items():
            if app in twins:
                continue
            declared = {f for spec in pipeline.specs for f in spec.outputs}
            views = Path(settings.BASE_DIR) / 'wama' / app / 'views.py'
            if not declared or not views.exists():
                continue
            rendered, _why = render_views(extract('app', app))
            generated += bool(rendered)
            for origin, source in (('app', views.read_text(encoding='utf-8')),
                                   ('généré', rendered or '')):
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.keyword) and node.arg in ('clear_fields',
                                                                     'output_fields'):
                        try:
                            listed = set(ast.literal_eval(node.value))
                        except ValueError:
                            found.append(f'{app} ({origin}): {node.arg} non littéral '
                                         f'({ast.unparse(node.value)})')
                            continue
                        found += [f'{app} ({origin}): {node.arg} nomme {f}'
                                  for f in sorted(listed & declared)]
        self.assertTrue(generated, 'no generated views: the generator side measures nothing')
        self.assertEqual([], found)


class EveryAppPipelineTest(SimpleTestCase):
    """Generic guard over EVERY pipeline an app registers (`APP_PIPELINES`) — written once, it
    holds for the next app without a test per app. What the cam_analyzer guards for its own
    registry (`tests_pass_registry.PipelineManifesteTest`), held here for the common one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from wama.common.catalog.function_catalog import FUNCTION_CATALOG, load_all
        load_all()
        cls.catalogue = FUNCTION_CATALOG
        cls.pipelines = dict(APP_PIPELINES)

    def test_the_fleet_is_measured(self):
        self.assertIn('composer', self.pipelines)

    def test_each_process_is_a_function_of_the_catalogue_bound_to_its_app(self):
        from wama.common.catalog.function_catalog import Binding
        for app, pipeline in self.pipelines.items():
            for spec in pipeline.specs:
                with self.subTest(app=app, process=spec.key):
                    function = self.catalogue.get(pipeline.function_key(spec))
                    self.assertIsNotNone(function, 'a process without a FunctionSpec is no node')
                    self.assertEqual((Binding.APP, app), (function.binding, function.app))

    def test_the_manifest_is_valid_and_carries_the_world_the_app_states(self):
        from wama.common.app_registry import app_world
        from wama.common.manifests.ingest import extract, validate
        for app, pipeline in self.pipelines.items():
            with self.subTest(app=app):
                manifest = extract('pipeline', app)
                self.assertIsNotNone(manifest, 'the registry is not a pipeline source')
                self.assertEqual([], list(validate(manifest) or []))
                self.assertEqual(app_world(app), manifest['world'])
                self.assertEqual([spec.key for spec in pipeline.specs],
                                 [node['id'] for node in manifest['body']['nodes']])

    def test_the_exported_manifest_is_the_one_of_the_corpus(self):
        """The versioned file must be what the registry gives TODAY, and the export command must
        see the pipeline — or the corpus loses it silently (`--check` would say « up to date »)."""
        import json
        from django.conf import settings
        from wama.common.management.commands.manifest_export import _pipeline_keys
        from wama.common.manifests.ingest import extract
        from wama.common.sandbox import sandbox_labels
        twins = set(sandbox_labels())
        for app in self.pipelines:
            if app in twins:
                # A sandbox twin is never versioned (`non_sandbox_apps`): the corpus holds real
                # apps. Its pipeline must stay OUT of the export instead.
                self.assertNotIn(app, _pipeline_keys())
                continue
            with self.subTest(app=app):
                self.assertIn(app, _pipeline_keys())
                written = Path(settings.BASE_DIR) / 'manifests' / 'pipelines' / f'{app}.json'
                self.assertTrue(written.exists(), 'the pipeline is not in the corpus')
                corpus = json.loads(written.read_text(encoding='utf-8'))
                live = extract('pipeline', app)
                self.assertEqual(corpus['body'], live['body'])

    def test_it_opens_in_the_studio_and_each_link_lands_on_a_port(self):
        """« One representation, two editors »: the canvas form, with each dependency resolved
        to the input port whose type matches what the upstream process gives."""
        from wama.common.manifests.builtin.pipeline import body_to_graph
        from wama.common.manifests.ingest import extract
        for app, pipeline in self.pipelines.items():
            with self.subTest(app=app):
                graph = body_to_graph(extract('pipeline', app)['body'])
                self.assertEqual([spec.key for spec in pipeline.specs],
                                 [node['id'] for node in graph['nodes']])
                for link in graph['links']:
                    self.assertTrue(link['to_port'], f"{link['from']} -> {link['to']} has no port")

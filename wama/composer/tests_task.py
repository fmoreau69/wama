"""The composer's item task runs through the common skeleton (2026-10-02).

Ported from a hand-written task to `task_skeleton.run_item_task` (`ROUTE §10.6`: an app with ONE
process adopts the skeleton without waiting for the common engine). What the skeleton itself
promises is held for every adopter by `common/tests/tests_task_skeleton_contract`; here, what the
composer's GLUE owes:

  * an « auto » choice STAYS « auto » — the drawn model is reported, never written into the
    setting (the old task replaced the user's choice at the first generation);
  * the output lands in the app's home given by the brick, not in a hand-built folder;
  * a failing engine ends in a relaunchable failure;
  * a launcher, not the task, says « running ».
"""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from wama.composer import tasks
from wama.composer.models import ComposerGeneration

AUTO = 'auto:text-to-music'
DRAWN = 'composer:musicgen-small'


def _celery_task():
    class _Task:
        class request:
            id = 'composer-task-test'
            retries = 0
            delivery_info = {}
    return _Task


class _Engine:
    """Stand-in backend: writes the output file and remembers what it was asked."""
    calls = []
    error = None

    def generate(self, **kwargs):
        type(self).calls.append(kwargs)
        if type(self).error:
            raise type(self).error
        Path(kwargs['output_path']).write_bytes(b'RIFF')

    def unload(self):
        """The common contract: the task gives its engine back after every launch (guarded in
        `tests_pipeline`) — a stand-in without it made each launch log a release warning."""


class ComposerTaskTest(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user = get_user_model().objects.create_user('composer_task', password='x')
        _Engine.calls, _Engine.error = [], None

    def _generation(self, **fields):
        fields.setdefault('model', AUTO)
        return ComposerGeneration.objects.create(user=self.user, prompt='a calm piano',
                                                 status='RUNNING', **fields)

    def _run(self, gen, cap=None):
        """Runs the real task body; the draw, the prompt pipeline, the engine and the ETA record
        are stand-ins (no catalogue, no model, no GPU)."""
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                mock.patch('wama.composer.utils.auto_model.resolve_auto_model',
                           return_value=DRAWN) as draw, \
                mock.patch('wama.common.backends.manager.backend_for_key', return_value=_Engine), \
                mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                           side_effect=lambda app, field, text, **kw: text), \
                mock.patch('wama.common.utils.model_readiness.warn_if_weights_missing'), \
                mock.patch('wama.composer.utils.model_config.clamp_duration',
                           side_effect=lambda value, model_id=None: cap or value), \
                mock.patch('wama.model_manager.services.eta_estimator.record_run') as record:
            tasks.compose_task.run.__func__(_celery_task(), gen.pk)
        gen.refresh_from_db()
        return gen, draw, record

    def test_an_auto_choice_stays_auto_and_the_drawn_model_is_reported(self):
        gen, draw, record = self._run(self._generation())
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertEqual(AUTO, gen.model, 'the drawn model replaced the user’s « auto » choice')
        draw.assert_called_once()
        self.assertEqual('musicgen-small', _Engine.calls[0]['model_id'])
        self.assertEqual(DRAWN, record.call_args.args[0], 'the ETA is not learnt for the drawn model')

    def test_a_designated_model_is_used_as_it_is(self):
        gen, draw, _record = self._run(self._generation(model='composer:musicgen-medium'))
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        draw.assert_not_called()
        self.assertEqual('musicgen-medium', _Engine.calls[0]['model_id'])

    def test_the_output_lands_in_the_apps_home(self):
        from wama.common.utils.media_paths import app_media_dir
        gen, _draw, _record = self._run(self._generation())
        home = app_media_dir('composer', self.user.id, 'output')
        self.assertTrue(gen.audio_output.name.startswith(home + '/'), gen.audio_output.name)
        self.assertTrue((Path(self.tmp) / gen.audio_output.name).is_file())
        self.assertFalse((Path(self.tmp) / 'composer').exists(),
                         'the output was written to the old hand-built folder')

    def test_the_cap_of_a_drawn_model_is_applied_but_not_written_into_the_setting(self):
        gen, _draw, _record = self._run(self._generation(duration=600), cap=30)
        self.assertEqual(30, _Engine.calls[0]['duration'])
        self.assertEqual(600, gen.duration, 'the cap of ONE draw became the user’s setting')

    def test_the_cap_of_a_designated_model_corrects_the_setting(self):
        """Counter-test: with a model the user named, the cap is the limit of HIS choice."""
        gen, _draw, _record = self._run(
            self._generation(model='composer:musicgen-medium', duration=600), cap=30)
        self.assertEqual((30, 30), (_Engine.calls[0]['duration'], gen.duration))

    def test_a_failing_engine_ends_in_a_relaunchable_failure(self):
        _Engine.error = RuntimeError('engine down')
        gen, _draw, record = self._run(self._generation())
        self.assertEqual('FAILURE', gen.status)
        self.assertIn('engine down', gen.error_message)
        self.assertEqual((0, AUTO), (gen.progress, gen.model))
        self.assertFalse(gen.audio_output)
        record.assert_not_called()


class MelodyGivenByUrlTest(TestCase):
    """The skeleton asks for the model BEFORE it downloads a declared URL: a melody given by URL
    must already count as a melody, or « auto » would draw a model that cannot take it."""

    def _spec_for(self, **fields):
        from wama.composer.utils import auto_model
        gen = ComposerGeneration(model=AUTO, prompt='x', **fields)
        with mock.patch.object(auto_model, 'resolve_model_choice', return_value=DRAWN) as draw:
            auto_model.resolve_auto_model(gen)
        return draw.call_args.kwargs['spec']

    def test_a_melody_url_asks_for_a_model_that_takes_a_melody(self):
        self.assertEqual(['work_audio'],
                         self._spec_for(source_url='https://example.org/m.mp3')['consumes'])

    def test_without_a_melody_the_draw_is_by_task(self):
        """Counter-test."""
        spec = self._spec_for()
        self.assertNotIn('consumes', spec)
        self.assertEqual('text-to-music', spec['task'])


class TheLauncherSaysRunningTest(TestCase):
    """« Running » is set by the launcher (`begin_processing`), no longer by the task: the
    assistant's tool, which sent the task alone, must go through it."""

    def test_the_assistants_tool_launches_a_running_generation(self):
        from wama import tool_api
        user = get_user_model().objects.create_user('composer_tool', password='x')
        with mock.patch('wama.composer.tasks.compose_task.apply_async') as dispatch:
            dispatch.return_value.id = 'task-from-tool'
            out = tool_api.compose_music(user, prompt='a calm piano', model='musicgen-small')
        self.assertNotIn('error', out, out)
        gen = ComposerGeneration.objects.get(pk=out['generation_id'])
        self.assertEqual(('RUNNING', 'task-from-tool'), (gen.status, gen.task_id))

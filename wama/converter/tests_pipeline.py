"""The converter card carries a PIPELINE — `WAMA_APP_GENERATION_ROUTE §10.6`, decision of Fabien
(2026-10-13): « every application must work as a pipeline ». Its task converted THEN applied the
AI post-processing (upscale, denoise, audio enhancement) to the converted file, rewritten in place.

What is held here, and why each point:

  * two processes — convert, and enhance only when a post-processing is ASKED and the account may
    have one (a guest may not) ;
  * the RAW conversion is kept when a post-processing follows (option 1 of Fabien): replaying the
    post-processing alone (×2 → ×4) starts again from it — never from an already processed file —
    and does not convert again ;
  * withdrawing the post-processing converts again: the output is the plain conversion ;
  * a failed post-processing fails the card (it was asked) but the conversion stays ;
  * the launcher no longer erases the output at the click ; a process has its own ▶.
"""
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from wama.common.models import JOB_FAILURE, JOB_SUCCESS
from wama.common.services import process_runs
from wama.converter import tasks
from wama.converter.function_specs import PIPELINE
from wama.converter.models import ConversionJob


class _Jobs(TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root)
        media.enable()
        self.addCleanup(media.disable)
        self.user = get_user_model().objects.create_user('converter_pipeline', password='x')
        self.conversions, self.enhanced_from = 0, []
        self.enhance_error = None

    def _job(self, **fields):
        source = self.root / 'in' / 'photo.png'
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b'source')
        fields.setdefault('status', 'RUNNING')
        return ConversionJob.objects.create(user=self.user, input_file='in/photo.png',
                                            input_filename='photo.png', media_type='image',
                                            output_format='webp', **fields)

    # ── stand-ins ──────────────────────────────────────────────────────────────────────────
    def _convert(self, input_path, output_path, output_format, options=None,
                 progress_callback=None):
        self.conversions += 1
        Path(output_path).write_bytes(b'converted')

    def _enhance(self, job, path, console, progress):
        if self.enhance_error:
            raise self.enhance_error
        self.enhanced_from.append(Path(path).read_bytes())
        Path(path).write_bytes(Path(path).read_bytes() + b'+' + (job.upscale or 'ai').encode())

    def _run(self, job, process=None):
        ConversionJob.objects.filter(pk=job.pk).update(status='RUNNING')
        with mock.patch('wama.common.backends.manager.route_for_nature',
                        return_value=self._convert), \
                mock.patch('wama.converter.utils.cross_app.apply_cross_app_options',
                           side_effect=self._enhance), \
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            tasks.convert_media_task.run(job.pk, process)
        job.refresh_from_db()
        return job

    def _states(self, job):
        return {row.node_id: row.status for row in process_runs.lines(job)}

    def _read(self, field_file):
        return (self.root / field_file.name).read_bytes()


class ProcessesTest(_Jobs):

    def _keys(self, job):
        return [s.key for s in PIPELINE.applicable(job, PIPELINE.requested_model(job))]

    def test_the_post_processing_takes_place_only_when_asked_and_allowed(self):
        self.assertEqual(['convert'], self._keys(self._job()))
        self.assertEqual(['convert', 'enhance'], self._keys(self._job(upscale='x2')))
        with mock.patch('wama.accounts.permissions.is_guest_account', return_value=True):
            self.assertEqual(['convert'], self._keys(self._job(upscale='x2')))


class ConversionRunTest(_Jobs):

    def test_a_plain_conversion_is_the_output(self):
        job = self._run(self._job())
        self.assertEqual({'convert': JOB_SUCCESS}, self._states(job))
        self.assertEqual(b'converted', self._read(job.output_file))
        self.assertFalse(job.converted_file)

    def test_the_raw_conversion_is_kept_and_the_post_processing_works_on_a_copy(self):
        job = self._run(self._job(upscale='x2'))
        self.assertEqual({'convert': JOB_SUCCESS, 'enhance': JOB_SUCCESS}, self._states(job))
        self.assertEqual(b'converted', self._read(job.converted_file), 'the raw stays raw')
        self.assertEqual(b'converted+x2', self._read(job.output_file))

    def test_replaying_the_post_processing_starts_again_from_the_raw_conversion(self):
        job = self._run(self._job(upscale='x2'))
        ConversionJob.objects.filter(pk=job.pk).update(upscale='x4')
        job.refresh_from_db()
        self.assertEqual({'enhance'}, PIPELINE.refresh(job))
        job = self._run(job)
        self.assertEqual(1, self.conversions, 'not converted again')
        self.assertEqual([b'converted', b'converted'], self.enhanced_from,
                         'never from an already processed file')
        self.assertEqual(b'converted+x4', self._read(job.output_file))

    def test_withdrawing_the_post_processing_makes_the_plain_conversion_the_output(self):
        job = self._run(self._job(upscale='x2'))
        ConversionJob.objects.filter(pk=job.pk).update(upscale='')
        job.refresh_from_db()
        self.assertIn('convert', PIPELINE.refresh(job))
        job = self._run(job)
        self.assertEqual(b'converted', self._read(job.output_file))
        self.assertFalse(job.converted_file)

    def test_a_failed_post_processing_fails_the_card_and_keeps_the_conversion(self):
        self.enhance_error = RuntimeError('GPU out of memory')
        job = self._run(self._job(upscale='x2'))
        self.assertEqual('FAILURE', job.status)
        self.assertEqual(JOB_FAILURE, self._states(job)['enhance'])
        self.assertEqual(b'converted', self._read(job.converted_file))


class ViewsTest(_Jobs):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_the_launcher_no_longer_erases_the_output_at_the_click(self):
        job = self._run(self._job(upscale='x2'))
        ConversionJob.objects.filter(pk=job.pk).update(status='SUCCESS')
        with mock.patch('wama.converter.tasks.convert_media_task.delay',
                        return_value=mock.Mock(id='t-1')):
            self.client.post(reverse('converter:start', args=[job.pk]))
        job.refresh_from_db()
        self.assertTrue(job.output_file and job.converted_file)

    def test_the_post_processing_has_its_own_play(self):
        job = self._run(self._job(upscale='x2'))
        ConversionJob.objects.filter(pk=job.pk).update(status='SUCCESS')
        with mock.patch.object(tasks.convert_media_task, 'apply_async',
                               return_value=mock.Mock(id='t-2')) as launch:
            response = self.client.post(reverse('converter:start_process',
                                                args=[job.pk, 'enhance']))
        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual({'process': 'enhance'}, launch.call_args.kwargs['kwargs'])

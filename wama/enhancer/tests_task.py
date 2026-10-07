"""Both enhancer queues (image/video, audio) carry TWO processes — « generate » then « output »
(common brick `output_process`), step P6 of `WAMA_APP_GENERATION_ROUTE §10.6`, 2026-10-03.

What is held here : changing the output format replays the output ALONE, from the file the
enhancement left ; changing an enhancement setting plays the engine again.

The engines are stand-ins : the CHAINING is tested, not the enhancement.
"""
import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from wama.common.services import process_runs
from wama.enhancer import tasks
from wama.enhancer.models import AudioEnhancement, Enhancement
from wama.common.tests.helpers import INLINE_CONVERSION, stand_in_conversion


class _TwoProcesses(TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        media_root = override_settings(MEDIA_ROOT=self.root)
        media_root.enable()
        self.addCleanup(media_root.disable)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.user = get_user_model().objects.create_user('enhancer_pipeline', password='x')
        self.calls = 0

    def _route(self, input_path, output_path, output_format=None, options=None,
               progress_callback=None, **_kw):
        self.calls += 1
        self.options = dict(options or {})
        with open(output_path, 'wb') as out:
            out.write(b'enhanced')
        return {'width': 8, 'height': 6}

    _convert = staticmethod(stand_in_conversion)

    def _states(self, item):
        return {line.node_id: line.status for line in process_runs.lines(item)}

    def _play(self, task, item, route, resolver, drawn, **settings):
        type(item).objects.filter(pk=item.pk).update(status='RUNNING', **settings)
        with mock.patch(route, self._route), \
                mock.patch(resolver, return_value=drawn), \
                mock.patch('wama.enhancer.utils.auto_model.vram_needed_gb', return_value=None), \
                mock.patch('wama.common.utils.model_readiness.warn_if_weights_missing'), \
                mock.patch(INLINE_CONVERSION,
                           side_effect=self._convert), \
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            task.run(item.pk)
        item.refresh_from_db()
        return item


class MediaQueueTest(_TwoProcesses):

    def _run(self, item, **settings):
        return self._play(tasks.enhance_media, item,
                          'wama.enhancer.backends.media_backend.enhance_image',
                          # the draw returns a catalogue KEY since route F4b ⑤ (2026-10-06)
                          'wama.enhancer.utils.auto_model.resolve_media_model',
                          'enhancer:RealESRGANx4', **settings)

    def _item(self):
        item = Enhancement.objects.create(user=self.user, media_type='image', ai_model='auto',
                                          upscale_factor=4, status='RUNNING')
        item.input_file.save('photo.png', ContentFile(b'\x89PNG' + b'\0' * 16), save=True)
        return item

    def test_an_image_plays_both_processes_and_keeps_auto_in_its_setting(self):
        item = self._run(self._item())
        self.assertEqual('SUCCESS', item.status, item.error_message)
        self.assertEqual({'generate': 'SUCCESS', 'output': 'SUCCESS'}, self._states(item))
        self.assertEqual('enhancer:RealESRGANx4', process_runs.line(item, 'generate').model_key)
        self.assertEqual('auto', item.ai_model)
        self.assertEqual(item.output_file.name, process_runs.line(item, 'output').output_ref)
        self.assertEqual([], item.native_outputs)

    def test_changing_the_format_replays_the_output_alone_and_keeps_the_enhanced_original(self):
        item = self._run(self._item())
        item = self._run(item, output_format='webp')
        self.assertEqual('SUCCESS', item.status, item.error_message)
        self.assertEqual(1, self.calls, 'the image was NOT enhanced again')
        self.assertTrue(item.output_file.name.endswith('.webp'), item.output_file.name)
        self.assertTrue(item.native_outputs[0].endswith('.native.png'), item.native_outputs)
        self.assertEqual(len(b'enhanced>webp'), item.output_file_size, 'the size of the FINAL file')
        item = self._run(item, output_format='original')
        self.assertEqual(1, self.calls)
        self.assertEqual([], item.native_outputs)
        folder = os.path.dirname(os.path.join(self.root, item.output_file.name))
        self.assertEqual(1, len(os.listdir(folder)), os.listdir(folder))

    def test_changing_an_enhancement_setting_plays_the_engine_again(self):
        item = self._run(self._item(), output_format='webp')
        item = self._run(item, denoise=True)
        self.assertEqual(2, self.calls)
        self.assertTrue(item.output_file.name.endswith('.webp'))
        folder = os.path.dirname(os.path.join(self.root, item.output_file.name))
        self.assertEqual(2, len(os.listdir(folder)), os.listdir(folder))


class AudioQueueTest(_TwoProcesses):

    def _run(self, item, **settings):
        return self._play(tasks.enhance_audio, item,
                          'wama.enhancer.backends.audio_backend.enhance_audio',
                          # the draw returns a catalogue KEY since route F4b ⑤ (2026-10-07)
                          'wama.enhancer.utils.auto_model.resolve_audio_engine',
                          'enhancer:deepfilternet', **settings)

    def test_the_backend_receives_the_engine_identifier_and_the_file_name_carries_it(self):
        item = AudioEnhancement.objects.create(user=self.user, engine='auto', status='RUNNING')
        item.input_file.save('voice.wav', ContentFile(b'RIFF' + b'\0' * 16), save=True)
        item = self._run(item)
        self.assertEqual('SUCCESS', item.status, item.error_message)
        # The common engine reads `deepfilternet`; a key would be an unknown engine to it.
        self.assertEqual('deepfilternet', self.options['engine'])
        self.assertIn('deepfilternet', os.path.basename(item.output_file.name))
        self.assertNotIn('enhancer-deepfilternet', item.output_file.name)

    def test_the_audio_queue_has_the_same_two_processes(self):
        item = AudioEnhancement.objects.create(user=self.user, engine='auto', status='RUNNING')
        item.input_file.save('voice.wav', ContentFile(b'RIFF' + b'\0' * 16), save=True)
        item = self._run(item)
        self.assertEqual('SUCCESS', item.status, item.error_message)
        self.assertEqual({'generate': 'SUCCESS', 'output': 'SUCCESS'}, self._states(item))
        item = self._run(item, output_format='mp3')
        self.assertEqual(1, self.calls, 'the audio was NOT restored again')
        self.assertTrue(item.output_file.name.endswith('.mp3'), item.output_file.name)
        self.assertTrue(item.native_outputs[0].endswith('.native.wav'), item.native_outputs)


class TheCardsShowTheirProcessesTest(TestCase):

    def setUp(self):
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        self.user = get_user_model().objects.create_user('enhancer_strip', password='x')
        for role in (DEFAULT_APP_ACCESS.get('enhancer') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(self.user)

    def test_both_cards_show_the_strip_and_the_bounded_route_refuses_an_unknown_process(self):
        from django.urls import reverse
        media = Enhancement.objects.create(user=self.user, media_type='image',
                                           input_file='x/photo.png')
        audio = AudioEnhancement.objects.create(user=self.user, input_file='x/voice.wav')
        for name, item in (('enhancer:card_html', media), ('enhancer:audio_card_html', audio)):
            html = self.client.get(reverse(name, args=[item.pk])).content.decode()
            for key in ('generate', 'output'):
                self.assertRegex(html, rf'wcv3-proc-run"[^>]*data-id="{item.pk}"[^>]*data-process="{key}"')
            self.assertIn('data-element-status="PENDING"', html)
        r = self.client.post(reverse('enhancer:start_process', args=[media.pk, 'mix']))
        self.assertEqual(400, r.status_code)
        r = self.client.post(reverse('enhancer:audio_start_process', args=[audio.pk, 'mix']))
        self.assertEqual(400, r.status_code)
        with mock.patch.object(tasks.enhance_media, 'apply_async',
                               return_value=mock.Mock(id='t-1')) as sent:
            r = self.client.post(reverse('enhancer:start_process', args=[media.pk, 'output']),
                                 data='{}', content_type='application/json')
        self.assertEqual(200, r.status_code, r.content)
        self.assertEqual({'process': 'output'}, sent.call_args.kwargs.get('kwargs'))

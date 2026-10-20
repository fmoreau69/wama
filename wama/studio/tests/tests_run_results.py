"""⬇ les RÉSULTATS d'un run du Studio (2026-10-20) : le bout de chaque branche, en un ZIP écrit par
l'écrivain du « ⬇ Télécharger tout » de la file — des natures différentes, chacune dans son format.

Avant, un run ne se téléchargeait pas : ses cards étaient à aller chercher, une par une, dans les
files de leurs apps.
"""
import io
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings

from wama.common.models import JOB_SUCCESS


def _names(response):
    blob = b''.join(response.streaming_content) if response.streaming else response.content
    return sorted(zipfile.ZipFile(io.BytesIO(blob)).namelist())


class BranchEndsTest(TestCase):

    def test_the_ends_are_the_processes_nothing_leaves_but_towards_an_output(self):
        from wama.studio.services.run_results import branch_ends
        graph = {'nodes': [{'id': 'src', 'app': 'media_import'}, {'id': 'a', 'app': 'converter'},
                           {'id': 'b', 'app': 'describer'}, {'id': 'c', 'app': 'imager'},
                           {'id': 'out', 'app': 'studio_output'}],
                 'links': [{'from': 'src', 'to': 'a'}, {'from': 'a', 'to': 'b'},
                           {'from': 'b', 'to': 'out'}]}
        # `a` feeds a process : intermediate. `b` only feeds an output : an end. The source and
        # the output are not processes.
        self.assertEqual(['b', 'c'], [n['id'] for n in branch_ends(graph)])


class RunZipTest(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp(prefix='wama_run_zip_')
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        from wama.common.services.nightly_tests import get_test_user
        self.user = get_test_user()
        # A test account that GOES THROUGH the Studio's gate (its declared roles), never a superuser.
        for role in (DEFAULT_APP_ACCESS.get('studio') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client = Client()
        self.client.force_login(self.user)

    def _run(self, graph, states):
        from wama.studio.models import StudioRun
        return StudioRun.objects.create(user=self.user, graph=graph, node_states=states,
                                        status=JOB_SUCCESS)

    def test_the_run_zip_holds_each_branch_end_in_its_own_nature(self):
        from wama.describer.models import Description
        from wama.imager.models import ImageGeneration
        video = ImageGeneration.objects.create(user=self.user, prompt='un chien', status='SUCCESS',
                                               generation_mode='txt2vid')
        video.output_video.save('chien.mp4', ContentFile(b'MP4'))
        middle = ImageGeneration.objects.create(user=self.user, prompt='un chat', status='SUCCESS',
                                                generation_mode='txt2vid')
        middle.output_video.save('chat.mp4', ContentFile(b'MP4'))
        text = Description.objects.create(user=self.user, filename='photo.jpg', status='SUCCESS',
                                          result_text='une description')
        graph = {'nodes': [{'id': 'm', 'app': 'imager'}, {'id': 'v', 'app': 'imager'},
                           {'id': 'd', 'app': 'describer'},
                           {'id': 'f', 'app': 'function:some.pure_function'},
                           {'id': 'out', 'app': 'studio_output'}],
                 'links': [{'from': 'm', 'to': 'd'}, {'from': 'v', 'to': 'out'}]}
        run = self._run(graph, {
            'm': {'status': JOB_SUCCESS, 'item_id': middle.pk},
            'v': {'status': JOB_SUCCESS, 'item_id': video.pk},
            'd': {'status': JOB_SUCCESS, 'item_id': text.pk},
            'f': {'status': JOB_SUCCESS, 'output': 'table · 3 ligne(s) · a, b'},
            'out': {'status': JOB_SUCCESS, 'output': 'médiathèque : « chien »'}})
        response = self.client.get(f'/studio/api/run/{run.pk}/download/')
        self.assertEqual(200, response.status_code)
        names = _names(response)
        self.assertEqual(2, len(names), names)
        self.assertEqual({'.mp4', '.txt'}, {Path(n).suffix for n in names})
        self.assertNotIn('chat', ' '.join(names), 'an INTERMEDIATE card went into the run ZIP')
        # The data computed in memory is NAMED as not kept, never silently dropped.
        status = self.client.get(f'/studio/api/run/{run.pk}/').json()
        self.assertEqual(2, status['results']['count'])
        self.assertEqual(['f'], [m['node'] for m in status['results']['missing']])

    def test_a_file_output_is_taken_only_when_the_account_can_read_it(self):
        from wama.studio.services.run_results import run_results
        own = Path(self.media) / 'users' / str(self.user.pk) / 'temp' / 'mesh.glb'
        own.parent.mkdir(parents=True)
        own.write_bytes(b'GLB')
        other = Path(self.media) / 'users' / str(self.user.pk + 1000) / 'temp' / 'mesh.glb'
        other.parent.mkdir(parents=True)
        other.write_bytes(b'GLB')
        graph = {'nodes': [{'id': 'g', 'app': 'function:some.job'},
                           {'id': 'h', 'app': 'function:some.job'}], 'links': []}
        rel = lambda p: p.relative_to(self.media).as_posix()
        run = self._run(graph, {'g': {'status': JOB_SUCCESS, 'output': rel(own)},
                                'h': {'status': JOB_SUCCESS, 'output': rel(other)}})
        # The executor's writing : the node's EXECUTION LINE designates its file (`output_ref`).
        from wama.common.services import process_runs
        for node_id, path in (('g', own), ('h', other)):
            process_runs.succeed(run, node_id, process_key='some.job', output_ref=rel(path))
        results, missing = run_results(run, self.user)
        self.assertEqual([own.resolve()], [r['path'].resolve() for r in results])
        self.assertEqual(['h'], [m['node'] for m in missing])
        # Counter-test : a node whose line designates no file has nothing to give, whatever its
        # canvas label says.
        process_runs.succeed(run, 'g', process_key='some.job', output_ref='')
        self.assertEqual([], run_results(run, self.user)[0])

    def test_a_card_step_at_a_branch_end_gives_its_card(self):
        """A step node (`function:<app>.<step>`) launched the step OF A CARD : its result is that
        card, read by the step's app — not the label of the node."""
        from wama.studio.services.run_results import run_results
        from wama.transcriber.models import Transcript
        item = Transcript.objects.create(user=self.user, status='SUCCESS', text='bonjour',
                                         summary='un résumé')
        run = self._run({'nodes': [{'id': 's', 'app': 'function:transcriber.summarize'}],
                         'links': []},
                        {'s': {'status': JOB_SUCCESS, 'item_id': item.pk, 'output': 'un résumé'}})
        results, missing = run_results(run, self.user)
        self.assertEqual([(Transcript, item.pk)], [(r['model'], r['item'].pk) for r in results])
        self.assertEqual([], missing)

    def test_the_requested_format_reaches_a_late_binding_app_as_in_the_queue(self):
        from unittest import mock
        from wama.common.utils import export_formats
        from wama.describer.models import Description
        item = Description.objects.create(user=self.user, filename='photo.jpg', status='SUCCESS',
                                          result_text='une description')
        run = self._run({'nodes': [{'id': 'd', 'app': 'describer'}], 'links': []},
                        {'d': {'status': JOB_SUCCESS, 'item_id': item.pk}})
        with mock.patch.object(export_formats, 'export_builder_for',
                               lambda app: lambda element, fmt: (fmt, b'rendu')):
            response = self.client.get(f'/studio/api/run/{run.pk}/download/', {'format': 'docx'})
        self.assertEqual(['.docx'], [Path(n).suffix for n in _names(response)])

    def test_a_failed_run_gives_its_successful_ends_and_a_running_one_nothing_yet(self):
        from wama.describer.models import Description
        from wama.studio.models import StudioRun
        done = Description.objects.create(user=self.user, filename='a.jpg', status='SUCCESS',
                                          result_text='a')
        graph = {'nodes': [{'id': 'ok', 'app': 'describer'}, {'id': 'ko', 'app': 'describer'}],
                 'links': []}
        run = self._run(graph, {'ok': {'status': JOB_SUCCESS, 'item_id': done.pk},
                                'ko': {'status': 'FAILURE', 'error': 'échec'}})
        StudioRun.objects.filter(pk=run.pk).update(status='FAILURE')
        self.assertEqual(1, self.client.get(f'/studio/api/run/{run.pk}/').json()['results']['count'])
        StudioRun.objects.filter(pk=run.pk).update(status='RUNNING')
        self.assertNotIn('results', self.client.get(f'/studio/api/run/{run.pk}/').json(),
                         'the results are read while the run is still polling')

    def test_the_page_offers_the_queue_download_button_and_its_switch(self):
        page = self.client.get('/studio/').content.decode('utf-8', errors='replace')
        self.assertIn('id="studioRunDownload"', page)
        self.assertIn('data-queue-download', page)
        self.assertIn('common/js/wama-global-progress.js', page)

    def test_a_run_without_results_says_so_and_another_account_sees_nothing(self):
        run = self._run({'nodes': [{'id': 'f', 'app': 'function:some.pure_function'}],
                         'links': []},
                        {'f': {'status': JOB_SUCCESS, 'output': 'table · 1 ligne(s)'}})
        response = self.client.get(f'/studio/api/run/{run.pk}/download/')
        self.assertEqual(404, response.status_code)
        self.assertEqual(['f'], [m['node'] for m in response.json()['missing']])
        from django.contrib.auth.models import User
        stranger = User.objects.create_user('run_zip_stranger', password='x')
        for group in self.user.groups.all():
            stranger.groups.add(group)
        other = Client()
        other.force_login(stranger)
        self.assertEqual(404, other.get(f'/studio/api/run/{run.pk}/download/').status_code)

"""The media INPUT CARDS of the Studio, and the LOT (Fabien's decision, 2026-10-20 —
`STUDIO_VISION §Entrées du Studio`).

The input card of an app (card v4) is rendered in the Studio: a UNIVERSAL card that takes the shape
of the card of the app it feeds, and SIMPLIFIED cards (work files, reference files, lot file). They
designate — nothing enters a queue while composing. Several work files OR a lot file make a lot,
and the pipeline runs once per element: each element is a child run, and the cards of each app
node are gathered into one lot of its queue.
"""
import importlib.util
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock, skipUnless

from django.conf import settings
from django.contrib.auth.models import Group
from django.test import Client, SimpleTestCase, TestCase, override_settings

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None

#: The ports of the avatarizer node as the REAL catalogue gives them (measured on 2026-10-20) — the
#: test database has no model, so `studio_node_ports` would fall back to its generic derivation.
AVATAR_PORTS = [
    {'id': 'prompt', 'label': 'Prompt', 'group': 'prompt', 'types': ['prompt'], 'required': False,
     'one_of': ['work_audio']},
    {'id': 'work_audio', 'label': 'Audio', 'group': 'travail', 'types': ['audio'],
     'required': False, 'one_of': ['prompt']},
    {'id': 'work_image', 'label': 'Image', 'group': 'travail', 'types': ['image'], 'required': True},
    {'id': 'work_object3d', 'label': 'Objet 3D', 'group': 'travail', 'types': ['3d'],
     'required': False},
]


def _avatar_ports():
    """`studio_node_ports` giving the avatarizer its real ports, every other app unchanged."""
    from wama.common import app_registry
    real = app_registry.studio_node_ports

    def ports(app_id):
        if app_id == 'avatarizer':
            return {'inputs': [dict(p) for p in AVATAR_PORTS],
                    'output': {'id': 'out', 'label': 'Sortie', 'types': ['video']}}
        return real(app_id)
    return mock.patch.object(app_registry, 'studio_node_ports', ports)


class _MediaCase(TestCase):
    """A throwaway MEDIA_ROOT and a test account that goes through the Studio's gate."""

    def setUp(self):
        self.media = tempfile.mkdtemp(prefix='wama_entries_')
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        from wama.common.services.nightly_tests import get_test_user
        self.user = get_test_user()
        roles = set()
        for app in ('studio', 'describer', 'anonymizer', 'avatarizer'):
            roles |= set((DEFAULT_APP_ACCESS.get(app) or {}).get('roles', []))
        for role in roles:
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])

    def own(self, name, content=b'x'):
        """A file in the test account's own space — the rel path a designation carries."""
        path = Path(self.media) / 'users' / str(self.user.pk) / 'temp' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path.relative_to(self.media).as_posix()

    def foreign(self, name):
        path = Path(self.media) / 'users' / str(self.user.pk + 1000) / 'temp' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x')
        return path.relative_to(self.media).as_posix()


# ── Common bricks ────────────────────────────────────────────────────────────────────────────

class CheckDesignationTest(_MediaCase):

    def test_a_designation_is_checked_by_the_rule_of_designate_without_copying(self):
        from wama.common.utils.media_paths import InputRefused, check_designation
        mine = self.own('a.png')
        self.assertEqual(mine, check_designation(mine, self.user))
        with self.assertRaises(InputRefused):
            check_designation(self.foreign('b.png'), self.user)
        with self.assertRaisesRegex(InputRefused, 'introuvable'):
            check_designation('users/x/nope.png', self.user)
        # Nothing was pointed or copied: the user's tree holds only what the test wrote.
        written = sorted(p.name for p in (Path(self.media) / 'users' / str(self.user.pk)).rglob('*')
                         if p.is_file())
        self.assertEqual(['a.png'], written)


class DownloadToUserTest(_MediaCase):

    def test_a_url_lands_in_the_user_space_as_a_deposited_file(self):
        from wama.common.utils import source_ingest

        def fake_download(url, mode, dest):
            path = os.path.join(dest, 'clip.mp3')
            Path(path).write_bytes(b'ID3')
            fake_download.mode = mode
            return path, 'titre'
        with mock.patch.object(source_ingest, '_download', fake_download):
            rel = source_ingest.download_to_user(self.user, 'https://exemple.org/clip', 'audio')
        self.assertTrue(rel.startswith(f'users/{self.user.pk}/temp/'), rel)
        self.assertTrue((Path(self.media) / rel).is_file())
        self.assertEqual('audio', fake_download.mode)
        from wama.filemanager.models import UserFile
        self.assertTrue(UserFile.objects.filter(user=self.user, file=rel).exists(),
                        'the file shows in the file manager, like a deposit')

    def test_a_path_is_not_a_url_to_download(self):
        from wama.common.utils.source_ingest import download_to_user
        with self.assertRaises(ValueError):
            download_to_user(self.user, 'users/1/temp/a.mp3')


class DeclaredModeTest(SimpleTestCase):

    def test_the_mode_of_a_url_is_the_one_the_app_states(self):
        """Read from `WAMA_INGEST`, never re-derived from a nature: the describer keeps a web page
        (`smart`), the transcriber takes the audio of a platform (`audio`) — a nature table gave
        the describer `media` (multi-nature port), and a page would have been fetched as a file."""
        from wama.common.utils.source_ingest import declared_mode
        from wama.describer.models import Description
        from wama.studio.models import StudioRun
        from wama.transcriber.models import Transcript
        self.assertEqual('smart', declared_mode(Description))
        self.assertEqual('audio', declared_mode(Transcript))
        self.assertEqual('media', declared_mode(StudioRun), 'nothing declared: the file as is')


class BatchLinesTest(SimpleTestCase):

    def test_every_family_gives_the_normalised_lines(self):
        from wama.common.utils.batch_parsers import parse_batch_lines
        tags, _w = parse_batch_lines('-i a.wav -p "bonjour" --speed 1.2\n-i b.wav\n')
        self.assertEqual(['a.wav', 'b.wav'], [l['input'] for l in tags])
        self.assertEqual({'speed': '1.2'}, tags[0]['options'])
        prompts, _w = parse_batch_lines('un chat\n# commentaire\nun chien\n', plain_as='prompt')
        self.assertEqual(['un chat', 'un chien'], [l['prompt'] for l in prompts])
        media, _w = parse_batch_lines('users/1/a.png\nhttps://x.org/b.jpg\n')
        self.assertEqual(['users/1/a.png', 'https://x.org/b.jpg'], [l['input'] for l in media])
        prose, warnings = parse_batch_lines('ceci est une phrase\n')
        self.assertEqual([], prose)
        self.assertTrue(warnings, 'prose is not a list of files — and it is SAID')


class LineToPortsTest(SimpleTestCase):

    def test_roles_go_to_the_port_of_their_group(self):
        from wama.common.utils.batch_parsers import line_to_ports
        ports, settings_ = line_to_ports(
            {'input': 'a.wav', 'reference': 'avatar.png', 'prompt': 'salut',
             'options': {'quality_mode': 'high'}, 'line_num': 3}, AVATAR_PORTS)
        self.assertEqual({'work_audio': 'a.wav', 'work_image': 'avatar.png', 'prompt': 'salut'},
                         ports)
        self.assertEqual({'quality_mode': 'high'}, settings_, 'other options are SETTINGS')

    def test_a_column_named_after_a_port_goes_to_that_port(self):
        from wama.common.utils.batch_parsers import line_to_ports
        ports, settings_ = line_to_ports(
            {'reference': 'role.png', 'options': {'work_image': 'named.png'}}, AVATAR_PORTS)
        self.assertEqual('named.png', ports['work_image'], 'the port name wins over the role alias')
        self.assertEqual({}, settings_)

    def test_a_role_without_a_port_is_refused_by_its_name(self):
        from wama.common.utils.batch_parsers import line_to_ports
        only_work = [{'id': 'work_file', 'group': 'travail', 'types': ['image']}]
        with self.assertRaisesRegex(ValueError, 'prompt'):
            line_to_ports({'prompt': 'x', 'line_num': 2}, only_work)


class LotOverviewTest(SimpleTestCase):

    def test_the_rule_of_an_app_lot_extracted_once(self):
        from wama.common.utils.batch_views import lot_overview
        self.assertEqual('SUCCESS', lot_overview(['SUCCESS', 'SUCCESS'])[1])
        self.assertEqual('RUNNING', lot_overview(['SUCCESS', 'RUNNING'])[1])
        self.assertEqual('FAILURE', lot_overview(['SUCCESS', 'FAILURE'])[1])
        self.assertEqual('PENDING', lot_overview(['FAILURE', 'PENDING'])[1],
                         'something still waits: not a failure yet')
        counts, _s = lot_overview(['SUCCESS', 'FAILURE', 'PENDING'])
        self.assertEqual((1, 1, 1), (counts['success'], counts['failure'], counts['pending']))

    def test_the_app_batch_status_view_reads_the_extracted_rule(self):
        source = (Path(settings.BASE_DIR) / 'wama' / 'common' / 'utils' / 'batch_views.py'
                  ).read_text(encoding='utf-8')
        body = source[source.index('def batch_status(request, pk):'):]
        body = body[:body.index('return JsonResponse')]
        self.assertIn('lot_overview(', body)
        self.assertNotIn("overall = 'SUCCESS'", body, 'a second copy of the rule')


# ── The lot unfolded at launch ───────────────────────────────────────────────────────────────

def _graph(source, target='describer', port='work_file', target_params=None):
    return {'nodes': [source, {'id': 't', 'app': target, 'params': target_params or {}}],
            'links': [{'from': source['id'], 'to': 't', 'to_port': port}]}


class LotGraphsTest(_MediaCase):

    def test_several_work_files_are_one_graph_per_file(self):
        from wama.studio.services.entries import lot_graphs
        refs = [self.own('a.png'), self.own('b.png'), 'https://exemple.org/c.png']
        graphs = lot_graphs(self.user, _graph({'id': 's', 'app': 'media_import',
                                               'params': {'entry': {'files': refs}}}))
        self.assertEqual([[r] for r in refs],
                         [g['nodes'][0]['params']['entry']['files'] for g in graphs])

    def test_one_file_unfolds_nothing(self):
        from wama.studio.services.entries import lot_graphs
        graph = _graph({'id': 's', 'app': 'media_import',
                        'params': {'entry': {'files': [self.own('a.png')]}}})
        self.assertEqual([], lot_graphs(self.user, graph))

    def test_a_lot_file_fills_whole_cards_and_its_settings_reach_the_app_node(self):
        from wama.studio.services.entries import CARD_PORT_ID, lot_graphs
        lot = self.own('lot.txt', b'-i a.wav -r avatar.png --bbox_shift 5\n-i b.wav\n')
        graph = _graph({'id': 's', 'app': 'batch_input', 'params': {'entry': {'lot': lot}}},
                       target='avatarizer', port=CARD_PORT_ID)
        with _avatar_ports():
            graphs = lot_graphs(self.user, graph)
        self.assertEqual(2, len(graphs))
        first = graphs[0]['nodes'][0]['params']['entry']
        self.assertEqual(['a.wav'], first['ports']['work_audio'])
        self.assertEqual(['avatar.png'], first['ports']['work_image'])
        self.assertEqual('5', graphs[0]['nodes'][1]['params']['bbox_shift'])
        self.assertNotIn('bbox_shift', graphs[1]['nodes'][1]['params'],
                         'a line setting is for ITS element only')

    def test_a_lot_file_of_one_line_is_unfolded_into_one_graph(self):
        from wama.studio.services.entries import CARD_PORT_ID, lot_graphs
        lot = self.own('one.txt', b'-i a.wav\n')
        graph = _graph({'id': 's', 'app': 'batch_input', 'params': {'entry': {'lot': lot}}},
                       target='avatarizer', port=CARD_PORT_ID)
        with _avatar_ports():
            graphs = lot_graphs(self.user, graph)
        self.assertEqual(1, len(graphs))
        self.assertNotIn('lot', graphs[0]['nodes'][0]['params']['entry'])

    def test_the_output_name_of_a_line_goes_with_its_element_without_any_folder(self):
        """`-o` names the element (`BATCH_FORMAT.md`: the NAME is honoured, not yet the
        destination) — a folder in it would become a path inside the run ZIP, `..` included."""
        from wama.studio.services.entries import CARD_PORT_ID, element_output, lot_graphs
        lot = self.own('named.txt', b'-i a.wav -o "intro.wav"\n'
                                    b'-i b.wav -o "../../ailleurs/fin"\n-i c.wav\n')
        graph = _graph({'id': 's', 'app': 'batch_input', 'params': {'entry': {'lot': lot}}},
                       target='avatarizer', port=CARD_PORT_ID)
        with _avatar_ports():
            graphs = lot_graphs(self.user, graph)
        self.assertEqual(['intro.wav', 'fin', ''], [element_output(g) for g in graphs])
        self.assertNotIn('output', graphs[2]['nodes'][0]['params']['entry'])
        self.assertEqual('', element_output(graph), 'the lot run itself names nothing')

    def test_what_cannot_be_played_is_refused_before_anything_runs(self):
        from wama.studio.services.entries import CARD_PORT_ID, lot_graphs
        unknown = self.own('bad.txt', b'-i a.wav --nope 1\n-i b.wav\n')
        cases = [
            (_graph({'id': 's', 'app': 'batch_input', 'params': {'entry': {'lot': unknown}}},
                    target='avatarizer', port=CARD_PORT_ID), 'nope'),
            (_graph({'id': 's', 'app': 'batch_input',
                     'params': {'entry': {'lot': self.foreign('x.txt')}}},
                    target='avatarizer', port=CARD_PORT_ID), 'non accessible'),
            (_graph({'id': 's', 'app': 'card_input',
                     'params': {'entry': {'ports': {'work_image': ['a.png', 'b.png']}}}},
                    target='avatarizer', port=CARD_PORT_ID), 'work_image'),
        ]
        two_lots = _graph({'id': 's', 'app': 'media_import',
                           'params': {'entry': {'files': ['a', 'b']}}})
        two_lots['nodes'].append({'id': 's2', 'app': 'reference_input',
                                  'params': {'entry': {'files': ['c', 'd']}}})
        cases.append((two_lots, 'Deux lots'))
        for graph, said in cases:
            with self.subTest(said=said):
                with self.assertRaisesRegex(ValueError, said), _avatar_ports():
                    lot_graphs(self.user, graph)


class LaunchLotTest(_MediaCase):

    def test_the_launch_creates_one_child_run_per_element(self):
        from wama.studio.services.launch import launch_graph
        graph = _graph({'id': 's', 'app': 'media_import',
                        'params': {'entry': {'files': [self.own('a.png'), self.own('b.png')]}}})
        with mock.patch('wama.studio.tasks.run_pipeline_task.delay',
                        return_value=mock.Mock(id='t')) as delay:
            run, error = launch_graph(self.user, graph)
        self.assertIsNone(error)
        self.assertEqual(2, run.elements.count())
        delay.assert_called_once_with(run.pk)
        self.assertEqual(graph, run.graph, 'the lot run keeps the graph the canvas shows')

    def test_a_refused_lot_launches_nothing(self):
        from wama.studio.models import StudioRun
        from wama.studio.services.launch import launch_graph
        graph = _graph({'id': 's', 'app': 'media_import',
                        'params': {'entry': {'files': ['a', 'b']}}})
        graph['nodes'].append({'id': 's2', 'app': 'reference_input',
                               'params': {'entry': {'files': ['c', 'd']}}})
        with mock.patch('wama.studio.tasks.run_pipeline_task.delay') as delay:
            run, error = launch_graph(self.user, graph)
        self.assertIsNone(run)
        self.assertIn('Deux lots', error)
        delay.assert_not_called()
        self.assertFalse(StudioRun.objects.filter(user=self.user).exists())


# ── The engine ───────────────────────────────────────────────────────────────────────────────

class _FakeApp:
    """A runner that records what each card receives — the app node's contract, nothing more."""

    def __init__(self):
        self.created = []

    def runner(self):
        def create(user, inputs, params):
            self.created.append(dict(inputs))
            return 100 + len(self.created)
        return {'create': create, 'start': lambda user, item_id: None,
                'poll': lambda user, item_id: {'status': 'SUCCESS', 'progress': 100,
                                               'output': f'users/{user.pk}/out/{item_id}.txt',
                                               'is_text': False},
                'output_type': 'document'}


class EngineLotTest(_MediaCase):

    def _play(self, graph, app):
        from wama.studio.services.launch import launch_graph
        from wama.studio.tasks import run_pipeline_task
        fake = _FakeApp()
        with mock.patch('wama.studio.tasks.run_pipeline_task.delay', return_value=mock.Mock(id='t')):
            run, error = launch_graph(self.user, graph)
        self.assertIsNone(error)
        with mock.patch('wama.studio.services.runners.runner_for',
                        lambda key: fake.runner() if key == app else None), \
                mock.patch('wama.studio.tasks.POLL_INTERVAL_S', 0), \
                mock.patch('wama.common.utils.queue_manipulation.consolidate_arrival') as gather:
            run_pipeline_task(run.pk)
        run.refresh_from_db()
        return run, fake, gather

    def test_the_pipeline_runs_once_per_element_and_the_cards_form_one_lot(self):
        files = [self.own('a.png'), self.own('b.png'), self.own('c.png')]
        run, fake, gather = self._play(
            _graph({'id': 's', 'app': 'media_import', 'params': {'entry': {'files': files}}}),
            'describer')
        self.assertEqual('SUCCESS', run.status, run.error_message)
        self.assertEqual(files, [c['work_file'] for c in fake.created])
        self.assertEqual(['SUCCESS'] * 3, [e.status for e in run.elements.order_by('pk')])
        from wama.describer.models import Description
        gather.assert_called_once_with(Description, [101, 102, 103], self.user)

    def test_a_universal_card_unfolds_onto_the_ports_and_its_url_is_fetched_by_nature(self):
        from wama.studio.services.entries import CARD_PORT_ID
        image = self.own('avatar.png')
        entry = {'ports': {'work_image': [image], 'work_audio': ['https://exemple.org/voix']}}
        fetched = []

        def download(user, url, mode):
            fetched.append((url, mode))
            return self.own('voix.mp3')
        with mock.patch('wama.common.utils.source_ingest.download_to_user', download),                 _avatar_ports():
            run, fake, _gather = self._play(
                _graph({'id': 's', 'app': 'card_input', 'params': {'entry': entry}},
                       target='avatarizer', port=CARD_PORT_ID), 'avatarizer')
        self.assertEqual('SUCCESS', run.status, run.error_message)
        received = fake.created[0]
        self.assertEqual(image, received['work_image'])
        self.assertEqual([('https://exemple.org/voix', 'audio')], fetched,
                         'the URL is downloaded AT LAUNCH, in the nature of its port')
        self.assertEqual(received['work_audio'], received['audio'],
                         'the principal entry is also found by its nature')

    def test_a_url_sent_to_an_app_is_fetched_in_the_mode_it_states(self):
        fetched = []

        def download(user, url, mode):
            fetched.append(mode)
            return self.own('page.html')
        with mock.patch('wama.common.utils.source_ingest.download_to_user', download):
            run, _fake, _gather = self._play(
                _graph({'id': 's', 'app': 'media_import',
                        'params': {'entry': {'files': ['https://exemple.org/article']}}}),
                'describer')
        self.assertEqual('SUCCESS', run.status, run.error_message)
        self.assertEqual(['smart'], fetched)

    def test_a_failed_element_does_not_stop_the_others(self):
        from wama.studio.services.launch import launch_graph
        from wama.studio.tasks import run_pipeline_task
        graph = _graph({'id': 's', 'app': 'media_import',
                        'params': {'entry': {'files': [self.own('a.png'), self.own('b.png')]}}})
        with mock.patch('wama.studio.tasks.run_pipeline_task.delay', return_value=mock.Mock(id='t')):
            run, _e = launch_graph(self.user, graph)
        calls = []

        def create(user, inputs, params):
            calls.append(inputs['work_file'])
            if len(calls) == 1:
                raise ValueError('panne du premier')
            return 7
        runner = {'create': create, 'start': lambda u, i: None,
                  'poll': lambda u, i: {'status': 'SUCCESS', 'output': 'x.txt', 'progress': 100},
                  'output_type': 'document'}
        with mock.patch('wama.studio.services.runners.runner_for',
                        lambda key: runner if key == 'describer' else None), \
                mock.patch('wama.studio.tasks.POLL_INTERVAL_S', 0):
            run_pipeline_task(run.pk)
        run.refresh_from_db()
        self.assertEqual(2, len(calls))
        self.assertEqual('FAILURE', run.status)
        self.assertIn('1/2', run.error_message)
        self.assertIn('panne du premier', run.error_message)

    def test_the_status_of_a_lot_run_sums_up_its_elements(self):
        files = [self.own('a.png'), self.own('b.png')]
        run, _fake, _gather = self._play(
            _graph({'id': 's', 'app': 'media_import', 'params': {'entry': {'files': files}}}),
            'describer')
        client = Client()
        client.force_login(self.user)
        data = client.get(f'/studio/api/run/{run.pk}/').json()
        self.assertEqual({'total': 2, 'done': 2, 'failed': 0, 'current': None}, data['lot'])
        self.assertEqual({'status': 'SUCCESS', 'done': 2, 'total': 2}, data['node_states']['t'])


class UnfoldTest(_MediaCase):

    def test_a_text_is_never_downloaded_even_if_it_starts_with_an_address(self):
        from wama.studio.services.entries import unfold
        inputs = {}
        with mock.patch('wama.common.utils.source_ingest.download_to_user') as download:
            unfold(self.user, 'imager', 'prompt',
                   {'type': 'prompt', 'value': 'https://exemple.org un chat'}, inputs)
        download.assert_not_called()
        self.assertEqual('https://exemple.org un chat', inputs['prompt'])

    def test_a_port_fed_twice_is_refused_instead_of_overwritten(self):
        from wama.common.app_registry import studio_node_ports
        from wama.studio.services.entries import unfold
        work = studio_node_ports('describer')['inputs'][0]['id']    # read, never supposed
        inputs = {}
        unfold(self.user, 'describer', 'card',
               {'type': 'card', 'is_card': True, 'value': {work: self.own('a.png')}}, inputs)
        with self.assertRaisesRegex(ValueError, 'deux fois'):
            unfold(self.user, 'describer', work, {'type': 'image', 'value': self.own('b.png')},
                   inputs)

    def test_a_card_port_the_app_does_not_have_is_refused(self):
        from wama.studio.services.entries import unfold
        with self.assertRaisesRegex(ValueError, 'reference_ghost'):
            unfold(self.user, 'describer', 'card',
                   {'type': 'card', 'is_card': True, 'value': {'reference_ghost': 'a.png'}}, {})


class LegacyMediaImportTest(_MediaCase):

    def test_an_old_graph_still_reads_its_file_and_its_owner_is_checked(self):
        from wama.common.manifests.builtin.pipeline import builtin_node
        source = builtin_node('media_import')
        self.assertEqual(('image', self.own('a.png')),
                         source.run(self.user, {'asset_path': self.own('a.png')}))
        with self.assertRaisesRegex(ValueError, 'non accessible'):
            source.run(self.user, {'asset_path': self.foreign('b.png')})

    def test_a_work_files_card_feeding_a_function_still_picks_its_media(self):
        """Towards a FUNCTION or the Output there is no app card to render in the modal: the
        library picker stays — hiding it left no way to choose a file (caught on 2026-10-20)."""
        from wama.studio.services.node_params import node_schema
        kinds = {p['name']: p['type'] for p in node_schema('media_import')['params']}
        self.assertEqual({'entry': 'hidden', 'asset_path': 'media_picker'}, kinds)


# ── The surfaces ─────────────────────────────────────────────────────────────────────────────

class PaletteAndInspectorTest(_MediaCase):

    def test_app_nodes_receive_the_card_port_that_the_card_v4_never_shows(self):
        from wama.common.app_registry import studio_node_ports
        from wama.studio.services.entries import CARD_PORT_ID
        from wama.studio.services.palette import palette_nodes
        nodes = palette_nodes(self.user)
        self.assertIn(CARD_PORT_ID, [p['id'] for p in nodes['describer']['inputs']])
        self.assertNotIn(CARD_PORT_ID, [p['id'] for p in studio_node_ports('describer')['inputs']],
                         'the derived port does not leak into the card v4 tabs nor the manifests')

    def test_media_and_data_inputs_name_their_world(self):
        from wama.studio.services.palette import palette_nodes
        nodes = palette_nodes(self.user)
        for key in ('text_input', 'card_input', 'media_import', 'reference_input', 'batch_input'):
            self.assertEqual('media', nodes[key]['world'], key)
        for key in ('dataset_input', 'data_connector'):
            self.assertEqual('data', nodes[key]['world'], key)
        from wama.common.app_registry import WORLD_SECTIONS
        self.assertEqual(WORLD_SECTIONS['media']['label'], nodes['card_input']['world_label'],
                         'the label of a world is the one the worlds declare')

    def test_the_input_sections_follow_the_order_the_worlds_set(self):
        from wama.common.app_registry import WORLD_SECTIONS
        from wama.studio.services.palette import palette_nodes
        worlds = []
        for meta in palette_nodes(self.user).values():
            if meta.get('kind') == 'source' and meta['world'] and meta['world'] not in worlds:
                worlds.append(meta['world'])
        self.assertEqual(sorted(worlds, key=lambda w: WORLD_SECTIONS[w]['order']), worlds)
        self.assertEqual(['media', 'data'], worlds)

    def test_each_input_card_states_what_its_modal_shows(self):
        from wama.studio.services.palette import palette_nodes
        nodes = palette_nodes(self.user)
        self.assertEqual({'card_input': 'card', 'batch_input': 'lot', 'media_import': 'files',
                          'reference_input': 'files', 'text_input': '', 'dataset_input': ''},
                         {k: nodes[k]['compose'] for k in ('card_input', 'batch_input',
                          'media_import', 'reference_input', 'text_input', 'dataset_input')})

    def test_what_a_universal_card_fills_shows_provided_on_the_app_node(self):
        from wama.studio.services.entries import CARD_PORT_ID
        from wama.studio.services.graph_flow import node_context
        graph = _graph({'id': 's', 'app': 'card_input',
                        'params': {'entry': {'ports': {'work_audio': ['users/1/temp/a.wav']},
                                             'prompt': 'bonjour'}}},
                       target='avatarizer', port=CARD_PORT_ID)
        with _avatar_ports():
            context = node_context(graph, 't', self.user)
        self.assertEqual(['audio'], context['inputs']['work_audio']['types'])
        self.assertEqual('bonjour', context['values'].get('text_content'),
                         'the text to say is PROVIDED by the card, not typed on the node')


class CardMatchTest(SimpleTestCase):
    """The input ↔ model matching of an app's card shown NEXT TO its generated panel (2026-10-21):
    the model select of the schema, and only the ports it JUDGES."""

    PORTS = [{'id': 'prompt', 'group': 'prompt'}, {'id': 'work_file', 'group': 'travail'},
             {'id': 'work_audio', 'group': 'travail'}]

    def _match(self, meta, field={'name': 'model'}):
        from wama.common.utils import auto_model, input_match
        with mock.patch.object(auto_model, 'catalog_field', lambda app: field), \
                mock.patch.object(input_match, 'select_match_meta', lambda app, name: meta):
            return input_match.card_match('app', self.PORTS)

    def test_a_port_no_model_of_the_select_names_is_not_judged_by_it(self):
        """The audio of the enhancer feeds ANOTHER engine, the file of the describer its cascade:
        judged by this select, it greyed every model (measured on 2026-10-21)."""
        match = self._match({'m1': {'inputs_required': ['work_file', 'prompt']},
                             'm2': {'inputs_optional': ['work_image']}})
        self.assertEqual('model', match['field'])
        self.assertEqual(['work_file'], match['ports'])
        self.assertEqual({'m1': ['work_file'], 'm2': []},
                         {k: v['inputs_required'] + v['inputs_optional']
                          for k, v in match['meta'].items()},
                         'the status line speaks only of what the card provides')
        self.assertIn('work_file', match['labels'])

    def test_nothing_to_match_gives_nothing(self):
        self.assertEqual({}, self._match({'m1': {'inputs_required': ['work_image']}}))
        self.assertEqual({}, self._match({'m1': {'inputs_required': ['work_file']}}, field=None))


class EntryCardViewTest(_MediaCase):

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.user)

    def test_the_card_v4_of_the_app_is_served_to_compose_without_creating(self):
        html = self.client.get('/studio/api/entry-card/', {'app': 'anonymizer'}).content.decode()
        self.assertIn('data-wama-ports', html)
        self.assertIn('data-wama-depot="attache"', html,
                      'a drop JOINS — even for an app whose drop creates a card on its page')
        self.assertNotIn('DetectBar', html, 'the lot bar creates cards: not rendered here')
        self.assertIn('id="studioEntryDrop"', html)
        from wama.studio.views import ENTRY_CARD_IDS
        self.assertIn('id="studioEntryIds"', html, 'the ids travel with the card, read by the modal')
        self.assertIn(json.dumps(ENTRY_CARD_IDS['card_id']), html)
        self.assertIn('le pipeline tournera une fois par ligne', html)

    def test_the_matching_travels_with_the_card(self):
        from wama.common.utils import input_match
        declared = {'field': 'model', 'meta': {'m': {'inputs_required': ['work_file']}},
                    'labels': {}, 'ports': ['work_file']}
        with mock.patch.object(input_match, 'card_match', lambda app, ports: declared):
            html = self.client.get('/studio/api/entry-card/', {'app': 'anonymizer'}).content.decode()
        payload = json.loads(html[html.index('id="studioEntryIds"'):].split('>', 1)[1]
                             .split('</script>', 1)[0])
        self.assertEqual(declared, payload['match'])
        self.assertIn('id="studioEntryMatch"', html, 'the status line of the matching is rendered')

    def test_an_app_page_is_unchanged(self):
        from django.template.loader import render_to_string
        html = render_to_string('common/_new_item_card_v4.html',
                                {'app_id': 'anonymizer', 'drop_zone_id': 'z', 'file_input_id': 'f'})
        self.assertIn('data-wama-depot="cree"', html)
        self.assertIn('DetectBar', html)

    def test_an_unknown_app_is_not_served(self):
        self.assertEqual(404, self.client.get('/studio/api/entry-card/',
                                              {'app': 'nope'}).status_code)

    def test_the_lot_file_is_read_by_the_rule_of_the_launch(self):
        lot = self.own('lot.txt', b'-i a.png\n-i b.png\n-i c.png\n')
        ok = self.client.post('/studio/api/entry-lot/', json.dumps({'app': 'describer', 'lot': lot}),
                              content_type='application/json')
        self.assertEqual({'count': 3}, ok.json())
        refused = self.client.post('/studio/api/entry-lot/',
                                   json.dumps({'app': 'describer', 'lot': self.foreign('x.txt')}),
                                   content_type='application/json')
        self.assertEqual(400, refused.status_code)

    def test_the_card_designates_as_principal_the_work_port_the_launch_unfolds(self):
        """The modal lets the PRINCIPAL work port accumulate files (a lot) and reads it on the card:
        the port whose input carries `file_input_id`. The launch unfolds a lot on `entry_form`'s
        `work` (`entries.card_lot`). Both must name the same port — « the first tab » was a second
        rule, which a reference port listed first would have broken (2026-10-21)."""
        import re

        from wama.common.app_registry import entry_form, studio_node_ports
        from wama.studio.views import ENTRY_CARD_IDS
        checked = 0
        for app in ('imager', 'transcriber', 'synthesizer', 'enhancer', 'avatarizer', 'converter'):
            with self.subTest(app=app):
                html = self.client.get('/studio/api/entry-card/', {'app': app}).content.decode()
                panes = re.findall(r'data-port-pane="([^"]+)" data-port-kind="file" '
                                   r'data-port-input="([^"]+)"', html)
                principal = [port for port, input_id in panes
                             if input_id == ENTRY_CARD_IDS['file_input_id']]
                work = entry_form((studio_node_ports(app) or {}).get('inputs') or [])['work']
                self.assertEqual([work], principal)
                checked += 1
        self.assertEqual(6, checked)

    def test_the_served_page_loads_the_bricks_of_the_card(self):
        page = self.client.get('/studio/').content.decode('utf-8', errors='replace')
        for script in ('common/js/wama-input-slots.js', 'common/js/wama-import.js',
                       'common/js/batch-import.js', 'common/js/wama-input-match.js',
                       'studio/js/wama-studio-entry.js'):
            self.assertIn(script, page)
        self.assertLess(page.index('studio/js/wama-studio-entry.js'),
                        page.index('studio/js/wama-studio.js'))


@skipUnless(HAS_V8, 'py_mini_racer absent')
class EntryJsTest(SimpleTestCase):

    def _src(self, rel):
        return (Path(settings.BASE_DIR) / 'staticfiles' / rel).read_text(encoding='utf-8')

    def test_the_served_scripts_parse_under_v8(self):
        from py_mini_racer import MiniRacer
        for rel in ('studio/js/wama-studio-entry.js', 'studio/js/wama-studio.js',
                    'common/js/wama-input-slots.js'):
            with self.subTest(rel=rel):
                MiniRacer().eval('(function(){' + self._src(rel) + '\n})')

    def test_the_card_brick_restricts_its_own_tabs_for_a_one_port_card(self):
        """A simplified card shows the tab of ITS port only — by the brick of the card, the only
        reader of its tabs (`tests_designation_js`)."""
        from py_mini_racer import MiniRacer
        ctx = MiniRacer()
        ctx.eval("""
var window = {}; var document = {readyState: 'complete', querySelectorAll: function () { return []; }};
function El(attr, id) { var e = {dataset: {}, style: {}, cls: {}};
  e.dataset[attr] = id; e.classList = {toggle: function (c, on) { e.cls[c] = !!on; }}; return e; }
var tabs = [El('portTab', 'work_file'), El('portTab', 'reference_image'), El('portTab', 'lot')];
var panes = [El('portPane', 'work_file'), El('portPane', 'reference_image'), El('portPane', 'lot')];
var card = {querySelectorAll: function (sel) { return sel === '[data-port-tab]' ? tabs : panes; }};
""")
        ctx.eval(self._src('common/js/wama-input-slots.js'))
        kept = ctx.eval("JSON.stringify(window.WamaInputSlots.restrict(card, ['reference_image']))")
        self.assertEqual('["reference_image"]', kept)
        self.assertEqual('none|' + '|none', ctx.eval(
            "tabs.map(function (t) { return t.style.display; }).join('|')"))
        self.assertTrue(ctx.eval("panes[1].cls['is-active'] === true && !panes[0].cls['is-active']"))
        self.assertEqual(3, ctx.eval("window.WamaInputSlots.restrict(card).length"),
                         'no list: every tab back')

    def test_the_modal_reads_the_card_through_its_brick(self):
        src = self._src('studio/js/wama-studio-entry.js')
        self.assertIn('WamaInputSlots.restrict(card, keep)', src)
        self.assertIn('p.urlInputId', src)
        self.assertNotIn('[data-port-tab', src, 'the tabs are read by the card brick only')
        from wama.studio.views import ENTRY_CARD_IDS
        for value in ENTRY_CARD_IDS.values():
            self.assertNotIn(f"'{value}'", src, f'{value}: declared by the server, never copied')
        # The principal port is the one the CARD designates (its `file_input_id`), never the first tab.
        self.assertIn('p.inputId === IDS.files', src)
        self.assertNotIn('filePorts(card)[0]', src)
        canvas = self._src('studio/js/wama-studio.js')
        self.assertIn('metaOf(node).compose', canvas)
        self.assertNotIn('ENTRY_MODES', canvas, 'what a modal shows is declared by the registry')

    def test_the_modal_matches_the_card_with_the_model_select_of_its_panel(self):
        """The gesture of the app pages (`WamaInputMatch.init`, slots = the card's ports by its
        brick), on the select the SERVER named — rewired at each render of the panel."""
        src = self._src('studio/js/wama-studio-entry.js')
        self.assertIn('WamaInputMatch.init(', src)
        self.assertIn("'[data-param-row=\"' + MATCH.field + '\"]'", src)
        self.assertIn('statusId: IDS.match', src)
        self.assertIn('opts.settings(settingsHost, wireMatch)', src)
        canvas = self._src('studio/js/wama-studio.js')
        self.assertIn('onRender: rendered', canvas)
        import re
        self.assertEqual(2, len(re.findall(r'^\s*rendered\(\);$', canvas, re.M)),
                         'called after BOTH renders of the panel')

    def test_input_slots_exposes_its_wiring_for_a_card_rendered_later(self):
        from py_mini_racer import MiniRacer
        ctx = MiniRacer()
        ctx.eval("var window = {}; var document = {readyState: 'complete', "
                 "querySelectorAll: function () { return []; }};")
        ctx.eval(self._src('common/js/wama-input-slots.js'))
        self.assertEqual('function', ctx.eval('typeof window.WamaInputSlots.wire'))

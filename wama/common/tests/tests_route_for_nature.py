"""The routing door by input NATURE (`route_for_nature`) — the app's `ROUTES`, one resolver.

Born 2026-10-05: the resolution « ROUTES[nature] → relative import → callable » was written four
times (enhancer, describer, the body emitted by `tasks_gen`, converter's inline conversion), and
the converter task — which DECLARES its routes — bypassed them with a hand-written `if/elif`.
Its routes were read by the manifest and the sandbox twin only. Here: the door, then — no app
named — every declared route through it, and no hand-made copy of the resolver.
"""
import ast
from importlib import import_module
from pathlib import Path
from unittest import mock

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase

from wama.common.backends.manager import route_for_nature

WAMA = Path(settings.BASE_DIR) / 'wama'


def _declared_routes():
    """(package, ROUTES) for every installed app whose `backends` package declares routes."""
    out = []
    for config in apps.get_app_configs():
        try:
            routes = getattr(import_module(f'{config.name}.backends'), 'ROUTES', None)
        except ImportError:
            continue
        if routes:
            out.append((config.name, routes))
    return out


class RouteForNatureTest(SimpleTestCase):

    def test_the_fleet_is_measured(self):
        packages = [package for package, _routes in _declared_routes()]
        self.assertTrue({'wama.converter', 'wama.describer', 'wama.enhancer'} <= set(packages), packages)

    def test_every_declared_route_resolves_to_a_callable(self):
        for package, routes in _declared_routes():
            for nature, path in routes.items():
                with self.subTest(package=package, nature=nature):
                    target = route_for_nature(package, nature)
                    self.assertTrue(callable(target))
                    self.assertEqual(path.rsplit('.', 1)[1], target.__name__)

    def test_a_nature_without_a_route_is_refused(self):
        with self.assertRaisesRegex(ValueError, "'hologram'"):        # the message keeps its value
            route_for_nature('wama.converter', 'hologram')
        with self.assertRaises(ValueError):
            route_for_nature('wama.converter', '')

    def test_the_table_the_caller_holds_wins(self):
        target = route_for_nature('wama.converter', 'x',
                                  routes={'x': 'backends.audio_backend.convert_audio'})
        self.assertEqual('convert_audio', target.__name__)

    def test_the_callable_is_read_at_call_time(self):
        """Tests replace a route function on its module — the door must hand THAT one."""
        sentinel = object()
        with mock.patch('wama.converter.backends.image_backend.convert_image', sentinel):
            self.assertIs(sentinel, route_for_nature('wama.converter', 'image'))


def _hand_resolutions(path):
    """Lines where a module reads a ROUTES table itself (`ROUTES.get(…)` / `ROUTES[…]`)."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    found = []
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == 'get':
            target = node.func.value
        elif isinstance(node, ast.Subscript):
            target = node.value
        if isinstance(target, ast.Name) and target.id in ('ROUTES', 'routes'):
            found.append(node.lineno)
    return found


class NoAppResolvesItsRoutesByHandTest(SimpleTestCase):
    """The resolver lives in ONE place; generated twins (`_01`) are emitted by the generator."""

    DOOR = WAMA / 'common' / 'backends' / 'manager.py'

    def test_no_module_reads_a_routes_table_itself(self):
        offenders = []
        for path in sorted(WAMA.rglob('*.py')):
            rel = path.relative_to(WAMA).as_posix()
            if path == self.DOOR or '/tests' in f'/{rel}' or path.name.startswith('tests') \
                    or rel.split('/')[0].endswith('_01') or 'codegen' in rel:
                continue
            offenders += [f'{rel}:{line}' for line in _hand_resolutions(path)]
        self.assertEqual([], offenders, 'resolve a nature through `route_for_nature`')



class ConverterFollowsItsRoutesTest(SimpleTestCase):
    """The converter task used to branch by hand: a route changed in ROUTES was ignored by it."""

    def test_the_task_glue_calls_the_route_its_table_declares(self):
        import tempfile
        from types import SimpleNamespace
        from django.test import override_settings
        from wama.converter import tasks
        from wama.converter import backends as converter_backends

        calls = []

        def witness(input_path, output_path, output_format, options=None, progress_callback=None):
            calls.append((Path(input_path).name, output_format, bool(options)))
            Path(output_path).write_bytes(b'converted')
            progress_callback(100)

        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'in.png'
            source.write_bytes(b'x')
            job = SimpleNamespace(
                id=7, pk=7, user_id=1, user=None, dest_dir='', output_format='webp',
                input_filename='in.png', input_file=SimpleNamespace(path=str(source)),
                media_type='image', options={}, CHAMPS_CROSS_APP=())
            ctx = SimpleNamespace(console=lambda *_a: None, progress=mock.Mock())
            routes = dict(converter_backends.ROUTES, image='backends.audio_backend.convert_audio')
            with override_settings(MEDIA_ROOT=Path(root)), \
                    mock.patch.object(converter_backends, 'ROUTES', routes), \
                    mock.patch('wama.converter.backends.audio_backend.convert_audio', witness), \
                    mock.patch('wama.accounts.permissions.is_guest_account', return_value=False), \
                    mock.patch('wama.converter.utils.cross_app.apply_cross_app_options'), \
                    mock.patch.object(tasks, 'converter_eta_key_size', return_value=None):
                result = tasks._convert(job, ctx)
        self.assertEqual([('in.png', 'webp', True)], calls, 'the route of the TABLE, not a hand branch')
        self.assertTrue(result['fields']['output_file'].endswith('.webp'))
        ctx.progress.assert_any_call(90)
        self.assertLessEqual(max(c.args[0] for c in ctx.progress.call_args_list), 90,
                             'the conversion stays under 90 — the AI post-processing reports 90-98')

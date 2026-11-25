"""Which element a tool step created or started — the meta-app contract, read (2026-10-06).

The channel gateway posts the end of a task in the thread it was asked from. It finds that
thread in the persisted tool steps, by the contract every queue app already follows:
  - a creation returns the UNIFORM key `item_id` (`STUDIO_VISION §2`) ;
  - a start names its element by its main argument (`primary_arg_name`, as the Studio calls it) ;
  - an element is designated by its FAMILY — the detail-adapter key (`DetailRegistry`), which
    tells apart the two models of the enhancer (`enhancer`, `audio_enhancer`).

⭐ What these tests found on their first run : `add_to_audio_enhancer` did not return `item_id`
— the « 10/10 » of `STUDIO_VISION` counted the ten apps, not the audio branch — and the four
historical creators (`create_image`, `synthesize_text`, `compose_music`, `convert_file`), still
offered to the model, only got the key through their canonical aliases. A measure without a
guard ages ; this one is now a test, DERIVED from the tool registry : a new creator is covered
without anyone listing it here.
"""
import ast
import inspect
import textwrap

from django.test import SimpleTestCase, TestCase

from wama import tool_api
from wama.common.utils.detail_registry import DetailRegistry


def _creators():
    """Every tool that CREATES a queue element : the `add_to_*` of a family, and what they wrap."""
    found = {}
    for name, fn in tool_api.TOOL_REGISTRY.items():
        if tool_api.tool_role(name) == 'add' and tool_api.tool_family(name):
            found[name] = inspect.unwrap(fn)
    return found


def _success_returns(fn):
    """The dict literals a function returns, except error answers (`{'error': …}`)."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    returns = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            keys = {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
            if 'error' not in keys:
                returns.append(keys)
    return returns


class EveryCreationReturnsTheUniformKeyTest(SimpleTestCase):

    def test_there_are_creators_to_check(self):
        """Counter-check of the derivation : an empty list would make the next test vacuous."""
        self.assertGreaterEqual(len(_creators()), 10, sorted(_creators()))

    def test_every_creator_returns_item_id_at_the_source(self):
        for name, fn in sorted(_creators().items()):
            with self.subTest(tool=name, source=fn.__name__):
                returns = _success_returns(fn)
                self.assertTrue(returns, f'{fn.__name__}: no literal success return to read')
                for keys in returns:
                    self.assertIn('item_id', keys, f'{fn.__name__} returns {sorted(keys)}')


class EveryFamilyHasItsDetailAndItsStatusTest(SimpleTestCase):

    def test_each_creator_family_names_a_detail_model_and_a_status_tool(self):
        """What the gateway relies on : the family of a creation gives the element's MODEL
        (`DetailRegistry`) and the tool that reads its result (`get_<family>_status`)."""
        for name in sorted(_creators()):
            family = tool_api.tool_family(name)
            with self.subTest(tool=name, family=family):
                self.assertIsNotNone(DetailRegistry.get(family), f'no detail adapter for {family}')
                self.assertIn(f'get_{family}_status', tool_api.TOOL_REGISTRY)

    def test_the_family_tells_apart_two_models_of_one_app(self):
        self.assertEqual('enhancer', tool_api.app_id_for_tool('start_audio_enhancer'))
        self.assertEqual('audio_enhancer', tool_api.tool_family('start_audio_enhancer'))
        self.assertNotEqual(DetailRegistry.get('enhancer')['model'],
                            DetailRegistry.get('audio_enhancer')['model'])

    def test_every_surface_a_creator_serves_has_its_detail_and_its_status_tool(self):
        """One creator per app serves EVERY domain a file arrives in (2026-11-25 : the enhancer had
        a second creator for its audio) — each domain's surface gives the element's model and the
        tool that reads it, twins included (`sandbox.surface_pairs`)."""
        from wama.common.utils.app_modes import arrival_domains, domain_surface
        checked = []
        for name in sorted(_creators()):
            app = tool_api.app_id_for_tool(name)
            for domain in arrival_domains(app):
                surface = domain_surface(app, domain)
                with self.subTest(tool=name, surface=surface):
                    self.assertIsNotNone(DetailRegistry.get(surface), f'no detail adapter for {surface}')
                    self.assertIn(f'start_{surface}', tool_api.TOOL_REGISTRY)
                    self.assertIn(f'get_{surface}_status', tool_api.TOOL_REGISTRY)
                checked.append(surface)
        self.assertIn('audio_enhancer', checked)

    def test_no_surface_of_an_app_has_a_creator_of_its_own(self):
        """`add_to_<surface>` beside `add_to_<app>` was the porting leftover of `ROUTE §11 #42` ⑥ :
        a domain is a level of the app's structure, its file arrives by the app's creator."""
        from wama.common.utils.app_modes import surface_app
        doubles = [name for name in tool_api.TOOL_REGISTRY if tool_api.tool_role(name) == 'add'
                   and surface_app(name[len('add_to_'):]) != name[len('add_to_'):]]
        self.assertEqual([], doubles)

    def test_a_historical_creator_has_the_family_of_its_app(self):
        self.assertEqual('imager', tool_api.tool_family('create_image'))
        self.assertIsNone(tool_api.tool_family('add_to_media_library'), 'transverse')
        self.assertIsNone(tool_api.tool_family('list_user_files'))


class ItemsOfStepTest(SimpleTestCase):

    def test_a_creation_designates_its_item(self):
        self.assertEqual([('anonymizer', 36)], tool_api.items_of_step(
            'add_to_anonymizer', {'file_path': 'x.jpg'}, {'item_id': 36, 'status': 'queued'}))

    def test_a_historical_creator_designates_its_item_too(self):
        self.assertEqual([('imager', 9)], tool_api.items_of_step(
            'create_image', {'prompt': 'p'}, {'generation_id': 9, 'item_id': 9}))

    def test_a_start_designates_the_element_named_by_its_main_argument(self):
        argument = tool_api.primary_arg_name('start_anonymizer')
        self.assertEqual([('anonymizer', 1036)], tool_api.items_of_step(
            'start_anonymizer', {argument: 1036}, {'status': 'started'}))

    def test_a_start_of_the_whole_queue_designates_each_started_element(self):
        self.assertEqual([('reader', 4), ('reader', 5)], tool_api.items_of_step(
            'start_reader', {}, {'status': 'started', 'count': 2, 'ids': [4, 5]}))

    def test_a_status_an_error_or_a_transverse_tool_designate_nothing(self):
        self.assertEqual([], tool_api.items_of_step(
            'get_anonymizer_status', {}, {'item_id': 1036, 'jobs': [{'id': 1036}]}))
        self.assertEqual([], tool_api.items_of_step(
            'add_to_anonymizer', {}, {'error': 'Valeur hors schéma', 'item_id': 3}))
        self.assertEqual([], tool_api.items_of_step('list_user_files', {}, {'item_id': 3}))

    def test_a_batch_launch_designates_its_child_cards_in_the_surface_it_names(self):
        """2026-11-04: `launch_batch` is generic (its name names no app), so its launched cards
        were found nowhere — no line in the exchange, no end told in the thread. Its result names
        the SURFACE the domain declares, and the child cards' ids."""
        self.assertEqual([('audio_enhancer', 7), ('audio_enhancer', 8)], tool_api.items_of_step(
            'launch_batch', {'app': 'audio_enhancer', 'batch_id': 3},
            {'started': True, 'app': 'audio_enhancer', 'batch_id': 3, 'ids': [7, 8]}))
        # Counter-checks: a refusal, and a start that names no surface (a model install).
        self.assertEqual([], tool_api.items_of_step(
            'launch_batch', {'app': 'audio_enhancer', 'batch_id': 3}, {'error': 'lot introuvable'}))
        from wama.tool_api import batch_of_step
        # The batch itself (2026-11-05): ONE line of the exchange, ONE end in the thread.
        self.assertEqual(('audio_enhancer', 3), batch_of_step(
            'launch_batch', {'started': True, 'app': 'audio_enhancer', 'batch_id': 3, 'ids': [7, 8]}))
        self.assertIsNone(batch_of_step('launch_batch', {'error': 'lot introuvable'}))
        self.assertIsNone(batch_of_step('start_reader', {'started': True, 'app': 'reader', 'batch_id': 1}),
                          'a start of an app names its family: not a batch')
        self.assertEqual([], tool_api.items_of_step(
            'install_model', {'model_key': 'm'}, {'started': True, 'model_key': 'm', 'task_id': 't'}))

    def test_the_family_of_a_creation_is_the_surface_it_returns(self):
        """The app's one creator returns the SURFACE of what it created (`created_surface`) : an
        audio received by the enhancer is followed as an audio element, never as an image."""
        self.assertEqual([('audio_enhancer', 5)], tool_api.items_of_step(
            'add_to_enhancer', {}, {'audio_enhancement_id': 5, 'item_id': 5,
                                    'surface': 'audio_enhancer'}))
        # Counter-check : a surface of ANOTHER app is not believed — the tool's own family stays.
        self.assertEqual([('enhancer', 5)], tool_api.items_of_step(
            'add_to_enhancer', {}, {'item_id': 5, 'surface': 'anonymizer'}))


class OneCreatorForEveryDomainTest(TestCase):
    """The enhancer's two domains by ONE creator, measured by REAL calls : the domain read from
    the file's nature (or named), the settings judged on the schema of the domain that receives."""

    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path

        from django.contrib.auth import get_user_model
        from django.test import override_settings

        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        setting = override_settings(MEDIA_ROOT=root)
        setting.enable()
        self.addCleanup(setting.disable)
        self.user = get_user_model().objects.create_superuser('one_creator', password='x')
        self.temp = Path(root) / 'users' / str(self.user.pk) / 'temp'
        self.temp.mkdir(parents=True)

    def _file(self, name, content=b'RIFF\x24\x00\x00\x00WAVEfmt ' + b'\0' * 32):
        (self.temp / name).write_bytes(content)
        return f'users/{self.user.pk}/temp/{name}'

    def test_an_audio_file_is_born_in_the_audio_domain_with_its_item_id(self):
        result = tool_api.execute_tool('add_to_enhancer', {'file_path': self._file('voix.wav')},
                                       self.user, model_call=True)
        self.assertNotIn('error', result)
        self.assertEqual(('audio_enhancer', 'audio'), (result['surface'], result['domain']))
        self.assertEqual(result['audio_enhancement_id'], result['item_id'])
        model = DetailRegistry.get('audio_enhancer')['model']
        self.assertTrue(model.objects.filter(pk=result['item_id'], user=self.user).exists())

    def test_an_image_file_is_born_in_the_image_domain(self):
        result = tool_api.execute_tool('add_to_enhancer', {'file_path': self._file('photo.png', b'x')},
                                       self.user, model_call=True)
        self.assertNotIn('error', result)
        self.assertEqual(('enhancer', 'image', result['item_id']),
                         (result['surface'], result['media_type'], result['enhancement_id']))

    def test_a_setting_of_the_other_domain_is_turned_down_and_nothing_is_created(self):
        model = DetailRegistry.get('audio_enhancer')['model']
        before = model.objects.count()
        result = tool_api.execute_tool('add_to_enhancer', {'file_path': self._file('voix.wav'),
                                                           'upscale_factor': 4},
                                       self.user, model_call=True)
        self.assertIn('upscale_factor', result.get('error', ''))
        self.assertEqual(before, model.objects.count())

    def test_a_value_of_the_receiving_domain_is_judged_on_its_own_schema(self):
        """`output_format` exists in both domains : `png` is offered to an image, never to an
        audio — the announcement is the union, the gate is the receiving domain's."""
        result = tool_api.execute_tool('add_to_enhancer', {'file_path': self._file('voix.wav'),
                                                           'output_format': 'png'},
                                       self.user, model_call=True)
        self.assertIn('output_format', result.get('error', ''))
        result = tool_api.execute_tool('add_to_enhancer', {'file_path': self._file('voix2.wav'),
                                                           'output_format': 'flac'},
                                       self.user, model_call=True)
        self.assertNotIn('error', result)
        model = DetailRegistry.get('audio_enhancer')['model']
        self.assertEqual('flac', model.objects.get(pk=result['item_id']).output_format)

    def test_a_named_domain_that_does_not_take_the_file_turns_it_down(self):
        result = tool_api.execute_tool('add_to_enhancer', {'file_path': self._file('photo.png', b'x'),
                                                           'domain': 'audio'},
                                       self.user, model_call=True)
        self.assertIn('error', result)

    def test_the_next_step_is_the_start_of_the_surface_created(self):
        result = tool_api.relay_next_step('add_to_enhancer', tool_api.execute_tool(
            'add_to_enhancer', {'file_path': self._file('voix.wav')}, self.user, model_call=True))
        self.assertEqual('start_audio_enhancer', result['next_step'])

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
        self.assertEqual('enhancer', tool_api.app_id_for_tool('add_to_audio_enhancer'))
        self.assertEqual('audio_enhancer', tool_api.tool_family('add_to_audio_enhancer'))
        self.assertNotEqual(DetailRegistry.get('enhancer')['model'],
                            DetailRegistry.get('audio_enhancer')['model'])

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

    def test_the_family_of_an_audio_creation_is_its_own(self):
        self.assertEqual([('audio_enhancer', 5)], tool_api.items_of_step(
            'add_to_audio_enhancer', {}, {'audio_enhancement_id': 5, 'item_id': 5}))


class AudioCreationReturnsItemIdTest(TestCase):
    """The one family that did not return the key — measured by a REAL call, not by reading."""

    def test_add_to_audio_enhancer_returns_item_id(self):
        import shutil
        import tempfile
        from pathlib import Path

        from django.contrib.auth import get_user_model
        from django.test import override_settings

        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        with override_settings(MEDIA_ROOT=root):
            user = get_user_model().objects.create_user('audio_item_id', password='x')
            sound = Path(root) / 'users' / str(user.pk) / 'temp' / 'voix.wav'
            sound.parent.mkdir(parents=True)
            sound.write_bytes(b'RIFF\x24\x00\x00\x00WAVEfmt ' + b'\0' * 32)
            result = tool_api.add_to_audio_enhancer(user, f'users/{user.pk}/temp/voix.wav')
        self.assertNotIn('error', result)
        self.assertEqual(result['audio_enhancement_id'], result['item_id'])

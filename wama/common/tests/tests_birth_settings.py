"""An element is BORN by the common cascade — `user_settings.new_element_settings` (2026-10-18).

The rule (`ROADMAP §23.2quater`): an element is born COMPLETE — schema defaults ← the author's
panel preferences ← what the deposit posts. Measured the day the criterion was written: 2 apps out
of 10 used the brick; the others each had a cascade of their own (defaults copied from the schema
into a `get_user_app_settings` dict, schema defaults without preferences, a default written in the
view when reading the POST). The grid's `user_settings` criterion only measured the WRITING of the
preferences, so all ten were green.
"""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama.common.services import conformity_checker as checker
from wama.common.utils import user_settings

#: A schema of three settings, all on the panel — `gif_fps` has no column on the plain model.
SCHEMA = [
    {'name': 'quality', 'type': 'number', 'default': 85, 'min': 1, 'max': 100,
     'dom_id': 'q', 'contexts': ['panel', 'item']},
    {'name': 'flip', 'type': 'toggle', 'default': False, 'dom_id': 'f', 'contexts': ['panel', 'item']},
    {'name': 'gif_fps', 'type': 'number', 'default': 12, 'min': 1, 'max': 60,
     'dom_id': 'g', 'contexts': ['panel', 'item']},
]


def _model(*columns):
    """A stand-in model: the brick only reads its concrete column names."""
    return SimpleNamespace(_meta=SimpleNamespace(
        concrete_fields=[SimpleNamespace(name=c) for c in columns]))


class NewElementSettingsTest(TestCase):
    """What an element is born with — the behaviour every app and the generator now rely on."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('birth_settings_case', password='x')
        self.app = 'birth_settings_case'

    def _born(self, model, **kw):
        return user_settings.new_element_settings(self.user, self.app, SCHEMA, model, **kw)

    def test_schema_defaults_then_the_authors_preferences_then_the_post(self):
        model = _model('quality', 'flip')
        self.assertEqual({'quality': 85, 'flip': False}, self._born(model))
        user_settings.save_panel_settings(self.user, self.app, SCHEMA, {'quality': '70'})
        self.assertEqual({'quality': 70, 'flip': False}, self._born(model))
        # The POST wins, COERCED by the schema: a form posts strings ('false', '90').
        self.assertEqual({'quality': 90, 'flip': True},
                         self._born(model, post={'quality': '90', 'flip': 'true'}))
        self.assertEqual({'quality': 70, 'flip': False}, self._born(model, post={'flip': 'false'}))

    def test_a_value_outside_the_declared_choices_is_never_written(self):
        schema = SCHEMA + [{'name': 'style', 'type': 'select', 'default': 'detailed',
                            'choices': [('detailed', 'Détaillé'), ('short', 'Court')],
                            'dom_id': 's', 'contexts': ['panel', 'item']}]
        model = _model('quality', 'flip', 'style')
        born = lambda **kw: user_settings.new_element_settings(self.user, self.app, schema, model, **kw)
        # A preference remembered before a choice was withdrawn falls back to the default…
        user_settings.save_user_app_settings(self.user, self.app, {'s': 'meeting'})
        self.assertEqual('detailed', born()['style'])
        # …and so does a stale POST; a valid one is taken.
        self.assertEqual('detailed', born(post={'style': 'meeting'})['style'])
        self.assertEqual('short', born(post={'style': 'short'})['style'])

    def test_a_preset_sits_between_the_schema_defaults_and_what_is_given(self):
        model = _model('quality', 'flip')
        self.assertEqual(60, self._born(model, preset={'quality': 60})['quality'])
        user_settings.save_panel_settings(self.user, self.app, SCHEMA, {'quality': '70'})
        self.assertEqual(70, self._born(model, preset={'quality': 60})['quality'],
                         "the author's choice is never overwritten by a preset")
        self.assertEqual(90, self._born(model, preset={'quality': 60}, post={'quality': '90'})['quality'])

    def test_an_empty_post_declared_as_a_value_drops_the_remembered_one(self):
        schema = SCHEMA + [{'name': 'seed', 'type': 'number', 'default': None,
                            'dom_id': 'sd', 'contexts': ['panel', 'item']}]
        model = _model('quality', 'flip', 'seed')
        born = lambda **kw: user_settings.new_element_settings(self.user, self.app, schema, model, **kw)
        user_settings.save_panel_settings(self.user, self.app, schema, {'seed': '42'})
        self.assertEqual(42, born(post={})['seed'])
        self.assertEqual(42, born(post={'seed': ''})['seed'], 'an empty number says nothing…')
        self.assertIsNone(born(post={'seed': ''}, empty_is_value=('seed',)).get('seed'),
                          '…unless the app declares that empty IS a choice (a random seed)')

    def test_a_default_the_author_never_set_does_not_bypass_a_show_if(self):
        """The defect the avatarizer showed: the panel's DEFAULTS were read as the author's
        choices, so a setting hidden by its `show_if` was written anyway."""
        schema = SCHEMA + [{'name': 'voice', 'type': 'text', 'default': 'fr', 'show_if': 'text',
                            'dom_id': 'v', 'contexts': ['panel', 'item']},
                           {'name': 'text', 'type': 'textarea', 'default': '', 'contexts': ['item']}]
        model = _model('quality', 'flip', 'voice', 'text')
        born = lambda **kw: user_settings.new_element_settings(self.user, self.app, schema, model, **kw)
        self.assertNotIn('voice', born(post={}))
        self.assertEqual('fr', born(post={'text': 'Bonjour'})['voice'])

    def test_a_setting_without_a_column_goes_to_the_declared_container_or_is_left_out(self):
        self.assertNotIn('gif_fps', self._born(_model('quality', 'flip')))
        born = self._born(_model('quality', 'flip', 'options'), options_field='options')
        self.assertEqual({'gif_fps': 12}, born['options'])
        # Counter-proof: without the declaration nothing is invented, even if the column exists.
        self.assertNotIn('options', self._born(_model('quality', 'flip', 'options')))

REAL_APPS = ('anonymizer', 'avatarizer', 'composer', 'converter', 'describer', 'enhancer',
             'imager', 'reader', 'synthesizer', 'transcriber')


class BirthSettingsCriterionTest(SimpleTestCase):
    """Every departure from the common cascade turns the criterion red — the counter-proof that
    it MEASURES (`/contre-epreuve`)."""

    def _state(self, files, names=('quality', 'model')):
        with tempfile.TemporaryDirectory() as d:
            for rel, text in files.items():
                (Path(d) / rel).write_text(text, encoding='utf-8')
            app = checker._AppFiles('fake')
            app.root = Path(d)
            with mock.patch.object(checker, '_declared_setting_names', return_value=set(names)):
                return checker._birth_settings_common(app)[0]

    def test_each_local_cascade_turns_red_and_the_brick_alone_is_green(self):
        brick = "def new_x(user, post=None):\n    return new_element_settings(user, 'x', P, M, post=post)\n"
        cases = (
            ({'views.py': brick}, True),
            # Defaults copied from the schema into the preferences read.
            ({'views.py': brick + "last = get_user_app_settings(user, 'x', {'quality': 85})\n"}, 'partial'),
            ({'views.py': "last = get_user_app_settings(user, 'x', {\n    'quality': 85})\n"}, False),
            # Schema defaults WITHOUT the author's preferences.
            ({'views.py': "birth = applicable_defaults(SCH, {'media_type': t})\n"}, False),
            # A DECLARED setting given a default in the view.
            ({'views.py': brick + "q = request.POST.get('quality', 85)\n"}, 'partial'),
            ({'views.py': brick + "m = request.POST.get('model', 'auto')\n"}, 'partial'),
            # An undeclared name is not a setting (`restart`, `url`) — nothing to port.
            ({'views.py': brick + "r = request.POST.get('restart', '0')\n"}, True),
            # An empty default is not a value written in the view.
            ({'views.py': brick + "m = request.POST.get('model', '')\n"}, True),
            # A remembered value keyed by a variable is an app rule, not a copied schema default
            # (the converter's last format per nature, `format_router`).
            ({'views.py': brick + "get_user_app_settings(user, app, {key: ''})\n"}, True),
            # A comment that tells the brick is not a call of it.
            ({'views.py': "# new_element_settings(user, ...) told\n"}, False),
            # A test that calls the brick does not make the app born by it.
            ({'tests_x.py': brick}, False),
        )
        for files, expected in cases:
            with self.subTest(files=files):
                self.assertEqual(expected, self._state(files))

    def test_the_ten_apps_today(self):
        """What IS, measured — each port moves one app to True, and this line with it."""
        states = {a: checker._birth_settings_common(checker._AppFiles(a))[0] for a in REAL_APPS}
        self.assertEqual({'anonymizer': True, 'avatarizer': True, 'composer': True,
                          'converter': True, 'describer': True, 'enhancer': True,
                          'imager': True, 'reader': True, 'synthesizer': True,
                          'transcriber': True}, states)


#: The assistant's creation tools, each born by its APP's birth function — the one its card deposit
#: and the file manager's import call (2026-10-29). One row per app : the tool, its call, the birth
#: function, and one setting the spy adds to what that function returns. The converter is not here:
#: all its ways in go through `apply_birth_settings`, another shape (it sets an existing job).
TOOL_BIRTHS = (
    ('anonymizer', 'add_to_anonymizer', {'file_path': 'png', 'precision_level': 60},
     'wama.anonymizer.views.new_media_settings', 'Media', 'blur_ratio', 41),
    ('avatarizer', 'add_to_avatarizer', {'text_content': 'Bonjour.', 'avatar_source': 'upload',
                                         'avatar_image_path': 'png', 'language': 'en'},
     'wama.avatarizer.views.new_avatar_settings', 'AvatarJob', 'bbox_shift', 3),
    ('composer', 'compose_music', {'prompt': 'a calm piano', 'model': 'musicgen-small'},
     'wama.composer.views.new_generation_settings', 'ComposerGeneration', 'duration', 13.0),
    ('describer', 'add_to_describer', {'file_path': 'png', 'output_language': 'en'},
     'wama.describer.views.new_description_settings', 'Description', 'max_length', 321),
    ('enhancer', 'add_to_enhancer', {'file_path': 'png', 'denoise': True},
     'wama.enhancer.views.new_enhancement_settings', 'Enhancement', 'blend_factor', 0.3),
    ('imager', 'create_image', {'prompt': 'a cat', 'num_images': 2},
     'wama.imager.views.new_generation_settings', 'ImageGeneration', 'steps', 13),
    ('reader', 'add_to_reader', {'file_path': 'png', 'mode': 'printed'},
     'wama.reader.views.new_reading_settings', 'ReadingItem', 'language', 'xx'),
    ('synthesizer', 'synthesize_text', {'text': 'Bonjour à tous.', 'pitch': 1.2},
     'wama.synthesizer.views.new_synthesis_settings', 'VoiceSynthesis', 'speed', 1.3),
    ('transcriber', 'add_to_transcriber', {'file_path': 'wav', 'preprocess_audio': True},
     'wama.transcriber.views.new_transcript_settings', 'Transcript', 'hotwords', 'zz-sentinel'),
)

_PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                     '1f15c4890000000d49444154789c6360000000000200015e2b4d6b0000000049454e44ae426082')


def _wav():
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b'\x00\x00' * 8000)
    return buf.getvalue()


class ToolsAreBornLikeACardDepositTest(TestCase):
    """An element created by the assistant (or a Studio node, which calls the same tool) is born
    like a card deposit: by its app's birth function, given what the call gave. Before, eight tools
    wrote their own defaults in their signature (`musicgen-small` and 10 s against the schema's
    « auto » and 210 s, `hunyuan-image-2.1` against « auto »…) and ignored the author's retained
    settings. The spy adds one value to what the birth function returns : the element must carry
    it — whichever path the tool takes, it is the app's birth that decides."""

    def setUp(self):
        from django.conf import settings
        self.user = get_user_model().objects.create_user('tool_birth_case', password='x')
        self.temp = Path(settings.MEDIA_ROOT) / f'users/{self.user.id}/temp'
        self.temp.mkdir(parents=True, exist_ok=True)
        self.files = {'png': self.temp / 'tool_birth.png', 'wav': self.temp / 'tool_birth.wav'}
        self.files['png'].write_bytes(_PNG)
        self.files['wav'].write_bytes(_wav())

    def tearDown(self):
        # By the paths created here, never by `MEDIA_ROOT` (AGENTS.md).
        for path in self.files.values():
            path.unlink(missing_ok=True)

    def _call(self, kwargs):
        rel = {k: f'users/{self.user.id}/temp/{self.files[v].name}' for k, v in kwargs.items()
               if isinstance(v, str) and v in self.files}
        return {**kwargs, **rel}

    def test_each_creation_tool_births_by_its_apps_function(self):
        from importlib import import_module

        from django.apps import apps as django_apps
        from wama import tool_api as T
        for app, tool, kwargs, birth, model_name, name, value in TOOL_BIRTHS:
            with self.subTest(app=app):
                module, attr = birth.rsplit('.', 1)
                original = getattr(import_module(module), attr)
                seen = []

                def spy(*args, _original=original, _name=name, _value=value, **kw):
                    seen.append(kw.get('post') or {})
                    return {**_original(*args, **kw), _name: _value}

                with mock.patch(birth, side_effect=spy), \
                        mock.patch('celery.app.task.Task.apply_async',
                                   return_value=mock.Mock(id='no-task')):
                    out = getattr(T, tool)(self.user, **self._call(kwargs))
                self.assertNotIn('error', out, out)
                self.assertTrue(seen, f'{tool} does not call {birth}')
                given = {k: v for k, v in kwargs.items()
                         if k not in ('file_path', 'text', 'prompt', 'avatar_source',
                                      'avatar_image_path', 'text_content', 'model')}
                for key, val in given.items():
                    self.assertEqual(val, seen[-1].get(key), f'{key} given, not posted to the birth')
                element = django_apps.get_model(app, model_name).objects.get(pk=out['item_id'])
                self.assertEqual(value, getattr(element, name),
                                 f'{tool} : the element does not carry what its birth returned')

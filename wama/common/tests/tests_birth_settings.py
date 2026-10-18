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
                          'converter': False, 'describer': True, 'enhancer': True,
                          'imager': True, 'reader': True, 'synthesizer': True,
                          'transcriber': True}, states)

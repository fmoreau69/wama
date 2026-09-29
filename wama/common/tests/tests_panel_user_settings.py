"""The right PANEL and the USER SETTINGS are the same list — for every app, from its schema.

Contract 3 of `WAMA_VERIFICATION §8` (2026-09-26). The panel is the surface of a user's
defaults: every setting it shows is one the user keeps, and the list of kept settings is DERIVED
from the schema (`params.USER_SETTINGS_DEFAULTS` = `param_schema.panel_defaults`), never written
by hand next to it — a hand list is how the transcriber's speech filter was shown in the panel
and never read.

Apps that still keep a hand-written list are named below: the list can only SHRINK.
"""
import importlib

from django.test import SimpleTestCase, TestCase

#: Apps whose user settings are still a hand-written list in their views (measured 2026-09-26 —
#: the `wama:redondance-ok` lines of `get_user_app_settings` calls). Porting one = declaring
#: `USER_SETTINGS_DEFAULTS` in its params.py, as imager and transcriber do.
NOT_YET_DERIVED = {'avatarizer', 'composer', 'converter', 'describer', 'reader', 'synthesizer',
                   # its own `UserSettings` table, outside the common brick (ROADMAP §23.3bis)
                   'enhancer'}


def _apps():
    """(app, params module, primary schema) for every non-sandbox app declaring a schema."""
    from wama.common.app_registry import APP_CATALOG
    from wama.common.utils.param_schema import declared_param_schemas
    out = []
    for app, spec in APP_CATALOG.items():
        if (spec or {}).get('sandbox'):
            continue
        declared = declared_param_schemas(app)
        if not declared:
            continue
        module = importlib.import_module(f'wama.{app}.params')
        out.append((app, module, declared))
    return out


def _panel_params(declared):
    return [p for schema in declared['schemas'].values() for p in schema
            if 'panel' in (p.get('contexts') or ()) and p.get('type') != 'hidden']


class PanelUserSettingsTest(SimpleTestCase):

    def test_every_derived_app_keeps_every_panel_setting(self):
        from wama.common.utils.param_schema import panel_defaults
        checked = 0
        for app, module, declared in _apps():
            defaults = getattr(module, 'USER_SETTINGS_DEFAULTS', None)
            if defaults is None:
                continue
            with self.subTest(app=app):
                key = getattr(module, 'user_setting_key', None)
                expected = set()
                for schema in declared['schemas'].values():
                    expected |= set(panel_defaults(schema, key=key))
                self.assertEqual(expected, set(defaults),
                                 'USER_SETTINGS_DEFAULTS must be the panel params of the schema')
                checked += 1
        self.assertGreaterEqual(checked, 2, 'imager and transcriber at least')

    def test_no_new_app_keeps_a_hand_written_list(self):
        measured = {app for app, module, declared in _apps()
                    if _panel_params(declared) and not hasattr(module, 'USER_SETTINGS_DEFAULTS')}
        self.assertEqual(set(), measured - NOT_YET_DERIVED,
                         'declare USER_SETTINGS_DEFAULTS (param_schema.panel_defaults) in params.py')
        self.assertEqual(set(), NOT_YET_DERIVED - measured,
                         'app ported: remove it from NOT_YET_DERIVED')


def _derived_apps():
    """(app, schema, brick kwargs) for every app whose user settings derive from its schema."""
    out = []
    for app, module, declared in _apps():
        if not hasattr(module, 'USER_SETTINGS_DEFAULTS'):
            continue
        kwargs = dict(getattr(module, 'PANEL_SETTINGS', None)
                      or {'key': getattr(module, 'user_setting_key', None)})
        schema = [p for s in declared['schemas'].values() for p in s]
        out.append((app, schema, kwargs))
    return out


class PanelSettingsBrickTest(TestCase):
    """The common brick (`user_settings.*_panel_*`, 2026-09-27) behaves the same for EVERY
    derived app: a fresh user reads the schema defaults, a saved value comes back, a reset gives
    the defaults back — by removing the preference, never by writing today's default."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create_user('panel_brick', password='x')

    def _numeric_panel_param(self, schema, kwargs):
        from wama.common.utils.param_schema import panel_dom_id
        key = kwargs.get('key') or panel_dom_id
        for p in schema:
            if p.get('type') in ('range', 'number') and key(p) and p.get('min') is not None                     and p.get('max') is not None and p.get('min') != p.get('max'):
                return p
        return None

    def test_a_saved_panel_value_comes_back_and_a_reset_removes_it(self):
        from wama.common.models import UserAppSetting
        from wama.common.utils import user_settings as us
        checked = []
        for app, schema, kwargs in _derived_apps():
            p = self._numeric_panel_param(schema, kwargs)
            if p is None:
                continue
            with self.subTest(app=app):
                name = p['name']
                fresh = us.read_panel_settings(self.user, app, schema, **kwargs)
                self.assertEqual(p.get('default'), fresh.get(name))
                chosen = p['max'] if p.get('default') != p['max'] else p['min']
                us.save_panel_settings(self.user, app, schema, {name: str(chosen)}, **kwargs)
                self.assertEqual(chosen, us.read_panel_settings(self.user, app, schema,
                                                                **kwargs)[name])
                us.reset_panel_settings(self.user, app, schema, **kwargs)
                self.assertEqual(p.get('default'), us.read_panel_settings(
                    self.user, app, schema, **kwargs)[name])
                self.assertFalse(UserAppSetting.objects.filter(user=self.user, app=app).exists(),
                                 'a reset must remove the preferences, not rewrite them')
                checked.append(app)
        self.assertIn('anonymizer', checked)

    def test_an_empty_number_never_overwrites_a_setting(self):
        from wama.common.utils import user_settings as us
        for app, schema, kwargs in _derived_apps():
            p = self._numeric_panel_param(schema, kwargs)
            if p is None:
                continue
            with self.subTest(app=app):
                self.assertEqual({}, us.save_panel_settings(self.user, app, schema,
                                                            {p['name']: ''}, **kwargs))

    def test_saving_the_default_value_keeps_no_preference(self):
        """The panel posts ALL its values at each gesture: keeping the defaults would freeze
        them, and a default changed later in the schema would reach nobody."""
        from wama.common.models import UserAppSetting
        from wama.common.utils import user_settings as us
        for app, schema, kwargs in _derived_apps():
            p = self._numeric_panel_param(schema, kwargs)
            if p is None or p.get('default') is None:
                continue
            with self.subTest(app=app):
                chosen = p['max'] if p.get('default') != p['max'] else p['min']
                us.save_panel_settings(self.user, app, schema, {p['name']: str(chosen)}, **kwargs)
                us.save_panel_settings(self.user, app, schema,
                                       {p['name']: str(p['default'])}, **kwargs)
                self.assertFalse(UserAppSetting.objects.filter(user=self.user, app=app).exists())

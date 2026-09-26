"""The right PANEL and the USER SETTINGS are the same list — for every app, from its schema.

Contract 3 of `WAMA_VERIFICATION §8` (2026-09-26). The panel is the surface of a user's
defaults: every setting it shows is one the user keeps, and the list of kept settings is DERIVED
from the schema (`params.USER_SETTINGS_DEFAULTS` = `param_schema.panel_defaults`), never written
by hand next to it — a hand list is how the transcriber's speech filter was shown in the panel
and never read.

Apps that still keep a hand-written list are named below: the list can only SHRINK.
"""
import importlib

from django.test import SimpleTestCase

#: Apps whose user settings are still a hand-written list in their views (measured 2026-09-26 —
#: the `wama:redondance-ok` lines of `get_user_app_settings` calls). Porting one = declaring
#: `USER_SETTINGS_DEFAULTS` in its params.py, as imager and transcriber do.
NOT_YET_DERIVED = {'avatarizer', 'composer', 'converter', 'describer', 'reader', 'synthesizer',
                   # their own `UserSettings` table, outside the common brick (ROADMAP §23.3bis)
                   'anonymizer', 'enhancer'}


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

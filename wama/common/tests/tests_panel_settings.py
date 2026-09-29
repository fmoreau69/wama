"""User settings of the right PANEL, derived from the schema — the helpers ported from the imager
to `param_schema` on 2026-09-26 (storage key = the panel dom_id by default, or declared)."""
from django.test import SimpleTestCase

from wama.common.utils.param_schema import (
    panel_defaults, panel_dom_id, panel_prefs_from_post, panel_values_by_name)

SCHEMA = [
    {'name': 'model', 'default': 'auto', 'contexts': ('item', 'panel'),
     'dom_id': {'panel': 'modelSelect', 'item': 'settingsModel'}},
    {'name': 'quality', 'default': 85, 'contexts': ('item', 'panel'), 'dom_id': 'qualityRange'},
    {'name': 'only_in_modal', 'default': 1, 'contexts': ('item',), 'dom_id': 'modalOnly'},
    {'name': 'no_dom_id', 'default': True, 'contexts': ('item', 'panel'), 'dom_id': ''},
]


def by_name(p):
    return p['name'] if 'panel' in p['contexts'] else None


class PanelSettingsTest(SimpleTestCase):

    def test_the_default_key_is_the_panel_dom_id_in_both_forms(self):
        self.assertEqual(['modelSelect', 'qualityRange', None, None],
                         [panel_dom_id(p) for p in SCHEMA])

    def test_only_panel_params_are_user_settings(self):
        self.assertEqual({'modelSelect': 'auto', 'qualityRange': 85}, panel_defaults(SCHEMA))
        self.assertEqual({'model': 'auto', 'quality': 85, 'no_dom_id': True},
                         panel_defaults(SCHEMA, key=by_name))

    def test_stored_values_come_back_by_param_name(self):
        stored = {'modelSelect': 'flux', 'qualityRange': 70, 'modalOnly': 9}
        self.assertEqual({'model': 'flux', 'quality': 70}, panel_values_by_name(stored, SCHEMA))

    def test_a_deposit_keeps_only_what_it_posts(self):
        """A key missing from the POST must not overwrite a stored setting."""
        self.assertEqual({'qualityRange': '60'},
                         panel_prefs_from_post({'quality': '60', 'only_in_modal': '3'}, SCHEMA))
        self.assertEqual({'model': 'x'}, panel_prefs_from_post({'model': 'x'}, SCHEMA, key=by_name))

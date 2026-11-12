"""The right PANEL and the USER SETTINGS are the same list — for every app, from its schema.

Contract 3 of `WAMA_VERIFICATION §8` (2026-09-26). The panel is the surface of a user's
defaults: every setting it shows is one the user keeps. Since 2026-11-12 the list of kept settings
and their storage key are derived by the common brick ALONE (`param_schema.setting_key`:
`<domain>.<name>` of a remembered param) — an app declares neither a key rule nor a list of
defaults next to its schema; a hand list is how the transcriber's speech filter was shown in the
panel and never read, and three key rules had grown side by side.
"""
import importlib

from django.test import SimpleTestCase, TestCase


def _apps():
    """(app, params module, declared schemas) for every non-sandbox app declaring a schema."""
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


def _derived_apps():
    """(app, schema, brick kwargs) for every DOMAIN of every app — the brick is told the domain,
    and the settings outside the schema (`PANEL_SETTINGS`) go with the domain that carries the
    principal schema (`app_modes.home_domain`)."""
    from wama.common.utils import app_modes
    out = []
    for app, module, _declared in _apps():
        home = app_modes.home_domain(app)
        for d in app_modes.get_domains(app):
            kwargs = dict(getattr(module, 'PANEL_SETTINGS', None) or {}) if d['id'] == home else {}
            out.append((app, app_modes.domain_schema(app, d['id']), dict(kwargs, domain=d['id'])))
    return out


class PanelUserSettingsTest(SimpleTestCase):

    def test_every_panel_setting_of_every_domain_is_kept_under_its_domain(self):
        from wama.common.utils.param_schema import _pget, remembered, setting_key
        checked = 0
        for app, schema, kwargs in _derived_apps():
            key = setting_key(app, schema)          # the rule the brick finds WITHOUT being told
            with self.subTest(app=app, domain=kwargs['domain']):
                for p in schema:
                    expected = f"{kwargs['domain']}.{_pget(p, 'name')}" if remembered(p) else None
                    self.assertEqual(expected, key(p))
                    checked += bool(expected)
        self.assertGreaterEqual(checked, 100, 'the fleet keeps more than a hundred panel settings')

    def test_no_app_carries_its_own_key_rule_or_list_of_defaults(self):
        """The three rules of before 2026-11-12 cannot come back: nothing to declare in params.py."""
        own = {app: [n for n in ('user_setting_key', 'USER_SETTINGS_DEFAULTS') if hasattr(module, n)]
               for app, module, _declared in _apps()}
        self.assertEqual({}, {app: names for app, names in own.items() if names})

    def test_a_name_two_domains_share_is_refused_when_nothing_tells_them_apart(self):
        # Counter-check: the rule never guesses a domain.
        from unittest import mock
        from wama.common.utils import app_modes
        from wama.common.utils.param_schema import setting_key
        both = {'name': 'model', 'contexts': ['panel']}
        domains = [{'id': 'a', 'params_schema': 'A'}, {'id': 'b', 'params_schema': 'B'}]
        schemas = {'a': [both, {'name': 'only_a', 'contexts': ['panel']}], 'b': [both]}
        with mock.patch.object(app_modes, 'get_domains', return_value=domains), \
                mock.patch.object(app_modes, 'domain_schema', side_effect=lambda app, d: schemas[d]):
            self.assertEqual('a.model', setting_key('x', schemas['a'])(both))
            self.assertEqual('b.model', setting_key('x', [both], domain='b')(both))
            with self.assertRaises(ValueError):
                setting_key('x', [both])(both)
            # Two domains on ONE schema are not told apart by their settings: the first declared.
            schemas['a'] = schemas['b']
            self.assertEqual('a.model', setting_key('x', [both])(both))


class PanelSettingsBrickTest(TestCase):
    """The common brick (`user_settings.*_panel_*`, 2026-09-27) behaves the same for EVERY
    derived app: a fresh user reads the schema defaults, a saved value comes back, a reset gives
    the defaults back — by removing the preference, never by writing today's default."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create_user('panel_brick', password='x')

    def _numeric_panel_param(self, schema, kwargs):
        from wama.common.utils.param_schema import domain_key
        key = domain_key(kwargs['domain'])
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
        self.assertGreater(len(checked), len(set(checked)), 'an app with two domains is read twice')

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

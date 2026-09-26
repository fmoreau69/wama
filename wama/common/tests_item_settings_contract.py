"""The settings route of an ELEMENT (`<app>:update_settings`) — ONE contract, every app.

Generalised on 2026-09-26 (`WAMA_VERIFICATION §8`, contract 1): the behaviour was tested app by
app (reader, enhancer, transcriber, converter), and `ItemEditRouteConventionTest` only checks the
route's name and path. Here, for EVERY app of the catalogue whose route takes an element id, with
a witness element built from its model and fields chosen from its schema — no app named:

  * the ⚙ modal's FormData AND the inspector's JSON both write the posted setting;
  * a post touches only what it carries;
  * a value outside the model field's choices is ignored, never written.
"""
import json

from django.db import models
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from wama.common.tests_queue_delete_contract import _instance


def _surfaces():
    """(app, element model, schema) for every app whose `update_settings` takes an element id."""
    from wama.common.app_registry import APP_CATALOG
    from wama.common.sandbox import twins_with_copied_views
    from wama.common.utils.param_schema import schema_for_app
    from wama.common.utils.preview_registry import PreviewRegistry
    copied = twins_with_copied_views()
    out = []
    for app, spec in APP_CATALOG.items():
        if app in copied or (spec or {}).get('sandbox'):
            continue      # sandbox twin: compared to its source, never measured on its own
        try:
            reverse(f'{app}:update_settings', args=[1])
        except NoReverseMatch:
            continue          # no route, or a route without an element id (a GLOBAL settings route)
        model = PreviewRegistry.get_model(app)
        schema = schema_for_app(app)
        if model is not None and schema:
            out.append((app, model, schema))
    return out


def _choice_fields(model, schema):
    """The schema's ELEMENT settings that are model fields with a closed list of choices."""
    fields = {f.name: f for f in model._meta.concrete_fields}
    out = []
    for p in schema:
        f = fields.get(p.get('name'))
        if f is None or 'item' not in (p.get('contexts') or ()) or p.get('type') == 'hidden':
            continue
        values = [c[0] for c in (f.choices or ()) if c[0] not in ('', None)]
        if len(values) >= 2 and isinstance(f, models.CharField):
            out.append((f.name, values))
    return out


def _writable_fields(model, schema):
    """Element settings the contract can WRITE: closed lists first, then toggles and free text —
    so an app whose selects draw their options from a catalogue is still measured."""
    fields = {f.name: f for f in model._meta.concrete_fields}
    out = list(_choice_fields(model, schema))
    for p in schema:
        f = fields.get(p.get('name'))
        if f is None or 'item' not in (p.get('contexts') or ()) or f.choices:
            continue
        if p.get('type') == 'toggle' and isinstance(f, models.BooleanField):
            out.append((f.name, [True, False]))
        elif p.get('type') in ('text', 'textarea') and isinstance(f, (models.CharField,
                                                                        models.TextField)):
            out.append((f.name, ['wama contract a', 'wama contract b']))
    return out


def _posted(value):
    """A value as the ⚙ modal's FormData carries it."""
    return ('true' if value else 'false') if isinstance(value, bool) else value


class ItemSettingsRouteContractTest(TestCase):

    def _login_for(self, app):
        from wama.common.app_registry import APP_CATALOG
        from wama.common.services.nightly_tests import get_test_dev_user, get_test_user
        user = (get_test_dev_user() if (APP_CATALOG.get(app) or {}).get('generated_from')
                else get_test_user())
        self.client.force_login(user)
        return user

    def test_the_fleet_is_measured(self):
        """Non-vacuity: without the apps, the sub-tests would guard nothing."""
        surfaces = _surfaces()
        self.assertGreaterEqual(len(surfaces), 8, [a for a, *_ in surfaces])
        unmeasured = [a for a, m, s in surfaces if not _writable_fields(m, s)]
        self.assertEqual([], unmeasured, 'apps whose settings route this contract cannot write')

    def test_form_data_and_json_both_write_only_what_they_post(self):
        for app, model, schema in _surfaces():
            fields = _writable_fields(model, schema)
            if not fields:
                continue
            with self.subTest(app=app):
                user = self._login_for(app)
                item = _instance(model, user)
                url = reverse(f'{app}:update_settings', args=[item.pk])
                name, values = fields[0]
                other = fields[1] if len(fields) > 1 else None
                other_before = getattr(item, other[0]) if other else None

                target = next(v for v in values if v != getattr(item, name))
                r = self.client.post(url, {name: _posted(target)})         # the ⚙ modal
                self.assertEqual(200, r.status_code, r.content[:300])
                item.refresh_from_db()
                self.assertEqual(getattr(item, name), target, 'FormData not written')

                target = next(v for v in values if v != getattr(item, name))
                r = self.client.post(url, json.dumps({name: target}),     # the inspector
                                     content_type='application/json')
                self.assertEqual(200, r.status_code, r.content[:300])
                item.refresh_from_db()
                self.assertEqual(getattr(item, name), target, 'JSON not written')
                if other:
                    self.assertEqual(getattr(item, other[0]), other_before,
                                     f'`{other[0]}` changed although it was not posted')

    def test_a_value_outside_the_choices_is_ignored(self):
        for app, model, schema in _surfaces():
            fields = _choice_fields(model, schema)
            if not fields:
                continue
            with self.subTest(app=app):
                user = self._login_for(app)
                item = _instance(model, user)
                name, _values = fields[0]
                before = getattr(item, name)
                r = self.client.post(reverse(f'{app}:update_settings', args=[item.pk]),
                                     json.dumps({name: 'not-a-choice'}),
                                     content_type='application/json')
                self.assertEqual(200, r.status_code, r.content[:300])
                item.refresh_from_db()
                self.assertEqual(getattr(item, name), before, f'`{name}` took a value outside its choices')

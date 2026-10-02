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

from wama.common.tests.tests_queue_delete_contract import _instance


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


# ── The batch ⚙ — the SAME rules as the element route (2026-10-02) ───────────────────────────

#: Apps whose batch settings view still applies the settings with code of its own, next to the
#: element route — declared with the reason, removed when the app is ported. An exemption that
#: is no longer needed fails the test.
BATCH_SETTINGS_STILL_LOCAL = {}


def _batch_surfaces():
    """(app, element model, schema, batch route) for every measured app that has batches."""
    from wama.common.utils.batch_common import batch_model_for
    out = []
    for app, model, schema in _surfaces():
        if batch_model_for(model) is None:
            continue
        try:
            reverse(f'{app}:batch_update', args=[1])
        except NoReverseMatch:
            out.append((app, model, schema, None))
            continue
        out.append((app, model, schema, f'{app}:batch_update'))
    return out


def _numeric_fields(model, schema):
    """The schema's bounded numeric settings that are model columns — (name, [min, max])."""
    fields = {f.name: f for f in model._meta.concrete_fields}
    out = []
    for p in schema:
        f = fields.get(p.get('name'))
        if f is None or 'item' not in (p.get('contexts') or ()):
            continue
        if p.get('type') == 'intent':
            out.append((f.name, [20, 80]))
        elif (p.get('type') in ('range', 'number') and p.get('min') is not None
              and p.get('max') is not None and p['min'] != p['max']
              and isinstance(f, (models.IntegerField, models.FloatField))):
            out.append((f.name, [p['min'], p['max']]))
    return out


def _batch_postable(schema):
    """Names of the settings the batch ⚙ can POST: those the schema declares for the `batch`
    context — or, when it declares none, the element ones (the batch then reuses the element
    modal: enhancer). A prompt is the text of ONE element: no batch modal carries it."""
    declared = {p['name'] for p in schema if 'batch' in (p.get('contexts') or ())}
    return declared or {p['name'] for p in schema if 'item' in (p.get('contexts') or ())}


def _settings_of(item, model, schema):
    """What the settings routes may write on `item`: its schema settings that are model fields."""
    fields = {f.name for f in model._meta.concrete_fields}
    item.refresh_from_db()
    return {p['name']: getattr(item, p['name']) for p in schema if p.get('name') in fields}


class BatchSettingsFollowTheItemRouteTest(TestCase):
    """The ⚙ of a BATCH writes on every daughter what the element route writes on ONE element.

    Measured on 2026-10-02: in six apps the batch view re-wrote the rules of the element route
    next to it (its own reading of the POST, its own validation, its own derived fields) — two
    codes for one rule, and the batch one had lost validations along the way. The factory now
    calls the app's ONE function (`make_batch_views(apply_settings=…)`), or the common
    declarative path. No app is named here: the same payload goes to both routes and the
    outcomes are compared.
    """

    _login_for = ItemSettingsRouteContractTest._login_for

    def test_the_fleet_is_measured(self):
        surfaces = _batch_surfaces()
        self.assertGreaterEqual(len(surfaces), 8, [a for a, *_ in surfaces])
        routeless = sorted(a for a, _m, _s, route in surfaces if route is None)
        self.assertEqual([], routeless, 'apps with batches but no `<app>:batch_update` route')
        stale = sorted(set(BATCH_SETTINGS_STILL_LOCAL) - {a for a, *_ in surfaces})
        self.assertEqual([], stale, 'exemptions naming no measured app')

    def _both_routes(self, app, model, schema, route, payload):
        """Post `payload` to the element route (one lone element) and to the batch route (two
        daughters). Returns the lone element's settings BEFORE, then (status, settings) of the
        lone element and of each daughter AFTER."""
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        user = self._login_for(app)
        lone = _instance(model, user)
        before = _settings_of(lone, model, schema)
        lot, daughters = _lot_de(model, user, 2)
        r_item = self.client.post(reverse(f'{app}:update_settings', args=[lone.pk]), payload)
        r_lot = self.client.post(reverse(route, args=[lot.pk]), payload)
        return (before, (r_item.status_code, _settings_of(lone, model, schema)),
                [(r_lot.status_code, _settings_of(d, model, schema)) for d in daughters])

    def _compare(self, pick_fields, payload_for, must_write):
        """Every setting the batch ⚙ can post, one at a time, on both routes. Returns the
        measured (app, setting) pairs and the exemptions that are no longer needed.
        `must_write`: a setting the element route does not write is not a measure (skipped)."""
        measured, diverging = [], {}
        for app, model, schema, route in _batch_surfaces():
            if route is None:
                continue
            postable = _batch_postable(schema)
            for name, values in pick_fields(model, schema):
                if name not in postable:
                    continue
                before, item_outcome, daughter_outcomes = self._both_routes(
                    app, model, schema, route, payload_for(model, name, values))
                if must_write and item_outcome[1] == before:
                    continue
                measured.append((app, name))
                if any(outcome != item_outcome for outcome in daughter_outcomes):
                    diverging.setdefault(app, []).append(
                        f'{name}: element {item_outcome} / batch {daughter_outcomes[0]}')
        for app in sorted(set(diverging) - set(BATCH_SETTINGS_STILL_LOCAL)):
            with self.subTest(app=app):
                self.fail('the batch does not write what the element route writes — '
                          + ' ; '.join(diverging[app]))
        needless = sorted(a for a in BATCH_SETTINGS_STILL_LOCAL
                          if a not in diverging and any(m[0] == a for m in measured))
        return measured, needless

    def test_a_batch_writes_on_each_daughter_what_the_item_route_writes(self):
        def payload(model, name, values):
            default = model._meta.get_field(name).get_default()
            return {name: _posted(next(v for v in values if v != default))}
        measured, needless = self._compare(
            lambda model, schema: _writable_fields(model, schema) + _numeric_fields(model, schema),
            payload, must_write=True)
        with_batches = {a for a, _m, _s, route in _batch_surfaces() if route}
        self.assertEqual(sorted(with_batches), sorted({app for app, _name in measured}),
                         'apps with batches where NO setting could be compared')
        self.assertEqual([], needless, 'exemptions no longer needed — remove them')

    def test_a_value_the_item_route_ignores_is_ignored_by_the_batch(self):
        measured, _needless = self._compare(
            _choice_fields, lambda model, name, values: {name: 'not-a-choice'}, must_write=False)
        self.assertGreaterEqual(len({app for app, _name in measured}), 3, measured)

    def test_no_app_keeps_a_batch_settings_view_of_its_own(self):
        """The copy must not come back: every `<app>:batch_update` IS the factory's view."""
        from django.urls import resolve
        for app, _model, _schema, route in _batch_surfaces():
            if route is None or app in BATCH_SETTINGS_STILL_LOCAL:
                continue
            with self.subTest(app=app):
                view = resolve(reverse(route, args=[1])).func
                self.assertEqual('wama.common.utils.batch_views', view.__module__,
                                 f'{app}: `{view.__name__}` is written in the app')

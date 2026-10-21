"""A DOMAIN names its settings schema; its element and an element's domain are DERIVED (2026-10-21).

Fabien: « un seul fonctionnement commun, universel, que toute app récupère ». Measured before:
the link domain ↔ settings ↔ element was code, written three ways — the enhancer by two element
models and two families of views, the imager by `is_video_generation` tested in five places, the
other apps by a single implicit domain. And the only per-mode `settings` lists (enhancer) had no
reader anywhere (JS, Python, manifest, API, tests) and named model COLUMNS, not params.

Now the declaration (`app_modes.APP_MODES`) says, per domain, the one thing nothing else says —
its schema (`params_schema`) — and everything else is read where it is already declared: the
surface of a domain (`route_prefix` + app) is the key of its element model in the detail
registry; when two domains share a model, the schema the detail spec picks per element names the
domain. No app is named below except to build witness elements.
"""
from unittest import mock

from django.test import SimpleTestCase

from wama.common.utils import app_modes
from wama.common.utils.app_modes import (APP_MODES, domain_schema, domain_schema_name,
                                         domain_surface, element_domain, surface_domains)
from wama.common.utils.detail_registry import DetailRegistry

#: The vocabulary a declaration may use — a key outside it is read by nothing (the per-mode
#: `settings` lists were exactly that, and drifted for four months without a signal).
DOMAIN_KEYS = {'id', 'label', 'icon', 'variant', 'accepts', 'params_schema', 'route_prefix',
               'mode_param', 'inputs', 'library_natures', 'modes'}
MODE_KEYS = {'id', 'label', 'icon', 'variant', 'realtime', 'inputs'}


def _domains():
    return [(app, d['id']) for app, decl in sorted(APP_MODES.items()) for d in decl.get('domains', [])]


class DeclarationVocabularyTest(SimpleTestCase):

    def test_a_domain_and_a_mode_only_use_the_known_vocabulary(self):
        for app, decl in sorted(APP_MODES.items()):
            for d in decl.get('domains', []):
                with self.subTest(app=app, domain=d['id']):
                    self.assertEqual(set(), set(d) - DOMAIN_KEYS, 'keys no reader knows')
                    for m in d.get('modes', []):
                        self.assertEqual(set(), set(m) - MODE_KEYS,
                                         f"mode {m.get('id')}: keys no reader knows")


class EveryDomainHasItsSchemaTest(SimpleTestCase):

    def test_the_fleet_is_measured(self):
        self.assertGreaterEqual(len(_domains()), 12, _domains())

    def test_every_domain_resolves_a_schema(self):
        for app, dom in _domains():
            with self.subTest(app=app, domain=dom):
                self.assertTrue(domain_schema(app, dom), 'no settings schema behind this domain')

    def test_the_domains_of_an_app_have_distinct_schemas(self):
        """The doctrine's criterion (`MODES_QUEUE_UX §2bis`): a domain exists because its
        SETTINGS diverge — so every domain of a multi-domain app names its own schema."""
        for app, decl in sorted(APP_MODES.items()):
            ids = [d['id'] for d in decl.get('domains', [])]
            if len(ids) < 2:
                continue
            names = [domain_schema_name(app, d) for d in ids]
            with self.subTest(app=app):
                self.assertTrue(all(names), f'a domain of {app} names no schema: {dict(zip(ids, names))}')
                self.assertEqual(len(names), len(set(names)), f'two domains, one schema: {names}')

    def test_an_undeclared_schema_is_the_main_one(self):
        from wama.common.utils.param_schema import schema_for_app
        for app, dom in _domains():
            if domain_schema_name(app, dom):
                continue
            with self.subTest(app=app, domain=dom):
                self.assertEqual(schema_for_app(app), domain_schema(app, dom))


class EveryDomainHasItsElementTest(SimpleTestCase):

    def test_the_surface_of_every_domain_registers_an_element_model(self):
        for app, dom in _domains():
            entry = DetailRegistry.get(domain_surface(app, dom))
            with self.subTest(app=app, domain=dom, surface=domain_surface(app, dom)):
                self.assertTrue(entry and entry.get('model'), 'no element model for this domain')
                self.assertEqual(app, entry['model']._meta.app_label)

    def test_a_shared_surface_picks_the_schema_of_each_of_its_domains_per_element(self):
        """Two domains, one element model: the detail spec's per-element choice must be able to
        name each domain's schema — otherwise an element could belong to no domain."""
        for app, decl in sorted(APP_MODES.items()):
            for surface in sorted({domain_surface(app, d['id']) for d in decl.get('domains', [])}):
                served = surface_domains(app, surface)
                if len(served) < 2:
                    continue
                form = ((DetailRegistry.get(surface) or {}).get('spec') or {}).get('params_schema')
                picks = ({form.get('then'), form.get('else')} if isinstance(form, dict) and 'when_any' in form
                         else {form.get('const')} if isinstance(form, dict) else set())
                with self.subTest(app=app, surface=surface):
                    self.assertEqual({domain_schema_name(app, d) for d in served}, picks - {None})


def _witness(model, truthy_fields=(), falsy=False):
    """An unsaved element whose named attributes (fields or properties) read true — or false."""
    element = model()
    patches = []
    concrete = {f.name for f in model._meta.concrete_fields}
    for name in truthy_fields:
        if name in concrete:
            setattr(element, name, None if falsy else 'x')
        else:
            patches.append(mock.patch.object(model, name, new_callable=mock.PropertyMock,
                                             return_value=not falsy))
    return element, patches


class ElementDomainTest(SimpleTestCase):

    def test_every_domain_is_found_back_from_an_element_of_its_model(self):
        for app, decl in sorted(APP_MODES.items()):
            for surface in sorted({domain_surface(app, d['id']) for d in decl.get('domains', [])}):
                model = DetailRegistry.get(surface)['model']
                served = surface_domains(app, surface)
                form = (DetailRegistry.get(surface).get('spec') or {}).get('params_schema')
                cases = [(_witness(model), served[0])] if len(served) == 1 else [
                    (_witness(model, form['when_any']), next(
                        d for d in served if domain_schema_name(app, d) == form['then'])),
                    (_witness(model, form['when_any'], falsy=True), next(
                        d for d in served if domain_schema_name(app, d) == form['else']))]
                for (element, patches), expected in cases:
                    with self.subTest(app=app, surface=surface, expected=expected):
                        for p in patches:
                            p.start()
                        try:
                            self.assertEqual(expected, element_domain(element))
                        finally:
                            for p in patches:
                                p.stop()

    def test_an_object_outside_the_registry_has_no_domain(self):
        self.assertIsNone(element_domain(object()))


class TheSettingsOfAnElementAreThoseOfItsDomainTest(SimpleTestCase):
    """The inspector reads the schema of the element's domain — the audio surface of the
    enhancer no longer copies its schema name as a constant in its spec."""

    def test_the_detail_spec_of_a_single_domain_surface_names_no_schema(self):
        for app, dom in _domains():
            surface = domain_surface(app, dom)
            if len(surface_domains(app, surface)) != 1:
                continue
            spec = (DetailRegistry.get(surface) or {}).get('spec') or {}
            with self.subTest(surface=surface):
                self.assertNotIn('params_schema', spec,
                                 'the domain names it (app_modes) — a second copy would drift')

    def test_the_element_schema_is_the_domain_schema(self):
        from wama.common.utils.detail_registry import spec_schema
        for app, dom in _domains():
            surface = domain_surface(app, dom)
            if len(surface_domains(app, surface)) != 1:
                continue
            entry = DetailRegistry.get(surface)
            with self.subTest(surface=surface):
                self.assertEqual(domain_schema(app, dom),
                                 spec_schema(entry['model'](), entry.get('spec') or {}, surface))


class StartToolFollowsTheSurfaceTest(SimpleTestCase):

    def test_the_start_tool_of_a_prefixed_domain_is_the_one_of_its_surface(self):
        from wama import tool_api
        from wama.common.services.scheduled_actions import start_tool_for
        for app, dom in _domains():
            prefix = app_modes.route_prefix(app, dom)
            if not prefix:
                continue
            surface = domain_surface(app, dom)
            if f'start_{surface}' not in tool_api.TOOL_REGISTRY:
                continue
            with self.subTest(surface=surface):
                self.assertEqual(f'start_{surface}', start_tool_for(app, prefix))

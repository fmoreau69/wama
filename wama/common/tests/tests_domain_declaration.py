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
from pathlib import Path
from unittest import mock

from django.test import RequestFactory, SimpleTestCase, TestCase

from wama.common.utils import app_modes
from wama.common.utils.app_modes import (APP_MODES, domain_schema, domain_schema_name,
                                         domain_surface, element_domain, surface_domains)
from wama.common.utils.detail_registry import DetailRegistry

#: The vocabulary a declaration may use — a key outside it is read by nothing (the per-mode
#: `settings` lists were exactly that, and drifted for four months without a signal).
DOMAIN_KEYS = {'id', 'label', 'icon', 'variant', 'description', 'accepts', 'params_schema', 'route_prefix',
               'mode_param', 'inputs', 'library_natures', 'extension_natures', 'modes'}
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


def _apps_without_a_named_domain(apps):
    """Apps that declare no domain, or an implicit one (`default`) — the rule of `app_modes`:
    « un domaine est TOUJOURS déclaré et NOMMÉ, même seul »."""
    out = []
    for app in apps:
        ids = [d.get('id') for d in app_modes.get_domains(app)]
        if not ids or not all(ids) or 'default' in ids or len(ids) != len(set(ids)):
            out.append((app, ids))
    return out


class EveryAppDeclaresANamedDomainTest(SimpleTestCase):
    """2026-11-12: the rule was written and held by nothing — the guards below loop over
    `APP_MODES`, so an app absent from it passed in silence. It is what lets a SECOND domain be
    added to any app later: there is always a first one to stand next to."""

    def test_every_app_of_the_catalogue_has_at_least_one_named_domain(self):
        from wama.common.app_registry import APP_CATALOG
        self.assertGreaterEqual(len(APP_CATALOG), 10)
        self.assertEqual([], _apps_without_a_named_domain(sorted(APP_CATALOG)))

    def test_an_app_without_a_domain_or_with_an_implicit_one_is_reported(self):
        # Counter-check: the measure sees what it is meant to see.
        answers = {'none': {}, 'implicit': {'domains': [{'id': 'default'}]},
                   'named': {'domains': [{'id': 'lecture'}]}}
        with mock.patch.object(app_modes, 'get_app_modes', side_effect=answers.get):
            self.assertEqual([('implicit', ['default']), ('none', [])],
                             _apps_without_a_named_domain(sorted(answers)))


class ADomainOneCanChooseSaysWhatItDoesTest(SimpleTestCase):
    """2026-11-12: the domain is chosen in the page TITLE; the menu, the subtitle and « À propos »
    say what each one does — so every domain of an app that has several declares its sentence."""

    def test_every_domain_of_an_app_with_several_says_what_it_does(self):
        silent = [(app, d['id']) for app, decl in sorted(APP_MODES.items())
                  if len(decl.get('domains', [])) > 1
                  for d in decl['domains'] if not (d.get('description') or '').strip()]
        self.assertEqual([], silent)

    def test_the_measure_sees_a_silent_domain(self):
        # Counter-check, on a declaration of the same shape.
        fake = {'x': {'domains': [{'id': 'a', 'description': 'Does a.'}, {'id': 'b'}]}}
        with mock.patch.dict(APP_MODES, fake, clear=True):
            silent = [(app, d['id']) for app, decl in sorted(APP_MODES.items())
                      if len(decl.get('domains', [])) > 1
                      for d in decl['domains'] if not (d.get('description') or '').strip()]
        self.assertEqual([('x', 'b')], silent)


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
                with self.subTest(app=app, surface=surface):
                    self.assertEqual({domain_schema_name(app, d) for d in served}, _picks(form) - {None})

    def test_the_element_of_a_domain_with_its_own_routes_reaches_the_manifest(self):
        """A domain that declares a route prefix has an element of its OWN (its surface): the
        manifest carries it beside the app's (`processing.elements`), measured the same way, and a
        generator reads it as the element of an app (`views_gen.element_bodies`)."""
        from wama.common.manifests.codegen.views_gen import element_bodies
        from wama.common.manifests.ingest import extract
        from wama.common.utils.batch_sync import SYNCED
        seen = 0
        for app, decl in sorted(APP_MODES.items()):
            own = {domain_surface(app, d['id']): d for d in decl.get('domains', [])
                   if d.get('route_prefix')}
            body = (extract('app', app) or {}).get('body') or {}
            elements = (body.get('processing') or {}).get('elements') or {}
            bodies = {surface: (prefix, derived)
                      for surface, prefix, derived in element_bodies(body, app)}
            with self.subTest(app=app):
                self.assertEqual(sorted(own), sorted(elements))
                self.assertEqual({''} | set(own), set(bodies))
                if not own:
                    self.assertIs(body, bodies[''][1], 'an app of one element renders its body')
                # The app's element keeps the routes and the tasks no domain element owns.
                main = bodies[''][1]['processing']
                prefixes = tuple(d['route_prefix'] + '_' for d in own.values())
                self.assertFalse([e for e in main.get('endpoints') or [] if prefixes
                                  and e.startswith(prefixes)])
                self.assertEqual(
                    sorted(e for e in body['processing'].get('endpoints') or []
                           if not (prefixes and e.startswith(prefixes))),
                    sorted(main.get('endpoints') or []))
            declared = {m['name'] for m in (body.get('data') or {}).get('models') or []}
            for surface, domain in sorted(own.items()):
                model = DetailRegistry.get(surface)['model']
                entry, (prefix, derived) = elements[surface], bodies[surface]
                with self.subTest(app=app, surface=surface):
                    self.assertEqual(model.__name__, entry['item_model'])
                    self.assertNotEqual(body['processing']['item_model'], entry['item_model'])
                    self.assertEqual(surface_domains(app, surface), entry['domains'])
                    self.assertEqual(DetailRegistry.get(surface)['spec'],
                                     entry['inspector']['detail_spec'])
                    # Its batch link is the registered one that points ITS model.
                    link = next(m for m in SYNCED if m.__name__ == entry['batch_link_model'])
                    self.assertIn(model, [f.related_model for f in link._meta.fields if f.is_relation])
                    self.assertLessEqual({entry['item_model'], entry['batch_link_model'],
                                          entry['model_spec']['batch']['name']}, declared)
                    # The settings its columns hold are those of ITS schema.
                    names = {p['name'] for p in domain_schema(app, domain['id'])}
                    self.assertTrue(entry['model_spec']['item']['params_fields'])
                    self.assertLessEqual(set(entry['model_spec']['item']['params_fields']), names)
                    # For a generator: an app whose element is this one, without a prefix.
                    self.assertEqual(domain['route_prefix'], prefix)
                    self.assertEqual(entry['item_model'], derived['processing']['item_model'])
                    self.assertEqual(entry['model_spec'], derived['processing']['model_spec'])
                    self.assertEqual(entry['inspector'], derived['inspector'])
                    self.assertEqual(domain_schema_name(app, domain['id']),
                                     derived['params']['primary'])
                    self.assertEqual([domain['id']], [d['id'] for d in derived['modes']['domains']])
                    self.assertNotIn('route_prefix', derived['modes']['domains'][0])
                    self.assertNotIn('elements', derived['processing'])
                    # Its routes are those of its prefix, the prefix removed — the real app's names.
                    self.assertEqual(
                        sorted(e[len(prefix) + 1:] for e in body['processing']['endpoints']
                               if e.startswith(prefix + '_')),
                        sorted(derived['processing']['endpoints']))
                    self.assertTrue(derived['processing']['endpoints'])
                    # Its task is the one that hands ITS model to the skeleton, and only that one.
                    self.assertEqual([entry['item_model']],
                                     [t.get('model') for t in derived['processing']['tasks']])
                    self.assertNotIn(entry['item_model'],
                                     [t.get('model') for t in bodies[''][1]['processing']['tasks']])
                    # Its surface follows THE rule on the key one renders (a twin has its own).
                    self.assertEqual([f'{prefix}_{app}_01'], [
                        s for s, _p, _b in element_bodies(body, f'{app}_01') if s])
                    seen += 1
        self.assertGreater(seen, 0, 'no domain of the park has routes of its own')


def _picks(form) -> set:
    """The schema names a detail-spec form can give, whatever its shape."""
    if not isinstance(form, dict):
        return set()
    if 'when_any' in form:
        return {form.get('then'), form.get('else')}
    if 'map' in form:
        return set((form.get('map') or {}).values()) | {form.get('default')}
    return {form.get('const')}


def _cases(app, model, form, served):
    """(unsaved element, expected domain) — one per domain of a surface, built from its form."""
    if len(served) == 1:
        return [((model(), []), served[0])]
    schema_of = {domain_schema_name(app, d): d for d in served}
    if 'map' in form:
        table = form.get('map') or {}
        out = [((model(**{form['field']: key}), []), schema_of[name]) for key, name in table.items()]
        if form.get('default'):
            out.append(((model(**{form['field']: 'wama_other'}), []),
                        schema_of[form['default']]))
        return out
    return [(_witness(model, form['when_any']), schema_of[form['then']]),
            (_witness(model, form['when_any'], falsy=True), schema_of[form['else']])]


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
                for (element, patches), expected in _cases(app, model, form, served):
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

    def test_the_batches_of_a_page_are_ranged_by_the_domain_of_their_first_element(self):
        """`batch_common.batches_by_domain` (2026-11-15, `ROUTE §11 #42` ⑦ b): one list per domain
        the app names, in the order of its declaration, by the rule of the card — two page views
        wrote it by hand. Both row shapes are read (a link carrying `elem`, the element itself)."""
        from types import SimpleNamespace

        from wama.common.utils.batch_common import batches_by_domain
        several = 0
        for app, decl in sorted(APP_MODES.items()):
            ids = [d['id'] for d in decl.get('domains', [])]
            rows, expected = [{'items': []}], {d: [] for d in ids}
            expected[ids[0]].append(rows[0])
            for surface in sorted({domain_surface(app, d) for d in ids}):
                model = DetailRegistry.get(surface)['model']
                form = (DetailRegistry.get(surface).get('spec') or {}).get('params_schema')
                for (element, more), domain in _cases(app, model, form, surface_domains(app, surface)):
                    if more:        # a property read on the class: one witness at a time
                        continue
                    for items in ([SimpleNamespace(elem=None), SimpleNamespace(elem=element)],
                                  [element]):
                        rows.append({'items': items})
                        expected[domain].append(rows[-1])
            several += len([d for d in ids if len(expected[d]) > (d == ids[0])]) > 1
            with self.subTest(app=app):
                found = batches_by_domain(app, rows)
                self.assertEqual(ids, list(found), 'one key per declared domain, in its order')
                self.assertEqual(expected, found)
        self.assertGreater(several, 1, 'the fleet holds apps whose page has several queues')
        self.assertEqual({}, batches_by_domain('wama_no_such_app', [{'items': []}]),
                         'no domain: the queue is one')


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

    def test_the_schema_of_any_element_is_read_once_for_its_domain(self):
        """`app_modes.element_schema` — the gear of a card, its ⚙, the writer of its settings and
        the settings of a drop read it (2026-11-02 : five copies in the imager and the
        anonymizer)."""
        from wama.common.utils.app_modes import element_schema, element_schema_name
        for app, decl in sorted(APP_MODES.items()):
            for surface in sorted({domain_surface(app, d['id']) for d in decl.get('domains', [])}):
                model = DetailRegistry.get(surface)['model']
                served = surface_domains(app, surface)
                form = (DetailRegistry.get(surface).get('spec') or {}).get('params_schema')
                for (element, patches), expected in _cases(app, model, form, served):
                    with self.subTest(app=app, surface=surface, expected=expected):
                        for p in patches:
                            p.start()
                        try:
                            self.assertEqual(domain_schema(app, expected), element_schema(element))
                            self.assertEqual(domain_schema_name(app, expected),
                                             element_schema_name(element))
                            # The card's ⚙ carries the settings of ITS domain (2026-11-18 : the
                            # anonymizer's document cards carried the image schema, without
                            # `ocr_scanned_pages` — nothing for the panel to reflect).
                            if hasattr(type(element), 'gear_data'):
                                from wama.common.utils.card_gear import gear_data
                                self.assertLessEqual(
                                    set(gear_data(element, domain_schema(app, expected))),
                                    set(element.gear_data))
                        finally:
                            for p in patches:
                                p.stop()


def _shared_surfaces():
    """(app, surface, model, form, served) for every surface that two domains or more share."""
    out = []
    for app, decl in sorted(APP_MODES.items()):
        for surface in sorted({domain_surface(app, d['id']) for d in decl.get('domains', [])}):
            served = surface_domains(app, surface)
            if len(served) > 1:
                entry = DetailRegistry.get(surface)
                out.append((app, surface, entry['model'],
                            (entry.get('spec') or {}).get('params_schema'), served))
    return out


class DomainsAreFoundInTheDatabaseTest(TestCase):
    """The SAME declaration finds a domain's elements in the database (2026-11-01): the queue and
    the bar of each tab (`app_modes.domain_filter`, `progress_views` without `domains=`). The
    imager wrote these filters by hand, with its own copy of the list of video modes."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user('domain_filter_owner', password='x')

    def test_the_fleet_has_a_shared_surface_to_measure(self):
        self.assertTrue(_shared_surfaces(), 'no surface shared by two domains: the guard is empty')

    def test_each_domain_filter_keeps_exactly_the_elements_of_its_domain(self):
        from wama.common.tests.tests_queue_delete_contract import _instance
        from wama.common.utils.app_modes import domain_filter
        for app, surface, model, form, served in _shared_surfaces():
            with self.subTest(surface=surface):
                made = {}
                for (element, _patches), expected in _cases(app, model, form, served):
                    field = form['field']
                    saved = _instance(model, self.user, **{field: getattr(element, field)})
                    made.setdefault(expected, set()).add(saved.pk)
                    self.assertEqual(expected, element_domain(saved))
                mine = model.objects.filter(pk__in=set().union(*made.values()))
                for dom in served:
                    kept = set(domain_filter(app, dom)(mine).values_list('pk', flat=True))
                    self.assertEqual(made.get(dom, set()), kept, f'{dom}: wrong elements')

    def test_the_progress_factory_gives_one_bar_per_shared_domain_without_being_told(self):
        """The bar the PAGE calls: the app's own `global_progress`, found among its routes. A
        factory rebuilt here with the defaults missed what the app passes it — the anonymizer's
        progress lives in `blur_progress` (2026-11-02, its `document` domain)."""
        import json
        for app, surface, model, _form, served in _shared_surfaces():
            with self.subTest(surface=surface):
                request = RequestFactory().get('/')
                request.user = self.user
                payload = json.loads(_wired_view(app, model, 'global_progress')(request).content)
                self.assertTrue(set(served) <= set(payload), payload)

    def test_a_wired_view_is_found_by_its_model_only(self):
        # Counterpart: the progress of ANOTHER model of the same app is not taken for this one.
        from django.contrib.auth.models import User
        for app, _surface, model, _form, _served in _shared_surfaces():
            with self.subTest(app=app):
                self.assertIsNone(_wired_view(app, User, 'global_progress', required=False))


def _wired_view(app, model, name, required=True):
    """The view `name` the app's routes serve for `model` — the factory marks its views with their
    model (`progress_views.make_progress_views`), decorators keep the mark."""
    from django.urls import get_resolver

    def callbacks(patterns):
        for pattern in patterns:
            if hasattr(pattern, 'url_patterns'):
                yield from callbacks(pattern.url_patterns)
            else:
                yield pattern.callback

    _prefix, resolver = get_resolver().namespace_dict[app]
    found = {cb for cb in callbacks(resolver.url_patterns)
             if getattr(cb, '__name__', '') == name and getattr(cb, 'work_model', None) is model}
    if not required and not found:
        return None
    assert len(found) == 1, f'{app}: {len(found)} wired view(s) {name} for {model.__name__}'
    return found.pop()

    def test_a_shared_surface_names_its_domains_by_a_field(self):
        """`when_any` reads properties, which no query filters: a shared surface that used it
        would have per-element domains and no queue. The derivation refuses it, saying so."""
        from wama.common.utils.app_modes import domain_filter
        for app, surface, _model, form, served in _shared_surfaces():
            with self.subTest(surface=surface):
                self.assertTrue(isinstance(form, dict) and form.get('field') and 'map' in form, form)
                for dom in served:
                    self.assertTrue(callable(domain_filter(app, dom)))

    def test_domains_the_spec_does_not_tell_apart_have_one_queue(self):
        """Une spec qui ne désigne le domaine d'AUCUNE façon : ses éléments ne se distinguent pas,
        une seule barre (la jumelle `translator_01`, deux domaines nés d'un manifeste sur un
        modèle — sa barre rendait une erreur serveur le jour de l'étape 1). Une spec qui les
        désigne par une propriété lève toujours, en le disant."""
        from wama.common.utils.app_modes import domain_filters
        shared = mock.patch.object(app_modes, 'surface_domains', return_value=['text', 'document'])
        with shared, mock.patch.object(DetailRegistry, 'get', return_value={'spec': {}}):
            self.assertEqual({}, domain_filters('twin', 'twin'))
        by_property = {'spec': {'params_schema': {'when_any': [], 'default': 'X'}}}
        with shared, mock.patch.object(DetailRegistry, 'get', return_value=by_property):
            with self.assertRaises(ValueError):
                domain_filters('twin', 'twin')


class TheSurfaceOfADomainLeadsBackToItsAppTest(SimpleTestCase):
    """2026-11-12 (`ROUTE §11 #42` ⑥) : the assistant kept a hand-written table of ONE pair
    (`audio_enhancer` → `enhancer`) and the grid wrote `audio_` in four criteria. Both are read
    from the declaration: a domain that gains its own routes enters without a line."""

    def test_every_surface_of_a_prefixed_domain_names_its_app(self):
        checked = 0
        for app, decl in sorted(APP_MODES.items()):
            for d in decl.get('domains', []):
                with self.subTest(app=app, domain=d['id']):
                    self.assertEqual(app, app_modes.surface_app(domain_surface(app, d['id'])))
                checked += bool(d.get('route_prefix'))
        self.assertGreaterEqual(checked, 1, 'the fleet has a domain with its own routes')

    def test_an_app_or_an_unknown_name_is_given_back(self):
        # Counter-check: nothing is invented for what no domain declares.
        self.assertEqual('reader', app_modes.surface_app('reader'))
        self.assertEqual('no_such_surface', app_modes.surface_app('no_such_surface'))

    def test_a_name_is_read_backwards_never_by_sweeping_the_catalogue(self):
        # Each row of the model list asks its SOURCE's identity (`app_identity` → `surface_app`) :
        # sweeping every app's domains for each one cost 11 112 reads, ~60 s a call under
        # gunicorn (2026-11-18). A model source reads no domain ; a surface reads its app's only.
        from unittest import mock
        with mock.patch.object(app_modes, 'get_domains', wraps=app_modes.get_domains) as read:
            self.assertEqual('openrouter', app_modes.surface_app('openrouter'))
            self.assertEqual(0, read.call_count)
            for app, decl in APP_MODES.items():
                for d in decl.get('domains', []):
                    if d.get('route_prefix'):
                        read.reset_mock()
                        self.assertEqual(app, app_modes.surface_app(domain_surface(app, d['id'])))
                        self.assertEqual({app}, {c.args[0] for c in read.call_args_list})

    def test_the_grid_and_the_assistant_read_the_declared_prefixes(self):
        from wama import tool_api
        from wama.common.services import conformity_checker
        prefixes = app_modes.route_prefixes()
        self.assertEqual(sorted({d['route_prefix'] for decl in APP_MODES.values()
                                 for d in decl.get('domains', []) if d.get('route_prefix')}), prefixes)
        for prefix in prefixes:
            self.assertRegex(f'{prefix}_delete', '^' + conformity_checker._ROUTE_PREFIX + 'delete$')
        self.assertRegex('delete', '^' + conformity_checker._ROUTE_PREFIX + 'delete$')
        self.assertNotRegex('delete', '^' + conformity_checker._ROUTE_PREFIX_REQUIRED + 'delete$')
        self.assertFalse(hasattr(tool_api, 'TOOL_APP_ALIAS'), 'the hand-written table is back')
        source = (Path(conformity_checker.__file__)).read_text(encoding='utf-8')
        self.assertNotRegex(source, r"\(\?:?audio_\)\?", 'a route prefix written by hand in a criterion')


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


class WhatASourceSaysInAdvanceTest(SimpleTestCase):
    """`surface_source_nature` (2026-11-14): what an address says before its file arrives is
    confronted with the surface — a video platform address was born « video » in an app that
    takes none. Measured over the fleet before the generated views were plugged onto it."""

    VIDEO = 'https://www.youtube.com/watch?v=abc'

    def test_a_platform_address_has_its_nature_only_where_a_domain_takes_it(self):
        answers = set()
        for app, domain in _domains():
            surface = app_modes.domain_surface(app, domain)
            taken = {t for d in app_modes.surface_domains(app, surface)
                     for t in app_modes.accepts(app, d)}
            expected = 'video' if 'video' in taken else None
            answers.add(expected)
            with self.subTest(app=app, surface=surface):
                self.assertEqual(expected, app_modes.surface_source_nature(app, surface, self.VIDEO))
                self.assertEqual('', app_modes.surface_source_nature(app, surface, 'https://x.org/page'),
                                 'an address that says nothing: the download will tell')
        self.assertEqual({'video', None}, answers, 'the fleet holds both cases')

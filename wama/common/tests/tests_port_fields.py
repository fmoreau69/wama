"""WHERE THE VALUE OF A PORT IS KEPT — one reader, `common/utils/port_fields` (2026-11-24).

Fabien : « une façon universelle, parfaitement alignée et pérenne » for the column of a port. Six
places copied the link port → field each for itself (the ingest target, the panel's spec, the lot
lines' `_LINE_FIELDS` / `COVER_FIELDS`, page JS, the extractor's « first FileField », the preview's
`file_field`) and three ports a card offers had none. The contract :
every port a card offers has the field that keeps its value, read by ONE reader ; a field the
element model lists exists ; the copies that remain say what the reader says.

The ports come from the models' capabilities : the test reads them in the VERSIONED corpus
(`manifests/models/`), the catalogue the base is projected from — the test base has none.
"""
import json
from collections import defaultdict
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase

#: (app, port) whose value no field keeps, with the reason — a list that can only shrink.
#: Emptied 2026-11-24 : the anonymizer's instruction is carried by its setting
#: (`ports_carried_elsewhere`), and a twin's catalogue entry is a copy of its source's
#: (`sandbox.py`, `copy.deepcopy(app_catalog[src])`), so `anonymizer_01` carries it too.
GAPS = {}
#: Twins whose `ready()` does not register the listing yet : it is projected by the extractor
#: (`inspector.port_fields`) and replayed by `apps_gen` in the twin's generated `apps.py` — every
#: twin's `apps.py` is generated, half of their `models.py` are copies (measured 2026-11-24). Can
#: only shrink.
#: Emptied 2026-11-24 : `anonymizer_01` regenerated (`app_sandbox substitute anonymizer_01 apps`)
#: once its source's new fields were committed.
TWINS_AWAITING_PROJECTION = set()
#: (app, field) a panel or a preview names that is the value of no port — with the reason. Can only
#: shrink.
NOT_A_PORT = {
    ('imager', 'prompt_file'): 'the former LOT-file field (`file2img`) : no port since 2026-09-10 '
                               '(« le LOT n\'a pas de port »), never filled since (imager/tests.py) '
                               '— its removal is Fabien\'s decision',
    ('imager_01', 'prompt_file'): 'same as its source',
    ('translator_01', 'source_document'): 'an app born from a manifest that names its work column '
                                          '(`input_field: source_document`) while the homonym '
                                          'column `work_file` receives the same file too — the '
                                          'generated view stores it twice ; to settle',
}


def _corpus_capabilities() -> dict:
    """`{source app: [capabilities]}` of the versioned model manifests."""
    found = defaultdict(list)
    for path in (Path(settings.BASE_DIR) / 'manifests' / 'models').glob('*.json'):
        body = json.loads(path.read_text(encoding='utf-8')).get('body') or {}
        source = (body.get('identity') or {}).get('source')
        if source and isinstance(body.get('capabilities'), dict):
            found[source].append(body['capabilities'])
    return found


class _CardPorts:
    """Each (app, domain, element model, ports its card offers) of the catalogue."""

    @classmethod
    def rows(cls):
        from wama.common import app_registry
        from wama.common.utils import app_modes
        from wama.common.utils.detail_registry import DetailRegistry
        corpus = _corpus_capabilities()
        with mock.patch.object(app_registry, 'app_model_capabilities',
                               lambda app_id: list(corpus.get(app_id, []))):
            for app in sorted(app_registry.APP_CATALOG):
                carried = app_registry.app_ports_carried_elsewhere(app)
                domains = [d.get('id') for d in app_modes.get_domains(app)] or [None]
                for domain in domains:
                    surface = (app_modes.domain_surface(app, domain) if domain else '') or app
                    model = (DetailRegistry.get(surface) or DetailRegistry.get(app) or {}).get('model')
                    if model is None:
                        continue
                    ports = (app_registry.studio_node_ports(app) or {}).get('inputs') or []
                    if domain:
                        ports = app_registry.ports_for_domain(app, domain, ports)
                    yield app, domain, model, [p for p in ports if p.get('id') not in carried], carried


class EveryPortOfACardHasItsFieldTest(SimpleTestCase):

    def test_every_port_a_card_offers_has_the_field_that_keeps_its_value(self):
        from wama.common.utils.port_fields import port_field
        missing, seen, resolved_twins = [], 0, set()
        unresolved_twins = set()
        for app, domain, model, ports, _carried in _CardPorts.rows():
            for port in ports:
                seen += 1
                pid = port['id']
                if port_field(model, pid) or (app, pid) in GAPS:
                    continue
                if app in TWINS_AWAITING_PROJECTION:
                    unresolved_twins.add(app)
                    continue
                missing.append(f'{app}/{domain}: {pid} ({model.__name__})')
        self.assertGreater(seen, 20, 'the ports of the catalogue are read')
        self.assertEqual([], missing, 'a port whose value no field keeps : list it on the element '
                                      'app (`register_port_fields` in its ready()), or name the column after the port')
        # Twins are not versioned (`.gitignore`, `wama/*_NN/`) : only a twin PRESENT is judged.
        from wama.common.app_registry import APP_CATALOG
        self.assertEqual(set(), (TWINS_AWAITING_PROJECTION & set(APP_CATALOG)) - unresolved_twins,
                         'these twins carry the listing now : remove them from the exemption')

    def test_an_exemption_is_still_needed(self):
        from wama.common.utils.port_fields import port_field
        from wama.common.app_registry import APP_CATALOG
        needed = set()
        for app, _domain, model, ports, _carried in _CardPorts.rows():
            needed |= {(app, p['id']) for p in ports if not port_field(model, p['id'])}
        present = {gap for gap in GAPS if gap[0] in APP_CATALOG}   # a twin may be absent (not versioned)
        self.assertEqual(set(), present - needed, 'these gaps are closed : remove them')


class TheListingNamesRealFieldsTest(SimpleTestCase):

    def test_no_listed_port_or_field_is_a_phantom(self):
        from django.apps import apps
        from wama.common.utils.app_modes import INPUT_TYPES
        from wama.common.utils.port_fields import port_field_map
        wrong, listed = [], 0
        for model in apps.get_models():
            mapping = port_field_map(model)
            names = {f.name for f in model._meta.get_fields() if getattr(f, 'concrete', False)}
            for port, field in mapping.items():
                listed += 1
                # `work` : the generic work port of an app no model declares inputs for.
                if port not in INPUT_TYPES and port != 'work':
                    wrong.append(f'{model._meta.label}: port « {port} » is no input token')
                if field not in names:
                    wrong.append(f'{model._meta.label}: « {field} » is no field of the model')
        self.assertGreater(listed, 10)
        self.assertEqual([], wrong)


class TheCopiesThatRemainAgreeTest(SimpleTestCase):
    """Until each copy reads the reader, it must say what the reader says."""

    def test_the_lot_lines_the_ingest_and_the_panel_name_the_field_of_the_reader(self):
        import importlib
        from wama.common.utils.detail_registry import DetailRegistry
        from wama.common.utils.port_fields import port_field
        disagree, compared = [], 0
        for app, _domain, model, ports, carried in _CardPorts.rows():
            if app in TWINS_AWAITING_PROJECTION:
                continue
            try:
                # A twin's COPIED views may still carry the lot lines' table : it must agree.
                views = importlib.import_module(f'wama.{app}.views')
            except ImportError:
                views = None
            if views is not None and DetailRegistry.get(app) and DetailRegistry.get(app).get('model') is model:
                for name in ('_LINE_FIELDS', 'COVER_FIELDS'):
                    for port, field in (getattr(views, name, None) or {}).items():
                        compared += 1
                        if port_field(model, port) != field:
                            disagree.append(f'{app}.views.{name}: {port} → {field}, '
                                            f'reader → {port_field(model, port) or "∅"}')
            all_ports = [p['id'] for p in ports] + list(carried)
            fields = {port_field(model, p) for p in all_ports} - {''}
            target = (getattr(model, 'WAMA_INGEST', None) or {}).get('target')
            if target:
                compared += 1
                if target not in fields:
                    disagree.append(f'{model._meta.label}.WAMA_INGEST target « {target} » is the '
                                    f'value of no port ({sorted(fields)})')
            text = ((DetailRegistry.get(app) or {}).get('spec') or {}).get('source_text')
            if isinstance(text, str) and 'prompt' in all_ports:
                if (DetailRegistry.get(app) or {}).get('model') is model:
                    compared += 1
                    if port_field(model, 'prompt') != text:
                        disagree.append(f'{app} panel source_text « {text} », reader → '
                                        f'{port_field(model, "prompt") or "∅"}')
            # The panel's INPUT files (`source_file`) are a display CHOICE (an order), not a copy of
            # the link : each still names the field of a port of this element — a port of the card,
            # or one the app lists (a port opened by the models its select offers, `options_ports`,
            # is not in the versioned corpus). ⚠ The preview's `file_field` is NOT checked : it may
            # show the RESULT (writer_01, translator_01 : `output_file`, measured 2026-11-24).
            from wama.common.utils import app_modes
            from wama.common.utils.port_fields import port_field_map
            surface = (app_modes.domain_surface(app, _domain) if _domain else '') or app
            if (DetailRegistry.get(surface) or {}).get('model') is not model:
                continue
            spec = (DetailRegistry.get(surface) or {}).get('spec') or {}
            shown = spec.get('source_file')
            shown = [shown] if isinstance(shown, str) else [f for f in shown or [] if isinstance(f, str)]
            listed = set(port_field_map(model).values())
            for field in shown:
                compared += 1
                if field not in fields | listed and (app, field) not in NOT_A_PORT:
                    disagree.append(f'{surface} panel source_file « {field} » is the field of no '
                                    f'port ({sorted(fields | listed)})')
        self.assertGreater(compared, 10)
        self.assertEqual([], disagree)


class TheListingTravelsThroughTheManifestTest(SimpleTestCase):
    """Schema-driven to the twin : the listing of an app is a facet of its manifest
    (`inspector.port_fields`), which the generator replays in the `ready()` it writes — the file
    every twin has generated (`apps.py`), whatever its `models.py`."""

    DRAFT = Path(settings.BASE_DIR) / 'manifests' / 'app_drafts' / 'writer.json'

    def _manifest(self, mapping, model=None):
        manifest = json.loads(self.DRAFT.read_text(encoding='utf-8'))
        item = manifest['body']['processing']['item_model']
        manifest['body'].setdefault('inspector', {})['port_fields'] = {model or item: mapping}
        return manifest, item

    def test_every_listing_goes_to_the_manifest_of_its_app(self):
        from django.apps import apps
        from wama.common.manifests.builtin.app import _inspector
        from wama.common.utils.port_fields import registered
        seen = 0
        for label, mapping in registered().items():
            app, model = label.split('.')[0], apps.get_model(label).__name__
            with self.subTest(model=label):
                self.assertEqual(mapping, (_inspector(app).get('port_fields') or {}).get(model))
                seen += 1
        self.assertGreater(seen, 5)
        self.assertNotIn('port_fields', _inspector('no_such_app'))

    def test_the_generator_replays_it_in_the_ready_of_the_app(self):
        import ast
        from wama.common.manifests.codegen.apps_gen import render_apps
        mapping = {'work_image': 'avatar_upload', 'work_object3d': 'avatar_upload'}
        manifest, item = self._manifest(mapping)
        source, reason = render_apps(manifest)
        self.assertIsNotNone(source, reason)
        calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)
                 and getattr(n.func, 'id', '') == 'register_port_fields']
        self.assertEqual(1, len(calls))
        self.assertEqual(item, calls[0].args[0].id)
        self.assertEqual(mapping, ast.literal_eval(calls[0].args[1]), 'literals only')
        plain, _reason = render_apps(json.loads(self.DRAFT.read_text(encoding='utf-8')))
        self.assertNotIn('register_port_fields', plain, 'nothing for an app that lists nothing')
        stranger, why = render_apps(self._manifest(mapping, model='Stranger')[0])
        self.assertIsNone(stranger)
        self.assertIn('inspector.port_fields', why)

    def test_the_input_column_of_a_twin_is_the_field_of_a_port(self):
        """The extractor named the twin's input column after the FIRST FileField : the imager's
        `prompt_file`, the former lot-file field, where its twin then put the working image. It is
        now the field of the card's main work port, read by the reader (2026-11-24)."""
        from wama.common import app_registry
        from wama.common.manifests.builtin.app import _model_spec
        from wama.common.utils.port_fields import port_field
        corpus = _corpus_capabilities()
        checked = 0
        with mock.patch.object(app_registry, 'app_model_capabilities',
                               lambda app_id: list(corpus.get(app_id, []))):
            for app, _domain, model, ports, _carried in _CardPorts.rows():
                entry = app_registry.APP_CATALOG.get(app) or {}
                if entry.get('generated_from') or entry.get('sandbox'):
                    continue
                files = {f.name for f in model._meta.fields if f.get_internal_type() == 'FileField'}
                port_files = {port_field(model, p['id']) for p in ports} & files
                if not port_files:
                    continue
                spec = _model_spec(app) or {}
                if (spec.get('item') or {}).get('name') != model.__name__:
                    continue          # the element of another surface : its own spec
                with self.subTest(app=app):
                    self.assertIn(spec['item'].get('input_field'), port_files)
                checked += 1
        self.assertGreater(checked, 5)

    def test_a_value_that_would_leave_its_place_in_the_code_is_turned_down(self):
        from wama.common.manifests.codegen.source_safety import source_safety_errors
        self.assertEqual([], source_safety_errors(
            {'inspector': {'port_fields': {'Item': {'work_file': 'input_file'}}}}))
        hostile = "x'); import os  #"
        for facet in ({'Item': {'work_file': hostile}}, {'Item': {hostile: 'input_file'}},
                      {hostile: {'work_file': 'input_file'}}):
            with self.subTest(facet=facet):
                self.assertTrue(source_safety_errors({'inspector': {'port_fields': facet}}))


class AGeneratedCopyKeepsWhatTheUserGaveTest(TestCase):
    """`ROUTE §10.6`, layer 2, point 4.6 : the generator counted as OUTPUTS the inputs kept in a
    field with an inherited name — a twin's ⧉ emptied the voice, the score or the avatar the user had
    given (measured on synthesizer_01, composer_01, avatarizer_01, 2026-11-24). The views it renders
    from an app's manifest never clear the field of a port."""

    def test_the_views_generated_for_an_app_never_clear_the_field_of_a_port(self):
        import re
        from wama.common.app_registry import APP_CATALOG
        from wama.common.management.commands.app_sandbox import render_payload
        from wama.common.manifests.codegen.views_gen import render_views
        from wama.common.manifests.ingest import extract
        from wama.common.utils.port_fields import registered
        checked = 0
        for label, mapping in sorted(registered().items()):
            app = label.split('.')[0]
            entry = APP_CATALOG.get(app) or {}
            if entry.get('generated_from') or entry.get('sandbox'):
                continue
            source, _reason = render_views(render_payload(extract('app', app), 'views', False))
            if not source:
                continue
            cleared = {field for group in re.findall(r"output_fields=\[([^\]]*)\]", source)
                       for field in re.findall(r"'(\w+)'", group)}
            with self.subTest(app=app):
                self.assertEqual(set(), cleared & set(mapping.values()),
                                 'a copy would clear a file the user gave')
            checked += 1
        self.assertGreater(checked, 3)


class AFieldSharedByTwoPortsTest(SimpleTestCase):
    """A legacy field that keeps two ports (one avatar : a photo OR a 3D object) gives each port
    the file of ITS nature — read by the translation the model draw already uses."""

    def test_each_port_gets_only_the_file_of_its_nature(self):
        from django.apps import apps
        from wama.common.app_registry import _CAT_OF
        from wama.common.utils.app_modes import INPUT_TYPES
        from wama.common.utils.port_fields import port_field_map, port_value, ports_sharing
        extension = {}
        for ext, category in _CAT_OF.items():
            extension.setdefault(category, ext)
        checked = 0
        for model in apps.get_models():
            for field in set(port_field_map(model).values()):
                sharing = ports_sharing(model, field)
                if len(sharing) < 2:
                    continue
                for port in sharing:
                    nature = (INPUT_TYPES.get(port) or {}).get('accept')
                    if not nature or nature not in extension:
                        continue
                    element = model(**{field: f'input/sample.{extension[nature]}'})
                    got = {p: bool(port_value(element, p)) for p in sharing}
                    self.assertEqual({p: p == port for p in sharing}, got,
                                     f'{model._meta.label}.{field} holding a {nature} file')
                    checked += 1
        self.assertGreater(checked, 1, 'a shared field exists today (the avatar) and is read')

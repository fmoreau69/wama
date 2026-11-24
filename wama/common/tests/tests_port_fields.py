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
from django.test import SimpleTestCase

#: (app, port) whose value no field keeps, with the reason — a list that can only shrink.
GAPS = {
    ('anonymizer', 'prompt'): "the instruction is a SETTING (`sam3_prompt`, `entry_form`) : "
                              "to be listed in `ports_carried_elsewhere`",
    ('anonymizer_01', 'prompt'): 'same as its source',
}
#: Twins whose GENERATED model does not carry the listing yet : it is projected by the extractor
#: (`manifests/builtin/app`) into the manifest, then by `models_gen` into the twin — the next step.
#: Can only shrink.
TWINS_AWAITING_PROJECTION = {
    'anonymizer_01', 'avatarizer_01', 'composer_01', 'converter_01', 'describer_01', 'enhancer_01',
    'imager_01', 'reader_01', 'synthesizer_01', 'transcriber_01',
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
                                      'model (`WAMA_PORT_FIELDS`), or name the column after the port')
        self.assertEqual(set(), TWINS_AWAITING_PROJECTION - unresolved_twins,
                         'these twins carry the listing now : remove them from the exemption')

    def test_an_exemption_is_still_needed(self):
        from wama.common.utils.port_fields import port_field
        needed = set()
        for app, _domain, model, ports, _carried in _CardPorts.rows():
            needed |= {(app, p['id']) for p in ports if not port_field(model, p['id'])}
        self.assertEqual(set(), set(GAPS) - needed, 'these gaps are closed : remove them')


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
        self.assertGreater(compared, 10)
        self.assertEqual([], disagree)


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

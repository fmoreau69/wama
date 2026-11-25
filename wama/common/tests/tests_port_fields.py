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
        from wama.common.utils.port_fields import port_field, table_ports
        missing, seen, resolved_twins = [], 0, set()
        unresolved_twins = set()
        for app, domain, model, ports, _carried in _CardPorts.rows():
            for port in ports:
                seen += 1
                pid = port['id']
                # Kept by a column, or DECLARED to live in the common inputs table (`table=`).
                if port_field(model, pid) or pid in table_ports(model) or (app, pid) in GAPS:
                    continue
                if app in TWINS_AWAITING_PROJECTION:
                    unresolved_twins.add(app)
                    continue
                missing.append(f'{app}/{domain}: {pid} ({model.__name__})')
        # The real apps alone offer about twenty ports (twins are not versioned : a fresh clone has
        # none) — the threshold only proves the catalogue is read.
        self.assertGreater(seen, 10, 'the ports of the catalogue are read')
        self.assertEqual([], missing, 'a port whose value no field keeps : list it on the element '
                                      'app (`register_port_fields` in its ready()), or name the column after the port')
        # Twins are not versioned (`.gitignore`, `wama/*_NN/`) : only a twin PRESENT is judged.
        from wama.common.app_registry import APP_CATALOG
        self.assertEqual(set(), (TWINS_AWAITING_PROJECTION & set(APP_CATALOG)) - unresolved_twins,
                         'these twins carry the listing now : remove them from the exemption')

    def test_an_exemption_is_still_needed(self):
        from wama.common.utils.port_fields import port_field, table_ports
        from wama.common.app_registry import APP_CATALOG
        needed = set()
        for app, _domain, model, ports, _carried in _CardPorts.rows():
            needed |= {(app, p['id']) for p in ports
                       if not port_field(model, p['id']) and p['id'] not in table_ports(model)}
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
        # The ports DECLARED in the common inputs table, and the old column a port left (`legacy`).
        from wama.common.utils.port_fields import registered_legacy, registered_table
        for label, ports in registered_table().items():
            model = apps.get_model(label)
            names = {f.name for f in model._meta.get_fields() if getattr(f, 'concrete', False)}
            for port in ports:
                if port not in INPUT_TYPES:
                    wrong.append(f'{label}: table port « {port} » is no input token')
                if port_field_map(model).get(port):
                    wrong.append(f'{label}: « {port} » is listed in a column AND in the table')
                # The DECLARED old column (raw : `legacy_field` hides a phantom by design).
                old = (registered_legacy().get(label) or {}).get(port)
                if old and old not in names:
                    wrong.append(f'{label}: legacy « {old} » of « {port} » is no field of the model')
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
            from wama.common.utils.port_fields import table_ports
            for field in shown:
                compared += 1
                # A field of a port, or a PORT that lives in the common inputs table (by its name).
                if (field not in fields | listed | set(table_ports(model))
                        and (app, field) not in NOT_A_PORT):
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

    def test_the_instruction_of_the_generated_add_view_goes_to_the_field_of_the_prompt_port(self):
        """The add view generated for a twin wrote the instruction to no field when the app keeps
        its prompt port in a column of another name (`text_content`) : « Rien à ajouter » for
        avatarizer_01 and synthesizer_01, the reds that started the reader (2026-11-23)."""
        from wama.common.app_registry import APP_CATALOG
        from wama.common.management.commands.app_sandbox import render_payload
        from wama.common.manifests.codegen.views_gen import _donnees
        from wama.common.manifests.ingest import extract
        from wama.common.utils.port_fields import registered
        checked = 0
        for label, mapping in sorted(registered().items()):
            app = label.split('.')[0]
            entry = APP_CATALOG.get(app) or {}
            if 'prompt' not in mapping or entry.get('generated_from') or entry.get('sandbox'):
                continue
            d = _donnees(render_payload(extract('app', app), 'views', False))
            if d.get('_raison') or not d['entry'].get('adds'):
                continue
            with self.subTest(app=app):
                self.assertEqual(mapping['prompt'], d['entry']['prompt_field'])
            checked += 1
        self.assertGreater(checked, 0, 'an app keeps its instruction in a column of another name')


class AFieldSharedByTwoPortsTest(SimpleTestCase):
    """A field that keeps two ports (one avatar : a photo OR a 3D object) gives each port the file
    of ITS nature — read by the translation the model draw already uses. A listed column
    (`port_value`) and the OLD column of ports that left for the table (`legacy`, read as a
    fallback until the relaunch migration copies it — the avatarizer's avatar, 2026-11-25) follow
    the same rule."""

    def test_each_port_gets_only_the_file_of_its_nature(self):
        from django.apps import apps
        from wama.common.app_registry import _CAT_OF
        from wama.common.utils.app_modes import INPUT_TYPES
        from wama.common.utils.port_fields import (_LEGACY, _label, port_field_map, port_files,
                                                   port_value, ports_sharing)
        extension = {}
        for ext, category in _CAT_OF.items():
            extension.setdefault(category, ext)
        checked = 0
        for model in apps.get_models():
            legacy = _LEGACY.get(_label(model)) or {}
            groups = [(field, ports_sharing(model, field), port_value)
                      for field in set(port_field_map(model).values())]
            groups += [(field, [p for p, f in legacy.items() if f == field],
                        lambda element, port: (port_files(element, port) or [None])[0])
                       for field in set(legacy.values())]
            for field, sharing, read in groups:
                if len(sharing) < 2:
                    continue
                for port in sharing:
                    nature = (INPUT_TYPES.get(port) or {}).get('accept')
                    if not nature or nature not in extension:
                        continue
                    element = model(**{field: f'input/sample.{extension[nature]}'})
                    got = {p: bool(read(element, p)) for p in sharing}
                    self.assertEqual({p: p == port for p in sharing}, got,
                                     f'{model._meta.label}.{field} holding a {nature} file')
                    checked += 1
        self.assertGreater(checked, 1, 'a shared field exists today (the avatar) and is read')


class _CardWithAPortWithoutColumn:
    """A REAL element model of the catalogue and a file token of the vocabulary that no field of it
    keeps — chosen from the declarations, never named."""

    @staticmethod
    def pick():
        from wama.common.app_registry import APP_CATALOG
        from wama.common.utils.app_modes import INPUT_TYPES
        from wama.common.utils.detail_registry import DetailRegistry
        from wama.common.utils.port_fields import port_field
        for app in sorted(a for a, s in APP_CATALOG.items()
                          if not s.get('sandbox') and not s.get('generated_from')):
            model = (DetailRegistry.get(app) or {}).get('model')
            if model is None or not any(f.name == 'user' for f in model._meta.concrete_fields):
                continue
            for token, spec in sorted(INPUT_TYPES.items()):
                if spec.get('kind') == 'file' and not port_field(model, token):
                    return app, model, token
        raise AssertionError('no element model with a port without column')


class TheCommonTableKeepsAPortWithoutColumnTest(TestCase):
    """`ElementInput` (2026-11-25, `INPUT_MODEL_MATCHING §6.13`) : a port that no column keeps
    stores its files there, one rank per file — and every gesture of a card sees them : reading,
    replacing, removing (released, announced), duplicating, transferring, the files index."""

    def setUp(self):
        import shutil
        import tempfile
        from django.contrib.auth import get_user_model
        from django.test import override_settings
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.app, self.model, self.port = _CardWithAPortWithoutColumn.pick()
        self.user = get_user_model().objects.create_user('element_input_owner', password='x')
        from django.db.models.signals import post_save
        with mock.patch.object(post_save, 'send', return_value=[]):   # no ingest, no hook
            self.card = self.model.objects.create(user=self.user)

    def _received(self, name, content=b'witness'):
        from wama.common.utils.media_paths import app_media_dir, designate, get_app_media_path
        folder = get_app_media_path(self.app, self.user.id, 'input')
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(content)
        return designate(f"{app_media_dir(self.app, self.user.id, 'input')}/{name}", self.user,
                         self.app)

    @staticmethod
    def _names(files):
        return [f.name.rsplit('/', 1)[-1] for f in files]

    def test_n_files_are_n_ranks_and_the_reader_returns_them(self):
        from wama.common.utils.port_fields import (input_rows, port_files, port_value,
                                                   store_port_inputs)
        self.assertEqual(2, store_port_inputs(self.card, self.port,
                                              [self._received('a.bin'), self._received('b.bin')]))
        self.assertEqual([0, 1], [r.rank for r in input_rows(self.card, self.port)])
        self.assertEqual(['a.bin', 'b.bin'], self._names(port_files(self.card, self.port)))
        self.assertTrue(port_value(self.card, self.port).name.endswith('a.bin'))

    def test_a_port_with_a_column_never_writes_to_the_table(self):
        from wama.common.utils.app_modes import INPUT_TYPES
        from wama.common.utils.port_fields import input_rows, port_field, store_port_inputs
        kept = next((t for t in sorted(INPUT_TYPES) if INPUT_TYPES[t].get('kind') == 'file'
                     and port_field(self.model, t)
                     and self.model._meta.get_field(port_field(self.model, t)).get_internal_type()
                     == 'FileField'), None)
        if kept is None:
            self.skipTest('this element model keeps no file port in a column')
        store_port_inputs(self.card, kept, [self._received('kept.bin')])
        self.card.refresh_from_db()
        self.assertTrue(getattr(self.card, port_field(self.model, kept)).name.endswith('kept.bin'))
        self.assertEqual([], input_rows(self.card), 'one truth per port : the column')

    def test_replacing_a_port_releases_the_former_file(self):
        from wama.common.models import ReleasedFile
        from wama.common.utils.port_fields import input_rows, store_port_inputs
        store_port_inputs(self.card, self.port, [self._received('old.bin')])
        store_port_inputs(self.card, self.port, [self._received('new.bin')])
        self.assertEqual(['new.bin'], self._names(r.file for r in input_rows(self.card)))
        self.assertTrue(ReleasedFile.objects.filter(user=self.user, path__endswith='old.bin').exists())

    def test_removing_the_card_releases_its_files_and_forgets_its_rows(self):
        from wama.common.models import ElementInput, ReleasedFile
        from wama.common.services.released_files import freed_by
        from wama.common.utils.port_fields import store_port_inputs
        from wama.common.utils.queue_duplication import release_card_files
        store_port_inputs(self.card, self.port, [self._received('gone.bin')])
        self.assertTrue(any(p.endswith('gone.bin') for p in freed_by([self.card])),
                        'the confirmation announces what the gesture frees')
        release_card_files(self.card)
        self.assertFalse(ElementInput.objects.filter(object_id=str(self.card.pk)).exists())
        self.assertTrue(ReleasedFile.objects.filter(user=self.user, path__endswith='gone.bin').exists())

    def test_the_retention_purge_takes_the_files_and_the_rows_of_the_card(self):
        """The purge deletes an expired card WITHOUT its removal gesture (`release_card_files`) :
        its rows and their files go with it, under the purge's own rule (owned, carried by no other
        row) — a file another card still holds stays."""
        import os
        from django.conf import settings
        from wama.common.models import ElementInput
        from wama.common.services.retention import _purge_instance
        from wama.common.utils.port_fields import input_rows, store_port_inputs
        from wama.common.utils.queue_duplication import duplicate_instance
        store_port_inputs(self.card, self.port, [self._received('expired.bin')])
        kept = duplicate_instance(self.card)                  # the same file, held by a copy
        path = os.path.join(settings.MEDIA_ROOT, input_rows(self.card)[0].file.name)
        _purge_instance(self.card)
        self.assertEqual(1, ElementInput.objects.filter(file__endswith='expired.bin').count())
        self.assertTrue(os.path.isfile(path), 'still held by the copy')
        _purge_instance(kept)
        self.assertFalse(ElementInput.objects.filter(file__endswith='expired.bin').exists())
        self.assertFalse(os.path.isfile(path), 'the last holder purged : the file goes')

    def test_a_copy_carries_the_same_files_and_the_index_sees_both(self):
        from wama.common.utils.file_references import direct_references
        from wama.common.utils.port_fields import input_rows, store_port_inputs
        from wama.common.utils.queue_duplication import duplicate_instance
        store_port_inputs(self.card, self.port, [self._received('shared.bin')])
        copy = duplicate_instance(self.card)
        self.assertEqual([r.file.name for r in input_rows(self.card)],
                         [r.file.name for r in input_rows(copy)])
        refs = direct_references(input_rows(self.card)[0].file.name)
        self.assertEqual(2, len([r for r in refs if r['label'] == 'common.ElementInput']))

    def test_a_transferred_card_takes_its_files_to_its_new_owner(self):
        from django.contrib.auth import get_user_model
        from wama.common.services.card_transfer import _hand_over_inputs
        from wama.common.utils.media_paths import app_media_dir
        from wama.common.utils.port_fields import input_rows, store_port_inputs
        store_port_inputs(self.card, self.port, [self._received('mine.bin')])
        other = get_user_model().objects.create_user('element_input_heir', password='x')
        _hand_over_inputs(self.card, other)
        row = input_rows(self.card)[0]
        self.assertEqual(other.pk, row.user_id)
        self.assertTrue(row.file.name.startswith(app_media_dir(self.app, other.pk, '')),
                        row.file.name)

    def test_the_generated_add_view_stores_a_port_without_column_in_the_table(self):
        """A model that brings a new nature opens a port that no column keeps : the add view
        generated for a twin receives it and stores it in the table — no migration. Measured on the
        manifest of a REAL app (extracted, as `substitute` does) with such a port added."""
        from wama.common.app_registry import APP_CATALOG
        from wama.common.management.commands.app_sandbox import render_payload
        from wama.common.manifests.codegen.views_gen import _donnees, render_views
        from wama.common.manifests.ingest import extract
        for app in sorted(a for a, s in APP_CATALOG.items()
                          if not s.get('sandbox') and not s.get('generated_from')):
            manifest = render_payload(extract('app', app), 'views', False)
            # The add view of the ATTACH / MIXED form receives the secondary ports (a drop that
            # creates the element receives its work port only — a gap of its own, named in
            # `INPUT_MODEL_MATCHING §6.13`).
            if (not manifest or _donnees(manifest).get('_raison')
                    or not _donnees(manifest)['entry'].get('adds')):
                continue
            columns = _donnees(manifest)['champ_noms']
            token = next((t for t in ('reference_voice', 'reference_document', 'reference_file')
                          if t not in columns), None)
            manifest['body'].setdefault('ports', {}).setdefault('inputs', []).append(
                {'id': token, 'group': 'reference', 'types': ['audio']})
            if _donnees(manifest)['secondary_fields'].get(token) != '':
                continue
            source, _reason = render_views(manifest)
            if source:
                self.assertIn('store_port_inputs(item, _port, _r)', source)
                return
        self.fail('no app manifest renders an add view with a port without column')


class APortLeavesItsColumnWithoutLosingAnythingTest(TestCase):
    """An app moves a port from its column to the table (`register_port_fields(…, legacy=)`, the
    avatarizer's avatar, 2026-11-25) : the code that reads the table is served BEFORE the relaunch
    plays the migration that copies the column — so the old column is read as a FALLBACK, emptied
    (its file released) when the port is written to the table, and every reader of declarations
    names the port where it named the column. Model and port chosen from the declarations."""

    def setUp(self):
        import shutil
        import tempfile
        from django.apps import apps
        from django.contrib.auth import get_user_model
        from django.db.models.signals import post_save
        from django.test import override_settings
        from wama.common.app_registry import APP_CATALOG
        from wama.common.utils.port_fields import registered_legacy
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        legacy = {label: m for label, m in registered_legacy().items()      # a real app, not a twin
                  if not (APP_CATALOG.get(label.split('.')[0]) or {}).get('generated_from')
                  and not (APP_CATALOG.get(label.split('.')[0]) or {}).get('sandbox')}
        if not legacy:
            self.skipTest('no app has moved a port to the table yet')
        label, mapping = sorted(legacy.items())[0]
        self.model = apps.get_model(label)
        self.app = self.model._meta.app_label
        self.port, self.column = sorted(mapping.items())[0]
        self.user = get_user_model().objects.create_user('legacy_port_owner', password='x')
        with mock.patch.object(post_save, 'send', return_value=[]):
            self.card = self.model.objects.create(user=self.user)

    def _file(self, name):
        from wama.common.utils.media_paths import app_media_dir, get_app_media_path
        folder = get_app_media_path(self.app, self.user.id, 'input')
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(b'witness')
        return f"{app_media_dir(self.app, self.user.id, 'input')}/{name}"

    def _extension(self):
        from wama.common.app_registry import _CAT_OF
        from wama.common.utils.app_modes import INPUT_TYPES
        nature = (INPUT_TYPES.get(self.port) or {}).get('accept')
        return next((ext for ext, cat in _CAT_OF.items() if cat == nature), 'bin')

    def test_the_old_column_is_read_until_the_card_has_a_row(self):
        from wama.common.utils.port_fields import port_field, port_files, port_value
        self.assertEqual('', port_field(self.model, self.port), 'the port has left its column')
        path = self._file(f'old.{self._extension()}')
        self.model.objects.filter(pk=self.card.pk).update(**{self.column: path})
        self.card.refresh_from_db()
        self.assertEqual([path], [f.name for f in port_files(self.card, self.port)])
        self.assertEqual(path, port_value(self.card, self.port).name)

    def test_writing_the_port_empties_the_old_column_and_releases_its_file(self):
        from wama.common.models import ReleasedFile
        from wama.common.utils.media_paths import designate
        from wama.common.utils.port_fields import input_rows, store_port_inputs
        ext = self._extension()
        old = self._file(f'before.{ext}')
        self.model.objects.filter(pk=self.card.pk).update(**{self.column: old})
        self.card.refresh_from_db()
        store_port_inputs(self.card, self.port,
                          [designate(self._file(f'after.{ext}'), self.user, self.app)])
        self.card.refresh_from_db()
        self.assertFalse(getattr(self.card, self.column), 'one place per value : the table')
        self.assertEqual([f'after.{ext}'], [r.file.name.rsplit('/', 1)[-1]
                                            for r in input_rows(self.card, self.port)])
        self.assertTrue(ReleasedFile.objects.filter(user=self.user, path=old).exists(),
                        'the replaced file is released, never dropped silently')

    def test_one_input_disputed_by_ports_goes_to_the_port_of_its_nature_and_empties_the_others(self):
        """`store_by_nature` (the avatar : a photo OR a 3D object) — ports chosen from the table
        declaration, extensions from the vocabulary."""
        from wama.common.app_registry import _CAT_OF
        from wama.common.models import ReleasedFile
        from wama.common.utils.app_modes import INPUT_TYPES
        from wama.common.utils.media_paths import designate
        from wama.common.utils.port_fields import port_files, store_by_nature, table_ports
        ext_of = {}
        for ext, cat in _CAT_OF.items():
            ext_of.setdefault(cat, ext)
        ports = [p for p in table_ports(self.model)
                 if (INPUT_TYPES.get(p) or {}).get('accept') in ext_of]
        if len(ports) < 2:
            self.skipTest('no element declares two table ports of distinct natures')
        first, second = ports[:2]
        exts = [ext_of[INPUT_TYPES[p]['accept']] for p in (first, second)]
        a = self._file(f'one.{exts[0]}')
        self.assertEqual(first, store_by_nature(self.card, ports, designate(a, self.user, self.app)))
        b = self._file(f'two.{exts[1]}')
        self.assertEqual(second, store_by_nature(self.card, ports, designate(b, self.user, self.app)))
        self.assertEqual([], port_files(self.card, first), 'one input : the other port is emptied')
        self.assertEqual([b], [f.name for f in port_files(self.card, second)])
        self.assertTrue(ReleasedFile.objects.filter(user=self.user, path=a).exists())

    def test_the_readers_of_declarations_name_a_port(self):
        """The panel's spec, the preview and the watched settings of a process name the PORT."""
        from wama.common.services.process_runs import snapshot
        from wama.common.utils.detail_registry import spec_value
        from wama.common.utils.media_paths import designate
        from wama.common.utils.port_fields import store_port_inputs
        path = self._file(f'named.{self._extension()}')
        store_port_inputs(self.card, self.port, [designate(path, self.user, self.app)])
        self.assertEqual(path, spec_value(self.card, self.port).name)
        self.assertEqual(path, spec_value(self.card, [self.port, 'no_such_field']).name)
        self.assertEqual({self.port: path}, snapshot(self.card, (self.port,)))
        self.assertIsNone(spec_value(self.card, 'no_such_field'), 'an unknown name stays None')

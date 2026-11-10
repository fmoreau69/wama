"""The WITNESS item of a surface (2026-10-18, Fabien : a thumbnail per brick in the UI bricks
catalogue). Each surface declares it (`Surface.witness`, data — also written in a generated app's
manifest) ; the nightly opens the surface on it and captures its bricks. These guards name no app :
they walk the declared surfaces."""
import ast
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.services.ui_smoke import (WITNESS_IMAGE_SIZE, WITNESS_OBJECTS, _garde_de_montage,
                                           witness_sample)
from wama.common.services import ui_smoke_surfaces
from wama.common.services.ui_smoke_surfaces import mount_witness, witness_guard, witness_guards
from wama.common.surfaces import SURFACES, BrickSlot, Surface, load_all


class DeclaredWitnessTest(TestCase):

    def setUp(self):
        load_all()
        self.user = get_user_model().objects.create_user('surface-witness', password='x')

    def _declaring(self):
        surfaces = [s for s in SURFACES.values() if s.witness]
        self.assertTrue(surfaces, 'at least one surface declares its witness')
        return surfaces

    def test_every_declared_witness_can_be_made(self):
        for surface in self._declaring():
            with self.subTest(surface=surface.id):
                self.assertEqual([], surface.witness_problems())

    def test_every_declared_witness_really_opens_its_surface(self):
        """Made like the nightly makes it (`mount_witness`), the item opens the page — what the
        surface declares and what it requires to open cannot drift apart."""
        for surface in self._declaring():
            with self.subTest(surface=surface.id):
                pk = mount_witness(surface, self.user.pk)
                item = surface.model_class().objects.get(pk=pk)
                self.assertEqual((True, ''), surface.can_open(item))

    def test_a_file_field_names_a_content_in_the_existing_vocabularies(self):
        surface = next(iter(self._declaring()))
        file_field = next(name for name, value in surface.witness.items()
                          if surface.model_class()._meta.get_field(name).get_internal_type()
                          in ('FileField', 'ImageField'))
        bad = Surface(app=surface.app, key='bad_witness', label='x', model=surface.model,
                      slots=(BrickSlot('a', surface.slots[0].brick, 0, 0, 1, 1),), reads={},
                      edits=surface.edits, witness={file_field: 'invented', 'no_such_field': 'x'})
        problems = ' '.join(bad.witness_problems())
        self.assertIn('invented', problems)
        self.assertIn('no_such_field', problems)


class WitnessCleanupTest(TestCase):
    """What a passage mounts leaves with it, on EVERY declared surface. The guard used to find its
    model through the preview registry, where an app can be absent : its witnesses stayed, one row
    per passage (Face Analyzer, 38 rows on 2026-11-10)."""

    def setUp(self):
        load_all()
        self.user = get_user_model().objects.create_user('witness-cleanup', password='x')
        self.surfaces = [s for s in SURFACES.values() if s.witness]

    def _file_paths(self, item):
        fields = [f.name for f in item._meta.fields
                  if f.get_internal_type() in ('FileField', 'ImageField')]
        return [Path(getattr(item, name).path) for name in fields if getattr(item, name)]

    def test_a_passage_leaves_neither_the_row_nor_the_files_of_its_witness(self):
        files_seen = 0
        for surface in self.surfaces:
            with self.subTest(surface=surface.id):
                model = surface.model_class()
                before = set(model.objects.values_list('pk', flat=True))
                with witness_guard(surface, 'test'):
                    item = model.objects.get(pk=mount_witness(surface, self.user.pk))
                    paths = self._file_paths(item)
                    self.assertTrue(all(p.is_file() for p in paths))
                files_seen += len(paths)
                self.assertEqual(before, set(model.objects.values_list('pk', flat=True)))
                self.assertFalse([p for p in paths if p.exists()])
        self.assertTrue(files_seen, 'witnesses carry files : the file half of this guard measures')

    def test_a_passage_keeps_what_existed_before_it(self):
        for surface in self.surfaces:
            with self.subTest(surface=surface.id):
                model = surface.model_class()
                kept = mount_witness(surface, self.user.pk)
                with witness_guard(surface, 'test'):
                    mount_witness(surface, self.user.pk)
                self.assertTrue(model.objects.filter(pk=kept).exists())

    def test_surfaces_of_one_model_share_one_guard(self):
        models = {s.model_class() for s in self.surfaces}
        self.assertLess(len(models), len(self.surfaces), 'the corpus has two surfaces of one model')
        self.assertEqual(len(models), len(witness_guards(self.surfaces, 'test')))

    def test_every_witness_mount_goes_through_the_guard_of_its_surface(self):
        """A direct call would fall back to the preview registry : the defect, one mount site away."""
        tree = ast.parse(Path(ui_smoke_surfaces.__file__).read_text(encoding='utf-8'))
        callers = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                   and any(isinstance(call, ast.Call) and getattr(call.func, 'id', '') == '_garde_de_montage'
                           for call in ast.walk(node))]
        self.assertEqual(['witness_guard'], callers)

    def test_a_guard_that_knows_no_model_says_it_will_remove_nothing(self):
        out = io.StringIO()
        with redirect_stdout(out), _garde_de_montage('no_such_app', 'test') as cleaned:
            pass
        self.assertEqual([], cleaned)
        self.assertIn('no_such_app', out.getvalue())


class WitnessSampleTest(TestCase):
    """Each content is read back by ITS reader : a witness nobody consumes proves nothing
    (`ui_smoke._png_1x1`, broken for months)."""

    def test_the_image_and_its_detections_coincide(self):
        from PIL import Image

        from wama.common.utils import detections
        content, ext = witness_sample('.png')
        self.assertEqual('.png', ext)
        self.assertEqual(WITNESS_IMAGE_SIZE, Image.open(io.BytesIO(content)).size)
        raw, ext = witness_sample('detections')
        self.assertEqual('.json', ext)
        doc = json.loads(raw)
        self.assertEqual(detections.KIND, doc['kind'])
        self.assertEqual([list(box) for _label, box in WITNESS_OBJECTS],
                         [d['box'] for d in doc['frames'][0]['d']])

    def test_the_document_splits_and_its_rendering_is_anchored(self):
        from wama.common.utils.document_sections import SECTION_ATTR, split_sections
        text = witness_sample('.md')[0].decode('utf-8')
        self.assertGreaterEqual(len(split_sections(text)), 3)
        self.assertIn(f'{SECTION_ATTR}="1"', witness_sample('.html')[0].decode('utf-8'))

    def test_the_score_has_voices_and_the_audio_sounds(self):
        self.assertIn('V:2', witness_sample('.abc')[0].decode('utf-8'))
        wav = witness_sample('.wav')[0]
        self.assertEqual(b'RIFF', wav[:4])
        self.assertTrue(any(wav[44:4000]), 'a waveform, not a flat line')

    def test_an_unknown_content_is_refused(self):
        with self.assertRaises(ValueError):
            witness_sample('.unknown')


class WitnessAccountTest(TestCase):
    """The witness is made for the account that OPENS the page : one routing rule for the session
    and the account id (`ui_smoke._uses_dev_account`) — the two copies had drifted, and the
    Writer's witness belonged to the standard account while the dev account opened the page."""

    def test_every_sandbox_app_routes_to_the_dev_account_and_no_other(self):
        from wama.common.app_registry import APP_CATALOG
        from wama.common.services.ui_smoke import _uses_dev_account
        for app, entry in APP_CATALOG.items():
            with self.subTest(app=app):
                expected = bool((entry or {}).get('generated_from') or (entry or {}).get('sandbox'))
                self.assertEqual(expected, _uses_dev_account(app))
        from wama.common.sandbox import born_apps
        for app in born_apps(APP_CATALOG):
            with self.subTest(born_from_manifest=app):
                self.assertTrue(_uses_dev_account(app))


class GeneratedWitnessTest(TestCase):

    def test_the_generator_renders_the_witness_written_in_the_manifest(self):
        from pathlib import Path

        from django.conf import settings

        from wama.common.manifests.codegen.surfaces_gen import declared_surfaces, render_surfaces
        manifest = json.loads((Path(settings.BASE_DIR) / 'manifests/app_drafts/writer.json')
                              .read_text(encoding='utf-8'))
        witness = declared_surfaces(manifest)[0]['witness']
        source, reason = render_surfaces(manifest)
        self.assertIsNone(reason)
        self.assertIn(f'witness={witness!r}', source)

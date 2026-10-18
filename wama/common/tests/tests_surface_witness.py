"""The WITNESS item of a surface (2026-10-18, Fabien : a thumbnail per brick in the UI bricks
catalogue). Each surface declares it (`Surface.witness`, data — also written in a generated app's
manifest) ; the nightly opens the surface on it and captures its bricks. These guards name no app :
they walk the declared surfaces."""
import io
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.services.ui_smoke import WITNESS_IMAGE_SIZE, WITNESS_OBJECTS, witness_sample
from wama.common.services.ui_smoke_surfaces import mount_witness
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
        born_from_manifest = [a for a, e in APP_CATALOG.items()
                              if (e or {}).get('sandbox') and not (e or {}).get('generated_from')]
        for app in born_from_manifest:
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

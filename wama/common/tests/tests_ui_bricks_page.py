"""The page of the UI bricks registry (2026-10-16, asked by Fabien : the map of the registries named
« Briques UI », nothing showed them). It derives from `common/surfaces.py` on each display, is reached
from the registry card and from the account menu, and shows which surfaces compose each brick."""
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape

from wama.common import registries
from wama.common.app_registry import app_identity, measured_adoption
from wama.common.mecanismes import MECHANISMS
from wama.common.surfaces import (BRICKS, SURFACES, THUMBNAILS_DIR, UIBrick, load_all,
                                  thumbnail_path)


class UIBricksPageTest(TestCase):

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('ui-bricks', password='x'))
        load_all()

    def _page(self):
        response = self.client.get(reverse('common:ui_bricks_catalog'))
        self.assertEqual(200, response.status_code)
        return response.content.decode('utf-8', 'replace')

    def test_every_declared_brick_has_its_card(self):
        page = self._page()
        self.assertTrue(BRICKS, 'the instrument sees the registry')
        for key, brick in BRICKS.items():
            with self.subTest(brick=key):
                self.assertIn(f'data-id="{key}"', page)
                self.assertIn(escape(brick.name), page)

    def test_a_brick_names_the_surfaces_that_compose_it(self):
        """An app is named by its declared identity (`app_identity`), never by its key."""
        page = self._page()
        self.assertTrue(SURFACES, 'at least one surface is declared')
        for surface in SURFACES.values():
            with self.subTest(surface=surface.id):
                self.assertIn(f'{app_identity(surface.app)["label"]} · {surface.label}', page)
                self.assertNotIn(f'>{surface.app} · ', page)

    def test_what_a_brick_reads_is_said_in_its_vocabulary(self):
        """`consumes` holds media natures or data types — the page says which, never a third word."""
        page = self._page()
        self.assertIn('nature de média', page)
        self.assertIn('type de données', page)

    def test_the_registry_card_and_the_account_menu_lead_here(self):
        url = reverse('common:ui_bricks_catalog')
        self.assertEqual('common:ui_bricks_catalog', registries.get('ui_bricks').url_name)
        from wama.common.app_registry import account_pages
        pages = {p['key']: p for p in account_pages()}
        self.assertEqual(url, reverse(pages['ui_bricks']['url_name']))
        self.assertEqual('wama', pages['ui_bricks']['section'])

    def test_a_derived_page_offers_no_refresh_button(self):
        page = self._page()
        self.assertNotIn('data-wama-refresh="ui_bricks"', page)
        self.assertIn('toujours à jour', page)


class BrickCompositionTest(TestCase):
    """Three levels (2026-10-19, Fabien) : a mechanism is a PIECE, a brick a WHOLE made of them.
    The page shows bricks only ; each says which mechanisms compose it, READ from its code — the
    owners of what it loads (`requires`) and what its own script consumes, by the very detection
    of the adoption scan (`mecanismes_scan.consumers`)."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('ui-parts', password='x'))
        load_all()

    def _page(self):
        response = self.client.get(reverse('common:ui_bricks_catalog'))
        self.assertEqual(200, response.status_code)
        return response.content.decode('utf-8', 'replace')

    def test_only_bricks_have_a_card(self):
        page = self._page()
        self.assertNotIn('data-f-famille', page, 'no « Système » family beside the bricks')
        for mechanism in MECHANISMS:
            if mechanism.key not in BRICKS:
                with self.subTest(mechanism=mechanism.key):
                    self.assertNotIn(f'data-id="{mechanism.key}"', page)

    def test_a_brick_is_composed_of_what_it_loads_and_what_its_script_uses(self):
        """The media transport loads the axis and the shuttle, and mounts the shared audio player
        through its `base.html` global — never the visitor identity for an `axis.attach(…)`."""
        parts = BRICKS['media_transport'].mechanisms()
        self.assertTrue({'media_axis', 'shuttle', 'audio_player'} <= set(parts), parts)
        self.assertNotIn('visitor_identity', parts)
        names = {m.key: m.name for m in MECHANISMS}
        card = self._page().split('data-id="media_transport"', 1)[1].split('wama-cat-card', 1)[0]
        for key in ('media_axis', 'shuttle', 'audio_player'):
            with self.subTest(part=key):
                self.assertIn(f'title="{key}">{names[key]}</span>', card)

    def test_a_composition_is_read_from_the_script_never_declared(self):
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as js:
            js.write('WamaAudioPlayer.mount(el); axis.attach(el);')
        brick = UIBrick(key='fake', name='Fausse', description='', script='fake/brick.js',
                        requires=('common/js/wama-shuttle.js',))
        with mock.patch('django.contrib.staticfiles.finders.find', return_value=js.name):
            self.assertEqual(['audio_player', 'shuttle'], brick.mechanisms())
        with mock.patch('django.contrib.staticfiles.finders.find', return_value=None):
            self.assertEqual(['shuttle'], brick.mechanisms(), 'a script not found reads nothing')


class PageBrickTest(TestCase):
    """Page bricks (2026-10-19, Fabien, step 3) : an app page mounts them by a template (or the
    base page, for all), never a surface. Nothing flows to them : they read what the mounting app
    DECLARES (a facet of its manifest, or its pipeline) ; the apps that mount them are the measured
    adoption of the mechanism that holds that template."""

    PAGE_BRICKS = ('entry_card', 'inspector_panel', 'media_viewer', 'queue')

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('ui-page', password='x'))
        load_all()

    def test_a_page_brick_reads_only_what_the_mounting_app_states(self):
        from wama.common.manifests.builtin.app import APP_FACETS
        from wama.common.manifests.kinds import MANIFEST_KINDS
        for key, brick in BRICKS.items():
            with self.subTest(brick=key):
                self.assertEqual(key in self.PAGE_BRICKS, brick.is_page)
                if not brick.is_page:
                    self.assertEqual((), brick.declarations, 'a surface brick reads what flows')
                    continue
                self.assertEqual((), brick.consumes, 'nothing flows to a page brick')
                self.assertTrue(brick.declarations)
                for value in brick.declarations:
                    kind, _, facet = value.partition('.')
                    self.assertIn(kind, MANIFEST_KINDS, value)
                    if facet:
                        self.assertEqual('app', kind, value)
                        self.assertIn(facet, APP_FACETS, value)

    def test_its_mount_is_a_file_a_page_names(self):
        from wama.common.surfaces import source_file
        for key in self.PAGE_BRICKS:
            with self.subTest(brick=key):
                self.assertTrue(source_file(BRICKS[key].mount), BRICKS[key].mount)

    def test_the_apps_that_mount_it_are_the_measured_adoption_of_its_template(self):
        report = {'generated_at': '2026-10-19T00:00:00+00:00',
                  'criteria': {'c_card': {'mechanism': 'new_item_card'}},
                  'apps': {'anonymizer': {'conv': {'c_card': True}},
                           'composer': {'conv': {'c_card': 'partial'}},
                           'imager': {'conv': {'c_card': False}}}}
        with mock.patch('wama.common.app_registry._conformity_report', return_value=report):
            adoption = BRICKS['entry_card'].adoption()
            self.assertEqual({'anonymizer': True, 'composer': 'partial', 'imager': False},
                             adoption['apps'])
            self.assertEqual(['c_card'], adoption['criteria'])
            self.assertEqual({'apps': {}, 'criteria': [], 'measured_at': None},
                             BRICKS['image_boxes'].adoption(), 'a surface brick: its surfaces')
            response = self.client.get(reverse('common:ui_bricks_catalog'))
        card = response.content.decode('utf-8', 'replace').split(
            'data-id="entry_card"', 1)[1].split('wama-cat-card', 1)[0]
        self.assertIn(f'>{app_identity("anonymizer")["label"]}</span>', card)
        self.assertIn(f'>{app_identity("composer")["label"]}<small>en partie</small>', card)
        self.assertNotIn(app_identity('imager')['label'], card, 'a red app does not mount it')
        self.assertIn('data-f-montage="Page"', card)
        self.assertIn('ports<small>facette de l&#x27;app</small>', card)

    def test_a_surface_never_places_a_page_brick(self):
        from wama.common.manifests.codegen.surfaces_gen import _check
        from wama.common.surfaces import BrickSlot, Surface, register_surface
        slot = BrickSlot(id='card', brick='entry_card', x=0, y=0, w=4, h=4)
        with self.assertRaises(ValueError):
            register_surface(Surface(app='nowhere', key='edit', label='x', model='x.Y',
                                     slots=(slot,), reads={}, edits='f'))
        self.assertNotIn('nowhere.edit', SURFACES)
        refused = _check({'key': 'edit', 'label': 'x', 'slots': [
            {'id': 'card', 'brick': 'entry_card', 'x': 0, 'y': 0, 'w': 4, 'h': 4}]}, {}, set())
        self.assertIn('brique de PAGE', refused)

    def test_a_composition_is_read_from_the_code_not_from_its_comments(self):
        """The viewer's script names, in comments only, the media picker that CALLS it and the
        queue scripts it resembles : none is a piece of it ; the overlay class it sets is one."""
        parts = BRICKS['media_viewer'].mechanisms()
        self.assertIn('preview', parts)
        for prose in ('media_picker', 'queue_front', 'queue_dnd', 'inspector'):
            with self.subTest(prose=prose):
                self.assertNotIn(prose, parts)


class MeasuredAdoptionTest(TestCase):
    """What the MEASURED grid says of a mechanism (`app_registry.measured_adoption`) : the
    criteria that check it and, per app, all green / partial / none — read from the report
    `/apps/` reads, never a scan of the repository ; without a report, nothing is invented."""

    REPORT = {'generated_at': '2026-10-18T00:00:00+00:00',
              'criteria': {'c_one': {'mechanism': 'checked'}, 'c_two': {'mechanism': 'checked'}},
              'apps': {'anonymizer': {'conv': {'c_one': True, 'c_two': True}},
                       'composer': {'conv': {'c_one': True, 'c_two': False}},
                       'imager': {'conv': {'c_one': False, 'c_two': False}},
                       'describer': {'conv': {}}}}

    def test_the_state_per_app_is_read_from_the_report(self):
        with mock.patch('wama.common.app_registry._conformity_report', return_value=self.REPORT):
            adoption = measured_adoption('checked')
            self.assertEqual(['c_one', 'c_two'], adoption['criteria'])
            self.assertEqual({'anonymizer': True, 'composer': 'partial', 'imager': False},
                             adoption['apps'])
            self.assertEqual([], measured_adoption('unchecked')['criteria'])

    def test_without_a_measured_report_nothing_is_invented(self):
        with mock.patch('wama.common.app_registry._conformity_report', return_value=None):
            self.assertEqual({'criteria': [], 'apps': {}, 'measured_at': None},
                             measured_adoption('checked'))


class BrickThumbnailTest(TestCase):
    """A brick's thumbnail is the capture the nightly took (`surfaces.thumbnail`), served from
    `STATIC_ROOT` under an address that changes with the capture ; without one, the card says so."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('ui-thumb', password='x'))
        load_all()

    def test_a_captured_brick_shows_its_capture_and_an_uncaptured_one_says_so(self):
        shot, bare = sorted(BRICKS)[:2]
        with tempfile.TemporaryDirectory() as root, override_settings(STATIC_ROOT=root):
            path = thumbnail_path(shot)
            path.parent.mkdir(parents=True)
            path.write_bytes(b'capture')
            response = self.client.get(reverse('common:ui_bricks_catalog'))
        page = response.content.decode('utf-8', 'replace')
        card = page.split(f'data-id="{shot}"', 1)[1].split('wama-cat-card', 1)[0]
        self.assertIn(f'class="wama-cat-thumb" src="/static/{THUMBNAILS_DIR}/{shot}.png?v=', card)
        other = page.split(f'data-id="{bare}"', 1)[1].split('wama-cat-card', 1)[0]
        self.assertIn('aucune capture', other)
        self.assertNotIn('<img class="wama-cat-thumb"', other)

"""The page of the UI bricks registry (2026-10-16, asked by Fabien : the map of the registries named
« Briques UI », nothing showed them). It derives from `common/surfaces.py` on each display, is reached
from the registry card and from the account menu, and shows which surfaces compose each brick."""
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

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
                self.assertIn(brick.name, page)

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

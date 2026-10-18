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
from wama.common.mecanismes import MECHANISMS, UI_DOMAIN
from wama.common.surfaces import (BRICK_FAMILIES, BRICKS, SURFACES, THUMBNAILS_DIR, load_all,
                                  thumbnail_path)

#: The components of the interface, sorted — the « Système » family reads them, nothing else.
SYSTEM = sorted(m.key for m in MECHANISMS if m.domain == UI_DOMAIN)


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


class SystemComponentsTest(TestCase):
    """The « Système » family (2026-10-18, Fabien) : the shared components of the interface, read
    from the `UI_DOMAIN` of the mechanisms registry — and « used by » is the adoption MEASURED by
    the conformity grid, the report `/apps/` reads, never a scan of the repository."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('ui-system', password='x'))
        load_all()

    def _page(self, report=None):
        with mock.patch('wama.common.app_registry._conformity_report', return_value=report):
            response = self.client.get(reverse('common:ui_bricks_catalog'))
        self.assertEqual(200, response.status_code)
        return response.content.decode('utf-8', 'replace')

    def test_every_component_of_the_interface_domain_has_its_card_and_no_other(self):
        page = self._page()
        self.assertTrue(SYSTEM, 'the instrument sees the domain')
        self.assertIn(f'data-f-famille="{BRICK_FAMILIES["system"]}"', page)
        for key in SYSTEM:
            with self.subTest(component=key):
                self.assertIn(f'data-id="{key}"', page)
        for mechanism in MECHANISMS:
            if mechanism.domain != UI_DOMAIN and mechanism.key not in BRICKS:
                with self.subTest(outside=mechanism.key):
                    self.assertNotIn(f'data-id="{mechanism.key}"', page)

    def test_used_by_is_the_adoption_the_grid_measured(self):
        checked, unchecked = SYSTEM[0], SYSTEM[1]
        report = {'generated_at': '2026-10-18T00:00:00+00:00',
                  'criteria': {'c_one': {'mechanism': checked}, 'c_two': {'mechanism': checked}},
                  'apps': {'anonymizer': {'conv': {'c_one': True, 'c_two': True}},
                           'composer': {'conv': {'c_one': True, 'c_two': False}},
                           'imager': {'conv': {'c_one': False, 'c_two': False}},
                           'describer': {'conv': {}}}}
        with mock.patch('wama.common.app_registry._conformity_report', return_value=report):
            adoption = measured_adoption(checked)
            self.assertEqual(['c_one', 'c_two'], adoption['criteria'])
            self.assertEqual({'anonymizer': True, 'composer': 'partial', 'imager': False},
                             adoption['apps'])
            self.assertEqual([], measured_adoption(unchecked)['criteria'])
        page = self._page(report)
        card = page.split(f'data-id="{checked}"', 1)[1].split('wama-cat-card', 1)[0]
        label = lambda app: app_identity(app)['label']
        self.assertIn(f'>{label("anonymizer")}</span>', card)
        self.assertIn(f'>{label("composer")}<small>partiel</small>', card)
        self.assertNotIn(f'>{label("imager")}', card)
        self.assertNotIn('>anonymizer</span>', card, 'a chip names the app, not its key')
        other = page.split(f'data-id="{unchecked}"', 1)[1].split('wama-cat-card', 1)[0]
        self.assertIn('aucun critère de la grille ne le vérifie', other)

    def test_without_a_measured_report_nothing_is_invented(self):
        self.assertEqual({'criteria': [], 'apps': {}, 'measured_at': None},
                         self._adoption_without_report())
        self.assertIn('aucun critère de la grille ne le vérifie', self._page(None))

    def _adoption_without_report(self):
        with mock.patch('wama.common.app_registry._conformity_report', return_value=None):
            return measured_adoption(SYSTEM[0])


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

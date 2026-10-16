"""The page of the UI bricks registry (2026-10-16, asked by Fabien : the map of the registries named
« Briques UI », nothing showed them). It derives from `common/surfaces.py` on each display, is reached
from the registry card and from the account menu, and shows which surfaces compose each brick."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wama.common import registries
from wama.common.surfaces import BRICKS, SURFACES, load_all


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
        page = self._page()
        self.assertTrue(SURFACES, 'at least one surface is declared')
        for surface in SURFACES.values():
            with self.subTest(surface=surface.id):
                self.assertIn(f'{surface.app} · {surface.label}', page)

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

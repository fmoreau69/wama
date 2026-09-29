"""
WAMA Common — Tests de FUMÉE transverses (créés 2026-07-06 après l'incident `layout` dupliqué).

Leçon de l'incident : un kwarg dupliqué dans APP_CATALOG (SyntaxError) a cassé menu déroulant,
accueil et /apps/ SANS être détecté — `manage.py check` n'importe jamais app_registry (seul le
rendu d'une page le fait, via le context processor), et le serveur déjà lancé gardait l'ancien
module en mémoire jusqu'au restart. Ces tests rendent RÉELLEMENT les pages.

Lancer : `python manage.py test wama.common` (WSL venv). À exécuter après TOUTE modification
de app_registry.py, d'un context processor, d'un template de base ou d'un index d'app.
"""

from django.test import TestCase
from django.urls import reverse


class CatalogSmokeTests(TestCase):
    """Le catalogue s'importe et alimente les surfaces transverses."""

    def test_app_catalog_importable_et_peuple(self):
        # Une SyntaxError dans app_registry.py fait échouer CE test (pas manage.py check).
        from wama.common.app_registry import APP_CATALOG
        self.assertGreaterEqual(len(APP_CATALOG), 10)

    def test_conformity_summary(self):
        from wama.common.app_registry import get_conformity_summary
        summary = get_conformity_summary()  # ne doit pas lever
        self.assertTrue(summary)


class PagesSmokeTests(TestCase):
    """Chaque surface visible rend 200 — accueil, catalogue, et l'index de CHAQUE app."""

    def test_accueil(self):
        self.assertEqual(self.client.get('/', follow=True).status_code, 200)

    def test_catalogue_apps(self):
        self.assertEqual(self.client.get('/common/apps/', follow=True).status_code, 200)

    def test_index_de_chaque_app_du_catalogue(self):
        from wama.common.app_registry import APP_CATALOG
        for key, meta in APP_CATALOG.items():
            with self.subTest(app=key):
                url = reverse(meta['url_name'])
                self.assertEqual(self.client.get(url, follow=True).status_code, 200,
                                 f"index de {key} ne rend pas 200")

"""Aucune route de la médiathèque ne sert un visiteur NON CONNECTÉ (2026-09-29).

Mesuré le jour même : 9 vues sur 17 n'avaient pas `@login_required` ; leur `_get_user` retombait sur
le compte anonyme de service, si bien qu'un visiteur non connecté DÉPOSAIT un asset (200, asset créé
au compte « anonymous »), listait, éditait ou supprimait ceux de ce compte, et lisait la liste des
ressources système. La garde est GÉNÉRIQUE : elle parcourt les routes déclarées de l'app, donc une
route ajoutée demain sans décorateur la fait rougir.
"""
import re

from django.conf import settings
from django.test import TestCase
from django.urls import URLPattern, reverse

from wama.media_library import urls as media_library_urls


def _routes():
    """(nom, chemin résolu) de chaque route — les paramètres reçoivent une valeur quelconque."""
    for pattern in media_library_urls.urlpatterns:
        if not isinstance(pattern, URLPattern) or not pattern.name:
            continue
        kwargs = {}
        for name, conv in pattern.pattern.converters.items():
            kwargs[name] = 1 if conv.__class__.__name__ == 'IntConverter' else 'x'
        yield pattern.name, reverse(f'{media_library_urls.app_name}:{pattern.name}', kwargs=kwargs)


class NoRouteServesAnAnonymousVisitorTest(TestCase):

    def test_the_routes_are_found(self):
        self.assertGreaterEqual(len(list(_routes())), 15, 'garde à vide')

    def test_every_route_sends_an_anonymous_visitor_to_the_login(self):
        login = str(settings.LOGIN_URL)
        for name, path in _routes():
            for method in ('get', 'post'):
                with self.subTest(route=name, method=method):
                    response = getattr(self.client, method)(path)
                    self.assertEqual(302, response.status_code,
                                     f'{name} ({method.upper()}) répond {response.status_code} à un anonyme')
                    self.assertTrue(re.search(re.escape(login), response['Location']),
                                    f'{name} redirige ailleurs que vers la connexion')

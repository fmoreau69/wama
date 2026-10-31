"""La CLÉ d'un élément dans les routes communes — `<item:pk>`, un numéro OU un UUID (2026-10-31).

Décision de Fabien : les pièces communes acceptent les clés UUID des apps du monde Lab plutôt que
de migrer leurs clés. Tenu ici : chaque route d'ÉLÉMENT se résout et se construit avec les deux
formes, une clé d'une autre forme rend 404 (jamais 500), et les objets propres au substrat
(notifications, demandes, planification) gardent un numéro.
"""
import uuid

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import resolve, reverse

#: Les routes d'un ÉLÉMENT d'app : nom → arguments avant la clé.
ITEM_ROUTES = {
    'unified_preview': ['anonymizer'],
    'unified_detail': ['anonymizer'],
    'surface': ['anonymizer', 'review'],
    'surface_data': ['anonymizer', 'review'],
    'surface_save': ['anonymizer', 'review'],
    'surface_revisions': ['transcriber', 'correct'],
    'api_envoyer_vers': ['anonymizer'],
    'api_result_reference': ['anonymizer', 'element'],
    'api_result_import': ['anonymizer'],
}


class ItemKeyRouteTest(SimpleTestCase):

    def test_every_item_route_takes_a_number_and_a_uuid(self):
        key = uuid.uuid4()
        for name, before in ITEM_ROUTES.items():
            with self.subTest(route=name):
                for pk, kind in ((42, int), (key, uuid.UUID)):
                    url = reverse(f'common:{name}', args=before + [pk])
                    match = resolve(url)
                    self.assertEqual(f'common:{name}', match.view_name)
                    self.assertEqual(pk, match.kwargs['pk'])
                    self.assertIsInstance(match.kwargs['pk'], kind)

    def test_a_key_of_neither_form_is_no_route(self):
        from django.urls import Resolver404
        with self.assertRaises(Resolver404):
            resolve('/common/preview/anonymizer/abc/')

    def test_the_objects_of_the_substrate_keep_a_number(self):
        from django.urls import NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse('common:notification_open', args=[uuid.uuid4()])

    def test_the_surface_routes_are_declared_once(self):
        """Les routes JUMELLES `<uuid:pk>` du 2026-10-29 sont retirées : un seul motif par nom."""
        from wama.common import urls
        names = [p.name for p in urls.urlpatterns if getattr(p, 'name', None)]
        for name in ITEM_ROUTES:
            self.assertEqual(1, names.count(name), name)


class ItemKeyOfTheOtherFormTest(TestCase):
    """Une clé de l'autre forme que celle du modèle : 404, pas une erreur."""

    def test_a_uuid_on_a_numbered_app_and_a_number_on_a_uuid_app_answer_404(self):
        user = get_user_model().objects.create_user('item_route_user', password='x')
        self.client.force_login(user)
        self.assertEqual(404, self.client.get(
            reverse('common:unified_detail', args=['anonymizer', uuid.uuid4()])).status_code)
        self.assertEqual(404, self.client.get(
            reverse('common:surface_data', args=['face_analyzer', 'analysis', 7])).status_code)

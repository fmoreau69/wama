"""Le regroupement À L'ARRIVÉE est UN mécanisme commun (2026-10-16, demande de Fabien : « tout
doit être commun, universel et uniforme dans WAMA »).

Avant : la `consolidate` de la fabrique ÉTAIT la fusion stricte, cinq apps la redéfinissaient pour
ranger par nature ou poser un champ de liaison, et l'import du gestionnaire de fichiers gardait une
liste écrite à la main de six helpers — imager et synthesizer n'y étaient pas : un lot envoyé vers
eux arrivait en N cards. Désormais chaque fabrique inscrit son regroupement
(`queue_manipulation.consolidate_arrival`) et tout chemin d'arrivée l'appelle.

Ce que ces gardes tiennent, sans nommer d'app : toute file à lot DÉCLARE son regroupement ; il
range les éléments dans l'ordre d'arrivée ; toute route `consolidate` d'app est celle de la
fabrique ; l'import ne connaît aucune app. Puis le geste réel, sur les deux apps qui en étaient
privées.
"""
import ast
import inspect
import io
import json
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import get_resolver, reverse

User = get_user_model()


def _surfaces_with_batches():
    """`(surface, modèle)` de chaque surface à lot, jumelles exclues — même relevé que les
    autres contrats génériques (`tests_send_to._surfaces_with_batches`)."""
    from wama.common.tests.tests_send_to import _surfaces_with_batches as surfaces
    return surfaces()


class ArrivalIsDeclaredOnceTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('arrival_contract', password='x')

    def test_every_queue_with_batches_registers_its_arrival(self):
        from wama.common.utils.queue_manipulation import _ARRIVALS, consolidate_arrival
        surfaces = _surfaces_with_batches()
        self.assertGreaterEqual(len(surfaces), 10, [s for s, _ in surfaces])
        for surface, model in surfaces:
            with self.subTest(surface=surface):
                consolidate_arrival(model, [], self.user)        # importe la vue au besoin
                self.assertIn(model, _ARRIVALS, f'{surface} : aucune fabrique de file déclarée')

    def test_arrived_items_end_in_one_batch_in_arrival_order(self):
        """Trois éléments de même nature (la fabrique de test les crée identiques) → UN lot,
        dans l'ordre des ids donnés (ici, l'inverse de leur création)."""
        from wama.common.tests.tests_queue_delete_contract import _instance
        from wama.common.utils.batch_common import batch_elements
        from wama.common.utils.queue_manipulation import consolidate_arrival
        for surface, model in _surfaces_with_batches():
            with self.subTest(surface=surface):
                items = [_instance(model, self.user) for _ in range(3)]
                ids = [i.pk for i in reversed(items)]
                batches = consolidate_arrival(model, ids, self.user)
                self.assertEqual(1, len(batches), f'{surface} : {len(batches)} lots pour une nature')
                self.assertEqual(ids, [e.pk for e in batch_elements(batches[0], model)])

    def test_a_single_arrival_lands_in_its_own_batch(self):
        from wama.common.tests.tests_queue_delete_contract import _instance
        from wama.common.utils.batch_common import batch_elements
        from wama.common.utils.queue_manipulation import consolidate_arrival
        for surface, model in _surfaces_with_batches():
            with self.subTest(surface=surface):
                item = _instance(model, self.user)
                batches = consolidate_arrival(model, [item.pk], self.user)
                self.assertEqual([item.pk], [e.pk for e in batch_elements(batches[0], model)])

    def test_every_app_consolidate_route_is_the_common_one(self):
        """Plus aucune `consolidate` écrite par une app : la route est la vue de la fabrique.
        Les jumelles de bac à sable sont exclues, comme des autres contrats génériques : elles
        portent le code de leur source ou du générateur au jour de leur création (un bouchon 501
        pour un domaine que le générateur ne sait pas encore produire), et se régénèrent — leur
        écart se mesure par la convergence, pas ici."""
        from wama.common.app_registry import APP_CATALOG
        twins = {app for app, spec in APP_CATALOG.items()
                 if (spec or {}).get('generated_from') or (spec or {}).get('sandbox')}
        seen = []
        for namespace, (_prefix, resolver) in get_resolver().namespace_dict.items():
            if namespace in twins:
                continue
            for pattern in resolver.url_patterns:
                name = getattr(pattern, 'name', '') or ''
                if name == 'consolidate' or name.endswith('_consolidate'):
                    view = inspect.unwrap(pattern.callback)
                    seen.append(namespace)
                    self.assertIn('make_queue_manipulation_views', view.__qualname__,
                                  f'{namespace}:{name} est une consolidate écrite par l\'app')
        self.assertGreaterEqual(len(set(seen)), 8, seen)

    def test_the_file_manager_import_names_no_app(self):
        """L'import range par la déclaration de chaque app : aucun nom d'app, aucun helper d'app."""
        from wama.filemanager import views
        tree = ast.parse(inspect.getsource(views.api_import_to_app))
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse({m for m in imported if m and m.startswith('wama.') and m.endswith('.views')},
                         imported)
        compared = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Compare)
                    and any(isinstance(op, ast.Eq) for op in n.ops)
                    and any(isinstance(c, ast.Constant) and isinstance(c.value, str)
                            for c in [n.left, *n.comparators])
                    and 'target_app' in ast.unparse(n)]
        self.assertEqual([], compared, 'un `target_app == "<app>"` est revenu dans l\'import')

    def test_the_consolidate_view_groups_by_nature_and_merge_still_rejects(self):
        """`consolidate` range (deux natures → deux lots) ; `merge` refuse (409) — sur une app à
        liaison, le converter (FK directe) étant tenu par `tests_queue_dnd.RefusDeFusionTest`."""
        from django.test import RequestFactory
        from wama.anonymizer.models import Media
        from wama.anonymizer.views import consolidate, merge
        image = Media.objects.create(user=self.user, media_type='image', file='a.png')
        video = Media.objects.create(user=self.user, media_type='video', file='b.mp4')
        request = RequestFactory().post('/', {'ids': [str(image.pk), str(video.pk)]})
        request.user = self.user
        self.assertEqual(409, merge(request).status_code)
        request = RequestFactory().post('/', {'ids': [str(image.pk), str(video.pk)]})
        request.user = self.user
        data = json.loads(consolidate(request).content)
        self.assertTrue(data['consolidated'])
        self.assertEqual(2, len(data['batch_ids']))


class ArrivalThroughTheFileManagerTest(TestCase):
    """Le geste RÉEL — « Envoyer vers » de deux fichiers — sur les deux apps que la liste écrite à
    la main oubliait : un lot à l'arrivée, dans l'ordre d'envoi."""

    def setUp(self):
        media = tempfile.mkdtemp(prefix='wama_arrival_')
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        setting = override_settings(MEDIA_ROOT=media)
        setting.enable()
        self.addCleanup(setting.disable)
        self.media = Path(media)
        self.user = User.objects.create_user('arrival_send', password='x', is_staff=True,
                                             is_superuser=True)
        self.client.force_login(self.user)

    def _temp(self, name, content: bytes) -> str:
        rel = f'users/{self.user.id}/temp/{name}'
        (self.media / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.media / rel).write_bytes(content)
        return rel

    def _send(self, app, files):
        paths = [self._temp(name, content) for name, content in files]
        response = self.client.post(reverse('filemanager:api_import'),
                                    json.dumps({'paths': paths, 'app': app}),
                                    content_type='application/json')
        self.assertEqual(200, response.status_code, response.content[:300])
        body = response.json()
        self.assertEqual(len(files), body['count'], body)
        return [r['id'] for r in body['results']]

    def _one_batch(self, model, ids):
        from wama.common.utils.batch_common import batch_elements, batch_model_for
        batches = batch_model_for(model).objects.filter(user=self.user)
        self.assertEqual(1, batches.count(), 'les fichiers envoyés ensemble ont formé plusieurs lots')
        self.assertEqual(ids, [e.pk for e in batch_elements(batches.get(), model)])

    def test_two_images_sent_to_the_imager_arrive_as_one_batch(self):
        from PIL import Image
        from wama.imager.models import ImageGeneration

        def png():
            buffer = io.BytesIO()
            Image.new('RGB', (8, 8), (10, 200, 30)).save(buffer, format='PNG')
            return buffer.getvalue()
        self._one_batch(ImageGeneration, self._send('imager', [('a.png', png()), ('b.png', png())]))

    def test_two_texts_sent_to_the_synthesizer_arrive_as_one_batch_with_their_output_names(self):
        from wama.synthesizer.models import BatchSynthesisItem, VoiceSynthesis
        ids = self._send('synthesizer', [('first.txt', b'Hello.'), ('second.txt', b'World.')])
        self._one_batch(VoiceSynthesis, ids)
        names = list(BatchSynthesisItem.objects.filter(synthesis_id__in=ids)
                     .order_by('row_index').values_list('output_filename', flat=True))
        self.assertTrue(all(n.endswith('.wav') for n in names), names)

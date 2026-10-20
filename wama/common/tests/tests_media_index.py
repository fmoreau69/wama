"""La recherche de la file par CONTENU (`WAMA_MEMORY.md §7sexies`, 2026-10-19).

Ce qui est gardé, sans aucun modèle chargé (le service de vectorisation est simulé) :
  1. QUOI s'indexe — les seules IMAGES qu'un élément porte et qui existent sur le disque ;
  2. l'INDEX — une passe écrit un vecteur par image, ne refait rien la fois suivante, refait une
     image changée au même chemin, et la purge retire ce dont l'élément a disparu ;
  3. la RÈGLE DE RÉPONSE — l'écart à la requête neutre, pas le score brut ; les droits de lecture
     du compte ; les éléments non indexés rendus « à indexer » ;
  4. le GESTE — l'API met l'indexation en tâche une fois, la tâche est au palier bas de la file
     GPU, planifiée la nuit hors de la plage des tests, et installe son modèle par la route ;
  5. le NAVIGATEUR — l'adresse d'une card se lit par la brique de la preview (V8).
"""
import importlib.util
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock, skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from wama.common.models import MEDIA_EMBEDDING_DIMS, MediaVector
from wama.common.vectors import media_index
from wama.common.vectors.spaces import MEDIA

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
JS = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'
User = get_user_model()


def _axis(i, scale=1.0):
    """Un vecteur unitaire de l'espace `media` le long de l'axe `i`."""
    vec = [0.0] * MEDIA_EMBEDDING_DIMS
    vec[i] = scale
    return vec


def _vec(coords):
    """Un vecteur de l'espace `media` aux coordonnées `{axe: valeur}`."""
    vec = [0.0] * MEDIA_EMBEDDING_DIMS
    for axis, value in coords.items():
        vec[axis] = value
    return vec


class _MediaCase(TestCase):
    """Un MEDIA_ROOT jetable, la seule surface `describer`, et deux comptes."""

    def setUp(self):
        from wama.describer.models import Description
        self.Description = Description
        self.root = tempfile.mkdtemp(prefix='wama_media_index_')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.root)
        override.enable()
        self.addCleanup(override.disable)
        patcher = mock.patch.object(media_index, 'surfaces', return_value={'describer': Description})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.me = User.objects.create_user('media_index_me', password='x')
        self.other = User.objects.create_user('media_index_other', password='x')

    def _file(self, rel, color=(200, 30, 30)):
        path = os.path.join(self.root, *rel.split('/'))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if rel.endswith('.png'):
            Image.new('RGB', (32, 32), color).save(path)
        else:
            Path(path).write_bytes(b'RIFF....WAVE')
        return rel

    def _element(self, user, rel):
        return self.Description.objects.create(user=user, input_file=rel,
                                               filename=os.path.basename(rel))


class ElementImagesTest(_MediaCase):

    def test_only_existing_images_are_indexed(self):
        image = self._element(self.me, self._file('users/1/describer/input/car.png'))
        sound = self._element(self.me, self._file('users/1/describer/input/talk.wav'))
        gone = self._element(self.me, 'users/1/describer/input/missing.png')
        self.assertEqual(media_index.element_images(image),
                         [('input_file', 'users/1/describer/input/car.png')])
        self.assertEqual(media_index.element_images(sound), [], "un son n'est pas une image")
        self.assertEqual(media_index.element_images(gone), [], 'un fichier absent ne compte pas')


class IndexTest(_MediaCase):

    def _run(self, vec=None):
        with mock.patch.multiple('wama.common.vectors.service_client', available=mock.DEFAULT,
                                 residency_allowed=mock.DEFAULT, embed=mock.DEFAULT,
                                 unload=mock.DEFAULT, release=mock.DEFAULT,
                                 reserve=mock.DEFAULT) as fakes:
            fakes['available'].return_value = True
            fakes['residency_allowed'].return_value = (False, 'test')
            fakes['embed'].side_effect = lambda space, items, **kw: [vec or _axis(0) for _ in items]
            return media_index.index(), fakes

    def test_a_pass_writes_one_vector_per_image_then_has_nothing_left(self):
        element = self._element(self.me, self._file('users/1/describer/input/car.png'))
        summary, fakes = self._run()
        self.assertEqual(summary['indexed'], 1)
        row = MediaVector.objects.get(surface='describer', object_id=element.pk)
        self.assertEqual((row.space, row.embedding_model, row.field),
                         (MEDIA.key, MEDIA.model, 'input_file'))
        self.assertEqual(fakes['embed'].call_args.args[0], MEDIA.key)
        fakes['unload'].assert_called_once_with(MEDIA.key)
        self.assertEqual(media_index.pending(), [], 'la seconde passe ne refait rien')

    def test_an_image_changed_at_the_same_path_is_indexed_again(self):
        rel = self._file('users/1/describer/input/car.png')
        self._element(self.me, rel)
        self._run()
        Image.new('RGB', (64, 48), (10, 10, 200)).save(os.path.join(self.root, *rel.split('/')))
        self.assertEqual([e['path'] for e in media_index.pending()], [rel])

    def test_the_purge_forgets_a_removed_element(self):
        element = self._element(self.me, self._file('users/1/describer/input/car.png'))
        self._run()
        element.delete()
        self.assertEqual(media_index.purge(), 1)
        self.assertFalse(MediaVector.objects.exists())

    def test_a_missing_model_writes_nothing(self):
        self._element(self.me, self._file('users/1/describer/input/car.png'))
        with mock.patch('wama.common.vectors.service_client.available', return_value=False):
            summary = media_index.index()
        self.assertTrue(summary['unavailable'])
        self.assertFalse(MediaVector.objects.exists())


class SearchTest(_MediaCase):
    """Axe 0 = la requête, axe 1 = la requête neutre. La voiture : brut 0,50, neutre 0 (écart
    +0,50). Le chat : brut 0,70 — PLUS HAUT —, neutre 0,71 (écart −0,01). C'est l'écart qui décide,
    pas le score brut (mesure du 2026-10-19)."""

    def setUp(self):
        super().setUp()
        self.car = self._element(self.me, self._file('users/1/describer/input/car.png'))
        self.cat = self._element(self.me, self._file('users/1/describer/input/cat.png'))
        self.theirs = self._element(self.other, self._file('users/2/describer/input/car2.png'))
        for element, vec in ((self.car, _vec({0: 0.5, 2: 0.866})),
                             (self.cat, _vec({0: 0.70, 1: 0.71, 3: 0.06})),
                             (self.theirs, _axis(0))):
            MediaVector.objects.create(surface='describer', object_id=element.pk, field='input_file',
                                       path=element.input_file.name, content_sig='x',
                                       space=MEDIA.key, embedding_model=MEDIA.model, embedding=vec)
        self.queries = [_axis(0)] + [_axis(1)] * len(media_index.NEUTRAL_QUERIES)

    def _search(self, user, addresses, query='voiture'):
        with mock.patch('wama.common.vectors.service_client.embed',
                        return_value=self.queries) as embed:
            return media_index.search(user, query, addresses), embed

    def test_the_offset_to_the_neutral_query_decides(self):
        result, embed = self._search(self.me, [('describer', self.car.pk), ('describer', self.cat.pk)])
        self.assertEqual([h['pk'] for h in result['hits']], [self.car.pk])
        self.assertEqual(embed.call_args.args[1], ['voiture', *media_index.NEUTRAL_QUERIES])
        self.assertTrue(embed.call_args.kwargs['query'], 'la requête porte le préfixe de l’espace')

    def test_an_element_the_account_cannot_list_is_never_answered(self):
        result, _ = self._search(self.me, [('describer', self.theirs.pk)])
        self.assertEqual((result['hits'], result['indexed']), ([], 0))

    def test_an_element_without_vector_is_returned_to_index(self):
        fresh = self._element(self.me, self._file('users/1/describer/input/new.png'))
        result, _ = self._search(self.me, [('describer', self.car.pk), ('describer', fresh.pk)])
        self.assertEqual(result['pending'], [('describer', fresh.pk)])

    def test_unknown_surfaces_and_bad_keys_are_ignored(self):
        result, embed = self._search(self.me, [('nowhere', 1), ('describer', 'x'), (None, None)])
        self.assertEqual(result, {'hits': [], 'pending': [], 'indexed': 0})
        embed.assert_not_called()


class SearchApiTest(_MediaCase):

    def setUp(self):
        super().setUp()
        cache.delete('common.index_media.queued')
        self.addCleanup(cache.delete, 'common.index_media.queued')
        self.element = self._element(self.me, self._file('users/1/describer/input/car.png'))
        self.url = reverse('common:api_queue_content_search')

    def _post(self, q='voiture'):
        return self.client.post(self.url, {'q': q, 'cards': [{'surface': 'describer',
                                                              'pk': self.element.pk}]},
                                content_type='application/json')

    def test_an_unindexed_queue_has_its_indexing_queued_once(self):
        self.client.force_login(self.me)
        with mock.patch('wama.common.tasks.index_media_task.delay') as delay:
            first = self._post().json()
            second = self._post().json()
        self.assertEqual((first['pending'], first['queued'], second['queued']), (1, True, False))
        delay.assert_called_once_with(addresses=[['describer', self.element.pk]])

    def test_it_is_a_gesture_of_a_signed_in_account(self):
        self.assertEqual(self._post().status_code, 302)
        self.client.force_login(self.me)
        self.assertEqual(self.client.get(self.url).status_code, 405)


class TaskTest(TestCase):

    def tearDown(self):
        cache.delete('common.index_media.lock')

    def test_the_task_runs_low_on_the_gpu_queue_at_night_out_of_the_test_window(self):
        from wama.common.services.calendar import BEAT_WINDOWS
        from wama.common.services.resource_governor import tier_for
        self.assertEqual(settings.CELERY_TASK_ROUTES['common.index_media']['queue'], 'gpu')
        self.assertEqual(tier_for('_media_index'), 'basse')
        self.assertEqual(settings.CELERY_BEAT_SCHEDULE['media-index-nightly']['task'],
                         'common.index_media')
        self.assertIn('media-index-nightly', BEAT_WINDOWS)

    def test_the_task_asks_the_route_for_its_model_then_indexes_the_named_elements(self):
        from wama.common.tasks import index_media_task
        with mock.patch('wama.common.utils.model_readiness.ensure_installed') as ensure, \
                mock.patch.object(media_index, 'index', return_value={'indexed': 1}) as run:
            index_media_task(addresses=[['describer', 3]])
        self.assertEqual(ensure.call_args.args[0], MEDIA.model_key)
        run.assert_called_once_with([('describer', 3)])

    def test_a_pass_already_running_is_not_doubled(self):
        from wama.common.tasks import MEDIA_INDEX_LOCK, index_media_task
        cache.add(MEDIA_INDEX_LOCK, 1, timeout=60)
        with mock.patch('wama.common.utils.model_readiness.ensure_installed'), \
                mock.patch.object(media_index, 'index') as run:
            self.assertEqual(index_media_task(), {'skipped': 'en cours'})
        run.assert_not_called()


@skipUnless(HAS_V8, 'py_mini_racer absent')
class BrowserTest(SimpleTestCase):

    def test_the_preview_brick_reads_the_element_of_a_card(self):
        from py_mini_racer import MiniRacer

        from .tests_cap_from_js import FAKE_DOM
        v8 = MiniRacer()
        v8.eval(FAKE_DOM)
        v8.eval((JS / 'media-preview.js').read_text(encoding='utf-8'))
        read = lambda url: v8.eval(f'JSON.stringify(window.WamaMediaPreview.elementOf({url!r}))')
        self.assertEqual(read('/common/preview/audio_enhancer/42/?side=output'),
                         '{"surface":"audio_enhancer","pk":42}')
        self.assertEqual(read('/common/preview/imager/7/'), '{"surface":"imager","pk":7}')
        self.assertEqual(read('/media/users/1/x.png'), 'null')

    def test_the_filter_bar_and_the_inspector_parse(self):
        from py_mini_racer import MiniRacer
        v8 = MiniRacer()
        for name in ('wama-filter-bar.js', 'wama-inspector.js'):
            with self.subTest(file=name):
                v8.eval('(function(){' + (JS / name).read_text(encoding='utf-8') + '\n})')

    def test_the_queue_bar_carries_the_content_search_route(self):
        template = (Path(settings.BASE_DIR) / 'wama' / 'common' / 'templates' / 'common'
                    / '_toolbar.html').read_text(encoding='utf-8')
        self.assertIn("{% url 'common:api_queue_content_search' as tb_content_url %}", template)
        source = (JS / 'wama-filter-bar.js').read_text(encoding='utf-8')
        self.assertIn('data-content-search-url', source)
        self.assertIn('WamaMediaPreview', source)

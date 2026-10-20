"""Le service de vectorisation commun (`WAMA_MEMORY.md §7sexies`, 2026-10-19).

Ce qui est gardé, sans aucun modèle ni GPU (le fournisseur est simulé) :
  1. les ESPACES — un par nature de média ; le texte est celui du RAG, à la taille de la colonne ;
  2. le MOTEUR — ce que le fournisseur reçoit (la forme d'image mesurée, le préfixe des seules
     requêtes, la troncature des seuls espaces qui la demandent) et la dégradation en `[]` ;
  3. le CLIENT — par le service quand il répond, par le même moteur dans le process sinon ;
  4. le SERVICE — ses routes, et le refus d'une entrée non préparée.
"""
import base64
import dataclasses
import io
from unittest import mock

import requests
from django.test import SimpleTestCase
from PIL import Image

from wama.common.vectors import engine, service_client, spaces


def _png(size=(1200, 600), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, 'PNG')
    return buf.getvalue()


def _answer(n, dims):
    return mock.Mock(status_code=200, json=lambda: {'embeddings': [[0.1] * dims for _ in range(n)]})


class SpacesTest(SimpleTestCase):

    def test_the_text_space_is_the_rag_at_the_size_of_its_column(self):
        from wama.common.memory import embed
        from wama.common.models import EMBEDDING_DIMS
        self.assertEqual(spaces.TEXT.dims, EMBEDDING_DIMS)
        self.assertEqual((embed.EMBEDDING_MODEL, embed.NUM_CTX),
                         (spaces.TEXT.model, spaces.TEXT.num_ctx))

    def test_the_nature_of_a_media_picks_its_space(self):
        self.assertIs(spaces.space_for('text'), spaces.TEXT)
        self.assertIs(spaces.space_for('image'), spaces.MEDIA)
        self.assertIsNone(spaces.space_for('video'), 'la vidéo ne se vectorise pas encore')
        self.assertIn('image', spaces.MEDIA.modalities)
        self.assertNotIn('image', spaces.TEXT.modalities)

    def test_each_space_names_the_catalogue_row_the_route_installs(self):
        for space in spaces.SPACES.values():
            with self.subTest(space=space.key):
                self.assertEqual(space.model_key, 'ollama:' + space.model)

    def test_a_space_carries_no_vram_figure_its_catalogue_row_does(self):
        # Un chiffre d'espace doublait celui de la ligne (3,8 / 2,3 Go contre 2,5 / 1,3) : le besoin
        # se lit au catalogue, où la mesure du chargement le rend (2026-10-20).
        names = {field.name for field in dataclasses.fields(spaces.VectorSpace)}
        self.assertFalse({n for n in names if 'vram' in n}, names)
        from wama.common.memory import embed
        self.assertFalse(hasattr(embed, 'VRAM_GB'))

    def test_an_unknown_space_is_refused(self):
        with self.assertRaises(ValueError):
            spaces.get('audio')


class EngineTest(SimpleTestCase):

    def test_an_image_leaves_as_the_only_form_the_provider_embeds(self):
        inputs = engine.prepare(spaces.MEDIA, [{'image': _png()}, 'une voiture'], query=True)
        image = Image.open(io.BytesIO(base64.b64decode(inputs[0]['image'])))
        self.assertEqual(set(inputs[0]), {'image'})
        self.assertEqual((image.format, max(image.size)), ('JPEG', engine.MAX_IMAGE_SIDE))
        self.assertEqual(inputs[1], spaces.MEDIA.query_prefix + 'une voiture')

    def test_only_a_query_carries_the_prefix(self):
        self.assertEqual(engine.prepare(spaces.TEXT, ['un fragment']), ['un fragment'])
        self.assertEqual(engine.prepare(spaces.TEXT, [{'text': 'anonymisation'}], query=True),
                         [spaces.TEXT.query_prefix + 'anonymisation'])

    def test_a_space_without_image_input_rejects_an_image(self):
        with self.assertRaises(ValueError):
            engine.prepare(spaces.TEXT, [{'image': _png()}])
        with self.assertRaises(ValueError):
            engine.prepare(spaces.TEXT, ['  '])

    def test_the_provider_receives_the_window_and_truncation_of_the_space(self):
        with mock.patch('requests.post', return_value=_answer(1, 1024)) as post:
            engine.embed('text', ['texte'])
        sent = post.call_args.kwargs['json']
        self.assertEqual((sent['model'], sent['dimensions'], sent['options']['num_ctx'],
                          sent['keep_alive']),
                         (spaces.TEXT.model, 1024, spaces.TEXT.num_ctx, engine.KEEP_ALIVE))
        with mock.patch('requests.post', return_value=_answer(1, 768)) as post:
            engine.embed('media', [{'image': _png()}])
        self.assertNotIn('dimensions', post.call_args.kwargs['json'],
                         "l'espace médias ne demande pas de troncature")

    def test_a_wrong_answer_degrades_to_nothing(self):
        cases = {'dimension': _answer(1, 512), 'count': _answer(2, 1024),
                 'http': mock.Mock(status_code=500, text='boom')}
        for name, answer in cases.items():
            with self.subTest(case=name), mock.patch('requests.post', return_value=answer):
                self.assertEqual(engine.embed('text', ['texte']), [])
        with mock.patch('requests.post', side_effect=requests.ConnectionError('éteint')):
            self.assertEqual(engine.embed('text', ['texte']), [])

    def test_the_next_provider_serves_when_the_first_fails(self):
        space = dataclasses.replace(spaces.TEXT, providers=('ollama', 'tts_service'))
        with mock.patch('requests.post', side_effect=[requests.ConnectionError('éteint'),
                                                      _answer(1, 1024)]) as post:
            self.assertEqual(len(engine.embed_inputs(space, ['texte'])), 1)
        self.assertEqual(post.call_count, 2)

    def test_the_provider_is_reached_at_its_effective_address(self):
        # Depuis WSL2, `127.0.0.1:11434` n'est pas Ollama : l'adresse vient du résolveur commun
        # (`external_sources.effective_url`), pas d'une lecture propre au moteur.
        with mock.patch('wama.common.utils.ollama_host.ollama_base',
                        return_value='http://passerelle:11434'), \
                mock.patch('requests.post', return_value=_answer(1, 1024)) as post:
            engine.embed('text', ['texte'])
        self.assertEqual(post.call_args.args[0], 'http://passerelle:11434/api/embed')

    def test_prepared_inputs_are_checked(self):
        engine.check_inputs(spaces.MEDIA, ['texte', {'image': 'aGVsbG8='}])
        for bad in ({'image': '/etc/passwd', 'path': 'x'}, {'text': 'x'}, 3, ''):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                engine.check_inputs(spaces.MEDIA, [bad])
        with self.assertRaises(ValueError):
            engine.check_inputs(spaces.TEXT, [{'image': 'aGVsbG8='}])

    def test_another_tag_of_the_family_is_not_the_model_of_the_space(self):
        tags = mock.Mock(json=lambda: {'models': [{'name': 'embeddinggemma-2:270m'}]})
        with mock.patch('requests.get', return_value=tags):
            self.assertFalse(engine.available('media'))
        tags = mock.Mock(json=lambda: {'models': [{'name': 'embeddinggemma-2:latest'}]})
        with mock.patch('requests.get', return_value=tags):
            self.assertTrue(engine.available('media'))


class ClientTest(SimpleTestCase):

    def test_the_service_receives_prepared_inputs(self):
        answer = mock.Mock(status_code=200, json=lambda: {'vectors': [[0.2] * 768]})
        with mock.patch('requests.post', return_value=answer) as post:
            vectors = service_client.embed('media', [{'image': _png()}])
        self.assertEqual(len(vectors), 1)
        self.assertTrue(post.call_args.args[0].endswith('/embed'))
        sent = post.call_args.kwargs['json']
        self.assertEqual(sent['space'], 'media')
        engine.check_inputs(spaces.MEDIA, sent['inputs'])

    def test_a_stopped_service_runs_the_same_engine_in_process(self):
        with mock.patch('requests.post', side_effect=requests.ConnectionError('éteint')), \
                mock.patch.object(engine, 'embed_inputs', return_value=[[0.0] * 1024]) as local:
            self.assertEqual(service_client.embed('text', ['texte']), [[0.0] * 1024])
        self.assertEqual(local.call_args.args[1], ['texte'])

    def test_a_service_that_times_out_degrades_without_a_second_wait(self):
        with mock.patch('requests.post', side_effect=requests.Timeout('lent')), \
                mock.patch.object(engine, 'embed_inputs') as local:
            self.assertEqual(service_client.embed('text', ['texte']), [])
        local.assert_not_called()

    def test_residency_is_asked_to_the_governor_per_space(self):
        self.assertEqual(service_client.owner(spaces.MEDIA),
                         'vectors-media#ollama:embeddinggemma-2:latest')
        need = mock.patch.object(service_client, 'need_gb', return_value=2.14)
        with need, mock.patch('wama.common.services.resource_governor.effective_free_gb',
                              return_value=2.14 * 2):
            self.assertFalse(service_client.residency_allowed('media')[0], 'marge de 3×')
        with need, mock.patch('wama.common.services.resource_governor.effective_free_gb',
                              return_value=2.14 * 4) as free:
            self.assertTrue(service_client.residency_allowed('media')[0])
        free.assert_called_once_with(exclude='vectors-media#ollama:embeddinggemma-2:latest')

    def test_the_need_of_a_space_is_read_at_its_catalogue_row(self):
        with mock.patch('wama.common.utils.auto_model.vram_needed_gb', return_value=2.14) as need:
            self.assertEqual(service_client.need_gb(spaces.MEDIA), 2.14)
        need.assert_called_once_with('ollama:embeddinggemma-2:latest')
        with mock.patch.object(service_client, 'need_gb', return_value=2.14), \
                mock.patch('wama.common.services.resource_governor.reserve_vram',
                           return_value=True) as reserve, \
                mock.patch('wama.common.services.resource_governor.mark_used'):
            self.assertTrue(service_client.reserve('media', expires_in_s=300))
        reserve.assert_called_once_with('vectors-media#ollama:embeddinggemma-2:latest', 2.14,
                                        expires_in_s=300)

    def test_an_unknown_need_neither_keeps_nor_reserves(self):
        # L'incertitude ne se résout jamais en occupant : pas de résidence, rien d'annoncé.
        with mock.patch.object(service_client, 'need_gb', return_value=None), \
                mock.patch('wama.common.services.resource_governor.reserve_vram') as reserve:
            allowed, why = service_client.residency_allowed('media')
            self.assertFalse(service_client.reserve('media'))
        self.assertFalse(allowed)
        self.assertIn('inconnue', why)
        reserve.assert_not_called()

    def test_a_call_that_keeps_the_model_goes_through_the_load_measure(self):
        answer = mock.Mock(status_code=200, json=lambda: {'vectors': [[0.2] * 768]})
        measure = 'wama.model_manager.services.model_registry.ModelRegistry.measure_ollama_load'
        with mock.patch('requests.post', return_value=answer), \
                mock.patch(measure, side_effect=lambda name, load: load()) as measured:
            self.assertEqual(len(service_client.embed('media', ['x'], keep_alive='10m')), 1)
            measured.assert_called_once()
            self.assertEqual(measured.call_args.args[0], spaces.MEDIA.model)
            measured.reset_mock()
            # Déchargé sitôt la réponse rendue : rien à observer, pas même `/api/ps`.
            service_client.embed('media', ['x'])
            service_client.embed('media', ['x'], keep_alive='0')
            measured.assert_not_called()


class ServiceTest(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from fastapi.testclient import TestClient

        import vector_service
        cls.api = TestClient(vector_service.app)

    def test_health_and_declared_spaces(self):
        self.assertEqual(self.api.get('/health').json()['status'], 'ok')
        keys = {s['key']: s['dims'] for s in self.api.get('/spaces').json()}
        self.assertEqual(keys, {'text': 1024, 'media': 768})

    def test_embed_runs_the_engine_on_prepared_inputs(self):
        with mock.patch.object(engine, 'embed_inputs', return_value=[[0.3] * 768]) as run:
            body = self.api.post('/embed', json={'space': 'media',
                                                    'inputs': [{'image': 'aGVsbG8='}]}).json()
        self.assertEqual((body['model'], body['dims'], len(body['vectors'])),
                         (spaces.MEDIA.model, 768, 1))
        self.assertIs(run.call_args.args[0], spaces.MEDIA)

    def test_an_unprepared_input_or_unknown_space_is_refused(self):
        with mock.patch.object(engine, 'embed_inputs') as run:
            self.assertEqual(self.api.post('/embed', json={
                'space': 'media', 'inputs': [{'image_path': '/etc/passwd'}]}).status_code, 422)
            self.assertEqual(self.api.post('/embed', json={
                'space': 'audio', 'inputs': ['x']}).status_code, 422)
        run.assert_not_called()

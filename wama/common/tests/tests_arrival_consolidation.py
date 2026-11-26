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
privées ; et l'outil d'ajout de l'assistant (2026-11-17), qui créait un élément par appel, jamais
de lot, et les arguments qui l'annoncent au modèle.
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


class _ArrivalMedia:
    """Un dossier de médias jetable et un compte : ce que les gestes réels d'arrivée partagent."""

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

    def _one_batch(self, model, ids):
        from wama.common.utils.batch_common import batch_elements, batch_model_for
        batches = batch_model_for(model).objects.filter(user=self.user)
        self.assertEqual(1, batches.count(), 'les fichiers envoyés ensemble ont formé plusieurs lots')
        self.assertEqual(ids, [e.pk for e in batch_elements(batches.get(), model)])


class ArrivalThroughTheFileManagerTest(_ArrivalMedia, TestCase):
    """Le geste RÉEL — « Envoyer vers » de deux fichiers — sur les deux apps que la liste écrite à
    la main oubliait : un lot à l'arrivée, dans l'ordre d'envoi."""

    def _send(self, app, files):
        paths = [self._temp(name, content) for name, content in files]
        response = self.client.post(reverse('filemanager:api_import'),
                                    json.dumps({'paths': paths, 'app': app}),
                                    content_type='application/json')
        self.assertEqual(200, response.status_code, response.content[:300])
        body = response.json()
        self.assertEqual(len(files), body['count'], body)
        return [r['id'] for r in body['results']]

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


class ArrivalThroughTheAssistantTest(_ArrivalMedia, TestCase):
    """L'outil d'ajout (assistant, API, MCP — `execute_tool`) : plusieurs fichiers de travail en UN
    appel → un élément par fichier par l'appel ordinaire, rangés en UN lot par la déclaration de
    l'app, dans l'ordre donné (2026-11-17 — il créait un élément par appel, jamais de lot)."""

    def _add(self, work_file):
        from wama import tool_api as T
        return T.execute_tool('add_to_synthesizer', {'work_file': work_file}, self.user,
                              model_call=True)

    def test_two_texts_given_in_one_call_arrive_as_one_batch_in_the_given_order(self):
        from wama import tool_api as T
        from wama.synthesizer.models import VoiceSynthesis
        out = self._add([self._temp('first.txt', b'Hello.'), self._temp('second.txt', b'World.')])
        self.assertEqual(2, out.get('count'), out)
        self.assertEqual(1, len(out['batch_ids']), out)
        self._one_batch(VoiceSynthesis, out['item_ids'])
        self.assertEqual(out['item_ids'],
                         [pk for _, pk in T.items_of_step('add_to_synthesizer', {}, out)])

    def test_a_list_written_as_json_text_is_read_as_the_list(self):
        out = self._add(json.dumps([self._temp('a.txt', b'A.'), self._temp('b.txt', b'B.')]))
        self.assertEqual(2, out.get('count'), out)

    def test_a_refused_file_is_named_and_the_others_are_created(self):
        out = self._add([self._temp('kept.txt', b'Kept.'), f'users/{self.user.id}/temp/missing.txt'])
        self.assertEqual(1, out.get('count'), out)
        self.assertEqual(['missing.txt'], [e['file'].rsplit('/', 1)[-1] for e in out['errors']])
        self.assertNotIn('batch_ids', out)

    def test_a_single_file_in_a_list_is_the_ordinary_call(self):
        out = self._add([self._temp('only.txt', b'Only.')])
        self.assertIn('item_id', out)
        self.assertNotIn('item_ids', out)

    def test_files_of_two_domains_arrive_as_one_batch_per_surface(self):
        """The enhancer's one creator (2026-11-25) : two images and two sounds in ONE call are born
        on two element models — one batch on each, each element followed under its surface, each
        batch launched under it."""
        from wama import tool_api as T
        from wama.common.utils.detail_registry import DetailRegistry
        wav = b'RIFF\x24\x00\x00\x00WAVEfmt ' + b'\0' * 32
        files = [self._temp('a.png', b'x'), self._temp('a.wav', wav),
                 self._temp('b.png', b'x'), self._temp('b.wav', wav)]
        # One file port of the tool (derived from the card, 2026-11-26) : each file goes to the port
        # of the domain that takes its nature.
        out = T.relay_next_step('add_to_enhancer', T.execute_tool(
            'add_to_enhancer', {T.primary_arg_name('add_to_enhancer'): files}, self.user,
            model_call=True))
        self.assertEqual(4, out.get('count'), out)
        surfaces = [surface for surface, _ in T.items_of_step('add_to_enhancer', {}, out)]
        self.assertEqual(['enhancer', 'audio_enhancer', 'enhancer', 'audio_enhancer'], surfaces)
        self.assertEqual({'enhancer', 'audio_enhancer'}, {b['app'] for b in out['batches']})
        for surface, pk in T.items_of_step('add_to_enhancer', {}, out):
            self.assertTrue(DetailRegistry.get(surface)['model'].objects.filter(pk=pk).exists())
        self.assertIn("launch_batch(app='audio_enhancer'", out['next_step_hint'])
        self.assertIn('`start_audio_enhancer`', out['next_step_hint'])


class ArrivalArgumentsAreDeclaredTest(TestCase):
    """Les arguments qui prennent plusieurs fichiers sont ceux où arrive un fichier de TRAVAIL de la
    card (`tool_api.arrival_arguments`, le contrat port → argument du Studio) — annoncés comme une
    liste au modèle, dans le schéma JSON comme dans la liste texte, et eux seuls."""

    def test_every_creator_announces_its_work_arguments_as_a_list_and_only_them(self):
        from wama import tool_api as T
        texts = T.tool_descriptions()
        covered = []
        for name in sorted(T.TOOL_REGISTRY):
            if T.tool_role(name) != 'add':
                continue
            arrivals = T.arrival_arguments(name)
            schema = T.tool_input_schema(name)['properties']
            with self.subTest(tool=name):
                self.assertLessEqual(arrivals, T.tool_arg_names(name))
                for arg, prop in schema.items():
                    self.assertEqual(arg in arrivals, 'anyOf' in prop, arg)
                    self.assertEqual(arg in arrivals, T.ARRIVAL_NOTE in texts[name]['args'][arg], arg)
            if arrivals:
                covered.append(name)
        self.assertGreaterEqual(len(covered), 9, covered)

    def test_a_port_that_takes_one_file_turns_down_a_list_in_every_app_before_anything_is_created(self):
        """Une référence, un résultat existant : UN fichier, la règle de l'`input` de la card — pour
        toute app, réelle ou née d'un manifeste (2026-11-18, Fabien : « il n'y a pas de raison que
        leur fonctionnement diffère »). La porte est `execute_tool`, avant l'outil : rien en base."""
        from django.contrib.auth import get_user_model
        from django.utils.module_loading import import_string

        from wama import tool_api as T
        from wama.studio.services.generic_runner import single_file_arguments
        user = get_user_model().objects.create_superuser('one_file', password='x')
        checked = []
        for name in sorted(T.TOOL_REGISTRY):
            if T.tool_role(name) != 'add':
                continue
            app = name[len('add_to_'):]
            for arg in sorted(single_file_arguments(app)):
                model = import_string(T.TRIAD_SPECS[app]['model'])
                before = model.objects.count()
                with self.subTest(tool=name, arg=arg):
                    out = T.execute_tool(name, {'prompt': 'x', arg: ['a.wav', 'b.wav']}, user,
                                         model_call=True)
                    self.assertIn(f"'{arg}' prend un seul fichier", out.get('error', ''), out)
                    self.assertEqual(before, model.objects.count(), 'nothing created')
                checked.append(name)
        self.assertGreaterEqual(len(set(checked)), 2, checked)

    def test_a_work_port_whose_token_takes_one_file_is_not_an_arrival(self):
        """La déclaration est celle que lit la card (`multi` du jeton, `input multiple`) : un port de
        travail qui ne la porte pas (un résultat existant) prend UN fichier, ici comme sur la card."""
        from unittest import mock

        from wama.studio.services import generic_runner
        port = {'id': 'work_file', 'group': 'travail', 'types': ['document'], 'label': 'Fichier'}
        # The ports the TOOL drew its signature from (`_tool_ports`, 2026-11-26) : they judge its
        # arguments.
        for multi, expected in ((True, {'work_file'}), (False, set())):
            with self.subTest(multi=multi), mock.patch.object(
                    generic_runner, '_tool_ports', return_value=[dict(port, multi=multi)]):
                self.assertEqual(expected, generic_runner.work_arguments('synthesizer'))

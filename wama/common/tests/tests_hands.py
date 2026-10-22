"""Les MAINS qui pilotent les scènes 3D (`common/hand_gestures.py`, `common/js/wama-hands.js`).

Ce que ces tests tiennent : le modèle des gestes est une ligne du catalogue, installée par la route
depuis son origine officielle (jamais un téléchargement « au premier usage ») ; la page le sert au
navigateur connecté et DIT quand il manque ; la page de toute scène porte la puce et la vignette ;
et l'interprétation des gestes — rejouée dans V8 sur des mains synthétiques — fait ce que Fabien a
demandé : un poing qui se déplace fait tourner (en miroir), deux poings qui s'écartent zooment, une
main ouverte ne fait rien, et une image mal lue ne fait ni saisir ni lâcher.
"""
import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from wama.common.hand_gestures import GESTURE_FILES, GESTURE_KEY, gesture_folder

User = get_user_model()


class GestureModelDeclarationTest(SimpleTestCase):

    def test_the_model_is_a_catalogue_line_installed_from_its_official_origin(self):
        from wama.common.external_sources import by_key
        from wama.model_manager.services.model_registry import ModelRegistry
        origin = GESTURE_FILES[0]['origin']
        self.assertIn(origin['source'], by_key(), "l'origine est une source DÉCLARÉE")
        self.assertEqual(Path(settings.MODEL_PATHS['vision']['mediapipe']), gesture_folder())
        registry = ModelRegistry.__new__(ModelRegistry)
        registry._models, registry.discovery_errors = {}, []
        registry._discover_hand_gesture_models()
        self.assertEqual([], registry.discovery_errors)
        row = registry._models[GESTURE_KEY]
        self.assertEqual('hand-gesture', row.capabilities['task'])
        self.assertEqual(GESTURE_FILES, row.extra_info['declared_files'])
        self.assertEqual(str(gesture_folder()), row.extra_info['install_dir'])

    def test_its_task_is_declared_and_has_a_category(self):
        from wama.model_manager.models import TASK_TO_MODEL_TYPE, TASK_TO_PLATFORM_TAGS, ModelTask, ModelType
        self.assertEqual(ModelType.VISION, TASK_TO_MODEL_TYPE[ModelTask.HAND_GESTURE])
        self.assertIn(ModelTask.HAND_GESTURE, TASK_TO_PLATFORM_TAGS)


class GestureModelRouteTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('hands_user', password='x')

    def _paths(self, folder):
        paths = {k: dict(v) for k, v in settings.MODEL_PATHS.items()}
        paths['vision']['mediapipe'] = Path(folder)
        return paths

    def test_an_anonymous_visitor_does_not_get_the_model(self):
        response = self.client.get(reverse('common:hand_model'))
        self.assertEqual(302, response.status_code)

    def test_an_absent_model_is_said_with_the_page_where_to_install_it(self):
        self.client.force_login(self.user)
        with tempfile.TemporaryDirectory() as folder, override_settings(MODEL_PATHS=self._paths(folder)):
            response = self.client.get(reverse('common:hand_model'))
        self.assertEqual(404, response.status_code)
        self.assertEqual({'installed': False, 'manage_url': reverse('model_manager:index')}, response.json())

    def test_an_installed_model_is_served_to_the_browser(self):
        self.client.force_login(self.user)
        with tempfile.TemporaryDirectory() as folder, override_settings(MODEL_PATHS=self._paths(folder)):
            (Path(folder) / GESTURE_FILES[0]['path']).write_bytes(b'task-bytes')
            response = self.client.get(reverse('common:hand_model'))
            # Lu jusqu'au bout, le fichier se ferme ; pas de `response.close()`, qui émet la fin de
            # requête et ferme la connexion à la base sous les tests suivants.
            body = b''.join(response.streaming_content)
        self.assertEqual(200, response.status_code)
        self.assertEqual(b'task-bytes', body)

    def test_the_hands_are_one_global_icon_not_a_button_per_scene(self):
        # Décision de Fabien (2026-10-22) : UNE interface globale, dans la barre du haut — cachée
        # tant qu'aucune page ne se déclare cible ; une scène n'a plus de bouton à elle.
        from wama.accounts.permissions import set_account_tier
        set_account_tier(self.user, 'admin')
        self.client.force_login(self.user)
        for url in (reverse('common:scene', args=['licenses']), reverse('accounts:user-constellation'),
                    reverse('home')):
            html = self.client.get(url).content.decode()
            self.assertIn('id="wamaHandsToggle"', html, url)
            self.assertIn(f'data-hands-model="{reverse("common:hand_model")}"', html, url)
            self.assertIn('"wama/hands-ui"', html, url)              # l'importmap commune
            self.assertIn('"mediapipe/tasks-vision"', html, url)
            self.assertNotIn('wc-hands-toggle', html, url)
            self.assertNotIn('data-hands-wasm', html, url)


# Un faux navigateur n'est pas utile : `HandGestures` ne touche pas au DOM.
def _gestures_engine():
    from py_mini_racer import MiniRacer
    source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js' / 'wama-hands.js').read_text(encoding='utf-8')
    ctx = MiniRacer()
    ctx.eval(source.replace('export class ', 'class ').replace('export async function ', 'async function ')
             .replace('export function ', 'function ').replace('export const ', 'const '))
    return ctx


def _hand(id_, gesture, x, y):
    return {'id': id_, 'gesture': gesture, 'score': 0.9, 'palm': {'x': x, 'y': y}}


def _pointing(id_, x, y, pinch_gap):
    """Une main ouverte dont le bout de l'index est en (x, y), le pouce à `pinch_gap` de lui ; la
    taille de la main (poignet → base du majeur) vaut 0,2."""
    return {'id': id_, 'gesture': 'Open_Palm', 'score': 0.9, 'palm': {'x': x, 'y': y + 0.1},
            'tips': {'index': {'x': x, 'y': y}, 'thumb': {'x': x + pinch_gap, 'y': y}}, 'size': 0.2}


class HandGesturesTest(SimpleTestCase):

    def setUp(self):
        try:
            self.ctx = _gestures_engine()
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        self.ctx.eval('var g = new HandGestures({ smoothing: 0 });')

    def _frame(self, *hands):
        return json.loads(self.ctx.eval(f'JSON.stringify(g.update({json.dumps(list(hands))}))'))

    def test_a_closed_fist_that_moves_turns_the_scene_in_mirror(self):
        for _ in range(3):
            self._frame(_hand('Right', 'Closed_Fist', 0.50, 0.50))
        out = self._frame(_hand('Right', 'Closed_Fist', 0.60, 0.45))
        self.assertEqual('rotate', out['mode'])
        self.assertAlmostEqual(-0.10, out['rotate']['dx'], places=6)      # miroir : la main va à droite
        self.assertAlmostEqual(-0.05, out['rotate']['dy'], places=6)

    def test_two_fists_moving_apart_zoom_in(self):
        for _ in range(3):
            self._frame(_hand('Left', 'Closed_Fist', 0.40, 0.5), _hand('Right', 'Closed_Fist', 0.60, 0.5))
        out = self._frame(_hand('Left', 'Closed_Fist', 0.30, 0.5), _hand('Right', 'Closed_Fist', 0.70, 0.5))
        self.assertEqual('zoom', out['mode'])
        self.assertAlmostEqual(0.5, out['zoom'], places=6)                  # deux fois plus écartées
        self.assertIsNone(out['rotate'])

    def test_an_open_hand_moves_nothing(self):
        for x in (0.3, 0.5, 0.7, 0.9):
            out = self._frame(_hand('Right', 'Open_Palm', x, 0.5))
        self.assertEqual('open', out['mode'])
        self.assertIsNone(out['rotate'])
        self.assertIsNone(out['zoom'])

    def test_one_misread_frame_neither_grabs_nor_releases(self):
        out = self._frame(_hand('Right', 'Closed_Fist', 0.5, 0.5))
        self.assertEqual('open', out['mode'], 'une seule image de poing ne saisit pas')
        for _ in range(3):
            self._frame(_hand('Right', 'Closed_Fist', 0.5, 0.5))
        self._frame(_hand('Right', 'None', 0.5, 0.5))                        # une image mal lue
        out = self._frame(_hand('Right', 'Closed_Fist', 0.6, 0.5))
        self.assertEqual('rotate', out['mode'], 'une image mal lue ne lâche pas la scène')
        self.assertIsNotNone(out['rotate'])

    def test_the_result_of_mediapipe_becomes_hands(self):
        landmarks = [{'x': 0.5, 'y': 0.5, 'z': 0}] * 21
        res = {'landmarks': [landmarks], 'gestures': [[{'categoryName': 'Closed_Fist', 'score': 0.8}]],
               'handedness': [[{'categoryName': 'Left', 'score': 0.9}]]}
        hands = json.loads(self.ctx.eval(f'JSON.stringify(handsFromResult({json.dumps(res)}))'))
        self.assertEqual(('Left', 'Closed_Fist'), (hands[0]['id'], hands[0]['gesture']))
        self.assertAlmostEqual(0.5, hands[0]['palm']['x'])

    def test_an_open_hand_points_and_a_pinch_clicks_once(self):
        out = self._frame(_pointing('Right', 0.5, 0.5, 0.15))
        self.assertEqual('point', out['mode'])
        self.assertAlmostEqual(0.5, out['pointer']['x'])                # le centre reste le centre
        self.assertFalse(out['click'])
        self.assertFalse(self._frame(_pointing('Right', 0.5, 0.5, 0.02))['click'], 'une image ne pince pas')
        out = self._frame(_pointing('Right', 0.5, 0.5, 0.02))
        self.assertTrue(out['click'])
        self.assertEqual('pinch', out['mode'])
        self.assertFalse(self._frame(_pointing('Right', 0.5, 0.5, 0.02))['click'], 'un pincement tenu ne reclique pas')

    def test_the_scene_is_mirrored_with_a_margin_so_its_edges_stay_reachable(self):
        edge = json.loads(self.ctx.eval('JSON.stringify(toScene({x: 0.88, y: 0.12}))'))
        self.assertEqual({'x': 0, 'y': 0}, edge)                           # miroir : la droite de l'image à gauche
        self.assertEqual({'x': 1, 'y': 1}, json.loads(self.ctx.eval('JSON.stringify(toScene({x: 0.05, y: 0.97}))')))

    def test_the_wide_field_asks_the_camera_for_16_9(self):
        wide = json.loads(self.ctx.eval('JSON.stringify(cameraConstraints(HAND_DEFAULTS))'))['video']
        self.assertAlmostEqual(16 / 9, wide['aspectRatio']['ideal'])
        self.assertEqual(1920, wide['width']['ideal'])
        chosen = json.loads(self.ctx.eval('JSON.stringify(cameraConstraints({wide: false, deviceId: "cam-2"}))'))['video']
        self.assertEqual({'exact': 'cam-2'}, chosen['deviceId'])
        self.assertAlmostEqual(4 / 3, chosen['aspectRatio']['ideal'])

    def test_sensitivity_amplifies_rotation_and_zoom_but_not_the_pointer(self):
        out = json.loads(self.ctx.eval('JSON.stringify(scaleGesture({mode: "rotate", rotate: {dx: 0.1, dy: -0.05}, '
                                       'zoom: null, pointer: {x: 0.3, y: 0.4}, click: false}, 2))'))
        self.assertAlmostEqual(0.2, out['rotate']['dx'])
        self.assertAlmostEqual(-0.1, out['rotate']['dy'])
        self.assertEqual({'x': 0.3, 'y': 0.4}, out['pointer'])
        zoom = json.loads(self.ctx.eval('JSON.stringify(scaleGesture({zoom: 0.5, rotate: null}, 2))'))['zoom']
        self.assertAlmostEqual(0.25, zoom)

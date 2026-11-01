"""Le DOMAINE d'un fichier arrivé hors de sa card — sa nature le désigne (2026-11-01).

Étape ③ de l'alignement des domaines (`ROUTE §11 #42`, plan accepté par Fabien : « le domaine doit
être proposé automatiquement en fonction de la nature du fichier de sortie à envoyer vers… C'est du
câblage propre à faire pour ne rien casser »). Mesuré avant : `app_modes.domain_for_category`
n'avait aucun appelant ; l'enhancer choisissait le domaine par trois listes d'extensions écrites à
la main (importeur du gestionnaire de fichiers, dépôt, lot), plus courtes que celles qu'il déclare
(`.m4v`, `.wmv`, `.avif`, `.heif`, `.aiff` offerts par « Envoyer vers », puis refusés), et rangeait
le GIF en vidéo à trois portes, en image aux trois autres ; l'importeur de l'imager refusait
`.tif`, `.heic`, `.avif`, que son menu offrait.

Ce que ce fichier tient :
  • une extension que l'app déclare et qu'un de ses domaines accepte n'est jamais refusée ;
  • le domaine qui reçoit est le premier déclaré qui prend la nature du fichier ;
  • un domaine lit une extension autrement que la taxonomie seulement par sa déclaration ;
  • l'élément né d'un « Envoyer vers » est dans le domaine que la réponse annonce ;
  • « Envoyer vers » retient ce domaine pour la page de l'app (V8) ;
  • aucune porte de l'enhancer ni de l'imager ne réécrit une liste d'extensions à côté.
"""
import importlib.util
import inspect
import io
import json
import re
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.app_registry import APP_CATALOG, category_of_path
from wama.common.tests.tests_cap_from_js import FAKE_DOM
from wama.common.utils.app_modes import (APP_MODES, accepts, arrival_domain, element_domain,
                                         file_nature, get_domains, surface_file_nature)
from wama.filemanager.tests_send_to_settings import SendToTestBase

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
JS = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'


def _offered(app):
    """Les extensions que l'app DÉCLARE (`input_extensions`) — ce que « Envoyer vers » offre."""
    return sorted({e if e.startswith('.') else '.' + e
                   for e in (APP_CATALOG.get(app) or {}).get('input_extensions') or ()})


class ArrivalDomainIsTheFileNatureTest(SimpleTestCase):

    def test_an_offered_extension_that_a_domain_accepts_is_never_refused(self):
        measured = 0
        for app in sorted(APP_MODES):
            taken = {n for d in get_domains(app) for n in accepts(app, d['id'])}
            for ext in _offered(app):
                if category_of_path('x' + ext) not in taken:
                    continue
                measured += 1
                with self.subTest(app=app, ext=ext):
                    domain = arrival_domain(app, 'x' + ext)
                    self.assertIsNotNone(domain, 'offered, a domain accepts it, refused')
                    self.assertIn(category_of_path('x' + ext), accepts(app, domain))
        self.assertGreater(measured, 50, 'the fleet is measured')

    def test_the_first_declared_domain_taking_the_nature_receives_the_file(self):
        self.assertEqual('image_video', arrival_domain('enhancer', 'clip.m4v'))
        self.assertEqual('audio', arrival_domain('enhancer', 'voice.aiff'))
        self.assertEqual('image', arrival_domain('imager', 'scan.tif'),
                         'both imager domains take an image: the first declared one')
        self.assertIsNone(arrival_domain('enhancer', 'subtitles.srt'))
        self.assertIsNone(arrival_domain('enhancer', 'notes.xyz'))

    def test_a_domain_reads_an_extension_otherwise_only_by_its_declaration(self):
        self.assertEqual('video', file_nature('enhancer', 'image_video', 'loop.gif'),
                         "the enhancer's GIF goes through its video route (`extension_natures`)")
        self.assertEqual('image', file_nature('imager', 'image', 'loop.gif'))
        for app, decl in sorted(APP_MODES.items()):
            for d in decl.get('domains', []):
                for ext, nature in (d.get('extension_natures') or {}).items():
                    with self.subTest(app=app, domain=d['id'], ext=ext):
                        self.assertIn(nature, accepts(app, d['id']), 'a nature the domain refuses')
                        self.assertIn(category_of_path('x.' + ext), accepts(app, d['id']))

    def test_a_surface_takes_only_what_its_domains_accept(self):
        self.assertIsNone(surface_file_nature('enhancer', 'enhancer', 'voice.wav'))
        self.assertEqual('audio', surface_file_nature('enhancer', 'audio_enhancer', 'voice.wav'))
        self.assertIsNone(surface_file_nature('enhancer', 'audio_enhancer', 'photo.png'))
        self.assertEqual('image', surface_file_nature('enhancer', 'enhancer', 'photo.heif'))


class NoDoorWritesItsExtensionListTest(SimpleTestCase):
    """Les portes d'arrivée de l'enhancer et de l'imager lisent la déclaration (`app_modes`)."""

    MEDIA_LITERAL = re.compile(r"""['"]\.(?:jpe?g|png|webp|bmp|tiff?|heic|gif|mp4|webm|mkv|"""
                               r"""avi|mov|flv|3gp|mp3|wav|flac|ogg|m4a|aac|opus|wma)['"]""")

    def _doors(self):
        from wama import tool_api
        from wama.enhancer import tasks as enhancer_tasks
        from wama.enhancer import views as enhancer_views
        from wama.filemanager import views as filemanager_views
        return [enhancer_views.upload, enhancer_views.batch_preview, enhancer_views.batch_create,
                enhancer_views.audio_upload, enhancer_tasks._derive_media_type,
                filemanager_views.import_to_enhancer, filemanager_views.import_to_imager,
                tool_api.add_to_enhancer, tool_api.add_to_audio_enhancer]

    def test_no_arrival_door_lists_media_extensions(self):
        found = []
        for door in self._doors():
            code = inspect.getsource(inspect.unwrap(door))
            found += [f'{door.__module__}.{door.__name__} : {m}'
                      for m in self.MEDIA_LITERAL.findall(code)]
        self.assertEqual([], found, '\n'.join(found))


def _gif() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    frames = [Image.new('RGB', (8, 8), c) for c in ((200, 0, 0), (0, 200, 0))]
    frames[0].save(buffer, format='GIF', save_all=True, append_images=frames[1:], duration=100)
    return buffer.getvalue()


def _png() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), (30, 30, 200)).save(buffer, format='PNG')
    return buffer.getvalue()


class SentFileLandsInItsDomainTest(SendToTestBase):
    """« Envoyer vers » par la route du gestionnaire : l'élément créé est dans le domaine que la
    réponse annonce, et c'est celui de la nature du fichier."""

    def _element(self, body):
        from django.apps import apps as django_apps
        return django_apps.get_model(body['model']).objects.get(pk=body['id'])

    def test_each_nature_sent_to_a_multi_domain_app_lands_in_its_domain(self):
        cases = [('enhancer', 'photo.png', _png(), 'image_video'),
                 ('enhancer', 'voice.wav', b'RIFF0000WAVE', 'audio'),
                 ('enhancer', 'voice.aiff', b'FORM0000AIFF', 'audio'),
                 ('imager', 'reference.png', _png(), 'image')]
        for app, name, content, expected in cases:
            with self.subTest(app=app, name=name):
                body = self.send_to(app, self.author, name, content)
                self.assertEqual(expected, body.get('domain'))
                self.assertEqual(expected, element_domain(self._element(body)))

    def test_a_gif_sent_to_the_enhancer_is_a_video_element(self):
        body = self.send_to('enhancer', self.author, 'loop.gif', _gif())
        self.assertEqual('image_video', body.get('domain'))
        self.assertEqual('video', self._element(body).media_type)

    def test_a_single_domain_app_answers_no_domain(self):
        body = self.send_to('converter', self.author, 'photo.png', _png())
        self.assertNotIn('domain', body)


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class SendToRemembersTheDomainTest(SimpleTestCase):
    """`WamaSendTo.envoyer` retient le domaine qui a reçu (`WamaApp.rememberDomain`) : la page
    de l'app s'ouvrira sur lui (`WamaModes.domainTabs`, même clé)."""

    PAGE = """
    var stored = {}, events = [];
    window.localStorage = {getItem: function (k) { return stored[k] || null; },
                           setItem: function (k, v) { stored[k] = v; }};
    function CustomEvent(t, o) { this.type = t; this.detail = (o || {}).detail; }
    document.dispatchEvent = function (e) { events.push(e.detail); };
    document.cookie = '';
    var ANSWER = null;
    function fetch() { return Promise.resolve({ok: true, status: 200,
        json: function () { return Promise.resolve(ANSWER); }}); }
    """

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM + self.PAGE)
        self.v8.eval((JS / 'wama-app-base.js').read_text(encoding='utf-8'))
        # `window` est l'objet global d'une page : les briques y lisent `WamaApp` sans préfixe.
        self.v8.eval('var WamaApp = window.WamaApp; WamaApp.toast = function () {};')
        self.v8.eval((JS / 'wama-send-to.js').read_text(encoding='utf-8'))

    def _send(self, answer):
        self.v8.eval(f'ANSWER = {json.dumps(answer)};'
                     " window.WamaSendTo.envoyer('/import/', ['a', 'b'], 'enhancer', 'Enhancer');")
        return json.loads(self.v8.eval('JSON.stringify(stored)'))

    def test_the_receiving_domain_is_remembered_for_the_app(self):
        stored = self._send({'imported': True, 'count': 1,
                             'results': [{'id': 1, 'path': 'a.wav', 'domain': 'audio'}]})
        self.assertEqual({'enhancerDomain': 'audio'}, stored)

    def test_files_landing_in_several_domains_leave_the_choice_alone(self):
        stored = self._send({'imported': True, 'count': 2,
                             'results': [{'id': 1, 'domain': 'audio'},
                                         {'id': 2, 'domain': 'image_video'}]})
        self.assertEqual({}, stored)

    def test_the_key_is_the_one_the_domain_tabs_read(self):
        self._send({'imported': True, 'id': 1, 'path': 'a.wav', 'domain': 'audio'})
        self.assertEqual('audio', json.loads(self.v8.eval(
            "JSON.stringify(window.WamaApp.rememberedDomain('enhancer'))")))

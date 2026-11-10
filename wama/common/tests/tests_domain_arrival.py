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

Puis (2026-11-01, Fabien : « Pour le Describer, on aligne… `.ico` est un icône, plutôt image… Et on
porte pour le reader ») :
  • le describer lit la nature d'un fichier à la taxonomie commune — il décrivait comme des
    documents un `.aiff`, un `.heif`, un `.qt` ou un `.ts` que sa zone de dépôt acceptait ;
  • une icône est une image, qu'aucune app n'accueille encore ;
  • « Envoyer vers » refuse, pour TOUTES les apps, ce qu'elles ne déclarent pas — le reader et le
    synthesizer en recopiaient la liste, le describer créait une card pour un `.xyz`.
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
from wama.common.utils.app_modes import (APP_MODES, accepts, arrival_domain, domain_nature,
                                         element_domain, file_nature, get_domains,
                                         surface_file_nature, surface_source_nature)
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

    def test_a_source_says_its_nature_before_its_file_arrives(self):
        """`surface_source_nature` (2026-11-10): an address that names its file goes through the
        gate, its query left aside; otherwise what the address says ahead (a media platform);
        '' when only the download will tell."""
        self.assertEqual('document', surface_source_nature(
            'anonymizer', 'anonymizer', 'https://ex.org/lettre.pdf?dl=1'))
        self.assertEqual('image', surface_source_nature('enhancer', 'enhancer',
                                                        'https://ex.org/photo.jpg?w=1'))
        self.assertIsNone(surface_source_nature('enhancer', 'enhancer', 'https://ex.org/a.wav'))
        self.assertEqual('video', surface_source_nature(
            'enhancer', 'enhancer', 'https://www.youtube.com/watch?v=abc'))
        self.assertEqual('', surface_source_nature('anonymizer', 'anonymizer',
                                                   'https://ex.org/download'))


class DescriberReadsTheCommonNatureTest(SimpleTestCase):
    """Le describer range un fichier par la taxonomie commune, lue par son domaine."""

    def test_every_extension_the_describer_takes_has_its_common_nature(self):
        from wama.describer.utils.content_analyzer import DOMAIN, file_nature as describer_nature
        taken = accepts('describer', DOMAIN)
        for ext in _offered('describer'):
            common = category_of_path('x' + ext)
            with self.subTest(ext=ext):
                self.assertEqual(common if common in taken else 'document',
                                 describer_nature('x' + ext))
        for name, nature in (('take.aiff', 'audio'), ('take.aif', 'audio'), ('photo.heif', 'image'),
                             ('clip.qt', 'video'), ('broadcast.ts', 'video')):
            with self.subTest(name=name):
                self.assertEqual(nature, describer_nature(name),
                                 'accepted at the door, described as a document before')

    def test_a_received_file_is_read_without_the_door(self):
        """Un fichier téléchargé d'une URL n'est pas passé par la zone de dépôt : sa nature se lit
        sans elle (`domain_nature`), et ce que le describer ne voit ni n'entend est un document."""
        from wama.describer.utils.content_analyzer import file_nature as describer_nature
        self.assertIsNone(file_nature('describer', 'description', 'icon.ico'), 'not offered')
        self.assertEqual('image', domain_nature('describer', 'description', 'icon.ico'))
        self.assertEqual('image', describer_nature('icon.ico'))
        for name in ('page.json', 'feed.xml', 'page', 'archive.zip'):
            with self.subTest(name=name):
                self.assertEqual('document', describer_nature(name))

    def test_the_queue_groups_and_the_batch_lines_by_the_same_reading(self):
        from types import SimpleNamespace

        from wama.describer.views import _describer_nature, _source_nature
        card = SimpleNamespace(detected_type='', input_file=None, source_url='https://x.org/take.aiff')
        self.assertEqual('audio', _describer_nature(card))
        self.assertEqual('video', _source_nature('/data/broadcast.ts', 'broadcast.ts'))

    def test_an_icon_is_an_image_that_no_app_takes_yet(self):
        self.assertEqual('image', category_of_path('favicon.ico'))
        self.assertEqual([], [app for app in sorted(APP_CATALOG) if '.ico' in _offered(app)],
                         'accepting an icon is a decision: no engine is proven on one')


class NoDoorWritesItsExtensionListTest(SimpleTestCase):
    """Les portes d'arrivée lisent la déclaration (`app_modes`, `accepts_file`) : enhancer, imager,
    describer, et les importeurs du reader et du synthesizer."""

    MEDIA_LITERAL = re.compile(r"""['"]\.?(?:jpe?g|png|webp|bmp|tiff?|heic|heif|avif|ico|gif|"""
                               r"""mp4|webm|mkv|avi|mov|qt|flv|3gp|m4v|wmv|mp3|wav|flac|ogg|"""
                               r"""m4a|aac|opus|wma|aiff?|docx|odt|rtf)['"]""")

    def _doors(self):
        from wama import tool_api
        from wama.describer import views as describer_views
        from wama.describer import workers as describer_workers
        from wama.describer.utils import content_analyzer
        from wama.enhancer import tasks as enhancer_tasks
        from wama.enhancer import views as enhancer_views
        from wama.filemanager import views as filemanager_views
        return [enhancer_views.upload, enhancer_views.batch_preview, enhancer_views.batch_create,
                enhancer_views.audio_upload, enhancer_tasks._derive_media_type,
                filemanager_views.import_to_enhancer, filemanager_views.import_to_imager,
                tool_api.add_to_enhancer, tool_api.add_to_audio_enhancer,
                describer_views.upload, describer_views._describer_nature,
                describer_views._source_nature, describer_workers._derive_detected_type,
                describer_workers._settle_nature, content_analyzer,
                filemanager_views.import_to_describer, filemanager_views.import_to_reader,
                filemanager_views.import_to_synthesizer, tool_api.add_to_describer]

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

    def test_what_an_app_does_not_list_is_refused_and_nothing_is_created(self):
        """La porte de tous les importeurs : `accepts_file`, ce que le menu propose."""
        from django.apps import apps as django_apps
        from django.urls import reverse
        self.client.force_login(self.author)
        for app, name, model in (('describer', 'notes.xyz', 'describer.Description'),
                                 ('reader', 'letter.docx', 'reader.ReadingItem'),
                                 ('transcriber', 'photo.png', 'transcriber.Transcript')):
            with self.subTest(app=app, name=name):
                before = django_apps.get_model(model).objects.count()
                body = self.client.post(
                    reverse('filemanager:api_import'),
                    json.dumps({'path': self._temp_file(self.author, name, b'x'), 'app': app}),
                    content_type='application/json').json()
                self.assertFalse(body.get('imported'), body)
                self.assertIn('Format non pris en charge', json.dumps(body, ensure_ascii=False))
                self.assertEqual(before, django_apps.get_model(model).objects.count())

    def test_a_sent_file_the_describer_takes_is_described_by_its_nature(self):
        body = self.send_to('describer', self.author, 'take.aiff', b'FORM0000AIFF')
        self.assertEqual('audio', self._element(body).detected_type)


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

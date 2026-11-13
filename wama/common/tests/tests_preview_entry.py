"""The ENTRY face of the item preview, and the modal that opens every face (2026-10-12).

Two defects reported by Fabien the same day : in the Describer, opening the preview of a card
said « No media URL available » ; in the Reader, a click on the input file opened nothing. The
measure over every app found the causes were common :
  • a TEXT face is served under `content` (`preview_utils`), the modal read `text_content` — every
    text face opened from a card (Describer, Reader, Transcriber outputs) was refused ;
  • the Entry face read a SECOND declaration of the input, the preview registry's `file_field`,
    which had drifted : composer and synthesizer declared their OUTPUT audio there ;
  • a broken entry adapter (anonymizer, input released) turned the whole preview into a 500,
    taking the existing output with it ;
  • three cards had their own entry gesture (reader, synthesizer) or the file manager's preview
    (converter, generated twins) instead of the common one.

Held here : the Entry face derives from the detail spec like the Output face ; ONE key carries
inline text, server and modal ; the cards open their entry by the common gesture.
"""
import importlib.util
import io
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.utils.media_paths import app_media_dir

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
JS = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'


def _named_fields(form):
    """The field NAMES a spec form designates (a name, or a « first non empty » list)."""
    if isinstance(form, str):
        return {form}
    if isinstance(form, (list, tuple)):
        return {f for f in form if isinstance(f, str)}
    return set()


def _path(url):
    """The path of a served URL — a MEDIA file carries its version (`?v=<mtime>`)."""
    return str(url or '').split('?')[0]


class EntryAndResultAreTwoDeclarationsTest(SimpleTestCase):
    """Generic over every app : what the spec calls the ENTRY is never what it calls the RESULT."""

    def test_no_app_names_its_output_field_as_its_input(self):
        from wama.common.utils.detail_registry import DetailRegistry
        from wama.common.utils.preview_registry import PreviewRegistry
        apps = PreviewRegistry.list_registered()
        self.assertGreater(len(apps), 8, 'the instrument sees the registered apps')
        crossed = {}
        for app in apps:
            spec = (DetailRegistry.get(app) or {}).get('spec') or {}
            entry = _named_fields(spec.get('source_file'))
            result = (_named_fields(spec.get('result_file')) | _named_fields(spec.get('result_files'))
                      | _named_fields(spec.get('result_text')))
            if entry & result:
                crossed[app] = sorted(entry & result)
        self.assertEqual({}, crossed)


class EntryFaceTest(TestCase):

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root, MEDIA_URL='/media/')
        media.enable()
        self.addCleanup(media.disable)
        self.user = get_user_model().objects.create_user('preview_entry_owner', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)

    def _file(self, app, sub, name, data=b'x'):
        rel = f"{app_media_dir(app, self.user.id, sub)}/{name}"
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as out:
            out.write(data)
        return rel

    def _preview(self, app, pk, side=None):
        url = f'/common/preview/{app}/{pk}/' + (f'?side={side}' if side else '')
        response = self.client.get(url)
        self.assertEqual(200, response.status_code, response.content[:300])
        return response.json()

    @staticmethod
    def _docx(text):
        import docx
        document = docx.Document()
        document.add_paragraph(text)
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    def test_the_composer_entry_is_its_prompt_never_its_audio(self):
        from wama.composer.models import ComposerGeneration
        gen = ComposerGeneration.objects.create(
            user=self.user, prompt='a calm piano by the sea', model='composer:musicgen-small',
            status='SUCCESS', audio_output=self._file('composer', 'output', 'sea.wav'))
        entry = self._preview('composer', gen.pk, 'input')
        self.assertEqual(('input', 'a calm piano by the sea'), (entry['side'], entry.get('content')))
        self.assertNotIn('url', entry, 'the output audio is not the entry')
        self.assertTrue(_path(self._preview('composer', gen.pk, 'output')['url']).endswith('sea.wav'))

    def test_the_synthesizer_entry_is_the_typed_text_or_the_text_of_its_file(self):
        from wama.synthesizer.models import VoiceSynthesis
        typed = VoiceSynthesis.objects.create(user=self.user, text_content='Bonjour à tous.')
        entry = self._preview('synthesizer', typed.pk, 'input')
        self.assertEqual(('input', 'Bonjour à tous.'), (entry['side'], entry.get('content')))
        filed = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self._file('synthesizer', 'input', 'lettre.docx', self._docx('Chère lectrice')))
        entry = self._preview('synthesizer', filed.pk, 'input')
        self.assertEqual('text/plain', entry['mime_type'])
        self.assertIn('Chère lectrice', entry['content'], 'the text of a .docx is extracted')
        self.assertTrue(_path(entry['url']).endswith('lettre.docx'), 'and the file stays downloadable')

    def test_a_reference_voice_is_never_the_entry_of_a_typed_text(self):
        """Measured by the porting instance on 307f0c3c : the synthesizer spec lifts
        `voice_reference` into `source_file` (for the side panel), and the Entry face showed the
        VOICE of a typed text. The route says the entry binds on the WORK port, never a reference."""
        from wama.synthesizer.models import VoiceSynthesis
        synthesis = VoiceSynthesis.objects.create(
            user=self.user, text_content='Bonjour à tous.',
            voice_reference=self._file('synthesizer', 'input', 'voix.wav'))
        entry = self._preview('synthesizer', synthesis.pk, 'input')
        self.assertEqual('Bonjour à tous.', entry.get('content'))
        self.assertNotIn('voix.wav', _path(entry.get('url')))

    def test_a_text_output_is_served_under_the_one_text_key(self):
        from wama.reader.models import ReadingItem
        item = ReadingItem.objects.create(
            user=self.user, input_file=self._file('reader', 'input', 'page.png'),
            status='SUCCESS', result_text='Texte lu sur la page.')
        output = self._preview('reader', item.pk, 'output')
        self.assertEqual(('output', 'Texte lu sur la page.'), (output['side'], output['content']))
        self.assertNotIn('text_content', output)
        entry = self._preview('reader', item.pk, 'input')
        self.assertEqual('image/png', entry['mime_type'])
        self.assertTrue(entry['sides']['has_input'] and entry['sides']['has_output'])

    def test_an_entry_that_breaks_does_not_take_the_output_down(self):
        from wama.anonymizer.models import Media
        media = Media.objects.create(
            user=self.user, file='', file_ext='.jpg', media_type='image', status='SUCCESS',
            output_file=self._file('anonymizer', 'output', 'street_blurred.jpg'))
        data = self._preview('anonymizer', media.pk)
        self.assertFalse(data['sides']['has_input'], 'the released input is said absent')
        self.assertEqual('output', data['side'], 'and the output that exists is served')
        self.assertTrue(_path(data['url']).endswith('street_blurred.jpg'))

    def test_behind_an_https_front_the_media_address_is_https(self):
        """Measured on the live 2026-10-13 : the front (Apache) ends TLS and the header was read
        only under `WAMA_HTTPS`, so a page served in https received `http://…/media/…` — and
        Chrome blocks a mixed-content FRAME : no HTML preview showed anywhere."""
        from wama.anonymizer.models import Media
        media = Media.objects.create(
            user=self.user, file='', file_ext='.jpg', media_type='image', status='SUCCESS',
            output_file=self._file('anonymizer', 'output', 'street_blurred.jpg'))
        url = f'/common/preview/anonymizer/{media.pk}/?side=output'
        self.assertTrue(self.client.get(url, HTTP_X_FORWARDED_PROTO='https').json()['url']
                        .startswith('https://'))
        self.assertTrue(self.client.get(url).json()['url'].startswith('http://'),
                        'a direct call, without the front, stays in http')

    def test_the_media_metadata_of_the_registry_joins_the_entry_of_the_same_file(self):
        from wama.anonymizer.models import Media
        media = Media.objects.create(
            user=self.user, file=self._file('anonymizer', 'input', 'street.mp4'), file_ext='.mp4',
            media_type='video', width=640, height=360, status='PENDING')
        entry = self._preview('anonymizer', media.pk, 'input')
        self.assertEqual('640x360', entry.get('resolution'))

    def test_the_file_manager_preview_is_the_same_file_face(self):
        rel = self._file('synthesizer', 'input', 'note.docx', self._docx('Une note.'))
        data = self.client.get('/filemanager/api/preview/', {'path': rel}).json()
        self.assertEqual('text/plain', data['mime_type'])
        self.assertIn('Une note.', data['content'])
        self.assertNotIn('text_content', data)

    def test_the_text_files_the_platform_does_not_know_stay_text(self):
        """`.log`, `.ini`, `.cfg`, `.md`, `.yaml` : unknown to the stdlib of one platform or
        typed `application/yaml` by the other (venv_linux — red under WSL only, 2026-10-12), they
        were forced to text by the file manager's own copy, gone with it (relecture of 307f0c3c).
        The rule lives in the common MIME table now, and PRIMES over the stdlib — for every
        consumer, on both platforms."""
        for name in ('journal.log', 'reglages.ini', 'outil.cfg', 'notes.md', 'conf.yaml'):
            rel = self._file('synthesizer', 'input', name, b'cle = valeur')
            data = self.client.get('/filemanager/api/preview/', {'path': rel}).json()
            self.assertTrue(data['mime_type'].startswith('text/'), f"{name} : {data['mime_type']}")


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class ModalReadsWhatTheServerServesTest(TestCase):
    """The modal's acceptance rule, run in V8 on payloads the SERVER produced."""

    def setUp(self):
        from py_mini_racer import MiniRacer

        from .tests_cap_from_js import FAKE_DOM
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval((JS / 'media-preview.js').read_text(encoding='utf-8'))

    def _showable(self, payload):
        import json
        return self.v8.eval(f'window.WamaMediaPreview.showable({json.dumps(payload)})')

    def test_every_face_the_server_serves_is_showable_and_an_error_is_not(self):
        from wama.common.utils.preview_utils import file_face
        text_output = {'name': 'Sortie', 'mime_type': 'text/plain', 'content': 'Une description.'}
        self.assertTrue(self._showable(text_output), 'the Describer case')
        self.assertTrue(self._showable({'name': 'Entrée', 'mime_type': 'text/plain', 'content': ''}),
                        'an empty text is still a text')
        self.assertTrue(self._showable(file_face('/media/users/1/x/input/a.png')))
        self.assertFalse(self._showable({'error': 'Aucun aperçu disponible pour cet élément'}))
        self.assertFalse(self._showable({'name': 'x', 'text_content': 'the old key'}),
                         'one key carries inline text — no second spelling')

    def test_no_reader_of_the_old_text_key_is_left(self):
        readers = {
            'media-preview.js': JS / 'media-preview.js',
            'wama-inspector.js': JS / 'wama-inspector.js',
            'filemanager.js': (Path(settings.BASE_DIR) / 'wama' / 'filemanager' / 'static'
                               / 'filemanager' / 'js' / 'filemanager.js'),
        }
        # The USE of the key (a property read, an object key) — a comment may name it, to say
        # why it is gone.
        use = re.compile(r'\.text_content\b|\btext_content\s*:')
        left = {name: len(use.findall(path.read_text(encoding='utf-8')))
                for name, path in readers.items()}
        self.assertEqual({name: 0 for name in readers}, left)


class CardsOpenTheirEntryByTheCommonGestureTest(SimpleTestCase):
    """Every queue card that opens its entry does it with the common gesture
    (`.preview-media-link` → the ITEM preview, its faces included) — never its own handler, never
    the file manager's preview (which knows no item, hence no Entry | Output faces)."""

    @staticmethod
    def _served(card: Path) -> bool:
        """The card is SERVED : another file of ITS app (a page's `card_template=`, the view that
        re-renders it) names it. A card copied into a twin and replaced by the generated one is
        named by nobody there — it is dead, and measuring it would measure nothing served
        (2026-10-12 : converter_01/_job_card.html, reader_01/_item_card.html)."""
        app_dir = card.parents[2]
        if app_dir.name == 'common':
            return True                 # une card COMMUNE est servie par les autres apps
        name = f'{card.parent.name}/{card.name}'
        return any(name in other.read_text(encoding='utf-8', errors='replace')
                   for pattern in ('**/*.html', '**/*.py') for other in app_dir.glob(pattern)
                   if other != card)

    @classmethod
    def _cards(cls):
        # Hors jumelles COPIÉES : figées par construction, elles ne suivent pas le code réel (même
        # règle que les autres contrats génériques, `sandbox.twins_with_copied_views`).
        from wama.common.sandbox import twins_with_copied_views
        copied = twins_with_copied_views()
        return sorted(card for card in Path(settings.BASE_DIR, 'wama').glob('*/templates/*/_*card*.html')
                      if card.parts[-4] not in copied and cls._served(card))

    @property
    def CARDS(self):
        return self._cards()

    def test_the_instrument_sees_the_cards(self):
        self.assertGreater(len(self.CARDS), 8)

    def test_no_card_keeps_a_local_entry_gesture(self):
        # The USE (a class, a target) — a comment may name the retired gesture.
        uses = (r'class="[^"]*\b(?:source-preview-btn|preview-text-btn)\b',
                r'data-preview-url="/filemanager/api/preview/')
        local = {}
        for card in self.CARDS:
            text = card.read_text(encoding='utf-8')
            for pattern in uses:
                if re.search(pattern, text):
                    local.setdefault(card.parent.name + '/' + card.name, []).append(pattern)
        self.assertEqual({}, local)

    def test_the_entry_link_targets_the_item_preview(self):
        link = re.compile(r'class="[^"]*\bpreview-media-link\b[^"]*"[^>]*?data-preview-url="([^"]*)"',
                          re.S)
        seen = 0
        for card in self.CARDS:
            for url in link.findall(card.read_text(encoding='utf-8')):
                seen += 1
                self.assertIn("common:unified_preview", url, f'{card.name} : {url}')
                # The ENTRY face, asked for : without it a finished item opens on its Output
                # (five cards, the Describer reported by Fabien on 2026-10-13).
                self.assertTrue(url.endswith('?side=input'), f'{card.name} : {url}')
        self.assertGreaterEqual(seen, 8, 'the instrument sees the entry links')

    def test_the_generator_emits_the_same_entry_link(self):
        from wama.common.manifests.codegen import templates_gen
        source = Path(templates_gen.__file__).read_text(encoding='utf-8')
        self.assertNotIn('/filemanager/api/preview/', source)
        self.assertIn("preview-media-link", source)
        self.assertIn("elem.id %}}?side=input", source)

    def test_no_card_cuts_its_entry_name_on_the_server(self):
        """2026-11-13 (Fabien : « survolant le titre d'une card, le nom complet ne s'affiche pas ») :
        the CSS cuts the name (ellipsis) and the common brick `WamaFullText` shows it whole on
        hover — a name cut on the SERVER (`truncatechars`) no longer exists anywhere in the page."""
        name = re.compile(r'class="[^"]*\bwcv3-in-name\b[^"]*"[^>]*>(.*?)</span>', re.S)
        cut = [card.parent.name + '/' + card.name for card in self.CARDS
               if any('truncatechars' in body for body in name.findall(card.read_text(encoding='utf-8')))]
        self.assertEqual([], cut)
        from wama.common.manifests.codegen import templates_gen
        source = Path(templates_gen.__file__).read_text(encoding='utf-8')
        label = re.search(r'entry_label = \((.*?)\)\n', source, re.S)
        self.assertIsNotNone(label, 'the instrument sees the generated entry label')
        self.assertNotIn('truncatechars', label.group(1))


class FullTextOnHoverTest(SimpleTestCase):
    """`WamaFullText` (base.html, 2026-11-13) : the ONE place that shows the whole text of a text
    the CSS cuts — cards, lots, the file tree, panels. No page writes its text into `title` itself
    (five variants found that day : the file tree, the viewer's title, eight cards that put a hint
    there instead of the name, two the prompt, two the name)."""

    BRICK = Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js' / 'wama-full-text.js'
    #: An element of the fake page : its computed style, its box, its parent.
    FAKE = r"""
        var handlers = {};
        var document = {addEventListener: function (t, f) { handlers[t] = f; }};
        function El(text, style, box, parent, title) {
            this.nodeType = 1; this.tagName = 'SPAN'; this.textContent = text;
            this._style = style; this._box = box; this.parentElement = parent || null;
            this.firstElementChild = null; this.dataset = {}; this._attrs = {};
            if (title) this._attrs.title = title;
            this.scrollWidth = box.sw || box.w; this.clientWidth = box.w;
            this.scrollHeight = box.h; this.clientHeight = box.h;
        }
        El.prototype.getAttribute = function (n) { return n in this._attrs ? this._attrs[n] : null; };
        El.prototype.setAttribute = function (n, v) { this._attrs[n] = String(v); };
        El.prototype.getBoundingClientRect = function () {
            var b = this._box; return {left: b.x, right: b.x + b.w, width: b.w, height: b.h};
        };
        var window = {getComputedStyle: function (el) {
            var s = el._style;
            return {textOverflow: s.textOverflow || 'clip', whiteSpace: s.whiteSpace || 'normal',
                    overflowX: s.overflowX || 'visible', webkitLineClamp: s.clamp || 'none',
                    getPropertyValue: function () { return s.clamp || 'none'; }};
        }};
    """

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        ctx = MiniRacer()
        ctx.eval(self.FAKE)
        ctx.eval(self.BRICK.read_text(encoding='utf-8'))
        return ctx

    def test_a_cut_name_shows_whole_with_the_hint_of_the_page_and_a_whole_name_is_left_alone(self):
        ctx = self._ctx()
        result = ctx.eval(r"""
            var ellipsis = {textOverflow: 'ellipsis', whiteSpace: 'nowrap'};
            var cut = new El('Keep Hope — version longue.mp3', ellipsis, {x: 0, w: 120, sw: 300, h: 20}, null, 'Aperçu');
            var whole = new El('court.mp3', ellipsis, {x: 0, w: 120, h: 20}, null, 'Aperçu');
            handlers.mouseover({target: cut}); handlers.mouseover({target: whole});
            handlers.mouseover({target: cut});      // twice : the hint is not stacked
            JSON.stringify([cut.getAttribute('title'), whole.getAttribute('title')]);
        """)
        self.assertEqual(['Keep Hope — version longue.mp3\nAperçu', 'Aperçu'], json.loads(result))

    def test_a_tree_node_wider_than_its_panel_shows_whole_and_one_that_fits_does_not(self):
        """The file tree (2026-11-13) : no ellipsis there, the panel CLIPS a one-line node — what
        `addFilenameTitles` covered by writing the title of EVERY node."""
        ctx = self._ctx()
        result = ctx.eval(r"""
            var panel = new El('', {overflowX: 'auto'}, {x: 10, w: 200, h: 400});
            var li = new El('', {}, {x: 10, w: 200, h: 20}, panel);
            var nowrap = {whiteSpace: 'nowrap'};
            var wide = new El('un_dossier_au_nom_tres_long', nowrap, {x: 30, w: 320, h: 20}, li);
            var fits = new El('court', nowrap, {x: 30, w: 60, h: 20}, li);
            // Without a box, at the origin of the page — what the browser gives the option of a
            // closed list (measured on 2026-11-13 : 48 « cut » elements, mostly options).
            var hidden = new El('option fermée', nowrap, {x: 0, w: 0, h: 0}, li);
            [wide, fits, hidden].forEach(function (e) { handlers.mouseover({target: e}); });
            JSON.stringify([wide.getAttribute('title'), fits.getAttribute('title'), hidden.getAttribute('title')]);
        """)
        self.assertEqual(['un_dossier_au_nom_tres_long', None, None], json.loads(result))

    def test_the_brick_is_mounted_on_every_page(self):
        base = (Path(settings.BASE_DIR) / 'wama' / 'templates' / 'base.html').read_text(encoding='utf-8')
        self.assertIn("common/js/wama-full-text.js", base)

    def test_no_page_copies_a_text_into_its_title(self):
        """A copy is the variant the brick replaces. ⚠ Read by pattern : a copy through a variable
        (`const t = el.textContent; el.title = t`) escapes it."""
        copy = re.compile(r"(?:\.title\s*=|setAttribute\(\s*['\"]title['\"]\s*,)[^;\n]*(?:textContent|innerText)")
        found = []
        for js in Path(settings.BASE_DIR, 'wama').glob('**/static/**/*.js'):
            if 'vendors' in js.parts or js.name == 'wama-full-text.js':
                continue
            for number, line in enumerate(js.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                if copy.search(line):
                    found.append(f'{js.relative_to(settings.BASE_DIR)}:{number}')
        self.assertEqual([], found)


class CardPreviewsOpenTheCommonViewerTest(SimpleTestCase):
    """The preview of a card, single or batch child, opens the common viewer — the one that
    carries the Entry | Output faces (2026-10-12, Fabien : the enhancer's batch children had no
    preview ; the Reader's double-click showed its output text alone)."""

    #: Apps whose JS takes over `wama:card-expand` to open their OWN modal, with the reason.
    #: An entry that no longer intercepts fails the test : the exemption must go with it. EMPTY
    #: since 2026-10-13 (R126) : the transcriber's tabbed modal was the last one — its speakers,
    #: coherence report, evaluation and TXT/SRT downloads are now the common viewer's.
    OWN_RESULT_MODAL = {}

    def test_a_batch_child_keeps_the_preview_of_a_single_card(self):
        guard = re.compile(r'\{%\s*if\b[^%]*\bnot\s+in_batch\b')
        guarded = [card.parent.name + '/' + card.name
                   for card in CardsOpenTheirEntryByTheCommonGestureTest._cards()
                   if guard.search(card.read_text(encoding='utf-8'))]
        self.assertEqual([], guarded)

    def test_no_card_keeps_its_own_result_button(self):
        # The result opens by the card's preview or the side panel's, in the common viewer whose
        # faces are the processes. The describer kept an 👁 to its own tabbed modal (retired
        # 2026-10-13, R125, asked by Fabien). The USE — a comment may name the retired button.
        own = [card.parent.name + '/' + card.name
               for card in CardsOpenTheirEntryByTheCommonGestureTest._cards()
               if re.search(r'class="[^"]*\bpreview-btn\b', card.read_text(encoding='utf-8'))]
        self.assertEqual([], own)

    def test_every_card_preview_says_where_its_double_click_leads(self):
        # The common gesture opens the viewer at `data-preview-url` ; without it the double-click
        # leads nowhere. The transcriber's card had none while its own modal took the gesture
        # (found on 2026-10-13, retiring that modal, R126).
        gesture = re.compile(r'<[^>]*class="[^"]*\bwama-card-preview\b[^"]*"[^>]*>', re.S)
        mute = []
        for card in CardsOpenTheirEntryByTheCommonGestureTest._cards():
            app = card.parent.name
            for tag in gesture.findall(card.read_text(encoding='utf-8')):
                if app not in self.OWN_RESULT_MODAL and 'data-preview-url=' not in tag:
                    mute.append(f'{app}/{card.name}')
        self.assertEqual([], mute)

    def test_only_a_declared_app_takes_over_the_double_click(self):
        # Hors jumelles : aucune substitution ne régénère leur `static/` (facettes du registre :
        # params, apps, urls, views, templates, models, tasks) — leur JS est TOUJOURS la copie
        # de la source à la création, il suit la source quand la jumelle est recréée.
        from wama.common.sandbox import sandbox_labels
        twins = set(sandbox_labels())
        listen = re.compile(r"addEventListener\(\s*['\"]wama:card-expand['\"]")
        takers = set()
        for script in Path(settings.BASE_DIR, 'wama').glob('*/static/**/*.js'):
            app = script.relative_to(Path(settings.BASE_DIR, 'wama')).parts[0]
            if app == 'common' or app in twins:
                continue
            if listen.search(script.read_text(encoding='utf-8', errors='replace')):
                takers.add(app)
        self.assertEqual(set(self.OWN_RESULT_MODAL), takers)


class SidesSwitchHasItsOwnPlaceTest(SimpleTestCase):
    """The switch of faces (Entrée | … | Sortie) has a DEDICATED place outside the preview — asked
    by Fabien (2026-10-13): laid ON the preview, it covered the toolbar of the PDF reader, the top of
    a text, the image or the video full screen. Under the preview first, ABOVE it since 2026-10-14
    (the faces are tabs — the look of the old transcriber modal). The geometry is measured in a
    browser by the nightly scenarios (`common.preview_layout`, and each `<app>.preview`); held
    here : the rule they apply, and the place the viewer gives the switch."""

    def test_the_verdict_names_what_is_wrong(self):
        from wama.common.services.ui_smoke_preview import sides_layout_fault
        good = {'cross': False, 'above': True, 'visible': True}
        self.assertEqual('', sides_layout_fault(None, 'x'))
        self.assertEqual('', sides_layout_fault({'bars': [good], 'fills': True}, 'x'))
        self.assertIn('RECOUVRE', sides_layout_fault(
            {'bars': [dict(good, cross=True, above=False)], 'fills': True}, 'pdf'))
        self.assertIn("n'est pas AU-DESSUS", sides_layout_fault(
            {'bars': [dict(good, above=False)], 'fills': True}, 'pdf'))
        self.assertIn("sort de l'écran", sides_layout_fault(
            {'bars': [dict(good, visible=False)], 'fills': True}, 'pdf'))
        # 2026-10-15 : les flèches de navigation masquaient le bouton de lecture d'un son.
        self.assertIn('flèche', sides_layout_fault(
            {'bars': [good], 'fills': True, 'navs': 2, 'nav_cross': True}, 'audio'))
        self.assertEqual('', sides_layout_fault(
            {'bars': [good], 'fills': True, 'navs': 2, 'nav_cross': False}, 'audio'))
        self.assertIn('hauteur', sides_layout_fault({'bars': [good], 'fills': False}, 'image',
                                                    must_fill=True))
        self.assertEqual('', sides_layout_fault({'bars': [good], 'fills': False}, 'audio'))

    def test_the_viewer_gives_the_switch_a_slot_outside_the_preview(self):
        source = (Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'
                  / 'media-preview.js').read_text(encoding='utf-8')
        # The slot is a sibling BEFORE the scrolling body, never inside `.preview-container`.
        markup = source[source.index('function createPreviewModal'):]
        self.assertLess(markup.index('class="modal-header'), markup.index('${SLOT_CLASS}'))
        self.assertLess(markup.index('${SLOT_CLASS}'), markup.index('class="modal-body'))
        self.assertLess(markup.index('class="modal-body'), markup.index('class="preview-container'))
        # A modal built by an older version (page left open) gets its slot before the body too.
        slot = source[source.index('function _sidesSlot'):source.index('function viewerKind')]
        self.assertIn("insertBefore(slot, body)", slot)
        # And no switch is laid absolutely on the preview any more.
        self.assertNotRegex(source, r"wama-modal-(sides|variants)[^\n]*\n[^\n]*position:absolute")

    def test_the_nightly_matrix_is_registered(self):
        from wama.common.services import nightly_tests
        from wama.common.services.ui_smoke_preview import register_preview_scenarios
        register_preview_scenarios()
        self.assertIn('common.preview_layout', {s.id for s in nightly_tests.REGISTRY})


class SidePanelExpandIsARealButtonTest(SimpleTestCase):
    """The expand button of the side panel's preview is a BUTTON, outside the preview — reported by
    Fabien (2026-10-13): an inert decoration (`pointer-events:none`) laid on the preview, over the
    scrollbar of a long text. The geometry is measured in a browser by the nightly scenarios
    (`<app>.preview`); held here : the rule they apply, and the place the inspector gives it."""

    def _inspector(self):
        return (Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'
                / 'wama-inspector.js').read_text(encoding='utf-8')

    def test_the_verdict_names_what_is_wrong(self):
        from wama.common.services.ui_smoke_preview import panel_expand_fault
        good = {'host': True, 'button': True, 'sized': True, 'receives': True, 'crosses': False}
        self.assertEqual('', panel_expand_fault(None))
        self.assertEqual('', panel_expand_fault({'host': False, 'button': False}))
        self.assertEqual('', panel_expand_fault(good))
        self.assertIn("pas de bouton", panel_expand_fault({'host': True, 'button': False}))
        self.assertIn('taille', panel_expand_fault(dict(good, sized=False)))
        self.assertIn('SUR', panel_expand_fault(dict(good, crosses=True)))
        self.assertIn('ne reçoit pas', panel_expand_fault(dict(good, receives=False)))

    def test_the_button_lives_in_the_section_title_and_opens_the_viewer(self):
        source = self._inspector()
        # The double-click is the common face viewer's since 2026-10-28 ; the panel keeps the button
        # of its section title.
        block = source[source.index('function _showExpandButton'):source.index('function restorePreview')]
        self.assertNotIn('pointer-events:none', block)
        self.assertNotIn('previewHost.appendChild', block)
        self.assertIn("createElement('button')", block)
        self.assertIn('previewTitleEl.appendChild(btn)', block)
        self.assertIn('_openViewer()', block)

    def test_writing_the_title_keeps_the_button(self):
        # The title is the item's name while a preview is shown : a bare `textContent =` would
        # wipe the button with it. One writer, which puts the button back.
        source = self._inspector()
        self.assertEqual(1, source.count('previewTitleEl.textContent ='))
        writer = source[source.index('function _setPreviewTitle'):]
        self.assertIn('_showExpandButton()', writer[:writer.index('\n    }\n')])

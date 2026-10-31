"""Ce que l'assistant ATTEINT — quatre trous relevés sur le fil web n° 32 (2026-10-11).

1. Les faits viennent des outils : la règle « question → répondre sans outil » contredisait
   `search_docs` ; tout outil nommé par une consigne doit exister.
2. `remember_fact` : « mets à jour ta mémoire » n'avait aucun outil d'écriture. Le souvenir est
   PROPOSÉ (provenance assistant, non approuvé), invisible au rappel jusqu'à validation.
3. `find_user_files` : la recherche par nom couvre ce que montre l'arbre du gestionnaire, dossiers
   connectés compris ; `designate` accepte `mounts/…` en COPIANT, jamais en déplaçant.
4. `open_page` : les pages du menu, avec le droit du menu ; le chat suit la page après la voix.
Aucun LLM, aucun GPU : l'embedder est interdit d'appel.
"""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from wama import tool_api
from wama.common.services import assistant_engine

NO_EMBEDDING = mock.patch('wama.common.memory.embed.embed_text',
                          side_effect=AssertionError('an assistant write must not embed'))


class PromptRulesTest(SimpleTestCase):

    PROMPTS = ('WAMA_TOOLS_PROMPT', 'WEB_VOICE_PROMPT', 'CHANNEL_FILES_PROMPT')
    #: Préfixes des noms d'outils du registre : un mot du prompt qui en porte un est un outil.
    TOOL_PREFIXES = ('search_', 'read_', 'memory_', 'find_', 'list_', 'open_', 'remember_',
                     'charger_', 'get_', 'add_to_', 'start_', 'inspect_', 'look_', 'switch_')

    def test_every_tool_a_rule_names_is_registered(self):
        """Une consigne qui nomme un outil renommé ou absent fait chercher au modèle un outil
        qui n'existe pas — et elle ne casse rien de visible."""
        import re
        named = set()
        for name in self.PROMPTS:
            for word in re.findall(r'\b[a-z]+(?:_[a-z]+)+\b', getattr(assistant_engine, name)):
                if word.startswith(self.TOOL_PREFIXES):
                    named.add(word)
        self.assertTrue({'search_docs', 'memory_recall', 'find_user_files', 'open_page'} <= named)
        self.assertEqual(set(), named - set(tool_api.TOOL_REGISTRY))

    def test_no_rule_sends_a_question_to_an_answer_without_tools(self):
        self.assertNotIn('answer directly without tools', assistant_engine.WAMA_TOOLS_PROMPT)
        self.assertIn('FACTS COME FROM TOOLS', assistant_engine.WAMA_TOOLS_PROMPT)


@NO_EMBEDDING
class RememberFactTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('reach_memory', password='x')
        from wama.accounts.permissions import set_account_tier
        self.staff = get_user_model().objects.create_user('reach_staff', password='x')
        set_account_tier(self.staff, 'admin')

    def test_the_memory_is_proposed_not_active(self, _embed):
        from wama.common.models import MemoryItem
        result = tool_api.execute_tool('remember_fact', {
            'content': "L'anonymizer n'est pas encore conforme au RGPD.",
            'subject': 'anonymizer'}, self.user)
        self.assertEqual('pending_review', result['status'])
        item = MemoryItem.objects.get(pk=result['id'])
        self.assertEqual((MemoryItem.PROV_ASSISTANT, 'assistant', self.user, 'anonymizer'),
                         (item.provenance, item.source_app, item.user, item.subject))
        self.assertIsNone(item.approved_at)
        self.assertEqual(0, tool_api.list_my_memories(self.user)['total'],
                         'an unapproved memory is invisible to recall (WAMA_MEMORY §6)')
        self.assertIn('administrateur', result['message'], 'a non-staff user is told who validates')

    def test_once_approved_it_is_what_the_assistant_lists(self, _embed):
        from wama.common.memory.store import approve
        from wama.common.models import MemoryItem
        result = tool_api.remember_fact(self.user, 'Fabien exporte ses transcriptions en PDF.')
        approve(MemoryItem.objects.get(pk=result['id']), par=self.staff)
        listed = tool_api.list_my_memories(self.user)['memories']
        self.assertEqual(['Fabien exporte ses transcriptions en PDF.'], [m['content'] for m in listed])
        again = tool_api.remember_fact(self.user, 'Fabien exporte  ses transcriptions en PDF.')
        self.assertEqual(('already_active', result['id']), (again['status'], again['id']))

    def test_bad_input_and_anonymous_callers_are_refused(self, _embed):
        self.assertIn('error', tool_api.remember_fact(self.user, '   '))
        self.assertIn('error', tool_api.remember_fact(self.user, 'x', kind='fact'))
        self.assertIn('error', tool_api.remember_fact(None, 'x'))

    def test_a_staff_member_is_sent_to_the_review_page(self, _embed):
        result = tool_api.remember_fact(self.staff, 'Le banc OCR se relance le lundi.')
        self.assertEqual(reverse('common:memories'), result['review_url'])
        self.assertIn('Mes souvenirs', result['message'])


class FindUserFilesTest(TestCase):

    def setUp(self):
        from wama.common.utils.media_paths import app_media_dir
        from wama.filemanager.models import MountedFolder
        User = get_user_model()
        self.user = User.objects.create_user('reach_files', password='x')
        self.other = User.objects.create_user('reach_other', password='x')
        media = Path(settings.MEDIA_ROOT)
        self._write(media / f'users/{self.user.id}/temp/DSC05016.JPG')
        self._write(media / app_media_dir('anonymizer', self.user.id, 'output')
                    / 'DSC05016_blurred.JPG')
        self._write(media / f'users/{self.other.id}/temp/DSC05016_other.JPG')
        # Un dossier CONNECTÉ : hors de MEDIA_ROOT, comme un partage ou un nuage monté.
        self.share = Path(tempfile.mkdtemp(prefix='wama_mount_'))
        self.addCleanup(shutil.rmtree, self.share, ignore_errors=True)
        self._write(self.share / 'rapports' / 'Rapport été.pdf')
        self.mount = MountedFolder.objects.create(user=self.user, name='Mon NAS',
                                                  local_path=str(self.share))
        self.other_mount = MountedFolder.objects.create(user=self.other, name='Autre',
                                                        local_path=str(self.share))

    @staticmethod
    def _write(path, data=b'x'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def test_a_name_is_found_in_the_temp_folder_and_in_app_outputs(self):
        result = tool_api.find_user_files(self.user, 'dsc05016')
        names = [r['name'] for r in result['results']]
        self.assertEqual({'DSC05016.JPG', 'DSC05016_blurred.JPG'}, set(names))
        self.assertNotIn('DSC05016_other.JPG', names, "another user's file is never found")
        self.assertEqual('DSC05016.JPG', tool_api.find_user_files(
            self.user, 'dsc05016.jpg')['results'][0]['name'], 'the exact name comes first')

    def test_a_connected_folder_is_searched_with_case_and_accents_ignored(self):
        result = tool_api.find_user_files(self.user, 'rapport ete')
        self.assertEqual(1, result['count'])
        hit = result['results'][0]
        self.assertEqual((f'mounts/{self.mount.id}/rapports/Rapport été.pdf', 'Mon NAS', True),
                         (hit['path'], hit['location'], hit['connected']))

    def test_a_root_searched_only_in_part_is_said(self):
        from wama.common.services import user_files
        with mock.patch.object(user_files, 'MAX_ENTRIES_PER_ROOT', 0):
            result = tool_api.find_user_files(self.user, 'rapport')
        self.assertIn('Mon NAS', [r['location'] for r in result['incomplete']])

    def test_a_connected_file_is_copied_into_the_app_never_moved(self):
        from wama.common.utils.media_paths import designate
        source = self.share / 'rapports' / 'Rapport été.pdf'
        received = designate(f'mounts/{self.mount.id}/rapports/Rapport été.pdf', self.user, 'reader')
        self.assertTrue(received.value.startswith(f'users/{self.user.id}/'), received.value)
        self.assertTrue((Path(settings.MEDIA_ROOT) / received.value).is_file())
        self.assertTrue(source.is_file(), 'the connected folder keeps its file')
        self.assertEqual(f'mounts/{self.mount.id}/rapports/Rapport été.pdf', received.designation)

    def test_another_users_connected_folder_is_refused(self):
        from wama.common.utils.media_paths import InputRefused, designate
        with self.assertRaises(InputRefused):
            designate(f'mounts/{self.other_mount.id}/rapports/Rapport été.pdf', self.user, 'reader')
        self.assertIn('error', tool_api.inspect_user_file(
            self.user, f'mounts/{self.other_mount.id}/rapports/Rapport été.pdf'))

    def test_a_connected_file_can_be_inspected_but_not_moved_to_the_library(self):
        path = f'mounts/{self.mount.id}/rapports/Rapport été.pdf'
        self.assertNotIn('error', tool_api.inspect_user_file(self.user, path))
        refused = tool_api.add_to_media_library(self.user, path, 'document')
        self.assertIn('DÉPLACE', refused['error'])
        self.assertTrue((self.share / 'rapports' / 'Rapport été.pdf').is_file())


class OpenPageTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_superuser('reach_nav', password='x')

    def test_an_app_is_opened_by_its_key_or_its_menu_name(self):
        by_key = tool_api.open_page(self.user, 'anonymizer')
        self.assertEqual(('navigate', reverse('anonymizer:index')), (by_key['action'], by_key['url']))
        by_name = tool_api.open_page(self.user, 'mediatheque')
        self.assertEqual(reverse('media_library:index'), by_name['url'],
                         'a surface outside the catalogue, accents ignored')

    def test_a_page_without_the_right_is_not_offered(self):
        with mock.patch('wama.accounts.permissions.accessible_apps', return_value=['anonymizer']):
            refused = tool_api.open_page(self.user, 'studio')
        self.assertIn('error', refused)
        offered = {p['key'] for p in refused['pages']}
        self.assertIn('anonymizer', offered)
        # Ni une app refusée, ni une page du compte qui relève d'une politique refusée (les
        # Registres et leurs pages) ; une page du compte sans politique reste offerte (2026-10-14).
        self.assertFalse(offered & {'studio', 'media_library', 'registries', 'model_manager',
                                    'models', 'functions', 'libraries'})
        self.assertIn('profile', offered)

    @override_settings(WAMA_PUBLIC_URL='https://wama.exemple.fr')
    def test_a_channel_gets_a_full_link(self):
        self.assertEqual('https://wama.exemple.fr' + reverse('anonymizer:index'),
                         tool_api.open_page(self.user, 'anonymizer')['link'])

    @override_settings(WAMA_PUBLIC_URL='')
    def test_without_a_public_address_there_is_no_link(self):
        self.assertEqual('', tool_api.open_page(self.user, 'anonymizer')['link'])


FAKE_BROWSER = r"""
var window = this;
var assigned = [];
window.location = { assign: function (url) { assigned.push(url); } };
window.setTimeout = function (fn) { fn(); };
var setTimeout = window.setTimeout;
var document = { readyState: 'complete', querySelectorAll: function () { return []; },
                 cookie: '' };
"""


class ChatFollowsThePageTest(SimpleTestCase):
    """`open_page` : le chat RETIENT la page et la suit quand le tour est dit — jamais une
    adresse externe (V8, sur le fichier SERVI)."""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-assistant-chat.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval(FAKE_BROWSER + source)
        ctx.eval("var chat = Object.create(WamaAssistantChat._Chat.prototype);")
        return ctx

    def test_the_page_opens_only_once_the_answer_is_spoken(self):
        ctx = self._ctx()
        ctx.eval("""
            chat.applyActions([{tool: 'open_page', result: {action: 'navigate', url: '/anonymizer/'}}]);
            var said; var spoken = new Promise(function (r) { said = r; });
            chat.followPendingPage(spoken);
        """)
        self.assertEqual(0, ctx.eval("assigned.length"), 'not while the voice still speaks')
        ctx.eval("said(true);")
        self.assertEqual(['/anonymizer/'], list(ctx.eval("assigned")))

    def test_an_external_address_is_never_followed(self):
        ctx = self._ctx()
        for url in ('https://ailleurs.example/', '//ailleurs.example/', 'javascript:alert(1)'):
            ctx.eval("chat.applyActions([{result: {action: 'navigate', url: %r}}]);"
                     "chat.followPendingPage(Promise.resolve(true));" % url)
        self.assertEqual(0, ctx.eval("assigned.length"))


class SidePanelsFromTheAssistantTest(SimpleTestCase):
    """Le mode simplifié est RETIRÉ (2026-10-27, décision de Fabien) : ce qu'il faisait de
    l'interface — masquer les volets — passe par le repli COMMUN des volets, à la voix aussi
    (`fold_side_panels`) ; et sur un téléphone, « Joindre » remplace ses zones de dépôt."""

    def test_the_tool_folds_through_the_page_and_keeps_nothing(self):
        self.assertNotIn('switch_ui_mode', tool_api.TOOL_REGISTRY)
        self.assertIn('fold_side_panels', tool_api.TOOL_REGISTRY)
        self.assertIsNone(tool_api.app_id_for_tool('fold_side_panels'), 'transverse')
        self.assertEqual({'action': 'panels', 'folded': True, 'message': 'Volets repliés.'},
                         tool_api.fold_side_panels(None))
        self.assertFalse(tool_api.fold_side_panels(None, folded='false')['folded'])

    def _chat(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-assistant-chat.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval(FAKE_BROWSER + source)
        ctx.eval("var chat = Object.create(WamaAssistantChat._Chat.prototype);")
        return ctx

    def test_the_chat_folds_the_panels_it_is_told_to(self):
        ctx = self._chat()
        ctx.eval("var asked = []; window.WamaPanels = {setAll: function (v) { asked.push(v); }};"
                 "chat.applyActions([{tool: 'fold_side_panels', result: {action: 'panels', folded: true}},"
                 "                   {tool: 'fold_side_panels', result: {action: 'panels', folded: false}}]);")
        self.assertEqual([True, False], list(ctx.eval('asked')))

    def test_attach_opens_the_system_picker_then_deposits_like_a_drop(self):
        ctx = self._chat()
        ctx.eval("""
            function node() { return { handlers: {}, attrs: {}, children: [],
                addEventListener: function (t, h) { this.handlers[t] = h; },
                setAttribute: function (k, v) { this.attrs[k] = v; },
                appendChild: function (c) { this.children.push(c); } }; }
            var attach = node(), root = node(), clicked = 0, deposited = [];
            root.querySelector = function (sel) { return sel === '[data-assistant-attach]' ? attach : null; };
            document.createElement = function () { var n = node(); n.click = function () { clicked++; }; return n; };
            chat.root = root;
            chat.deposit = function (files) { deposited.push(files); };
            chat.bindDeposit();
            var picker = root.children[0];
            attach.handlers.click();
            picker.files = [{name: 'photo.jpg'}];
            picker.handlers.change();
        """)
        self.assertEqual('file', ctx.eval('picker.type'))
        self.assertTrue(ctx.eval('picker.multiple'))
        self.assertEqual(1, ctx.eval('clicked'), 'the button opens the system picker')
        import json
        self.assertEqual([[{'name': 'photo.jpg'}]], json.loads(ctx.eval('JSON.stringify(deposited)')))
        self.assertEqual('', ctx.eval('picker.value'), 'the same file can be picked again')
        self.assertIn('data-fm-designate', list(ctx.eval('Object.keys(root.attrs)')), 'drop still wired')

    def test_both_chats_carry_the_attach_button(self):
        for template in ('templates/home.html', 'common/templates/common/_assistant_avatar.html'):
            self.assertIn('data-assistant-attach', (Path(settings.BASE_DIR) / 'wama' / template)
                          .read_text(encoding='utf-8'), template)


class HandModeFromTheAssistantTest(TestCase):
    """« Active le mode main en 3D » (2026-10-30, demande de Fabien) : l'assistant n'atteignait
    aucune scène 3D (`open_page` ne les connaissait pas) et n'avait aucun geste pour les mains."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('reach_hands_admin', password='x')
        self.member = get_user_model().objects.create_user('reach_hands_member', password='x')

    def test_a_scene_is_a_page_with_the_right_of_its_request(self):
        from wama.common.scenes import SCENES, page_url
        users = SCENES['users']
        opened = tool_api.open_page(self.admin, users.page_title)
        self.assertEqual(('navigate', page_url(users)), (opened['action'], opened['url']))
        # La scène des utilisateurs est réservée à l'administration (`permission='admin'`) ; les
        # scènes ouvertes à tout compte le restent pour un membre.
        refused = tool_api.open_page(self.member, users.page_title)
        self.assertIn('error', refused)
        offered = {p['key'] for p in refused['pages']}
        self.assertNotIn('scene:users', offered)
        self.assertTrue({f'scene:{k}' for k, s in SCENES.items() if s.permission == 'auth'} <= offered)

    def test_the_tool_switches_the_hands_and_names_the_scenes_it_can_drive(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertIn('error', tool_api.use_hand_mode(AnonymousUser()))
        on = tool_api.use_hand_mode(self.member)
        self.assertEqual(('hands', True), (on['action'], on['on']))
        self.assertNotIn('scene:users', {s['key'] for s in on['scenes']})
        self.assertIn('scene:users', {s['key'] for s in tool_api.use_hand_mode(self.admin)['scenes']})
        self.assertFalse(tool_api.use_hand_mode(self.member, on='false')['on'])
        self.assertIsNone(tool_api.app_id_for_tool('use_hand_mode'), 'transverse')


HANDS_BROWSER = r"""
function fakeNode() { return { hidden: false, style: {}, attrs: {}, dataset: {}, children: [],
    classes: {}, classList: { toggle: function (c, on) { this.o[c] = !!on; }, contains: function (c) { return !!this.o[c]; }, o: {} },
    setAttribute: function (k, v) { this.attrs[k] = v; if (k === 'hidden') this.hidden = true; },
    removeAttribute: function (k) { delete this.attrs[k]; if (k === 'hidden') this.hidden = false; },
    addEventListener: function () {}, append: function () {}, appendChild: function () {},
    getContext: function () { return {}; } }; }
var item = fakeNode(), clicks = 0;
item.hidden = true;
var toggleBtn = fakeNode();
toggleBtn.closest = function () { return item; };
toggleBtn.click = function () { clicks += 1; };
var store = {};
var sessionStorage = { getItem: function (k) { return k in store ? store[k] : null; },
                       setItem: function (k, v) { store[k] = String(v); },
                       removeItem: function (k) { delete store[k]; } };
window.sessionStorage = sessionStorage;
document.getElementById = function (id) { return id === 'wamaHandsToggle' ? toggleBtn : null; };
document.createElement = fakeNode;
document.body = fakeNode();
"""


class HandModeInTheBrowserTest(SimpleTestCase):
    """Le chat exécute `use_hand_mode` par l'icône ✋ quand la page a une scène, et RETIENT le
    souhait sinon ; la scène qui se déclare ensuite l'exauce une fois (V8, fichiers SERVIS)."""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        js = Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
        ctx = MiniRacer()
        ctx.eval(FAKE_BROWSER + HANDS_BROWSER + (js / 'wama-assistant-chat.js').read_text(encoding='utf-8'))
        ctx.eval("var chat = Object.create(WamaAssistantChat._Chat.prototype);")
        # Le module des mains, chargé comme un script : ses `export` retirés, `import.meta` et `URL`
        # remplacés — `start()` montre l'icône allumée AVANT d'attendre le moteur de gestes.
        hands = ((js / 'wama-hands-ui.js').read_text(encoding='utf-8')
                 .replace('export async function', 'async function').replace('export function', 'function')
                 .replace('import.meta.url', "'/static/common/js/wama-hands-ui.js'")
                 .replace('import.meta.resolve(', 'String('))
        ctx.eval("var URL = function (u) { this.href = u; }; var innerWidth = 1, innerHeight = 1;"
                 "window.WamaApp = {loadStyle: function () {}}; var addEventListener = function () {};"
                 "var getComputedStyle = function () { return {getPropertyValue: function () { return ''; }}; };"
                 "(function () {" + hands + "; window.registerHandTarget = registerHandTarget; })();")
        return ctx

    def test_on_a_page_with_a_scene_the_icon_is_clicked(self):
        ctx = self._ctx()
        ctx.eval("item.hidden = false;"
                 "chat.applyActions([{tool: 'use_hand_mode', result: {action: 'hands', on: true}}]);")
        self.assertEqual(1, ctx.eval('clicks'))
        self.assertEqual(0, ctx.eval('Object.keys(store).length'), 'applied now, nothing kept')
        ctx.eval("toggleBtn.classList.o.active = true;"
                 "chat.applyActions([{result: {action: 'hands', on: true}}]);")
        self.assertEqual(1, ctx.eval('clicks'), 'already on: not switched off by a second « on »')

    def test_without_a_scene_the_wish_waits_for_the_scene_that_opens(self):
        ctx = self._ctx()
        ctx.eval("chat.applyActions([{tool: 'use_hand_mode', result: {action: 'hands', on: true}}]);")
        self.assertEqual(0, ctx.eval('clicks'), 'no scene: the hidden icon is not clicked')
        self.assertEqual('on', ctx.eval("store['wama.hands.wish']"))
        ctx.eval("window.registerHandTarget({});")
        self.assertTrue(ctx.eval("toggleBtn.classList.o.active"), 'the scene switches the hands on')
        self.assertEqual(0, ctx.eval('Object.keys(store).length'), 'granted once')

    def test_a_scene_without_a_wish_leaves_the_hands_off(self):
        """Contre-épreuve : déclarer une scène n'allume pas la caméra de soi-même."""
        ctx = self._ctx()
        ctx.eval("window.registerHandTarget({});")
        self.assertFalse(ctx.eval("!!toggleBtn.classList.o.active"))

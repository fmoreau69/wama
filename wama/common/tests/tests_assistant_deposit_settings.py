"""
Le chat de l'assistant (2026-10-18, décisions de Fabien) : ses RÉGLAGES quittent la carte du chat
pour la section « Paramètres » du volet et la modale ⚙ commune (le chemin du mode simplifié, et du
mini-chat des autres pages) ; et on y GLISSE des fichiers comme dans Discord — déposés par le geste
partagé, en pastilles, envoyés avec le message ou seuls (« Que puis-je en faire ? »).

Rien de neuf n'est inventé : schéma `assistant/params.py`, modale `WamaParams.settingsModal`,
dépôt `enregistrer_fichier_utilisateur`, message `assistant_engine.message_with_deposits` (sorti de
la passerelle, qui l'écrivait depuis le 21/08).
"""
import json
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse


class DepositMessageTest(SimpleTestCase):
    """UNE graphie pour toute surface : celle que Discord écrivait."""

    def test_files_without_text_ask_what_to_do(self):
        from wama.common.services.assistant_engine import message_with_deposits
        self.assertEqual("[Fichiers déposés dans mon espace WAMA : `users/1/temp/a.png`]\n"
                         "Que puis-je en faire ?",
                         message_with_deposits('', ['users/1/temp/a.png']))

    def test_the_text_follows_the_header_and_no_file_changes_nothing(self):
        from wama.common.services.assistant_engine import message_with_deposits
        self.assertTrue(message_with_deposits('Floute-la', ['x.png']).endswith('\nFloute-la'))
        self.assertEqual('Bonjour', message_with_deposits('  Bonjour ', []))

    def test_the_gateway_writes_it_through_the_same_function(self):
        """La passerelle ne recompose plus le message à la main."""
        source = (Path(settings.BASE_DIR) / 'wama' / 'gateway' / 'core.py').read_text(encoding='utf-8')
        self.assertIn('message_with_deposits(texte,', source)
        self.assertNotIn('Fichiers déposés dans mon espace WAMA', source)


class WebTurnTakesDepositedFilesTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('deposit_web', password='x')
        self.client.force_login(self.user)

    def test_only_readable_files_enter_the_message(self):
        from wama import views
        mine = f'users/{self.user.pk}/temp/a.png'
        with mock.patch('wama.filemanager.services.resoudre_chemin_lisible',
                        side_effect=lambda u, p: ('/x', None) if p == mine else (None, ('no', 403))):
            message = views._turn_message(self.user, {'message': '', 'files': [mine, 'users/999/b.png']})
        self.assertIn(f'`{mine}`', message)
        self.assertNotIn('users/999', message, "un chemin posté n'est pas un chemin à soi")
        self.assertTrue(message.endswith('Que puis-je en faire ?'))

    def test_a_turn_with_only_files_is_accepted(self):
        """Contre-épreuve de « Message is required » : un dépôt seul est un message."""
        with mock.patch('wama.filemanager.services.resoudre_chemin_lisible',
                        return_value=('/x', None)), \
                mock.patch('wama.common.services.resource_governor.release_in_progress',
                           return_value=False), \
                mock.patch('wama.common.services.assistant_engine.conversation_turn',
                           return_value={'response': 'Je vois une image.'}) as turn:
            r = self.client.post(reverse('ai_chat'), data=json.dumps({'message': '',
                                                                      'files': ['users/1/temp/a.png']}),
                                 content_type='application/json')
        self.assertEqual(200, r.status_code)
        self.assertIn('Que puis-je en faire ?', turn.call_args.args[1])


class AssistantSettingsSurfacesTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('settings_surfaces', password='x')
        self.client.force_login(self.user)

    def test_the_settings_route_serves_what_the_common_modal_renders(self):
        d = self.client.get(reverse('ai_chat_settings')).json()
        names = [p['name'] for p in d['schema']]
        self.assertIn('voice_sentence_pause', names)
        self.assertEqual(['voice'], [g['key'] for g in d['groups']])
        self.assertIn('voice_clause_pause', d['values'])
        # Les champs de la modale (contexte `item`) : ceux du volet, sous d'autres identifiants.
        shown = [p['name'] for p in d['schema'] if 'item' in (p.get('contexts') or [])]
        self.assertEqual(['model', 'quality_intent', 'temperature', 'seed', 'top_p',
                          'voice_sentence_pause', 'voice_clause_pause'], shown)

    def test_the_modal_form_is_saved_and_bounded(self):
        """La modale commune poste un FORMULAIRE (`WamaParams.settingsModal`), pas du JSON."""
        from wama.common.services.assistant_engine import assistant_settings
        r = self.client.post(reverse('ai_chat_settings'),
                             {'voice_sentence_pause': '0.9', 'voice_clause_pause': '7'})
        self.assertEqual(200, r.status_code, r.content)
        saved = assistant_settings(self.user)
        self.assertAlmostEqual(0.9, float(saved['voice_sentence_pause']))
        self.assertAlmostEqual(1.0, float(saved['voice_clause_pause']))

    def test_the_home_page_shows_the_settings_in_the_panel_not_in_the_chat_card(self):
        html = self.client.get('/').content.decode('utf-8')
        section = re.search(r'id="settings-section".*?</div>\s*</div>', html, re.S)
        self.assertIsNotNone(section, 'la section « Paramètres » du volet manque')
        self.assertIn('id="ai-settings"', section.group(0))
        self.assertIn('id="ai-settings-open"', html)          # la ⚙ du mode simplifié
        self.assertIn('data-settings-url=', html)


FAKE_BROWSER = r"""
var window = this;
var document = { readyState: 'complete', querySelectorAll: function () { return []; },
                 cookie: '', addEventListener: function () {},
                 createElement: function () { return { style: {}, appendChild: function () {},
                                                        addEventListener: function () {} }; } };
var posted = [];
function fetch(url, options) {
  posted.push({ url: url, body: options && options.body ? JSON.parse(options.body) : null });
  return Promise.resolve({ ok: true, headers: { get: function () { return 'application/json'; } },
    json: function () { return Promise.resolve({ success: true, response: 'ok',
      schema: [{ name: 'voice_sentence_pause' }], groups: [{ key: 'voice' }], values: { a: 1 } }); } });
}
var modal = null;
window.WamaParams = { settingsModal: function (cfg) { modal = cfg; return Promise.resolve(); } };
window.WamaFM = { upload: function (files) {
  return Promise.resolve({ uploaded: files.map(function (f, i) {
    return { path: 'users/1/temp/' + f.name, name: f.name }; }) }); } };
"""


class ChatDepositAndGearTest(SimpleTestCase):
    """V8, sur le fichier SERVI : le dépôt passe par `WamaFM.upload`, les chemins partent avec le
    message suivant puis s'effacent ; la ⚙ ouvre la modale COMMUNE au contexte `item`."""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-assistant-chat.js').read_text(encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval(FAKE_BROWSER + source)
        ctx.eval("""
            var chat = Object.create(WamaAssistantChat._Chat.prototype);
            chat.cfg = { chatUrl: '/api/ai-chat/', streamUrl: '', settingsUrl: '/api/ai-chat/settings/' };
            chat.deposits = []; chat.full = false;
            chat.input = { value: '', disabled: false, focus: function () {}, style: {},
                           parentNode: { parentNode: { insertBefore: function () {} } } };
            chat.sendBtn = {};
            chat.feed = { appendChild: function () {}, scrollTop: 0, scrollHeight: 0 };
            chat.setStatus = function () {}; chat.dropGreeting = function () {};
            chat.startWaiting = function () {}; chat.stopWaiting = function () {};
            chat.autoGrow = function () {}; chat.renderDeposits = function () {};
            chat.bubble = function () { return {}; }; chat.scrollToEnd = function () {};
        """)
        return ctx

    @staticmethod
    def _read(ctx, name):
        return json.loads(ctx.eval('JSON.stringify(%s)' % name))

    def test_a_dropped_file_goes_with_the_next_message_then_is_cleared(self):
        ctx = self._ctx()
        ctx.eval("chat.deposit([{ name: 'photo.jpg' }]);")
        self.assertEqual([{'path': 'users/1/temp/photo.jpg', 'name': 'photo.jpg'}],
                         self._read(ctx, 'chat.deposits'))
        ctx.eval("chat.input.value = ''; chat.send();")   # sans texte : le dépôt seul part
        self.assertEqual({'message': '', 'files': ['users/1/temp/photo.jpg']}, self._read(ctx, 'posted')[0]['body'])
        self.assertEqual([], self._read(ctx, 'chat.deposits'))

    def test_a_message_without_deposit_sends_no_files(self):
        """Contre-épreuve : le corps d'avant, inchangé."""
        ctx = self._ctx()
        ctx.eval("chat.input.value = 'Bonjour'; chat.send();")
        self.assertEqual({'message': 'Bonjour'}, self._read(ctx, 'posted')[0]['body'])

    def test_a_file_dragged_from_the_tree_is_designated_by_its_path_without_upload(self):
        """Mode normal : l'arbre du volet gauche glisse un CHEMIN — rien n'est re-téléversé."""
        ctx = self._ctx()
        ctx.eval("""
            var attrs = {}, listeners = {}, uploads = 0;
            window.WamaFM.upload = function () { uploads++; return Promise.resolve({}); };
            chat.root = { setAttribute: function (k, v) { attrs[k] = v; },
                          addEventListener: function (t, f) { listeners[t] = f; },
                          classList: { add: function () {}, remove: function () {} } };
            chat.bindDeposit();
            listeners['filemanager:designate']({ detail: { files: [
              { path: 'users/1/input/a.wav', name: 'a.wav' }, { path: 'users/1/input/a.wav' },
              { path: 'users/1/input/b.pdf' }] } });
        """)
        self.assertIn('data-fm-designate', self._read(ctx, 'attrs'), "le chat ne se déclare pas cible de l'arbre")
        self.assertEqual([{'path': 'users/1/input/a.wav', 'name': 'a.wav'},
                          {'path': 'users/1/input/b.pdf', 'name': 'b.pdf'}], self._read(ctx, 'chat.deposits'))
        self.assertEqual(0, self._read(ctx, 'uploads'))
        ctx.eval("chat.input.value = 'Transcris'; chat.send();")
        self.assertEqual({'message': 'Transcris', 'files': ['users/1/input/a.wav', 'users/1/input/b.pdf']},
                         self._read(ctx, 'posted')[0]['body'])

    def test_the_tree_hands_declared_targets_their_paths_before_resolving_an_app(self):
        """L'accueil ne déclare aucune app : résoudre l'app d'abord y rendait « dépôt impossible »."""
        source = (Path(settings.BASE_DIR) / 'staticfiles' / 'filemanager' / 'js'
                  / 'filemanager.js').read_text(encoding='utf-8')
        self.assertIn("document.querySelectorAll('.drop-zone, [data-fm-designate]')", source)
        stop = source[source.index("$(document).on('dnd_stop.vakata', function(e, data) {\n            const dragData"):]
        self.assertLess(stop.index("new CustomEvent('filemanager:designate'"),
                        stop.index('getAppFromDropZone(currentDropZone)'))

    def test_the_chat_drop_gesture_is_measured_every_night(self):
        """Le geste nocturne `common.assistant.chat_drop` (poste, arbre, envoi) est AU REGISTRE : son
        bloc d'enregistrement avale les exceptions, un scénario cassé à l'import disparaîtrait sans
        un mot — et le défaut du mode normal (D36) redeviendrait invisible."""
        try:
            import playwright  # noqa: F401
        except ImportError:
            self.skipTest('Playwright absent de ce venv : les scénarios UI ne s’enregistrent pas')
        from wama.common.services.nightly_tests import REGISTRY
        (scenario,) = [s for s in REGISTRY if s.id == 'common.assistant.chat_drop']
        self.assertEqual(('common', 'ui'), (scenario.app, scenario.stage))

    def test_the_gear_opens_the_common_modal_on_the_item_context(self):
        ctx = self._ctx()
        ctx.eval("chat.openSettings();")
        cfg = self._read(ctx, 'modal')
        self.assertEqual(('item', '/api/ai-chat/settings/'), (cfg['context'], cfg['saveUrl']))
        self.assertEqual([{'key': 'voice'}], cfg['groups'])

"""The page of the UI bricks registry (2026-10-16, asked by Fabien : the map of the registries named
« Briques UI », nothing showed them). It derives from `common/surfaces.py` on each display, is reached
from the registry card and from the account menu, and shows which surfaces compose each brick."""
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape

from wama.common import registries
from wama.common.app_registry import app_identity, measured_adoption
from wama.common.mecanismes import MECHANISMS
from wama.common.surfaces import (BRICKS, SURFACES, THUMBNAILS_DIR, UIBrick, load_all,
                                  thumbnail_path)


class UIBricksPageTest(TestCase):

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('ui-bricks', password='x'))
        load_all()

    def _page(self):
        response = self.client.get(reverse('common:ui_bricks_catalog'))
        self.assertEqual(200, response.status_code)
        return response.content.decode('utf-8', 'replace')

    def test_every_declared_brick_has_its_card(self):
        page = self._page()
        self.assertTrue(BRICKS, 'the instrument sees the registry')
        for key, brick in BRICKS.items():
            with self.subTest(brick=key):
                self.assertIn(f'data-id="{key}"', page)
                self.assertIn(escape(brick.name), page)

    def test_a_brick_names_the_surfaces_that_compose_it(self):
        """An app is named by its declared identity (`app_identity`), never by its key."""
        page = self._page()
        self.assertTrue(SURFACES, 'at least one surface is declared')
        for surface in SURFACES.values():
            with self.subTest(surface=surface.id):
                self.assertIn(f'{app_identity(surface.app)["label"]} · {surface.label}', page)
                self.assertNotIn(f'>{surface.app} · ', page)

    def test_what_a_brick_reads_is_said_in_its_vocabulary(self):
        """`consumes` holds media natures or data types — the page says which, never a third word."""
        page = self._page()
        self.assertIn('nature de média', page)
        self.assertIn('type de données', page)

    def test_the_registry_card_and_the_account_menu_lead_here(self):
        url = reverse('common:ui_bricks_catalog')
        self.assertEqual('common:ui_bricks_catalog', registries.get('ui_bricks').url_name)
        from wama.common.app_registry import account_pages
        pages = {p['key']: p for p in account_pages()}
        self.assertEqual(url, reverse(pages['ui_bricks']['url_name']))
        self.assertEqual('wama', pages['ui_bricks']['section'])

    def test_a_derived_page_offers_no_refresh_button(self):
        page = self._page()
        self.assertNotIn('data-wama-refresh="ui_bricks"', page)
        self.assertIn('toujours à jour', page)


class BrickCompositionTest(TestCase):
    """Three levels (2026-10-19, Fabien) : a mechanism is a PIECE, a brick a WHOLE made of them.
    The page shows bricks only ; each says which mechanisms compose it, READ from its code — the
    owners of what it loads (`requires`) and what its own script consumes, by the very detection
    of the adoption scan (`mecanismes_scan.consumers`)."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('ui-parts', password='x'))
        load_all()

    def _page(self):
        response = self.client.get(reverse('common:ui_bricks_catalog'))
        self.assertEqual(200, response.status_code)
        return response.content.decode('utf-8', 'replace')

    def test_only_bricks_have_a_card(self):
        page = self._page()
        self.assertNotIn('data-f-famille', page, 'no « Système » family beside the bricks')
        for mechanism in MECHANISMS:
            if mechanism.key not in BRICKS:
                with self.subTest(mechanism=mechanism.key):
                    self.assertNotIn(f'data-id="{mechanism.key}"', page)

    def test_a_brick_is_composed_of_what_it_loads_and_what_its_script_uses(self):
        """The media transport loads the axis and the shuttle, and mounts the shared audio player
        through its `base.html` global — never the visitor identity for an `axis.attach(…)`."""
        parts = BRICKS['media_transport'].mechanisms()
        self.assertTrue({'media_axis', 'shuttle', 'audio_player'} <= set(parts), parts)
        self.assertNotIn('visitor_identity', parts)
        names = {m.key: m.name for m in MECHANISMS}
        card = self._page().split('data-id="media_transport"', 1)[1].split('wama-cat-card', 1)[0]
        for key in ('media_axis', 'shuttle', 'audio_player'):
            with self.subTest(part=key):
                self.assertIn(f'title="{key}">{names[key]}</span>', card)

    def test_a_brick_card_lists_the_shortcuts_the_brick_owns(self):
        """2026-10-29 : the catalogue reads `UIBrick.shortcuts`, the same declaration as the
        Actions brick of a surface ; a brick that declares none has no « Clavier » row."""
        page = self._page()
        card = page.split('data-id="media_transport"', 1)[1].split('wama-cat-card', 1)[0]
        self.assertIn('<b>Clavier</b>', card)
        self.assertIn('<kbd>J / K / L</kbd> lecture arrière / pause / lecture avant, par crans '
                      'de vitesse', card)
        quiet = page.split('data-id="html_preview"', 1)[1].split('wama-cat-card', 1)[0]
        self.assertNotIn('<b>Clavier</b>', quiet)

    def test_a_composition_is_read_from_the_script_never_declared(self):
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as js:
            js.write('WamaAudioPlayer.mount(el); axis.attach(el);')
        brick = UIBrick(key='fake', name='Fausse', description='', script='fake/brick.js',
                        requires=('common/js/wama-shuttle.js',))
        with mock.patch('django.contrib.staticfiles.finders.find', return_value=js.name):
            self.assertEqual(['audio_player', 'shuttle'], brick.mechanisms())
        with mock.patch('django.contrib.staticfiles.finders.find', return_value=None):
            self.assertEqual(['shuttle'], brick.mechanisms(), 'a script not found reads nothing')


class PageBrickTest(TestCase):
    """Page bricks (2026-10-19, Fabien, step 3) : an app page mounts them by a template (or the
    base page, for all), never a surface. Nothing flows to them : they read what the mounting app
    DECLARES (a facet of its manifest, or its pipeline) ; the apps that mount them are the measured
    adoption of the mechanism that holds that template."""

    PAGE_BRICKS = ('entry_card', 'global_progress', 'inspector_panel', 'media_viewer', 'queue',
                   'toolbar',
                   # 2026-10-29 : les sections du volet, chacune sa brique (`volet.PANEL_SLOTS`).
                   'item_preview', 'item_details', 'settings_panel', 'assistant_panel')

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('ui-page', password='x'))
        load_all()

    def test_a_page_brick_reads_only_what_the_mounting_app_states(self):
        from wama.common.manifests.builtin.app import APP_FACETS
        from wama.common.manifests.kinds import MANIFEST_KINDS
        for key, brick in BRICKS.items():
            with self.subTest(brick=key):
                self.assertEqual(key in self.PAGE_BRICKS, brick.is_page)
                if not brick.is_page:
                    self.assertEqual((), brick.declarations, 'a surface brick reads what flows')
                    continue
                self.assertEqual((), brick.consumes, 'nothing flows to a page brick')
                self.assertTrue(brick.declarations)
                for value in brick.declarations:
                    kind, _, facet = value.partition('.')
                    self.assertIn(kind, MANIFEST_KINDS, value)
                    if facet:
                        self.assertEqual('app', kind, value)
                        self.assertIn(facet, APP_FACETS, value)

    def test_its_mount_is_a_file_a_page_names(self):
        from wama.common.surfaces import source_file
        for key in self.PAGE_BRICKS:
            with self.subTest(brick=key):
                self.assertTrue(source_file(BRICKS[key].mount), BRICKS[key].mount)

    def test_the_apps_that_mount_it_are_the_measured_adoption_of_its_template(self):
        report = {'generated_at': '2026-10-19T00:00:00+00:00',
                  'criteria': {'c_card': {'mechanism': 'new_item_card'}},
                  'apps': {'anonymizer': {'conv': {'c_card': True}},
                           'composer': {'conv': {'c_card': 'partial'}},
                           'imager': {'conv': {'c_card': False}}}}
        with mock.patch('wama.common.app_registry._conformity_report', return_value=report):
            adoption = BRICKS['entry_card'].adoption()
            self.assertEqual({'anonymizer': True, 'composer': 'partial', 'imager': False},
                             adoption['apps'])
            self.assertEqual(['c_card'], adoption['criteria'])
            self.assertEqual({'apps': {}, 'criteria': [], 'measured_at': None},
                             BRICKS['image_boxes'].adoption(), 'a surface brick: its surfaces')
            response = self.client.get(reverse('common:ui_bricks_catalog'))
        card = response.content.decode('utf-8', 'replace').split(
            'data-id="entry_card"', 1)[1].split('wama-cat-card', 1)[0]
        self.assertIn(f'>{app_identity("anonymizer")["label"]}</span>', card)
        self.assertIn(f'>{app_identity("composer")["label"]}<small>en partie</small>', card)
        self.assertNotIn(app_identity('imager')['label'], card, 'a red app does not mount it')
        self.assertIn('data-f-montage="Page"', card)
        self.assertIn('ports<small>facette de l&#x27;app</small>', card)

    def test_a_surface_never_places_a_page_brick(self):
        from wama.common.manifests.codegen.surfaces_gen import _check
        from wama.common.surfaces import BrickSlot, Surface, register_surface
        slot = BrickSlot(id='card', brick='entry_card', x=0, y=0, w=4, h=4)
        with self.assertRaises(ValueError):
            register_surface(Surface(app='nowhere', key='edit', label='x', model='x.Y',
                                     slots=(slot,), reads={}, edits='f'))
        self.assertNotIn('nowhere.edit', SURFACES)
        refused = _check({'key': 'edit', 'label': 'x', 'slots': [
            {'id': 'card', 'brick': 'entry_card', 'x': 0, 'y': 0, 'w': 4, 'h': 4}]}, {}, set())
        self.assertIn('brique de PAGE', refused)

    def test_a_composition_is_read_from_the_code_not_from_its_comments(self):
        """The viewer's script names, in comments only, the media picker that CALLS it and the
        queue scripts it resembles : none is a piece of it ; the overlay class it sets is one."""
        parts = BRICKS['media_viewer'].mechanisms()
        self.assertIn('preview', parts)
        for prose in ('media_picker', 'queue_front', 'queue_dnd', 'inspector'):
            with self.subTest(prose=prose):
                self.assertNotIn(prose, parts)


class MeasuredAdoptionTest(TestCase):
    """What the MEASURED grid says of a mechanism (`app_registry.measured_adoption`) : the
    criteria that check it and, per app, all green / partial / none — read from the report
    `/apps/` reads, never a scan of the repository ; without a report, nothing is invented."""

    REPORT = {'generated_at': '2026-10-18T00:00:00+00:00',
              'criteria': {'c_one': {'mechanism': 'checked'}, 'c_two': {'mechanism': 'checked'}},
              'apps': {'anonymizer': {'conv': {'c_one': True, 'c_two': True}},
                       'composer': {'conv': {'c_one': True, 'c_two': False}},
                       'imager': {'conv': {'c_one': False, 'c_two': False}},
                       'describer': {'conv': {}}}}

    def test_the_state_per_app_is_read_from_the_report(self):
        with mock.patch('wama.common.app_registry._conformity_report', return_value=self.REPORT):
            adoption = measured_adoption('checked')
            self.assertEqual(['c_one', 'c_two'], adoption['criteria'])
            self.assertEqual({'anonymizer': True, 'composer': 'partial', 'imager': False},
                             adoption['apps'])
            self.assertEqual([], measured_adoption('unchecked')['criteria'])

    def test_without_a_measured_report_nothing_is_invented(self):
        with mock.patch('wama.common.app_registry._conformity_report', return_value=None):
            self.assertEqual({'criteria': [], 'apps': {}, 'measured_at': None},
                             measured_adoption('checked'))


class BrickThumbnailTest(TestCase):
    """A brick's thumbnail is the capture the nightly took (`surfaces.thumbnail`), served from
    `STATIC_ROOT` under an address that changes with the capture ; without one, the card says so."""

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('ui-thumb', password='x'))
        load_all()

    def test_a_captured_brick_shows_its_capture_and_an_uncaptured_one_says_so(self):
        shot, bare = sorted(BRICKS)[:2]
        with tempfile.TemporaryDirectory() as root, override_settings(STATIC_ROOT=root):
            path = thumbnail_path(shot)
            path.parent.mkdir(parents=True)
            path.write_bytes(b'capture')
            response = self.client.get(reverse('common:ui_bricks_catalog'))
        page = response.content.decode('utf-8', 'replace')
        card = page.split(f'data-id="{shot}"', 1)[1].split('wama-cat-card', 1)[0]
        self.assertIn(f'class="wama-cat-thumb" src="/static/{THUMBNAILS_DIR}/{shot}.png?v=', card)
        other = page.split(f'data-id="{bare}"', 1)[1].split('wama-cat-card', 1)[0]
        self.assertIn('aucune capture', other)
        self.assertNotIn('<img class="wama-cat-thumb"', other)


def _static(path):
    from pathlib import Path

    from django.contrib.staticfiles import finders
    return Path(finders.find(path)).read_text(encoding='utf-8')


class AccountKeysTest(TestCase):
    """2026-11-15 (Fabien, 12/11 : « un utilisateur personnalise ses raccourcis, par brique, depuis
    la page des briques UI ») — the keys an ACCOUNT gives to the actions of a brick : third stage of
    the resolution (brick default, then the page preset, then the account). Same shape, same
    validation, same rule as a page preset ; kept as an account setting, served to every page."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('keys-owner', password='x')
        self.other = get_user_model().objects.create_user('keys-other', password='x')
        self.client.force_login(self.user)
        load_all()

    def _post(self, brick, keys):
        import json
        return self.client.post(reverse('common:brick_keys'),
                                json.dumps({'brick': brick, 'keys': keys}),
                                content_type='application/json')

    def test_a_key_given_on_the_bricks_page_is_kept_for_the_account_alone(self):
        from wama.common.utils.user_keys import user_keymap
        response = self._post('media_transport', {'toggle': ['KeyP']})
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual({'toggle': ['KeyP']}, body['keys'])
        shown = {k['name']: k['label'] for row in body['rows'] for k in row['keys']}
        self.assertEqual('P', shown['toggle'], 'the answer says the keys as they now read')
        self.assertEqual({'media_transport': {'toggle': ['KeyP']}}, user_keymap(self.user))
        self.assertEqual({}, user_keymap(self.other))
        self.assertEqual({}, user_keymap(None))
        # The page shows the resolved key, and hands the module what it edits.
        page = self.client.get(reverse('common:ui_bricks_catalog')).content.decode('utf-8', 'replace')
        self.assertIn('data-key-settings="media_transport"', page)
        self.assertIn('id="wama-key-settings"', page)
        self.assertIn('wama-key-settings.js', page)
        self.assertIn('<kbd>P</kbd> lecture / pause', page)
        # Giving nothing puts the brick back on today's defaults : the entry is REMOVED.
        self.assertEqual(200, self._post('media_transport', {}).status_code)
        self.assertEqual({}, user_keymap(self.user))

    def test_what_cannot_apply_is_not_kept(self):
        from wama.common.utils.user_keys import user_keymap
        for brick, keys, said in (('media_transport', {'fly': ['KeyF']}, 'ne nomme pas'),
                                  ('media_transport', {'toggle': ['KeyX'], 'stop': ['KeyX']}, 'KeyX'),
                                  ('media_transport', {'toggle': 'Space'}, 'liste'),
                                  ('no_such_brick', {'toggle': ['KeyP']}, 'aucune action')):
            with self.subTest(keys=keys):
                response = self._post(brick, keys)
                self.assertEqual(400, response.status_code)
                self.assertIn(said, ' ; '.join(response.json()['problems']))
        self.assertEqual({}, user_keymap(self.user))
        self.client.logout()
        self.assertEqual(302, self._post('media_transport', {'toggle': ['KeyP']}).status_code)

    def test_the_account_comes_after_the_page_preset_and_the_keyboard_resolves_alike(self):
        """The correction page gives ← to the jump ; the account gives ← back to the axis step :
        the jump loses it (a key given leaves the action that had it, one stage higher), and the
        page serves ONE merged table — the one the common keyboard resolves."""
        from py_mini_racer import MiniRacer

        from wama.common.surfaces import merge_overrides
        from wama.common.tests.tests_surfaces import BrickShortcutsTest, KeyDispatcherTest, _js
        account = {'media_transport': {'nudge_back': ['ArrowLeft'], 'toggle': ['KeyP']}}
        correct = SURFACES['transcriber.correct']
        merged = correct.keymap_for(account)['media_transport']
        self.assertEqual([], merged['jump_back'], 'the preset keeps the action, not the key')
        self.assertEqual(['ArrowRight'], merged['jump_forward'])
        self.assertEqual(['ArrowLeft'], merged['nudge_back'])
        served = correct.to_dict(account)
        self.assertEqual(merged, served['keys']['media_transport'])
        resolved = {k: n for s in served['bricks']['media_transport']['shortcuts']
                    for k, n in zip(s['keys'], s['names'])}
        self.assertEqual(('nudge_back', 'jump_forward', 'toggle'),
                         (resolved['ArrowLeft'], resolved['ArrowRight'], resolved['KeyP']))
        self.assertNotIn('Space', resolved)
        v8 = MiniRacer()
        v8.eval(KeyDispatcherTest.SETUP + _js('common/js/wama-keys.js'))
        self.assertEqual(resolved, BrickShortcutsTest._keyboard_table(v8, 'media_transport', merged))
        # Without an account the page is the one it registers.
        self.assertEqual(correct.keymap(), correct.keymap_for(None))
        self.assertEqual({'a': [], 'b': ['K']}, merge_overrides({'a': ['K']}, {'b': ['K']}))

    def test_a_key_two_bricks_of_one_page_take_is_said_on_both_and_fixed_by_another_key(self):
        """Fabien, 2026-11-15 : « il faut détecter les conflits de raccourcis et permettre de les
        corriger ». The account gives the transport the key of the timeline's tool (C) : kept —
        the clash exists only where both bricks sit — but SAID, on both bricks, with the page ;
        another key lifts it. The rule is the registry's (`key_conflicts`), the one every
        registered surface is held by."""
        from wama.common.utils.user_keys import account_conflicts, key_settings
        self.assertEqual({}, account_conflicts({}))
        self.assertEqual({}, account_conflicts({'media_transport': {'toggle': ['KeyP']}}))
        body = self._post('media_transport', {'toggle': ['KeyC']}).json()
        self.assertTrue(body['ok'], 'a clash is said, the key is kept')
        said = {k['key']: k['conflict'] for row in body['rows'] for k in row['keys']}
        self.assertIn(BRICKS['media_timeline'].name, said['KeyC'])
        self.assertIn(SURFACES['transcriber.correct'].label, said['KeyC'], 'the page is named')
        self.assertEqual('', said['KeyL'])
        other = {k['key']: k['conflict'] for row in body['bricks']['media_timeline']['rows']
                 for k in row['keys']}
        self.assertIn(BRICKS['media_transport'].name, other['KeyC'], 'said on the other brick too')
        # Either brick lifts it : here the timeline's tool takes another key.
        fixed = self._post('media_timeline', {'boundaries': ['KeyB']})
        self.assertEqual(200, fixed.status_code)
        after = key_settings(self.user)
        self.assertEqual([], [k['key'] for brick in after.values() for row in brick['rows']
                              for k in row['keys'] if k['conflict']])
        # Page bricks share every app page : a clash between two of them is seen too.
        clash = account_conflicts({'queue': {'select_all': ['ArrowDown']}})
        self.assertIn('ArrowDown', clash.get('queue', {}))
        self.assertIn("pages d'application", clash['queue']['ArrowDown'][0])
        module = _static('common/js/wama-key-settings.js')
        self.assertIn('is-conflict', module)
        self.assertIn('config.bricks = res.data.bricks;', module)

    def test_the_page_module_sends_the_keystroke_as_the_registry_names_it(self):
        """`wama-key-settings.js`, played in V8 with the real common keyboard : a click on a key,
        then the keystroke — taken by a LAYER of the common keyboard (no brick acts meanwhile),
        named by its place (`Shift+KeyP`) or by the character it yields (`;`), sent with what
        the account had already set ; Escape gives up ; the row is drawn again from the answer."""
        import json

        from py_mini_racer import MiniRacer

        from wama.common.utils.user_keys import key_rows
        config = {'url': '/keys/', 'bricks': {'media_transport': {
            'rows': key_rows('media_transport'), 'keys': {'stop': ['KeyS']}}}}
        v8 = MiniRacer()
        v8.eval('''
            var listeners = {}, sent = [], toasts = [], row = {innerHTML: '',
                getAttribute: function () { return 'media_transport'; }};
            var source = {textContent: %s};
            var document = {
                addEventListener: function (k, fn) { (listeners[k] = listeners[k] || []).push(fn); },
                removeEventListener: function () {},
                getElementById: function (id) { return id === 'wama-key-settings' ? source : null; },
                querySelector: function (s) { return s.indexOf('data-key-settings') >= 0 ? row : null; },
                activeElement: null};
            var window = {document: document}; globalThis.document = document;
            window.WamaApp = {escapeHtml: function (t) { return String(t); }, csrfToken: function () { return 't'; },
                toast: function (m, kind) { toasts.push(kind); },
                csrfFetch: function (url, token, o) { sent.push(JSON.parse(o.body));
                    var chain = {then: function () { return chain; }, catch: function () { return chain; }};
                    return chain; }};
            function key(name) {
                return {classList: {add: function () {}, remove: function () {}}, textContent: '',
                        getAttribute: function () { return name; },
                        closest: function (s) { return s === '.wama-key-edit' ? this
                            : (s === '[data-key-settings]' ? row : null); }};
            }
            function click(el) { listeners.click.forEach(function (fn) {
                fn({target: el, stopPropagation: function () {}}); }); }
            function press(code, k, mods) {
                var e = Object.assign({code: code, key: k, target: {}, defaultPrevented: false,
                    preventDefault: function () { e.defaultPrevented = true; }}, mods || {});
                listeners.keydown.forEach(function (fn) { fn(e); });
                return e.defaultPrevented;
            }
        ''' % json.dumps(json.dumps(config)))
        v8.eval(_static('common/js/wama-keys.js'))
        v8.eval(_static('common/js/wama-key-settings.js'))
        out = json.loads(v8.eval('''(function () {
            var r = {drawn: row.innerHTML.indexOf('data-name="toggle"') >= 0, idle: press('KeyP', 'p')};
            click(key('toggle'));
            r.modifier = press('ShiftLeft', 'Shift', {shiftKey: true});
            r.taken = press('KeyP', 'P', {shiftKey: true});
            click(key('jump_back')); press('Semicolon', ';');
            click(key('stop')); r.escape = press('Escape', 'Escape');
            r.after = press('KeyP', 'p');
            r.sent = sent;
            return JSON.stringify(r);
        })()'''))
        self.assertTrue(out['drawn'], 'each named key is drawn as a control')
        self.assertFalse(out['idle'], 'nothing waits : the keystroke is left alone')
        self.assertFalse(out['modifier'], 'a modifier alone is not a key')
        self.assertTrue(out['taken'])
        self.assertFalse(out['after'])
        self.assertEqual([{'brick': 'media_transport', 'keys': {'stop': ['KeyS'], 'toggle': ['Shift+KeyP']}},
                          {'brick': 'media_transport', 'keys': {'stop': ['KeyS'], 'jump_back': [';']}}],
                         out['sent'], 'Escape sends nothing')
        self.assertTrue(out['escape'])

    def test_every_page_gets_the_keys_of_its_page_bricks_and_a_surface_gives_its_own(self):
        from django.test import RequestFactory

        from wama.common.utils.user_keys import SETTING, SETTINGS_APP, save_user_keys, user_keymap
        from wama.common.utils.user_settings import save_user_app_settings
        from wama.common.utils.volet import page_controls_config
        self.assertEqual([], save_user_keys(self.user, 'queue', {'select_all': ['Ctrl+e']}))
        self.assertEqual([], save_user_keys(self.user, 'media_transport', {'toggle': ['KeyP']}))
        request = RequestFactory().get('/')
        request.user = self.user
        config = page_controls_config(request)
        self.assertEqual({'queue': {'select_all': ['Ctrl+e']}}, config['keys'],
                         'page bricks only : a surface merges its own with its preset')
        queue = next(g for g in config['shortcuts'] if g['brick'] == 'queue')
        self.assertIn('Ctrl+E', [i['label'] for i in queue['items']], 'the help says the resolved keys')
        request.user = self.other
        self.assertNotIn('keys', page_controls_config(request))
        self.assertIn('global.WamaKeys.remap(brick, config.keys[brick]);',
                      _static('common/js/wama-page-controls.js'))
        # An entry that no longer applies (an action the brick stopped naming, a brick gone) is
        # ignored, never served.
        save_user_app_settings(self.user, SETTINGS_APP, {SETTING: {
            'queue': {'select_all': ['Ctrl+e'], 'gone': ['KeyG']}, 'no_such_brick': {'x': ['KeyX']}}})
        self.assertEqual({'queue': {'select_all': ['Ctrl+e']}}, user_keymap(self.user))

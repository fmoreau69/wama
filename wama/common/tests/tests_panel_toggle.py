"""Repli des volets latéraux par leur FRONTIÈRE — brique `WamaPanels` (2026-10-10).

Ce qui est gardé, dans l'ordre où cela peut casser :

1. **La brique est montée partout** : `base.html` charge sa feuille et son script, et applique
   l'état retenu AVANT le premier rendu (sinon la page s'ouvre volets dépliés puis se replie).
2. **Une seule source pour la place des volets** : les marges `--wama-*-gutter`. Toute règle qui
   POSITIONNE quelque chose d'après la largeur brute d'un volet (`--fm-sidebar-width`,
   `--fm-right-panel-width`) ne verrait pas un volet replié et laisserait une bande vide. Le
   contrôle est générique — il balaie le dépôt — parce que ces règles naissent dans les pages
   (éditeur du transcriber, cam_analyzer), pas dans la brique.
3. **Le mode simplifié s'applique sur place** : il ne renvoie plus à l'accueil sans le dire.
4. **Deux contextes de largeur** (2026-10-12, ROADMAP §27 étape 2) : sous le point de rupture
   `lg` de Bootstrap, volets repliés d'office, un seul ouvert, mémoire à part — le choix fait en
   grand n'est jamais écrasé. Joué dans V8 avec un faux DOM : le script d'amorce de base.html
   PUIS la brique, sur la même mémoire.
5. **La barre du haut et le pied ne se chevauchent plus** : grilles `1fr auto 1fr`, libellés
   qui s'effacent derrière leur icône quand la barre manque de place. Le rendu se mesure au
   navigateur (scénario nocturne `common.layout.tablet`) ; ici, la forme qui le permet.
"""
import importlib.util
import re
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase

BASE = Path(settings.BASE_DIR)
COMMON = BASE / 'wama' / 'common' / 'static' / 'common'
HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None

#: Une règle qui place un élément d'après la largeur BRUTE d'un volet : `left|right|margin-*`
#: suivi directement de la variable de largeur. Les définitions de la variable et la largeur des
#: volets eux-mêmes (`width: var(--fm-…)`) ne sont pas des positionnements.
RAW_PLACEMENT = re.compile(
    r'(?:\bleft|\bright|margin-left|margin-right)\s*:\s*var\(\s*--fm-(?:sidebar-width|right-panel-width)')


def _read(path):
    return Path(path).read_text(encoding='utf-8')


def _sources():
    """Gabarits et feuilles de style du dépôt — hors copies servies, vendors et jumelles du bac
    à sable (`<app>_NN`), qui sont des copies générées qu'on ne modifie jamais à la main."""
    for root in ('wama', 'wama_lab', 'wama_data'):
        for path in (BASE / root).rglob('*'):
            if path.suffix not in ('.css', '.html') or not path.is_file():
                continue
            parts = path.relative_to(BASE).parts
            if 'vendors' in parts or any(re.search(r'_\d+$', p) for p in parts):
                continue
            yield path


class PanelToggleMountedTest(TestCase):

    def _render(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        return render_to_string('base.html', {}, request=request)

    def test_base_loads_the_sheet_and_the_script(self):
        page = self._render()
        self.assertIn('common/css/wama-panel-toggle.css', page)
        self.assertIn('common/js/wama-panel-toggle.js', page)

    def test_the_remembered_state_is_applied_before_the_first_paint(self):
        page = self._render()
        head_script = _boot_script(page)
        self.assertLess(page.index('window.WamaPanelsContext'), page.index('class="top_nav"'),
                        'the state must be applied before the first paint, at the top of <body>')
        # La clé et la classe se composent du côté : 'wama_panel_' + side, 'wama-' + side + '-collapsed'.
        self.assertIn("'wama_panel_' + side", head_script, 'the remembered state must be read at the top of <body>')
        self.assertIn("'wama-' + side + '-collapsed'", head_script)
        self.assertIn('panels.apply();', head_script)
        # Le seuil est celui de Bootstrap, lu dans sa feuille — pas un nombre à nous.
        self.assertIn("--bs-breakpoint-lg", head_script)


def _boot_script(page):
    """Le script d'amorce de base.html, tel que rendu : le bloc `<script>` qui pose
    `WamaPanelsContext`. Repéré par ce nom et non par `<body` — la feuille en ligne de l'en-tête
    écrit « <body> » dans un commentaire, avant la vraie balise."""
    at = page.index('window.WamaPanelsContext')
    return page[page.rindex('<script>', 0, at) + len('<script>'):page.index('</script>', at)]


#: Un faux DOM juste suffisant : classes du <body>, stockage, requête de largeur pilotable.
V8_HARNESS = r"""
var window = globalThis;
var store = {}, classes = {}, mqHandlers = [], narrowNow = false;
var localStorage = { getItem: function (k) { return k in store ? store[k] : null; },
                     setItem: function (k, v) { store[k] = String(v); } };
var classList = {
  contains: function (c) { return !!classes[c]; },
  add: function (c) { classes[c] = true; },
  remove: function (c) { delete classes[c]; },
  toggle: function (c, force) { if (force === undefined) force = !classes[c];
                                if (force) classes[c] = true; else delete classes[c]; return force; } };
function el() { return { dataset: {}, style: { setProperty: function () {} }, setAttribute: function () {},
                         addEventListener: function () {}, querySelector: function () { return {}; } }; }
var document = { readyState: 'complete', documentElement: {}, addEventListener: function () {},
                 body: { classList: classList, appendChild: function () {} },
                 getElementById: function (id) { return (id === 'filemanager-sidebar' || id === 'wama-right-panel') ? {} : null; },
                 createElement: el };
window.matchMedia = function () { return { get matches() { return narrowNow; },
                                           addEventListener: function (t, h) { mqHandlers.push(h); } }; };
function getComputedStyle() { return { getPropertyValue: function () { return '992px'; } }; }
function setTimeout() {}
function Event() {}
function CustomEvent() {}
window.dispatchEvent = function () {};
function state() { return JSON.stringify({ narrow: !!classes['wama-narrow'],
  left: !classes['wama-left-collapsed'], right: !classes['wama-right-collapsed'], store: store }); }
function setWidth(narrow) { narrowNow = narrow; mqHandlers.forEach(function (h) { h(); }); }
"""


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class TwoWidthContextsTest(TestCase):
    """L'amorce de base.html puis la brique, joués dans V8 sur la même mémoire."""

    def _context(self, narrow):
        import json
        from py_mini_racer import MiniRacer
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        boot = _boot_script(render_to_string('base.html', {}, request=request))
        ctx = MiniRacer()
        ctx.eval(V8_HARNESS)
        ctx.eval(f'narrowNow = {"true" if narrow else "false"};')
        ctx.eval(boot)
        ctx.eval(_read(COMMON / 'js' / 'wama-panel-toggle.js'))
        return ctx, (lambda: json.loads(ctx.eval('state()')))

    def test_a_narrow_screen_starts_with_both_panels_collapsed(self):
        _, state = self._context(narrow=True)
        s = state()
        self.assertTrue(s['narrow'])
        self.assertEqual((s['left'], s['right']), (False, False))

    def test_a_wide_screen_keeps_both_panels_open_by_default(self):
        _, state = self._context(narrow=False)
        s = state()
        self.assertFalse(s['narrow'])
        self.assertEqual((s['left'], s['right']), (True, True))

    def test_only_one_panel_is_open_on_a_narrow_screen(self):
        ctx, state = self._context(narrow=True)
        ctx.eval("WamaPanels.setCollapsed('left', false)")
        self.assertEqual((state()['left'], state()['right']), (True, False))
        ctx.eval("WamaPanels.setCollapsed('right', false)")
        s = state()
        self.assertEqual((s['left'], s['right']), (False, True), 'opening one panel collapses the other')
        self.assertEqual(s['store'], {'wama_panel_left_narrow': 'collapsed', 'wama_panel_right_narrow': 'open'})

    def test_each_width_keeps_its_own_memory(self):
        ctx, state = self._context(narrow=True)
        ctx.eval("WamaPanels.setCollapsed('right', false)")      # portrait : le panneau
        ctx.eval('setWidth(false)')                              # rotation en paysage
        s = state()
        self.assertEqual((s['narrow'], s['left'], s['right']), (False, True, True),
                         'the wide default comes back untouched')
        self.assertNotIn('wama_panel_left', s['store'])
        ctx.eval("WamaPanels.setCollapsed('left', true)")        # en grand : on replie l'explorateur
        self.assertEqual((state()['left'], state()['right']), (False, True), 'no exclusivity when wide')
        ctx.eval('setWidth(true)')                               # retour en portrait
        s = state()
        self.assertEqual((s['narrow'], s['left'], s['right']), (True, False, True))
        ctx.eval('setWidth(false)')
        s = state()
        self.assertEqual((s['left'], s['right']), (False, True), 'the wide choice is found again')
        self.assertEqual(s['store']['wama_panel_left'], 'collapsed')


class HeaderAndFooterDoNotOverlapTest(SimpleTestCase):

    def test_the_header_is_a_three_column_grid_with_a_container(self):
        css = _read(BASE / 'wama' / 'filemanager' / 'static' / 'filemanager' / 'css' / 'filemanager.css')
        self.assertIn('container: wama-header / inline-size;', css)
        self.assertIn('grid-template-columns: 1fr auto 1fr;', css)
        logo = css[css.index('.wama-header .wama-logo {'):]
        logo = logo[:logo.index('}')]
        self.assertNotIn('position: absolute', logo, 'an absolute logo covers its neighbours')
        self.assertIn('@container wama-header (max-width:', css)

    def test_the_header_labels_can_step_aside(self):
        header = _read(BASE / 'wama' / 'templates' / 'includes' / 'header.html')
        self.assertGreaterEqual(header.count('wama-header-label'), 4)   # Applications, mode, nom, Login
        self.assertIn('wama-header-name', header)

    def test_the_footer_stats_no_longer_float_over_the_title(self):
        base = _read(BASE / 'wama' / 'templates' / 'base.html')
        stats = base[base.index('id="systemStats"'):]
        self.assertNotIn('position-absolute', stats[:stats.index('>')])
        self.assertIn('wama-footer-row', base)
        css = _read(BASE / 'wama' / 'filemanager' / 'static' / 'filemanager' / 'css' / 'filemanager.css')
        self.assertIn('grid-template-columns: 1fr minmax(0, auto) 1fr;', css)

    def test_the_layout_is_measured_every_night(self):
        from wama.common.services import nightly_tests
        self.assertIn('common.layout.tablet', {s.id for s in nightly_tests.REGISTRY})


class OneSourceForPanelRoomTest(SimpleTestCase):

    def test_the_gutters_drop_to_zero_whenever_a_panel_leaves_the_screen(self):
        css = _read(COMMON / 'css' / 'wama-panel-toggle.css')
        self.assertIn('body.wama-left-collapsed { --wama-left-gutter: 0px; }', css)
        self.assertRegex(css, r'body\.wama-right-collapsed,\s*body\.wama-sans-volet \{ --wama-right-gutter: 0px; \}')
        self.assertIn('body.wama-simple { --wama-left-gutter: 0px; --wama-right-gutter: 0px; }', css)

    def test_the_central_area_and_the_header_read_the_gutters(self):
        css = _read(BASE / 'wama' / 'filemanager' / 'static' / 'filemanager' / 'css' / 'filemanager.css')
        self.assertIn('margin-left: var(--wama-left-gutter, var(--fm-sidebar-width)) !important;', css)
        self.assertIn('margin-right: var(--wama-right-gutter, var(--fm-right-panel-width)) !important;', css)
        self.assertIn('left: var(--wama-left-gutter, var(--fm-sidebar-width)) !important;', css)

    def test_nothing_is_placed_after_the_raw_width_of_a_panel(self):
        offenders = []
        for path in _sources():
            for n, line in enumerate(_read(path).splitlines(), 1):
                if RAW_PLACEMENT.search(line):
                    offenders.append(f'{path.relative_to(BASE)}:{n}: {line.strip()[:90]}')
        self.assertEqual(offenders, [], 'a collapsed panel would leave an empty band — place '
                                        'with var(--wama-left-gutter) / var(--wama-right-gutter):\n'
                                        + '\n'.join(offenders))

    def test_the_guard_sees_a_raw_placement(self):
        # Contre-épreuve du motif : la forme d'avant le 2026-10-10 est bien reconnue.
        self.assertTrue(RAW_PLACEMENT.search('left: var(--fm-sidebar-width, 280px);'))
        self.assertTrue(RAW_PLACEMENT.search('margin-right: var(--fm-right-panel-width) !important;'))
        self.assertFalse(RAW_PLACEMENT.search('left: var(--wama-left-gutter, var(--fm-sidebar-width));'))
        self.assertFalse(RAW_PLACEMENT.search('width: var(--fm-sidebar-width);'))


class PanelEdgeBehaviourTest(SimpleTestCase):

    def test_touch_screens_see_the_handle_without_hovering(self):
        css = _read(COMMON / 'css' / 'wama-panel-toggle.css')
        coarse = css[css.index('@media (pointer: coarse)'):]
        self.assertIn('.wama-panel-edge-pill { opacity: .8;', coarse)

    def test_simple_mode_hides_the_edges_with_the_panels(self):
        self.assertIn('body.wama-simple .wama-panel-edge { display: none; }',
                      _read(COMMON / 'css' / 'wama-panel-toggle.css'))

    def test_the_avatar_is_not_loaded_in_a_collapsed_right_panel(self):
        js = _read(COMMON / 'js' / 'wama-avatar-panel.js')
        self.assertIn("c.contains('wama-right-collapsed')", js)
        self.assertIn('!panelHidden()', js)

    def test_the_settings_hint_reopens_a_collapsed_right_panel(self):
        # « Réglages : volet de droite » pointerait vers un volet replié : la phrase le rouvre.
        hint = _read(BASE / 'wama' / 'common' / 'templates' / 'common' / '_settings_hint.html')
        self.assertIn('data-wama-panel-open="right"', hint)
        css = _read(COMMON / 'css' / 'wama-inspector.css')
        self.assertIn('body.wama-right-collapsed:not(.wama-simple) .wama-settings-hint--collapsed { display: inline; }', css)
        js = _read(COMMON / 'js' / 'wama-panel-toggle.js')
        self.assertIn("closest('[data-wama-panel-open]')", js)

    def test_the_page_is_told_after_the_animation(self):
        js = _read(COMMON / 'js' / 'wama-panel-toggle.js')
        self.assertIn("global.dispatchEvent(new Event('resize'));", js)
        self.assertIn("new CustomEvent('wama:panels'", js)

    def test_the_served_copies_are_the_sources(self):
        for rel in ('css/wama-panel-toggle.css', 'js/wama-panel-toggle.js', 'js/wama-avatar-panel.js',
                    'css/wama-inspector.css'):
            self.assertEqual(_read(COMMON / rel), _read(BASE / 'staticfiles' / 'common' / rel),
                             f'staticfiles/common/{rel} differs from its source — resync')
        rel = Path('filemanager') / 'css' / 'filemanager.css'
        self.assertEqual(_read(BASE / 'wama' / 'filemanager' / 'static' / rel), _read(BASE / 'staticfiles' / rel),
                         f'staticfiles/{rel} differs from its source — resync')

    @skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
    def test_the_script_parses_under_v8(self):
        from py_mini_racer import MiniRacer
        MiniRacer().eval('(function(){' + _read(COMMON / 'js' / 'wama-panel-toggle.js') + '\n})')


class SimpleModeStaysInPlaceTest(SimpleTestCase):

    def test_switching_to_simple_mode_no_longer_sends_home(self):
        base = _read(BASE / 'wama' / 'templates' / 'base.html')
        toggle = base[base.index('window.wamaToggleMode = function'):base.index('function _updateBtn')]
        self.assertNotIn('location.href', toggle, 'the mode applies where the user is')
        self.assertIn('window.wamaSetMode(next);', toggle)

    def test_the_button_says_where_the_simplified_home_is(self):
        header = _read(BASE / 'wama' / 'templates' / 'includes' / 'header.html')
        self.assertIn('le logo WAMA ouvre l’accueil simplifié', header)

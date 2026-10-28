"""Repli des volets latéraux par leur FRONTIÈRE — brique `WamaPanels` (2026-10-10).

Ce qui est gardé, dans l'ordre où cela peut casser :

1. **La brique est montée partout** : `base.html` charge sa feuille et son script, et applique
   l'état retenu AVANT le premier rendu (sinon la page s'ouvre volets dépliés puis se replie).
2. **Une seule source pour la place des volets** : les marges `--wama-*-gutter`. Toute règle qui
   POSITIONNE quelque chose d'après la largeur brute d'un volet (`--fm-sidebar-width`,
   `--fm-right-panel-width`) ne verrait pas un volet replié et laisserait une bande vide. Le
   contrôle est générique — il balaie le dépôt — parce que ces règles naissent dans les pages
   (éditeur du transcriber, cam_analyzer), pas dans la brique.
3. **Le mode simplifié est RETIRÉ** (2026-10-27, décision de Fabien) : le bouton de l'en-tête
   replie les deux volets d'un geste, chacun se rouvre seul, le bouton suit ; un navigateur qui
   l'avait choisi retrouve une fois ses volets repliés ; plus aucune trace du mode dans le code.
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
                     setItem: function (k, v) { store[k] = String(v); },
                     removeItem: function (k) { delete store[k]; } };
// Le bouton des volets de l'en-tête (`[data-wama-panels-switch]`).
var switchBtn = { hidden: false, title: '', attrs: {}, icon: { className: '' }, onclick: null,
                  setAttribute: function (k, v) { this.attrs[k] = v; },
                  querySelector: function () { return this.icon; },
                  addEventListener: function (t, h) { this.onclick = h; } };
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
                 querySelectorAll: function (sel) { return sel === '[data-wama-panels-switch]' ? [switchBtn] : []; },
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

    def _context(self, narrow, before=''):
        import json
        from py_mini_racer import MiniRacer
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        boot = _boot_script(render_to_string('base.html', {}, request=request))
        ctx = MiniRacer()
        ctx.eval(V8_HARNESS)
        ctx.eval(f'narrowNow = {"true" if narrow else "false"};' + before)
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


    # ── Le bouton de l'en-tête (2026-10-27, Fabien : il remplace « Simplifié ») ──────────────
    def _switch(self, ctx):
        import json
        return json.loads(ctx.eval("JSON.stringify({icon: switchBtn.icon.className, "
                                   "pressed: switchBtn.attrs['aria-pressed'], title: switchBtn.title})"))

    def test_the_header_switch_folds_both_then_follows_each_panel(self):
        ctx, state = self._context(narrow=False)
        self.assertEqual('fas fa-table-columns', self._switch(ctx)['icon'], 'both open: the open form')
        ctx.eval('switchBtn.onclick()')
        self.assertEqual((state()['left'], state()['right']), (False, False), 'one gesture folds both')
        self.assertEqual(('fas fa-expand', 'true'), tuple(self._switch(ctx).values())[:2])
        ctx.eval("WamaPanels.setCollapsed('left', false)")      # rouvert seul, par sa frontière
        self.assertEqual('fas fa-expand', self._switch(ctx)['icon'], 'one panel back is not both')
        ctx.eval("WamaPanels.setCollapsed('right', false)")
        self.assertEqual('fas fa-table-columns', self._switch(ctx)['icon'], 'both back: the open form again')
        ctx.eval('switchBtn.onclick()')
        ctx.eval('switchBtn.onclick()')
        self.assertEqual((state()['left'], state()['right']), (True, True), 'folded, then unfolded')

    def test_on_a_narrow_screen_the_switch_opens_the_assistant_panel_only(self):
        ctx, state = self._context(narrow=True)
        self.assertEqual('fas fa-expand', self._switch(ctx)['icon'])
        ctx.eval('switchBtn.onclick()')
        self.assertEqual((state()['left'], state()['right']), (False, True), 'one panel at a time')
        ctx.eval('switchBtn.onclick()')
        self.assertEqual((state()['left'], state()['right']), (False, False))

    def test_a_browser_left_in_simplified_mode_finds_its_panels_folded_once(self):
        ctx, state = self._context(narrow=False, before="store['wama_ui_mode'] = 'simple';")
        s = state()
        self.assertEqual((s['left'], s['right']), (False, False))
        self.assertNotIn('wama_ui_mode', s['store'], 'translated once, then forgotten')
        ctx.eval("WamaPanels.setCollapsed('left', false)")
        self.assertTrue(state()['left'], 'a plain fold: each panel reopens on its own')


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
        # 2026-10-28 : `container-fluid` (défilement + 20 px de marge basse pour TOUTE `.container-fluid`,
        # `app_modern.css`) faisait défiler le pied pour quelques pixels.
        row = base[base.index('wama-footer-row') - 80:base.index('wama-footer-row')]
        self.assertNotIn('container-fluid', row[row.rindex('<div'):], 'the footer row scrolls')
        css = _read(BASE / 'wama' / 'filemanager' / 'static' / 'filemanager' / 'css' / 'filemanager.css')
        self.assertIn('grid-template-columns: 1fr minmax(0, auto) 1fr;', css)
        # Téléphone (2026-10-28) : à 390 px, « Disque » sortait de 66 px — le titre laisse sa place.
        phone = css[css.index('@media (max-width: 575.98px)', css.index('.wama-footer-text')):]
        self.assertIn('.wama-footer-row { grid-template-columns: 0 0 1fr;', phone[:phone.index('}\n}')])

    def test_the_layout_is_measured_every_night(self):
        from wama.common.services import nightly_tests
        self.assertIn('common.layout.tablet', {s.id for s in nightly_tests.REGISTRY})


class OneSourceForPanelRoomTest(SimpleTestCase):

    def test_the_gutters_drop_to_zero_whenever_a_panel_leaves_the_screen(self):
        css = _read(COMMON / 'css' / 'wama-panel-toggle.css')
        self.assertIn('body.wama-left-collapsed { --wama-left-gutter: 0px; }', css)
        self.assertRegex(css, r'body\.wama-right-collapsed,\s*body\.wama-sans-volet \{ --wama-right-gutter: 0px; \}')

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

    def test_the_avatar_is_not_loaded_in_a_collapsed_right_panel(self):
        js = _read(COMMON / 'js' / 'wama-avatar-panel.js')
        self.assertIn("classList.contains('wama-right-collapsed')", js)
        self.assertIn('!panelHidden()', js)

    def test_the_settings_hint_reopens_a_collapsed_right_panel(self):
        # « Réglages : volet de droite » pointerait vers un volet replié : la phrase le rouvre.
        hint = _read(BASE / 'wama' / 'common' / 'templates' / 'common' / '_settings_hint.html')
        self.assertIn('data-wama-panel-open="right"', hint)
        css = _read(COMMON / 'css' / 'wama-inspector.css')
        self.assertIn('body.wama-right-collapsed .wama-settings-hint--collapsed { display: inline; }', css)
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


class SimplifiedModeRetiredTest(SimpleTestCase):
    """Le mode simplifié est RETIRÉ (2026-10-27, décision de Fabien) : le bouton des volets, le
    « Joindre » du chat et le repli d'office des volets à largeur étroite portent ses usages. Un
    reste — une règle `wama-simple`, une vue, un champ lu — ferait revivre un second mode."""

    TRACES = re.compile(r'wama-simple|switch_ui_mode|wamaSetMode|wamaToggleMode|homeSimple|\bui_mode\b')

    def test_no_trace_of_the_mode_is_left_in_the_code(self):
        offenders = []
        for root in ('wama', 'wama_lab', 'wama_data'):
            for path in (BASE / root).rglob('*'):
                if path.suffix not in ('.py', '.js', '.css', '.html') or not path.is_file():
                    continue
                parts = path.relative_to(BASE).parts
                if ({'vendors', 'migrations', 'tests'} & set(parts)
                        or any(re.search(r'_\d+$', p) for p in parts) or path.name.startswith('tests')):
                    continue
                for n, line in enumerate(_read(path).splitlines(), 1):
                    if self.TRACES.search(line):
                        offenders.append(f'{path.relative_to(BASE)}:{n}: {line.strip()[:90]}')
        self.assertEqual([], offenders)

    def test_the_header_carries_the_panels_switch(self):
        header = _read(BASE / 'wama' / 'templates' / 'includes' / 'header.html')
        self.assertIn('data-wama-panels-switch', header)
        self.assertNotIn('uiModeSwitchBtn', header)
        js = _read(COMMON / 'js' / 'wama-panel-toggle.js')
        self.assertIn("btn.addEventListener('click', function () { setAll(allOpen()); });", js)

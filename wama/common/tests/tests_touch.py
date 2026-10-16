"""WAMA au DOIGT — règle commune des écrans tactiles, `wama-touch.css` (ROADMAP §27, étape 1).

Ce qui est gardé, dans l'ordre où cela peut casser :

1. **La règle est montée partout, en dernier** : `base.html` la charge APRÈS les feuilles
   communes — ses planchers priment au doigt sur les tailles compactes des briques.
2. **Un seul critère tactile** : `(pointer: coarse)`. Un `(hover: none)` ou un `any-pointer`
   ailleurs ferait basculer une partie de l'interface et pas l'autre sur un même appareil.
3. **Rien ne se révèle plus au seul survol par une règle locale** : une action qui n'apparaît
   qu'au survol de son hôte passe par la convention `.wama-reveal-host` / `.wama-reveal`, qui la
   montre aussi au clavier et toujours au doigt. Le contrôle est générique — il balaie le dépôt —
   parce que ces règles naissent dans les pages (médiathèque, aperçu), pas dans la brique.
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
TOUCH_CSS = COMMON / 'css' / 'wama-touch.css'
HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None

#: Ce qu'une règle de survol RÉVÈLE : la visibilité de l'élément.
REVEAL_DECL = re.compile(r'\b(?:opacity|visibility|display)\s*:', re.I)
#: Les autres critères tactiles, refusés : un seul critère pour tout WAMA.
OTHER_TOUCH_QUERIES = re.compile(r'\(\s*(?:hover\s*:\s*none|any-pointer\s*:|any-hover\s*:)', re.I)


def _read(path):
    return Path(path).read_text(encoding='utf-8')


def _sources(suffixes=('.css', '.html')):
    """Sources du dépôt — hors copies servies, vendors, archives et jumelles du bac à sable
    (`<app>_NN`), qui sont des copies générées qu'on ne modifie jamais à la main."""
    for root in ('wama', 'wama_lab', 'wama_data'):
        for path in (BASE / root).rglob('*'):
            if path.suffix not in suffixes or not path.is_file():
                continue
            parts = path.relative_to(BASE).parts
            if ('vendors' in parts or 'archive' in parts
                    or any(re.search(r'_\d+$', p) for p in parts) or path.name.endswith('.min.css')):
                continue
            yield path


def _rules(text, is_html):
    """(sélecteur, déclarations) de chaque règle — les blocs `@media` sont aplatis."""
    chunks = re.findall(r'<style[^>]*>(.*?)</style>', text, re.S) if is_html else [text]
    for chunk in chunks:
        chunk = re.sub(r'/\*.*?\*/', '', chunk, flags=re.S)
        for m in re.finditer(r'([^{}@;]+)\{([^{}]*)\}', chunk):
            yield m.group(1).strip(), m.group(2)


def hover_reveals(text, is_html=False):
    """Règles qui changent la VISIBILITÉ d'un AUTRE élément au survol (`hôte:hover cible`).

    Un pseudo-élément (`:hover::after`) n'est pas visé : c'est un décor de l'élément survolé
    lui-même, pas une action qu'on ne verrait pas.
    """
    found = []
    for selector, declarations in _rules(text, is_html):
        if ':hover' not in selector or not REVEAL_DECL.search(declarations):
            continue
        for one in selector.split(','):
            if ':hover' not in one:
                continue
            after = one.split(':hover')[-1]
            if after.startswith('::'):
                continue
            # `hôte:hover:not(.x) cible` : les pseudo-classes collées au survol ne sont pas la cible.
            after = re.sub(r'^(?::(?!:)[\w-]+(?:\([^)]*\))?)+', '', after)
            if after.strip() and not after.startswith('::'):
                found.append(one.strip())
    return found


class TouchRuleMountedTest(TestCase):

    def test_base_loads_the_touch_sheet_after_the_common_sheets(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        page = render_to_string('base.html', {}, request=request)
        self.assertIn('common/css/wama-touch.css', page)
        sheets = re.findall(r'href="[^"]*?/((?:common|filemanager)/css/[\w.-]+\.css)', page)
        self.assertEqual(sheets[-1], 'common/css/wama-touch.css',
                         f'wama-touch.css must come last among the common sheets, got {sheets[-3:]}')


class OneTouchCriterionTest(SimpleTestCase):

    def test_the_touch_sheet_sets_both_sizes(self):
        css = _read(TOUCH_CSS)
        self.assertIn('--wama-touch-target: 44px;', css)
        self.assertIn('--wama-touch-min: 24px;', css)
        coarse = css[css.index('@media (pointer: coarse)'):]
        for selector in ('.btn,', '.nav-link,', '.dropdown-item,', '[role="button"],', 'summary {'):
            self.assertIn(selector, coarse)
        self.assertIn('min-height: var(--wama-touch-target);', coarse)

    def test_no_other_touch_query_anywhere(self):
        offenders = []
        for path in _sources(('.css', '.html', '.js')):
            for n, line in enumerate(_read(path).splitlines(), 1):
                if OTHER_TOUCH_QUERIES.search(line):
                    offenders.append(f'{path.relative_to(BASE)}:{n}: {line.strip()[:90]}')
        self.assertEqual(offenders, [], 'the touch criterion of WAMA is (pointer: coarse):\n'
                                        + '\n'.join(offenders))

    def test_the_explorer_takes_the_large_jstree_variant_on_touch(self):
        js = _read(BASE / 'wama' / 'filemanager' / 'static' / 'filemanager' / 'js' / 'filemanager.js')
        self.assertIn("matchMedia('(pointer: coarse)').matches) ? 'large' : false", js)


class NothingRevealedOnHoverAloneTest(SimpleTestCase):

    def test_no_local_rule_reveals_an_element_on_hover(self):
        offenders = []
        for path in _sources():
            if path == TOUCH_CSS:
                continue
            for selector in hover_reveals(_read(path), path.suffix == '.html'):
                offenders.append(f'{path.relative_to(BASE)}: {selector[:100]}')
        self.assertEqual(offenders, [], 'an action shown on hover alone does not exist on a touch '
                                        'screen — use .wama-reveal-host / .wama-reveal:\n'
                                        + '\n'.join(offenders))

    def test_the_guard_sees_a_local_reveal(self):
        # Contre-épreuve : les formes d'avant le 2026-10-12 sont reconnues, les décors ne le sont pas.
        self.assertTrue(hover_reveals('.asset-card:hover .card-actions-overlay { opacity: 1; }'))
        self.assertTrue(hover_reveals('<style>.sr-card:hover .sr-import-btn { opacity: 1; }</style>', True))
        self.assertTrue(hover_reveals('@media (min-width: 1px) { .a:hover > .b { display: block; } }'))
        self.assertTrue(hover_reveals('.a:hover:not(.off) .b { visibility: visible; }'))
        self.assertFalse(hover_reveals('.asset-card:hover { border-color: #4a4a7a; }'))
        self.assertFalse(hover_reveals('.x .header:hover::after { opacity: .85; }'))
        self.assertFalse(hover_reveals('.drop-zone:hover i { transform: scale(1.1); }'))

    def test_the_convention_shows_on_hover_keyboard_and_touch(self):
        css = _read(TOUCH_CSS)
        self.assertIn('.wama-reveal-host:hover .wama-reveal', css)
        self.assertIn('.wama-reveal-host:has(:focus-visible) .wama-reveal', css)
        coarse = css[css.index('@media (pointer: coarse)'):]
        self.assertIn('.wama-reveal { opacity: 1; }', coarse)

    def test_what_gives_way_to_a_revealed_action_hides_with_the_same_triggers(self):
        # `.wama-reveal-hide`, l'inverse : effacé au survol et au clavier, jamais montré au doigt.
        css = _read(TOUCH_CSS)
        self.assertIn('.wama-reveal-host:hover .wama-reveal-hide', css)
        self.assertIn('.wama-reveal-host:has(:focus-visible) .wama-reveal-hide', css)
        coarse = css[css.index('@media (pointer: coarse)'):]
        self.assertIn('.wama-reveal-hide { display: none; }', coarse)

    def test_the_former_hover_sites_adopted_the_convention(self):
        sites = {
            # (le filemanager n'est plus un site : sa copie de l'aperçu — `updatePreviewContent`,
            # morte — est retirée le 2026-10-13, ses fichiers s'ouvrent dans la visionneuse commune)
            COMMON / 'js' / 'media-preview.js': ("'preview-image-wrapper wama-reveal-host'",
                                                 "'preview-fullscreen-btn wama-reveal'"),
            BASE / 'wama' / 'media_library' / 'static' / 'media_library' / 'js' / 'media-library.js': (
                'asset-card wama-reveal-host', 'btn-group-actions wama-reveal',
                "'sr-card wama-reveal-host'", 'sr-import-btn wama-reveal'),
            COMMON / 'js' / 'wama-panel-toggle.js': ("'wama-panel-edge wama-reveal-host'",
                                                     'wama-panel-edge-pill wama-reveal'),
            # Panneau de la cloche (2026-10-13), porté sur la convention le 2026-10-16 : il écrivait
            # ses propres `:hover` et un second critère tactile, `(hover: none)`.
            COMMON / 'js' / 'wama-notifications.js': (' wama-reveal-host"', 'wn-go wama-reveal',
                                                      'wn-dot wama-reveal-hide', 'wn-tools wama-reveal'),
        }
        for path, needles in sites.items():
            src = _read(path)
            for needle in needles:
                self.assertIn(needle, src, f'{path.name}: {needle}')


class TouchServedCopiesTest(SimpleTestCase):

    TOUCHED = (
        'common/css/wama-touch.css', 'common/css/media-preview.css', 'common/css/wama-panel-toggle.css',
        'common/css/wama-inspector.css', 'common/css/wama-card-v3.css', 'common/css/app_modern.css',
        'common/css/wama-input-slots.css', 'common/css/wama-assistant-panel.css',
        'common/js/media-preview.js', 'common/js/wama-panel-toggle.js',
        'filemanager/css/filemanager.css', 'filemanager/js/filemanager.js',
        'media_library/js/media-library.js', 'studio/css/wama-studio.css',
        'common/css/wama-notifications.css', 'common/js/wama-notifications.js',
    )

    def test_the_served_copies_are_the_sources(self):
        for rel in self.TOUCHED:
            app = rel.split('/', 1)[0]
            source = BASE / 'wama' / app / 'static' / rel
            self.assertEqual(_read(source), _read(BASE / 'staticfiles' / rel),
                             f'staticfiles/{rel} differs from its source — resync')

    @skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
    def test_the_touched_scripts_parse_under_v8(self):
        from py_mini_racer import MiniRacer
        for rel in self.TOUCHED:
            if rel.endswith('.js'):
                app = rel.split('/', 1)[0]
                with self.subTest(script=rel):
                    MiniRacer().eval('(function(){' + _read(BASE / 'wama' / app / 'static' / rel) + '\n})')

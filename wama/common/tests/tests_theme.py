"""THÈMES — le socle du chantier ouvert le 2026-10-17 (demande de Fabien : plusieurs thèmes ou
modes, « sombre / clair / UGE / etc »). Ce qui le tient :
  • la DÉCLARATION (`common/themes.py`) et ses lecteurs : la page, le scénario de contraste, le
    registre ;
  • les TOKENS (`common/css/wama-theme.css`) : chaque thème déclaré les définit TOUS, et aucun
    token lu n'est inconnu (une faute de frappe dans `var(--wama-…)` rend une couleur par défaut
    du navigateur — le noir — sans que rien ne casse) ;
  • le BUDGET des couleurs écrites en dur, qui ne peut que DESCENDRE : le chantier des thèmes est
    d'abord un chantier de tokens, et un ajout en dur est une couleur qu'aucun thème ne pourra
    changer. Motif de `tests_identifier_language` : le budget égale la mesure, une marge serait
    une autorisation d'en ajouter."""
import re
from pathlib import Path

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase

ROOT = Path(settings.BASE_DIR)
THEME_CSS = ROOT / 'wama' / 'common' / 'static' / 'common' / 'css' / 'wama-theme.css'
BASE_HTML = ROOT / 'wama' / 'templates' / 'base.html'

#: Une couleur ÉCRITE : hexadécimale, ou fonction de couleur dont les canaux sont des nombres.
#: `rgba(var(--bs-primary-rgb), .25)` lit un token : ce n'en est pas une (affûté le 2026-10-18).
COLOUR = re.compile(r'#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\((?!\s*var\()')
#: Dans un gabarit, une entité (`&#123;`) ou une ancre (`href="#…"`) n'est pas une couleur.
NOT_COLOUR_HTML = re.compile(r'&#\w+;|href="#[^"]*"')
#: Une valeur CITÉE dans un commentaire ne peint rien (affûté le 2026-10-18).
COMMENT_CSS = re.compile(r'/\*.*?\*/', re.S)
COMMENT_HTML = re.compile(r'<!--.*?-->|\{#.*?#\}|\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', re.S)
TWIN = re.compile(r'^wama/[a-z_]+_\d\d/')

#: Hors du budget, chacun avec sa raison.
OUTSIDE = {
    'wama/common/static/common/css/wama-theme.css': "le DOMICILE des valeurs de thème",
    'wama/static/css/bootstrap.min.css': "copie d'une librairie, pas du code de WAMA",
}
#: Familles hors du budget : (motif, raison).
OUTSIDE_FAMILIES = (
    (re.compile(r'^wama/templates/includes/wama_(rapport_[a-z_]+|fiches)\.html$'),
     "documents EXPORTÉS, lus hors de WAMA : leur palette suit `prefers-color-scheme`, pas le thème"),
    (re.compile(r'/docs/'), "maquettes de proposition rangées avec la doc d'une app"),
)

#: Couleurs écrites en dur, par nature de fichier — la mesure du jour, qui ne peut que descendre.
#: Le JS n'y est pas : ses couleurs sont surtout des palettes de DESSIN (canvas, graphes), que le
#: scénario de contraste mesure au rendu.
#: Mesuré le 2026-10-17, card commune portée : 862 dans les feuilles, 883 dans les gabarits
#: (`app_modern.css` en tête, 163) ; 854 le même jour, les huit textes d'alerte fixes retirés
#: (étape 2, `ROADMAP §28`). Le 2026-10-18 : `app_modern.css` porté (155 → 0) et l'instrument
#: AFFÛTÉ dans le même geste (une valeur citée en commentaire, une couleur aux canaux lus d'une
#: variable ne comptent plus) — 688 et 795 ; puis les quinze autres feuilles communes portées
#: (sauf `wama-catalog.css`, en cours ailleurs) — 284 : ce qui reste est aux APPS. Puis les
#: feuilles d'apps (arbre de fichiers, Studio, Cam Analyzer, catalogue, accueil) portées et deux
#: feuilles que plus aucune page ne chargeait retirées (R145, R146) — 54 ; puis la présentation,
#: une fois ses gabarits servis avec les tokens — 0 : AUCUNE feuille de WAMA n'écrit plus de
#: couleur. Ce qui reste est dans les `<style>` des gabarits.
BUDGET = {'.css': 0, '.html': 795}

#: Fichiers PORTÉS sur les tokens : ils restent à zéro.
TOKENISED = tuple(f'wama/common/static/common/css/{name}.css' for name in (
    'wama-card-v3', 'app_modern', 'media-preview', 'wama-assistant-panel', 'wama-card-menu',
    'wama-filter-bar', 'wama-input-slots', 'wama-inspector-autofill', 'wama-inspector',
    'wama-notifications', 'wama-panel-toggle', 'wama-params', 'wama-prompt-chips',
    'wama-queue-dnd', 'wama-share', 'wama-surface', 'wama-touch', 'wama-catalog')) + (
    'wama/filemanager/static/filemanager/css/filemanager.css',
    'wama/studio/static/studio/css/wama-studio.css',
    'wama_lab/cam_analyzer/static/cam_analyzer/css/cam_analyzer.css',
    'wama/static/css/general_index.css',
    'wama/static/presentation/wama-presentation.css')


def _outside(rel):
    return rel in OUTSIDE or any(pattern.search(rel) for pattern, _why in OUTSIDE_FAMILIES)


def _sources(suffixes):
    for base in ('wama', 'wama_lab', 'wama_data'):
        for path in (ROOT / base).rglob('*'):
            rel = path.relative_to(ROOT).as_posix()
            if path.suffix in suffixes and 'vendors' not in path.parts and not TWIN.match(rel):
                yield rel, path.read_text(encoding='utf-8', errors='replace')


def colour_count(rel, text):
    if rel.endswith('.html'):
        text = NOT_COLOUR_HTML.sub('', COMMENT_HTML.sub('', COMMENT_CSS.sub('', text)))
    else:
        text = COMMENT_CSS.sub('', text)
    return len(COLOUR.findall(text))


def measured_budget():
    total = dict.fromkeys(BUDGET, 0)
    for rel, text in _sources(tuple(BUDGET)):
        if not _outside(rel):
            total[Path(rel).suffix] += colour_count(rel, text)
    return total


def unknown_tokens(sources):
    """{token: premier fichier qui le lit} pour chaque `var(--wama-…)` SANS repli qu'aucune
    source ne définit (`--wama-x:` ou `setProperty('--wama-x')`)."""
    defined, read = set(), {}
    for rel, text in sources:
        defined.update(re.findall(r'(--wama-[a-z0-9-]+)\s*:', text))
        defined.update(re.findall(r'setProperty\(\s*[\'"](--wama-[a-z0-9-]+)', text))
        for name in re.findall(r'var\(\s*(--wama-[a-z0-9-]+)\s*\)', text):
            read.setdefault(name, rel)
    return {name: rel for name, rel in read.items() if name not in defined}


SHEET_LINK = re.compile(r"""\{%\s*static(?:_v)?\s+['"]([^'"]+\.css)['"]\s*%\}""")


def sheets_reading_tokens():
    """Les chemins PUBLIÉS des feuilles qui lisent un token de thème."""
    return {path.relative_to(static).as_posix()
            for base in ('wama', 'wama_lab', 'wama_data')
            for static in (ROOT / base).rglob('static') if static.is_dir()
            for path in static.rglob('*.css')
            if 'vendors' not in path.parts and 'var(--wama-' in path.read_text(encoding='utf-8', errors='replace')}


def standalone_pages_missing_tokens(sources, reads=None):
    """Les gabarits AUTONOMES (un document `<html>` qui n'étend rien — un fragment inclus vit dans
    la page qui l'inclut) qui chargent une feuille lisant un token sans avoir chargé
    `common/css/wama-theme.css` avant elle."""
    reads = sheets_reading_tokens() if reads is None else reads
    missing = []
    for rel, text in sources:
        if re.search(r'\{%\s*extends\b', text) or not re.search(r'<html\b', text):
            continue
        linked = SHEET_LINK.findall(COMMENT_HTML.sub('', text))
        readers = [i for i, sheet in enumerate(linked) if sheet in reads]
        theme = linked.index('common/css/wama-theme.css') if 'common/css/wama-theme.css' in linked else None
        if readers and (theme is None or theme > readers[0]):
            missing.append(rel)
    return missing


def theme_blocks(css=None):
    """{clé de thème: {token: valeur}} lus dans wama-theme.css (ou dans `css`) ; le bloc `:root`
    seul est celui du thème par défaut."""
    css = re.sub(r'/\*.*?\*/', '', css if css is not None else THEME_CSS.read_text(encoding='utf-8'),
                 flags=re.S)
    blocks = {}
    for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        tokens = dict(re.findall(r'(--wama-[a-z0-9-]+)\s*:\s*([^;]+);', body))
        for selector in selectors.split(','):
            m = re.fullmatch(r'\s*:root\[data-wama-theme="([a-z0-9_-]+)"\]\s*', selector)
            key = m.group(1) if m else (':root' if selector.strip() == ':root' else None)
            if key:
                blocks.setdefault(key, {}).update(tokens)
    return blocks


class ThemeDeclarationTest(SimpleTestCase):

    def test_the_default_theme_is_declared_and_keys_are_unique(self):
        from wama.common.themes import DEFAULT, THEMES
        keys = [t.key for t in THEMES]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn(DEFAULT, keys)
        for t in THEMES:
            with self.subTest(theme=t.key):
                self.assertIn(t.bootstrap, ('light', 'dark'), 'the native modes of Bootstrap 5.3')
                self.assertTrue(t.label.strip())

    def test_an_unknown_key_falls_back_to_the_default_never_to_nothing(self):
        from wama.common.themes import DEFAULT, theme
        self.assertEqual(DEFAULT, theme('no-such-theme').key)

    def test_every_page_gets_its_theme_from_the_context(self):
        from wama.common.context_processors import theme
        from wama.common.themes import DEFAULT
        request = RequestFactory().get('/')
        self.assertEqual(DEFAULT, theme(request)['theme'].key)
        self.assertIn('wama.common.context_processors.theme',
                      settings.TEMPLATES[0]['OPTIONS']['context_processors'])

    def test_base_sets_the_theme_on_html_and_loads_the_tokens_first(self):
        html = BASE_HTML.read_text(encoding='utf-8')
        self.assertRegex(html, r'<html[^>]*data-wama-theme="\{\{ theme\.key \}\}"[^>]*'
                               r'data-bs-theme="\{\{ theme\.bootstrap \}\}"')
        sheets = re.findall(r"static_v '((?:common|css)/[^']+\.css)'", html)
        self.assertEqual('common/css/wama-theme.css', sheets[0],
                         'the tokens are defined before any sheet that reads them')

    def test_a_standalone_page_loads_the_tokens_before_a_sheet_that_reads_them(self):
        """Une page qui n'étend pas `base.html` (la présentation, l'architecture) ne reçoit pas
        `wama-theme.css` : une feuille qui y lit `var(--wama-…)` y perdrait toutes ses couleurs."""
        self.assertEqual([], standalone_pages_missing_tokens(_sources(('.html',))))

    def test_the_standalone_guard_sees_a_page_without_the_tokens(self):
        """Contre-épreuve sur des sources écrites pour elle."""
        reads = {'presentation/scene.css'}
        page = "<html><link href=\"{% static_v 'presentation/scene.css' %}\"></html>"
        self.assertEqual(['p.html'], standalone_pages_missing_tokens([('p.html', page)], reads))
        fixed = ("<html><link href=\"{% static_v 'common/css/wama-theme.css' %}\">"
                 "<link href=\"{% static_v 'presentation/scene.css' %}\"></html>")
        self.assertEqual([], standalone_pages_missing_tokens([('p.html', fixed)], reads))
        child = "{% extends 'base.html' %}<link href=\"{% static_v 'presentation/scene.css' %}\">"
        fragment = "<link href=\"{% static_v 'presentation/scene.css' %}\"><div></div>"
        self.assertEqual([], standalone_pages_missing_tokens([('c.html', child), ('f.html', fragment)], reads))

    def test_the_registry_lists_the_declared_themes(self):
        from wama.common import registries
        from wama.common.themes import THEMES
        import wama.common.registries_builtin  # noqa: F401 — enregistre les registres
        registry = registries.get('themes')
        self.assertEqual({t.key for t in THEMES}, set(registry.entries()))

    def test_the_contrast_scenario_plays_every_declared_theme(self):
        source = (ROOT / 'wama' / 'common' / 'services' / 'ui_smoke_contrast.py').read_text(encoding='utf-8')
        self.assertIn('for theme in THEMES:', source)
        self.assertIn("page.evaluate(_APPLY_THEME, [theme.key, theme.bootstrap])", source)


class ThemeTokensTest(SimpleTestCase):

    def test_every_declared_theme_defines_every_token(self):
        from wama.common.themes import DEFAULT, THEMES
        blocks = theme_blocks()
        reference = set(blocks.get(':root', {}))
        self.assertTrue(reference, 'the default theme is also set on :root alone')
        self.assertEqual(blocks[':root'], blocks.get(DEFAULT), ':root alone IS the default theme')
        for t in THEMES:
            with self.subTest(theme=t.key):
                self.assertIn(t.key, blocks, 'a declared theme has its block in wama-theme.css')
                self.assertEqual(reference, set(blocks[t.key]), 'a theme redefines EVERY token')

    def test_every_channel_token_is_three_integers(self):
        """`rgba(var(--wama-overlay-rgb), .06)` : un token `-rgb` qui ne vaut pas « r, g, b »
        rend la déclaration invalide, et le voile disparaît sans rien dire."""
        for key, block in theme_blocks().items():
            for name, value in block.items():
                if name.endswith('-rgb'):
                    with self.subTest(theme=key, token=name):
                        self.assertRegex(value.strip(), r'^\d{1,3},\s*\d{1,3},\s*\d{1,3}$')

    def test_no_block_for_an_undeclared_theme(self):
        from wama.common.themes import THEMES
        self.assertEqual(set(), set(theme_blocks()) - {':root'} - {t.key for t in THEMES})

    def test_every_token_read_is_defined_somewhere(self):
        """`var(--wama-labl)` ne casse rien : la couleur retombe sur celle du navigateur. Une
        lecture AVEC repli (`var(--wama-sticky-top, 84px)`) est une surcharge facultative voulue."""
        self.assertEqual({}, unknown_tokens(_sources(('.css', '.html', '.js'))))

    def test_the_guard_sees_a_misspelt_token(self):
        """Contre-épreuve sur des sources écrites pour elle : l'instrument n'est pas aveugle."""
        sources = [('a.css', ':root { --wama-text-label: #fff; }'),
                   ('b.css', '.x { color: var(--wama-text-labl); top: var(--wama-free, 4px); }'),
                   ('c.js', "el.style.setProperty('--wama-set', '1'); el.style.top = 'var(--wama-set)';")]
        self.assertEqual({'--wama-text-labl': 'b.css'}, unknown_tokens(sources))

    def test_the_reading_sees_an_incomplete_theme(self):
        """Contre-épreuve : la lecture des blocs voit un thème qui oublie un token."""
        blocks = theme_blocks(':root, :root[data-wama-theme="dark"] { --wama-a: #fff; --wama-b: #000; }\n'
                              ':root[data-wama-theme="light"] { --wama-a: #000; }')
        self.assertEqual({':root', 'dark', 'light'}, set(blocks))
        self.assertEqual({'--wama-b'}, set(blocks[':root']) - set(blocks['light']))


class ModeFollowingComponentsTest(SimpleTestCase):
    """Étape 2 (2026-10-17) : le sombre repose sur le mode natif de Bootstrap. Un composant dont
    Bootstrap accorde texte et fond au mode ne se repeint pas d'une couleur fixe — vécu : les
    huit variantes d'alerte forçaient le texte du mode clair, 1,9:1 sur leur fond devenu sombre."""

    ALERT_FIXED = re.compile(r'\.alert-(?:info|warning|success|danger|primary|secondary|light|dark)\b'
                             r'[^{}]*\{[^{}]*\bcolor\s*:\s*(?:#|rgba?\(|hsla?\()')

    def test_no_sheet_repaints_an_alert_with_a_fixed_text_colour(self):
        offenders = [rel for rel, text in _sources(('.css',)) if self.ALERT_FIXED.search(text)]
        self.assertEqual([], offenders, 'read `var(--bs-alert-color)`, which follows the mode')

    def test_the_guard_sees_a_fixed_alert_colour(self):
        self.assertTrue(self.ALERT_FIXED.search('.modal-content .alert-warning * { color: #664d03 !important; }'))
        self.assertFalse(self.ALERT_FIXED.search('.alert, .alert * { color: var(--bs-alert-color) !important; }'))


class HardCodedColourBudgetTest(SimpleTestCase):

    def test_the_budget_equals_the_measure(self):
        """Ne JAMAIS relever le budget pour faire passer un ajout : lire un token. Le baisser
        après un portage est le geste normal — et exigé : une marge laisserait entrer une couleur."""
        self.assertEqual(BUDGET, measured_budget())

    def test_tokenised_files_stay_at_zero(self):
        for rel in TOKENISED:
            with self.subTest(file=rel):
                self.assertEqual(0, colour_count(rel, (ROOT / rel).read_text(encoding='utf-8')))

    def test_every_exclusion_still_exists_and_says_why(self):
        for rel, why in OUTSIDE.items():
            with self.subTest(file=rel):
                self.assertTrue((ROOT / rel).exists(), 'an exclusion of a removed file is removed')
                self.assertTrue(why.strip())

    def test_the_count_sees_colours_and_skips_what_is_not_one(self):
        self.assertEqual(3, colour_count('a.css', 'a{color:#fff;background:rgba(0,0,0,.3);border-color:hsl(1,2%,3%)}'))
        self.assertEqual(1, colour_count('a.html', '<a href="#top">&#8594;</a><i style="color:#abc">'))
        self.assertEqual(0, colour_count('a.css', '/* était #6c757d */ a{box-shadow:0 0 0 1px rgba(var(--bs-primary-rgb), .25)}'))
        self.assertEqual(1, colour_count('a.html', '{# #fff #}<!-- #000 --><b style="color:rgb(1,2,3)">'))

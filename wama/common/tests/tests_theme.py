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
from django.test import RequestFactory, SimpleTestCase, TestCase

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
COMMENT_JS = re.compile(r'/\*.*?\*/|(?<![:\'"\\])//[^\n]*', re.S)
#: Dans un gabarit, chaque commentaire se retire DANS SON LANGAGE : un `accept="video/*"` n'ouvre
#: pas un commentaire CSS. Affûté le 2026-10-18 — retiré sur tout le fichier, ce `/*` avalait tout
#: jusqu'au `*/` suivant, et 76 couleurs n'étaient pas comptées (47 dans une seule page).
CODE_ZONE = re.compile(r'<style\b[^>]*>(?P<css>.*?)</style>'
                       r'|\{%\s*block\s+app_styles\s*%\}(?P<blk>.*?)\{%\s*endblock'
                       r'|<script\b[^>]*>(?P<js>.*?)</script>', re.S)
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
#: Les fichiers `.js` n'y sont pas : leurs couleurs sont surtout des palettes de DESSIN (canvas,
#: graphes), que le scénario de contraste mesure au rendu. Celles des `<script>` d'un gabarit, si :
#: elles se lisent par `WamaApp.themeColor('--bs-danger')` (wama-app-base.js).
#: Mesuré le 2026-10-17, card commune portée : 862 dans les feuilles, 883 dans les gabarits
#: (`app_modern.css` en tête, 163) ; 854 le même jour, les huit textes d'alerte fixes retirés
#: (étape 2, `ROADMAP §28`). Le 2026-10-18 : `app_modern.css` porté (155 → 0) et l'instrument
#: AFFÛTÉ dans le même geste (une valeur citée en commentaire, une couleur aux canaux lus d'une
#: variable ne comptent plus) — 688 et 795 ; puis les quinze autres feuilles communes portées
#: (sauf `wama-catalog.css`, en cours ailleurs) — 284 : ce qui reste est aux APPS. Puis les
#: feuilles d'apps (arbre de fichiers, Studio, Cam Analyzer, catalogue, accueil) portées et deux
#: feuilles que plus aucune page ne chargeait retirées (R145, R146) — 54 ; puis la présentation,
#: une fois ses gabarits servis avec les tokens — 0 : AUCUNE feuille de WAMA n'écrit plus de
#: couleur. Puis les gabarits : l'instrument affûté (commentaires retirés par langage, 795 → 871)
#: et, dans le même geste, leurs `<style>`, attributs `style=` et dessins de `<script>` portés — 0.
BUDGET = {'.css': 0, '.html': 0}

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


def _without_template_comments(text):
    """Le gabarit sans ses commentaires, chacun retiré dans son langage."""
    text = COMMENT_HTML.sub('', text)

    def zone(m):
        for name, comment in (('css', COMMENT_CSS), ('blk', COMMENT_CSS), ('js', COMMENT_JS)):
            if m.group(name) is not None:
                start, end = m.start(name) - m.start(), m.end(name) - m.start()
                return m.group(0)[:start] + comment.sub('', m.group(name)) + m.group(0)[end:]
        return m.group(0)
    return CODE_ZONE.sub(zone, text)


def colour_count(rel, text):
    if rel.endswith('.html'):
        text = NOT_COLOUR_HTML.sub('', _without_template_comments(text))
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
        for name in re.findall(r'themeColor\(\s*[\'"](--wama-[a-z0-9-]+)', text):
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


INCLUDE = re.compile(r"""\{%\s*include\s+['"]([^'"]+)['"]""")
TOKEN_READ = re.compile(r'var\(\s*--wama-|themeColor\(')


def _template_text(name):
    """Le texte d'un gabarit nommé dans un `{% include %}` (dossiers `templates/` de WAMA), ou ''."""
    for base in ('wama', 'wama_lab', 'wama_data'):
        for folder in (ROOT / base).rglob('templates'):
            path = folder / name
            if path.is_file():
                return path.read_text(encoding='utf-8', errors='replace')
    return ''


def standalone_pages_missing_tokens(sources, reads=None, included=None):
    """Les gabarits AUTONOMES (un document `<html>` qui n'étend rien — un fragment inclus vit dans
    la page qui l'inclut) qui lisent un token — par une feuille qu'ils chargent, par leurs propres
    styles ou scripts, ou par un gabarit qu'ils incluent — sans avoir chargé
    `common/css/wama-theme.css` AVANT la première lecture."""
    reads = sheets_reading_tokens() if reads is None else reads
    included = _template_text if included is None else included
    missing = []
    for rel, text in sources:
        if re.search(r'\{%\s*extends\b', text) or not re.search(r'<html\b', text):
            continue
        text = COMMENT_HTML.sub('', text)
        firsts = [m.start() for m in SHEET_LINK.finditer(text) if m.group(1) in reads]
        firsts += [m.start() for m in TOKEN_READ.finditer(text)]
        firsts += [m.start() for m in INCLUDE.finditer(text) if TOKEN_READ.search(included(m.group(1)))]
        theme = next((m.start() for m in SHEET_LINK.finditer(text) if m.group(1) == 'common/css/wama-theme.css'), None)
        if firsts and (theme is None or theme > min(firsts)):
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
            m = re.fullmatch(r'\s*(?::root)?\[data-wama-theme="([a-z0-9_-]+)"\]\s*', selector)
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

    def test_the_standalone_guard_sees_inline_and_included_reads(self):
        """Contre-épreuve : un style de la page, ou un gabarit inclus, qui lit un token compte aussi."""
        styles = {'_style.html': '<style>.slide { background: var(--wama-violet); }</style>'}
        inline = '<html><style>body { color: var(--wama-text); }</style></html>'
        include = "<html><head>{% include '_style.html' %}</head></html>"
        late = "<html>{% include '_style.html' %}<link href=\"{% static_v 'common/css/wama-theme.css' %}\"></html>"
        ok = "<html><link href=\"{% static_v 'common/css/wama-theme.css' %}\">{% include '_style.html' %}</html>"
        pages = [('inline.html', inline), ('include.html', include), ('late.html', late), ('ok.html', ok)]
        self.assertEqual(['inline.html', 'include.html', 'late.html'],
                         standalone_pages_missing_tokens(pages, set(), lambda name: styles.get(name, '')))

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


class LightThemeIsTheMirrorTest(SimpleTestCase):
    """Étape 4 (2026-10-18) : le clair est le MIROIR DE LUMINANCE du sombre (`theme_mirror.py`),
    qui conserve chaque rapport de contraste — sauf les tokens que `themes.py` déclare fixes ou
    surfaces. Un token clair retouché à la main sans y être déclaré rougit ici."""

    @staticmethod
    def _ratio_to_white(value):
        """Rapport au blanc ; une couleur translucide est d'abord posée sur le blanc."""
        from wama.common.theme_mirror import luminance, parse
        _kind, rgb, alpha = parse(value)
        if alpha:
            a = int(alpha, 16) / 255 if len(alpha) == 2 and not alpha.startswith('.') and '.' not in alpha else float(alpha)
            rgb = tuple(a * c + (1 - a) * 255 for c in rgb)
        return 1.05 / (luminance(rgb) + 0.05)

    def test_every_light_token_is_the_mirror_or_declared(self):
        from wama.common import themes
        from wama.common.theme_mirror import mirror
        blocks = theme_blocks()
        dark, light = blocks['dark'], blocks['light']
        for name, value in dark.items():
            with self.subTest(token=name):
                if name in themes.LIGHT_FIXED or name.startswith(themes.LIGHT_FIXED_PREFIXES):
                    self.assertEqual(value.strip(), light[name].strip(), 'a FIXED token keeps its value')
                elif name in themes.LIGHT_HAND:
                    self.assertNotEqual(value.strip(), light[name].strip(), 'a hand-set token differs')
                elif name in themes.LIGHT_SURFACES:
                    # plus claire que son miroir, ou presque blanche (≤ 1,1:1 au blanc : un voile
                    # d'encart) — un texte sombre n'y perd jamais de contraste qui compte
                    self.assertLessEqual(self._ratio_to_white(light[name]),
                                         max(self._ratio_to_white(mirror(value)) * 1.01, 1.1),
                                         'a structure surface is lighter than its mirror, or near white')
                else:
                    expected = mirror(value)
                    self.assertAlmostEqual(self._ratio_to_white(expected), self._ratio_to_white(light[name]),
                                           delta=self._ratio_to_white(expected) * 0.03,
                                           msg=f'the mirror of {value} is {expected}')

    def test_every_declared_exception_names_a_token(self):
        from wama.common import themes
        tokens = set(theme_blocks()['dark'])
        for name in (*themes.LIGHT_FIXED, *themes.LIGHT_SURFACES, *themes.LIGHT_HAND):
            with self.subTest(token=name):
                self.assertIn(name, tokens, 'an exception of a removed token is removed')
        for name, why in {**themes.LIGHT_FIXED, **themes.LIGHT_HAND}.items():
            self.assertTrue(why.strip())

    def test_the_mirror_keeps_every_contrast_ratio(self):
        """Contre-épreuve de la règle elle-même : le rapport d'un texte à son fond est conservé,
        inversé ; le noir et le blanc s'échangent ; un gris reste un gris."""
        from wama.common.theme_mirror import luminance, mirror, parse

        def ratio(a, b):
            ya, yb = (luminance(parse(v)[1]) for v in (a, b))
            return (max(ya, yb) + 0.05) / (min(ya, yb) + 0.05)
        for text, ground in (('#9aa3ab', '#212529'), ('#ffc107', '#1a1a2e'), ('#dee2e6', '#2b3035')):
            with self.subTest(pair=(text, ground)):
                self.assertAlmostEqual(ratio(text, ground), ratio(mirror(text), mirror(ground)), delta=0.15)
        self.assertEqual(('#000000', '#ffffff'), (mirror('#fff'), mirror('#000')))
        r, g, b = parse(mirror('#9aa3ab'))[1]
        self.assertLessEqual(max(r, g, b) - min(r, g, b), 171 - 154, 'a tint kept, not invented')
        self.assertEqual('rgba(0, 0, 0, .08)', mirror('rgba(255, 255, 255, .08)'), 'opacity kept')

    def test_a_region_can_fix_its_theme(self):
        """Îlot : `data-wama-theme` sur un élément y redéfinit les tokens (sélecteur non limité à
        `:root`) — l'encart au dégradé de l'accueil reste sombre en thème clair."""
        css = THEME_CSS.read_text(encoding='utf-8')
        self.assertIn(':root,\n[data-wama-theme="dark"] {', css)
        self.assertIn('\n[data-wama-theme="light"] {', css)
        home = (ROOT / 'wama' / 'templates' / 'home.html').read_text(encoding='utf-8')
        self.assertIn('data-wama-theme="dark" data-bs-theme="dark"', home)


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


class ThemeColorForDrawingTest(SimpleTestCase):
    """`WamaApp.themeColor` (wama-app-base.js) : un canvas ou un graphe ne lit pas `var(--…)`, la
    brique lui rend la VALEUR du token du thème actif. Exécutée seule dans V8 (patron de
    `tests_toast`) ; ⚠ `py_mini_racer` n'est que dans venv_win : skippe sous venv_linux."""

    FAKE = """var document = { documentElement: {} };
    var tokens = { '--bs-danger': ' #dc3545', '--bs-danger-rgb': '220, 53, 69' };
    function getComputedStyle(el) { return { getPropertyValue: function (t) { return tokens[t] || ''; } }; }
    """

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        src = (ROOT / 'wama/common/static/common/js/wama-app-base.js').read_text(encoding='utf-8')
        body = re.search(r'\n  function themeColor\(.*?\n  }\n', src, re.S)
        self.assertIsNotNone(body, '`themeColor` a disparu ou changé de forme')
        self.assertIn('themeColor: themeColor', src, 'la brique est exposée sur WamaApp')
        self.ctx = MiniRacer()
        self.ctx.eval(self.FAKE + body.group(0))

    def test_a_token_gives_its_value_and_a_channel_token_composes_a_veil(self):
        self.assertEqual('#dc3545', self.ctx.eval("themeColor('--bs-danger')"))
        self.assertEqual('rgba(220, 53, 69, 0.1)', self.ctx.eval("themeColor('--bs-danger-rgb', 0.1)"))

    def test_the_served_copy_is_the_source(self):
        self.assertEqual((ROOT / 'wama/common/static/common/js/wama-app-base.js').read_bytes(),
                         (ROOT / 'staticfiles/common/js/wama-app-base.js').read_bytes())


class ThemeChoiceTest(TestCase):
    """Étape 5 (2026-10-19) : le compte CHOISIT son thème au Profil — « Automatique » (le défaut,
    qui suit le système), ou un thème déclaré. Réglage durable (`user_settings`), lu sur toute page."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user('theme-choice-test', password='x')

    def _request(self, user=None):
        from django.contrib.auth.models import AnonymousUser
        request = RequestFactory().get('/')
        request.user = user or AnonymousUser()
        return request

    def test_nothing_chosen_means_automatic_and_the_server_paints_the_default(self):
        from wama.common.context_processors import theme
        from wama.common.themes import AUTO, DEFAULT, DEFAULT_CHOICE
        self.assertEqual(AUTO, DEFAULT_CHOICE)
        for user in (None, self.user):
            with self.subTest(account=bool(user)):
                ctx = theme(self._request(user))
                self.assertEqual(AUTO, ctx['theme_choice'])
                self.assertEqual(DEFAULT, ctx['theme'].key)

    def test_a_chosen_theme_is_what_every_page_gets(self):
        from wama.common.context_processors import theme
        from wama.common.themes import save_theme_choice
        save_theme_choice(self.user, 'light')
        ctx = theme(self._request(self.user))
        self.assertEqual(('light', 'light', 'light'),
                         (ctx['theme_choice'], ctx['theme'].key, ctx['theme'].bootstrap))
        self.assertEqual('light', ctx['theme_declared']['choice'])

    def test_a_choice_that_is_not_offered_is_refused_and_a_stale_one_falls_back(self):
        from wama.common.themes import DEFAULT_CHOICE, save_theme_choice, theme_choice
        from wama.common.utils.user_settings import save_user_app_settings
        with self.assertRaises(ValueError):
            save_theme_choice(self.user, 'no-such-theme')
        save_user_app_settings(self.user, 'common', {'theme': 'retired-theme'})
        self.assertEqual(DEFAULT_CHOICE, theme_choice(self.user))

    def test_the_profile_offers_every_choice_and_saves_it(self):
        from django.urls import reverse
        from wama.common.themes import THEMES, choices, theme_choice
        self.assertEqual(['auto'] + [t.key for t in THEMES], [k for k, _ in choices()])
        self.client.force_login(self.user)
        url = reverse('accounts:profile-theme')
        self.assertEqual(400, self.client.post(url, '{"theme": "nope"}', content_type='application/json').status_code)
        response = self.client.post(url, '{"theme": "light"}', content_type='application/json')
        self.assertEqual({'success': True, 'theme': 'light'}, response.json())
        self.assertEqual('light', theme_choice(self.user))
        html = self.client.get(reverse('accounts:profile')).content.decode()
        self.assertIn('id="themeSelect"', html)
        for key, label in choices():
            self.assertIn(f'<option value="{key}"', html)
        self.assertRegex(html, r'<option value="light" selected>')
        self.assertRegex(html, r'<html[^>]*data-wama-theme="light"[^>]*data-bs-theme="light"')

    def test_base_resolves_automatic_before_any_sheet(self):
        html = BASE_HTML.read_text(encoding='utf-8')
        declared = html.index('theme_declared|json_script:"wama-theme-declared"')
        script = html.index("static_v 'common/js/wama-theme.js'")
        first_sheet = html.index('rel="stylesheet"')
        self.assertLess(declared, script)
        self.assertLess(script, first_sheet, 'the theme is set before the first paint')


class ThemeScriptTest(SimpleTestCase):
    """`wama-theme.js` exécuté dans V8 avec un faux `document` : « Automatique » suit le mode du
    système, et le suit encore quand il change ; un choix explicite ne le suit pas.
    ⚠ `py_mini_racer` n'est que dans venv_win : skippe sous venv_linux."""

    FAKE = """var attrs = {}, listeners = [], systemLight = %s;
    var document = {
      documentElement: { setAttribute: function (k, v) { attrs[k] = v; } },
      getElementById: function () { return { textContent: %s }; } };
    var window = { matchMedia: function () { return {
      get matches() { return systemLight; },
      addEventListener: function (e, f) { listeners.push(f); } }; } };
    function flip() { systemLight = !systemLight; listeners.forEach(function (f) { f(); }); }
    """

    def _run(self, choice, system_light):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        import json
        from wama.common.themes import declared_for_pages
        ctx = MiniRacer()
        payload = json.dumps(json.dumps(declared_for_pages(choice)))
        ctx.eval(self.FAKE % ('true' if system_light else 'false', payload)
                 + (ROOT / 'wama/common/static/common/js/wama-theme.js').read_text(encoding='utf-8'))
        return ctx

    def _theme(self, ctx):
        return ctx.eval("attrs['data-wama-theme'] + '/' + attrs['data-bs-theme']")

    def test_automatic_follows_the_system_and_its_changes(self):
        ctx = self._run('auto', system_light=True)
        self.assertEqual('light/light', self._theme(ctx))
        ctx.eval('flip()')
        self.assertEqual('dark/dark', self._theme(ctx))

    def test_an_explicit_choice_ignores_the_system(self):
        ctx = self._run('dark', system_light=True)
        self.assertEqual('dark/dark', self._theme(ctx))
        ctx.eval('flip()')
        self.assertEqual('dark/dark', self._theme(ctx))

    def test_the_profile_applies_a_choice_in_place(self):
        ctx = self._run('dark', system_light=False)
        self.assertEqual('light', ctx.eval("window.WamaTheme.apply('light')"))
        self.assertEqual('light/light', self._theme(ctx))
        self.assertEqual('dark', ctx.eval("window.WamaTheme.apply('auto')"))

    def test_the_served_copy_is_the_source(self):
        self.assertEqual((ROOT / 'wama/common/static/common/js/wama-theme.js').read_bytes(),
                         (ROOT / 'staticfiles/common/js/wama-theme.js').read_bytes())


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

    def test_a_comment_is_removed_in_its_own_language_only(self):
        """Vécu : `accept="video/*"` ouvrait un « commentaire » CSS qui avalait la page jusqu'au
        `*/` suivant — 47 couleurs d'une page n'étaient pas comptées."""
        page = ('<input accept="video/*"><style>a { color: #fff; } /* #000 */</style>'
                '<script>ctx.fillStyle = "#dc3545"; // #111\n</script>')
        self.assertEqual(2, colour_count('a.html', page))
        self.assertEqual(1, colour_count('a.html', '{% block app_styles %}b{color:#abc}/* #def */{% endblock %}'))

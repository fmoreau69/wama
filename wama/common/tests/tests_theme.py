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
        self.assertIn('apply_theme(page, theme)', source)
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
        from wama.common.theme_mirror import contrast_ratio, mirror, parse

        def ratio(a, b):
            return contrast_ratio(parse(a)[1], parse(b)[1])
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
        self.assertIn(':root,\n[data-wama-theme="dark"]', css)
        self.assertIn('\n[data-wama-theme="light"],\n', css)
        home = (ROOT / 'wama' / 'templates' / 'home.html').read_text(encoding='utf-8')
        self.assertIn('data-wama-theme="dark" data-bs-theme="dark"', home)


COLOUR_LITERAL = re.compile(r'#[0-9a-fA-F]{3,8}\b|rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})'
                            r'|^\s*(\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3})\s*$')


def own_blocks(css=None):
    """{clé de thème: {propriété: valeur}} des blocs qui ne nomment QU'UN thème — ce qu'un thème
    dérivé redéfinit lui-même, `--bs-*` compris (`theme_blocks` y mêle les valeurs reçues)."""
    css = re.sub(r'/\*.*?\*/', '', css if css is not None else THEME_CSS.read_text(encoding='utf-8'),
                 flags=re.S)
    blocks = {}
    for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        m = re.fullmatch(r'\s*\[data-wama-theme="([a-z0-9_-]+)"\]\s*', selector)
        if m:
            blocks.setdefault(m.group(1), {}).update(re.findall(r'(--[a-z0-9-]+)\s*:\s*([^;]+);', body))
    return blocks


def colours_outside_charter(block, charter):
    """Les couleurs écrites dans `block` qui ne sont ni une couleur de `charter`, ni l'une de ses
    teintes déclarées (`derived`) — en hexadécimal, en `rgba(r, g, b, a)` ou en canaux « r, g, b »."""
    allowed = {c.lower() for c in charter['colors'].values()} | {c.lower() for c in charter['derived']}
    found = {}
    for name, value in block.items():
        for m in COLOUR_LITERAL.finditer(value):
            channels = [g for g in m.groups() if g is not None]
            if channels:
                colour = '#%02x%02x%02x' % tuple(int(c) for c in channels)
            else:
                colour = m.group(0).lower()
                if len(colour) == 4:
                    colour = '#' + ''.join(c * 2 for c in colour[1:])
            if colour not in allowed:
                found[name] = colour
    return found


class DerivedThemeTest(SimpleTestCase):
    """Les thèmes UGE et La Suite numérique (2026-10-19) DÉRIVENT du clair, La Suite sombre du
    sombre : chacun reçoit chaque valeur de sa base par la liste de sélecteurs du bloc de celle-ci,
    et son bloc ne redéfinit que l'identité, chaque couleur venant de sa charte
    (`themes.CHARTERS`)."""

    def test_a_derived_theme_is_in_the_selector_list_of_its_base(self):
        from wama.common.themes import THEMES
        css = re.sub(r'/\*.*?\*/', '', THEME_CSS.read_text(encoding='utf-8'), flags=re.S)
        lists = [re.findall(r'\[data-wama-theme="([a-z0-9_-]+)"\]', sel)
                 for sel, _ in re.findall(r'([^{}]+)\{([^{}]*)\}', css)]
        keys = {t.key for t in THEMES}
        for t in THEMES:
            if not t.base:
                continue
            with self.subTest(theme=t.key):
                self.assertIn(t.base, keys)
                self.assertFalse(next(b for b in THEMES if b.key == t.base).base, 'one level of derivation')
                self.assertTrue(any(t.base in keys_ and t.key in keys_ for keys_ in lists),
                                'the derived theme receives every value of its base')
                self.assertEqual(theme_blocks()[t.base].keys(), theme_blocks()[t.key].keys())

    def test_every_colour_of_a_derived_theme_comes_from_its_charter(self):
        from wama.common.themes import CHARTERS, THEMES
        own = own_blocks()
        for t in THEMES:
            if t.base and not t.generated:
                with self.subTest(theme=t.key):
                    self.assertIn(t.charter, CHARTERS, 'a derived theme names its charter')
                    self.assertIn(t.key, own, 'and redefines something')
                    self.assertEqual({}, colours_outside_charter(own[t.key], CHARTERS[t.charter]))

    def test_a_derived_shade_is_the_stated_mix(self):
        from wama.common.themes import CHARTERS
        for key, charter in CHARTERS.items():
            colours = {c.lower() for c in charter['colors'].values()}
            for shade, (colour, mix, part) in charter['derived'].items():
                with self.subTest(charter=key, shade=shade):
                    self.assertIn(colour.lower(), colours)
                    a, b = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (colour, mix))
                    expected = '#%02x%02x%02x' % tuple(round(part * x + (1 - part) * y) for x, y in zip(a, b))
                    self.assertEqual(expected, shade.lower())

    def test_the_charter_guard_sees_a_foreign_colour(self):
        """Contre-épreuve sur un bloc écrit pour elle : hexadécimal court, `rgba` et canaux."""
        charter = {'colors': {'principale': '#2f2a85'}, 'derived': {}}
        block = {'--a': '#2f2a85', '--b': 'rgba(47, 42, 133, .5)', '--c': '47, 42, 133',
                 '--d': '#fff', '--e': 'rgba(13, 110, 253, .5)', '--f': '1, 2, 3'}
        self.assertEqual({'--d': '#ffffff', '--e': '#0d6efd', '--f': '#010203'},
                         colours_outside_charter(block, charter))

    def test_the_text_colours_of_the_charter_read_on_its_grounds(self):
        """Ce que le bloc d'un thème dérivé pose comme TEXTE (liens, accent lu, primaire de
        Bootstrap en texte) passe 4,5:1 sur les fonds de sa base — le blanc en clair, les surfaces
        du sombre en sombre — et sur son fond de page ; la primaire, fond d'un bouton plein, passe
        4,5:1 sous son texte blanc. En sombre, la primaire n'est pas lue comme texte : aucune
        couleur ne passe 4,5:1 à la fois sous un texte blanc et sur un fond sombre."""
        from wama.common.theme_mirror import contrast_ratio, parse
        from wama.common.themes import THEMES

        def ratio(a, b):
            return contrast_ratio(parse(a)[1], parse(b)[1])
        own, blocks = own_blocks(), theme_blocks()
        texts = ('--wama-accent-text', '--wama-link', '--wama-link-soft', '--wama-accent-soft-text',
                 '--bs-primary-text-emphasis')
        for t in THEMES:
            if not t.base or t.generated:
                continue        # un thème généré : `GeneratedThemeTest`, pour toute graine
            block, base = own[t.key], blocks[t.base]
            if t.bootstrap == 'light':
                grounds, read = ('#ffffff',), texts + ('--bs-primary',)
            else:
                grounds, read = (base['--wama-surface'], base['--wama-surface-raised']), texts
            for name in read:
                for ground in grounds + (block['--wama-page-bg-start'],):
                    with self.subTest(theme=t.key, token=name, ground=ground):
                        self.assertGreaterEqual(ratio(block[name], ground), 4.5)
            with self.subTest(theme=t.key, filled='--bs-primary'):
                self.assertGreaterEqual(ratio(block['--bs-primary'], base['--wama-text-on-accent']), 4.5)


def served_licensed_fonts(paths, sheets, names):
    """Ce qui SERVIRAIT une police sous licence commerciale (`names`) : un fichier de police des
    dossiers statiques qui la porte dans son nom, ou un `@font-face` qui la déclare."""
    def key(text):
        return re.sub(r'[\s_-]+', '', text).lower()
    wanted = [key(n) for n in names]
    found = [p for p in paths if p.lower().endswith(('.ttf', '.otf', '.woff', '.woff2', '.eot'))
             and any(w in key(p) for w in wanted)]
    for rel, text in sheets:
        for face in re.findall(r'@font-face\s*\{[^}]*\}', text):
            if any(w in key(face) for w in wanted):
                found.append(rel)
    return found


class ThemeIdentityTest(SimpleTestCase):
    """Le logo et la police d'une charte (2026-10-19, Fabien : « oui pour le logo UGE » ; « TT
    Norms est payé par l'UGE pour être utilisé »)."""

    def test_a_theme_logo_is_served_and_shown_under_its_theme_only(self):
        from wama.common.context_processors import theme
        from wama.common.themes import THEMES
        logos = [t for t in THEMES if t.logo]
        self.assertTrue(logos)
        self.assertEqual(logos, theme(RequestFactory().get('/'))['theme_logos'])
        header = (ROOT / 'wama' / 'templates' / 'includes' / 'header.html').read_text(encoding='utf-8')
        self.assertIn('{% for t in theme_logos %}', header)
        sheet = (ROOT / 'wama' / 'filemanager' / 'static' / 'filemanager' / 'css' / 'filemanager.css')
        css = sheet.read_text(encoding='utf-8')
        self.assertRegex(css, r'\.wama-theme-logo \{\s*display: none;', 'hidden unless its theme is active')
        for t in logos:
            with self.subTest(theme=t.key):
                source = ROOT / 'wama' / 'common' / 'static' / t.logo
                self.assertTrue(source.is_file())
                self.assertEqual(source.read_bytes(), (ROOT / 'staticfiles' / t.logo).read_bytes())
                self.assertIn(f'[data-wama-theme="{t.key}"] .wama-theme-logo[data-theme-logo="{t.key}"]', css)

    def test_a_licensed_font_is_named_never_served(self):
        from wama.common.themes import LICENSED_FONTS
        paths = [p.relative_to(ROOT).as_posix() for top in ('wama', 'wama_lab', 'wama_data', 'staticfiles')
                 for ext in ('ttf', 'otf', 'woff', 'woff2', 'eot') for p in (ROOT / top).rglob(f'*.{ext}')]
        self.assertTrue(paths, 'the walk sees the font files that are served (Font Awesome…)')
        self.assertEqual([], served_licensed_fonts(paths, _sources(('.css', '.html')), LICENSED_FONTS))
        self.assertIn('"TT Norms Pro"', THEME_CSS.read_text(encoding='utf-8'), 'named, for a workstation that has it')

    def test_a_charter_font_is_the_family_of_its_themes_and_free_ones_are_served(self):
        """La police de la charte (`CHARTERS[…]['font']`, 2026-10-20) est la première famille de
        chaque thème qui en vient ; une police SERVIE l'est par la route des vendors front
        (`tools/update_vendors.sh`), copie servie comprise, et sa feuille déclare la famille et
        des fontes présentes. Une police sous licence n'a jamais de feuille."""
        from django.contrib.staticfiles import finders

        from wama.common.context_processors import theme
        from wama.common.themes import CHARTERS, LICENSED_FONTS, THEMES, font_stylesheets
        own = own_blocks()
        for t in THEMES:
            font = CHARTERS.get(t.charter, {}).get('font')
            if not font:
                continue
            with self.subTest(theme=t.key):
                stack = own[t.key]['--bs-body-font-family']
                self.assertEqual(font['family'], stack.split(',')[0].strip().strip('"\''))
        sheets = font_stylesheets()
        self.assertIn('vendors/roboto-flex-5.3.0/index.css', sheets)
        self.assertEqual(sheets, theme(RequestFactory().get('/'))['theme_font_sheets'])
        self.assertIn('{% for sheet in theme_font_sheets %}', BASE_HTML.read_text(encoding='utf-8'))
        route = (ROOT / 'tools' / 'update_vendors.sh').read_text(encoding='utf-8')
        for charter in CHARTERS.values():
            font = charter.get('font') or {}
            if any(n.lower() in font.get('family', '').lower() for n in LICENSED_FONTS):
                self.assertEqual('', font['stylesheet'], 'a licensed font is named, never served')
        for sheet in sheets:
            with self.subTest(sheet=sheet):
                source = Path(finders.find(sheet))
                self.assertEqual(source.read_bytes(), (ROOT / 'staticfiles' / sheet).read_bytes())
                self.assertIn(sheet.split('/')[1].rsplit('-', 1)[0], route, 'vendored by the route')
                text = source.read_text(encoding='utf-8')
                families = {c['font']['family'] for c in CHARTERS.values()
                            if c.get('font', {}).get('stylesheet') == sheet}
                for family in families:
                    self.assertIn(f"font-family: '{family}'", text)
                urls = re.findall(r'url\(\s*["\']?([^)"\']+)', text)
                self.assertTrue(urls)
                for url in urls:
                    self.assertTrue((source.parent / url).is_file(), url)
                    self.assertTrue((ROOT / 'staticfiles' / Path(sheet).parent / url).is_file(), url)

    def test_the_font_guard_sees_a_served_file_and_a_font_face(self):
        """Contre-épreuve sur des sources écrites pour elle."""
        paths = ['wama/static/fonts/TT_Norms-Pro-Regular.woff2', 'wama/static/fonts/roboto.woff2',
                 'wama/static/img/tt-norms.png']
        sheets = [('a.css', '@font-face { font-family: "TT Norms Pro"; src: url(x.woff2); }'),
                  ('b.css', 'body { font-family: "TT Norms Pro", Tahoma; }')]
        self.assertEqual(['wama/static/fonts/TT_Norms-Pro-Regular.woff2', 'a.css'],
                         served_licensed_fonts(paths, sheets, ('TT Norms',)))


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
    """Étape 5 (2026-10-19) : le compte CHOISIT son thème au Profil — un thème déclaré (le sombre
    par défaut), ou « Automatique », qui suit le système. Réglage durable (`user_settings`), lu sur
    toute page."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user('theme-choice-test', password='x')

    def _request(self, user=None):
        from django.contrib.auth.models import AnonymousUser
        request = RequestFactory().get('/')
        request.user = user or AnonymousUser()
        return request

    def test_nothing_chosen_means_dark_whatever_the_system(self):
        """Décision de Fabien (2026-10-19) : sombre par défaut, « Automatique » se choisit. Le
        script ne doit donc rien corriger d'après le système — c'est ce qui garde les captures
        nocturnes (Playwright = système clair, compte de test sans choix) en sombre."""
        from wama.common.context_processors import theme
        from wama.common.themes import DEFAULT_CHOICE
        self.assertEqual('dark', DEFAULT_CHOICE)
        for user in (None, self.user):
            with self.subTest(account=bool(user)):
                ctx = theme(self._request(user))
                self.assertEqual(('dark', 'dark', 'dark'),
                                 (ctx['theme_choice'], ctx['theme'].key, ctx['theme_declared']['choice']))

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
        self.assertEqual({'success': True, 'theme': 'light', 'css': ''},
                         {k: response.json()[k] for k in ('success', 'theme', 'css')})
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


def seed_sweep():
    """Des graines de tout le cercle des teintes, de toute clarté et saturation, et les extrêmes."""
    import colorsys
    seeds = ['#000000', '#ffffff', '#ffff00', '#00ffff', '#808080', '#0d6efd']
    for h in range(0, 360, 15):
        for light in (0.15, 0.35, 0.5, 0.65, 0.85):
            for sat in (0.3, 0.7, 1.0):
                rgb = colorsys.hls_to_rgb(h / 360, light, sat)
                seeds.append('#' + ''.join(f'{round(c * 255):02x}' for c in rgb))
    return seeds


def generated_text_faults(base, block):
    """Les textes d'un bloc généré qui ne passent pas 4,5:1 sur un fond de leur base ou sur leur
    page, et la primaire qui ne le passe pas sous son texte blanc — les règles d'un thème dérivé."""
    from wama.common.theme_generator import grounds
    from wama.common.theme_mirror import contrast_ratio as ratio
    from wama.common.theme_mirror import parse

    def rgb(name):
        return parse(block[name])[1]
    texts = ['--wama-accent-text', '--wama-link', '--wama-link-soft', '--wama-accent-soft-text',
             '--bs-primary-text-emphasis'] + (['--bs-primary'] if base == 'light' else [])
    read_on = grounds(base, rgb('--wama-page-bg-start')) + (rgb('--wama-page-bg-end'),)
    faults = [(name, ground) for name in texts for ground in read_on if ratio(rgb(name), ground) < 4.5]
    on_fill = parse(theme_blocks()[base]['--wama-text-on-accent'])[1]
    if ratio(rgb('--bs-primary'), on_fill) < 4.5:
        faults.append(('--bs-primary', on_fill))
    return faults


class GeneratedThemeTest(TestCase):
    """Étape 7 (2026-10-20) : le thème PERSONNALISÉ — une base et une couleur d'accent choisies au
    Profil, le bloc d'identité GÉNÉRÉ (`theme_generator`), jamais édité à la main."""

    def test_every_seed_gives_legible_texts_in_both_bases(self):
        from wama.common.theme_generator import generate
        from wama.common.themes import THEMES
        generated = [t for t in THEMES if t.generated]
        self.assertEqual({'light', 'dark'}, {t.base for t in generated})
        seeds = seed_sweep()
        self.assertGreater(len(seeds), 300)
        for t in generated:
            for seed in seeds:
                with self.subTest(theme=t.key, seed=seed):
                    self.assertEqual([], generated_text_faults(t.base, generate(t.base, seed)))

    def test_the_legibility_guard_sees_a_dark_link_and_a_pale_primary(self):
        """Contre-épreuve : un lien trop sombre sur le sombre, une primaire trop pâle sous le blanc."""
        from wama.common.theme_generator import generate
        block = dict(generate('dark', '#0d6efd'), **{'--wama-link': '#1a2638'})
        self.assertEqual(['--wama-link'], sorted({n for n, _ in generated_text_faults('dark', block)}))
        block = dict(generate('light', '#0d6efd'), **{'--bs-primary': '#96bcec'})
        self.assertIn('--bs-primary', {n for n, _ in generated_text_faults('light', block)})

    def test_a_generated_block_only_sets_tokens_its_base_has(self):
        from wama.common.theme_generator import generate
        for base in ('light', 'dark'):
            names = set(generate(base, '#16a34a'))
            wama = {n for n in names if n.startswith('--wama-')}
            self.assertEqual(set(), wama - set(theme_blocks()[base]))
            self.assertEqual(set(), names - wama - {n for b in own_blocks().values() for n in b},
                             'a Bootstrap property that a charter theme also sets')

    def test_a_seed_that_is_not_a_colour_is_refused(self):
        from django.contrib.auth.models import User

        from wama.common.theme_generator import generate
        from wama.common.themes import save_theme_choice
        user = User.objects.create_user('theme-generated-test', password='x')
        for bad in ('red', '#fff', 'url(x)', '#0d6efd;}', None):
            with self.subTest(seed=bad), self.assertRaises(ValueError):
                generate('dark', bad)
        with self.assertRaises(ValueError):
            save_theme_choice(user, 'custom-dark', '#0d6efd;} body{display:none')

    def test_a_chosen_accent_is_served_on_every_page_and_only_under_a_generated_theme(self):
        from django.contrib.auth.models import User
        from django.urls import reverse

        from wama.common.context_processors import theme
        from wama.common.theme_generator import css_block
        from wama.common.themes import DEFAULT_ACCENT, save_theme_choice
        user = User.objects.create_user('theme-generated-page', password='x')
        request = RequestFactory().get('/')
        request.user = user
        save_theme_choice(user, 'custom-dark')
        self.assertEqual(css_block('custom-dark', 'dark', DEFAULT_ACCENT), theme(request)['theme_generated_css'])
        save_theme_choice(user, 'custom-light', '#16A34A')
        self.assertEqual(css_block('custom-light', 'light', '#16a34a'), theme(request)['theme_generated_css'])
        save_theme_choice(user, 'uge')
        self.assertEqual('', theme(request)['theme_generated_css'], 'the accent stays, unused')
        self.client.force_login(user)
        url = reverse('accounts:profile-theme')
        self.assertEqual(400, self.client.post(url, '{"theme": "custom-dark", "accent": "blue"}',
                                               content_type='application/json').status_code)
        data = self.client.post(url, '{"theme": "custom-dark", "accent": "#dc2626"}',
                                content_type='application/json').json()
        self.assertEqual(css_block('custom-dark', 'dark', '#dc2626'), data['css'])
        html = self.client.get(reverse('accounts:profile')).content.decode()
        self.assertIn('<style id="wama-theme-generated">[data-wama-theme="custom-dark"] {', html)
        self.assertIn('data-accent="#dc2626"', html)
        self.assertIn('id="themeAccentInput"', html)

    def test_base_sets_the_generated_block_after_the_tokens(self):
        html = BASE_HTML.read_text(encoding='utf-8')
        self.assertLess(html.index("static_v 'common/css/wama-theme.css'"),
                        html.index('<style id="wama-theme-generated">{{ theme_generated_css|safe }}</style>'))

    def test_the_contrast_scenario_measures_the_generated_block(self):
        """`apply_theme` sur une fausse page : un thème généré reçoit son bloc, un autre rien."""
        from wama.common.services.ui_smoke_contrast import apply_theme
        from wama.common.theme_generator import css_block
        from wama.common.themes import DEFAULT_ACCENT, THEMES

        class Page:
            def __init__(self):
                self.calls = []

            def evaluate(self, script, args):
                self.calls.append(('theme', tuple(args)))

            def add_style_tag(self, content):
                self.calls.append(('style', content))
        for t in THEMES:
            with self.subTest(theme=t.key):
                page = Page()
                apply_theme(page, t)
                expected = [('theme', (t.key, t.bootstrap))]
                if t.generated:
                    expected.append(('style', css_block(t.key, t.base, DEFAULT_ACCENT)))
                self.assertEqual(expected, page.calls)


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


def make_charter_pdf(path, pages):
    """Un PDF de charte écrit pour le test (PyMuPDF), une page par chaîne de `pages`."""
    import fitz
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((40, 60), text, fontsize=10)
    doc.save(str(path))
    doc.close()


#: Une charte comme l'extraction les rend : le libellé COLLÉ au code d'avant, l'ordre brouillé,
#: et un « principes » lointain qui ne désigne aucune couleur (relevé sur la charte UGE).
SCRAMBLED = ("Les principes de la charte\nCOULEURS\nCMJN 100 78 47 56\nRVB\n15 • 39 • 59\n#0f273b\n"
             "RVB 232 / 53 / 131\n#e83583\n#ef7d00Couleur principale :\nCouleurs secondaires :Pantone 2746C\n"
             "RVB\n47 • 42 • 133\n#2f2a85\nRGB 300 12 12\nTYPOGRAPHIE\nTT Norms est la typographie")


class CharterThemeTest(TestCase):
    """Étape 7, voie 2 (2026-10-20) : une CHARTE graphique lue au Profil — les règles relèvent les
    couleurs écrites, le LLM choisit parmi elles, un humain valide ; la ligne `UserTheme` a une
    provenance (privée, partagée par une portée, système une fois promue par un admin)."""

    def test_the_rules_find_every_written_colour_once_in_order(self):
        from wama.common.theme_charter import colour_candidates
        found = colour_candidates(SCRAMBLED)
        self.assertEqual(['#0f273b', '#e83583', '#ef7d00', '#2f2a85'], [c['hex'] for c in found])
        self.assertEqual(2, found[0]['count'], 'RVB and hex of the same colour')
        self.assertIn('Couleur principale', found[3]['context'])
        self.assertNotIn('#2c0c0c', [c['hex'] for c in found], 'a channel above 255 is no colour')
        self.assertEqual([], colour_candidates('#0d6efdcc fond, #1234567 rien'), 'eight digits, seven digits')

    def test_the_principal_is_the_colour_its_own_label_names(self):
        from wama.common.theme_charter import labelled_principal, rules_proposal, colour_candidates
        found = colour_candidates(SCRAMBLED)
        self.assertEqual('#2f2a85', labelled_principal(found), 'glued label, distant « principes » ignored')
        self.assertEqual('#2f2a85', rules_proposal(SCRAMBLED, found)['principal'])
        unlabelled = colour_candidates('#808080 gris\n#1167d4 bleu')
        self.assertEqual('#1167d4', rules_proposal('', unlabelled)['principal'], 'first vivid colour')

    def test_the_model_chooses_among_the_written_colours_never_beyond(self):
        from wama.common.theme_charter import colour_candidates, propose
        found = colour_candidates(SCRAMBLED)
        answer = ('<think>…</think>{"name": "Université X", "principal": "#E83583", "base": "dark", '
                  '"font": "TT Norms"}')
        p = propose(SCRAMBLED, found, chat=lambda messages: (answer, None))
        self.assertEqual(('llm', '#e83583', 'Université X', 'dark', 'TT Norms'),
                         (p['reader'], p['principal'], p['name'], p['base'], p['font']))
        invented = propose(SCRAMBLED, found, chat=lambda m: ('{"principal": "#123456"}', None))
        self.assertEqual(('rules', '#2f2a85'), (invented['reader'], invented['principal']))
        self.assertIn('#123456', invented['note'])
        down = propose(SCRAMBLED, found, chat=lambda m: (None, 'connexion refusée'))
        self.assertEqual(('rules', '#2f2a85'), (down['reader'], down['principal']))
        hostile = propose(SCRAMBLED, found, chat=lambda m: (
            '{"principal": "#2f2a85", "font": "x\\"; } body { display: none"}', None))
        self.assertEqual('', hostile['font'], 'a font name that could close the declaration is dropped')
        self.assertEqual('rules', propose('rien', [])['reader'])

    def test_the_model_reads_the_label_hint_and_the_typography(self):
        from wama.common.theme_charter import colour_candidates, propose
        seen = {}
        long_text = 'x' * 20000 + SCRAMBLED

        def chat(messages):
            seen['user'] = messages[1]['content']
            return '{"principal": "#2f2a85"}', None
        propose(long_text, colour_candidates(long_text), chat=chat)
        self.assertIn('#2f2a85 (written after:', seen['user'])
        self.assertIn('← its label says principal', seen['user'])
        self.assertIn('TT Norms est la typographie', seen['user'], 'the typography beyond the first pages')

    def test_a_named_font_enters_the_generated_block_and_nothing_else_does(self):
        from wama.common.theme_generator import css_block, generate
        block = generate('light', '#2f2a85', 'TT Norms Pro')
        self.assertEqual('"TT Norms Pro", var(--bs-font-sans-serif)', block['--bs-body-font-family'])
        self.assertNotIn('--bs-body-font-family', generate('light', '#2f2a85'))
        for bad in ('x"; } body {', 'a' * 70, '<b>'):
            with self.subTest(font=bad), self.assertRaises(ValueError):
                css_block('custom-light', 'light', '#2f2a85', bad)

    def _accounts(self):
        from django.contrib.auth.models import User
        return (User.objects.create_user('charter-author', password='x'),
                User.objects.create_user('charter-reader', password='x'),
                User.objects.create_superuser('charter-admin', 'a@x.fr', 'x'))

    def _context(self, user):
        from wama.common.context_processors import theme
        request = RequestFactory().get('/')
        request.user = user
        return theme(request)

    def test_a_charter_is_read_validated_private_shared_and_promoted(self):
        import json
        import tempfile
        from unittest import mock

        from django.urls import reverse

        from wama.common import theme_charter
        from wama.common.models import UserTheme
        from wama.common.theme_generator import css_block
        from wama.common.themes import charter_choices, theme_choice
        author, reader, admin = self._accounts()
        self.client.force_login(author)
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / 'Charte_Labo.pdf'
            make_charter_pdf(pdf, ['Les principes de la charte du labo', SCRAMBLED])
            answer = '{"name": "Labo X", "principal": "#2f2a85", "base": "light", "font": "TT Norms"}'
            with mock.patch.object(theme_charter, '_chat', return_value=(answer, None)), open(pdf, 'rb') as f:
                read = self.client.post(reverse('accounts:profile-theme-charter-read'), {'charter': f}).json()
        self.assertTrue(read['success'], read)
        self.assertEqual(('llm', '#2f2a85', 'Labo X'),
                         (read['proposal']['reader'], read['proposal']['principal'], read['proposal']['name']))
        self.assertIn('#2f2a85', [c['hex'] for c in read['candidates']])
        self.assertEqual(0, UserTheme.objects.count(), 'reading saves nothing')

        save = reverse('accounts:profile-theme-charter-save')
        body = {'name': 'Labo X', 'base': 'light', 'accent': '#2f2a85', 'font': 'TT Norms',
                'filename': 'Charte_Labo.pdf', 'reader': 'llm', 'colours': ['#2f2a85'], 'scope': 'private'}
        self.assertEqual(400, self.client.post(save, json.dumps(dict(body, accent='indigo')),
                                               content_type='application/json').status_code)
        data = self.client.post(save, json.dumps(body), content_type='application/json').json()
        row = UserTheme.objects.get(pk=data['pk'])
        self.assertEqual((author.pk, 'private'), (row.owner_id, row.visibility))
        expected = css_block('custom-light', 'light', '#2f2a85', 'TT Norms')
        self.assertEqual((expected, 'custom-light'), (data['css'], data['key']))
        self.assertEqual(expected, self._context(author)['theme_generated_css'])
        self.assertEqual('custom-light', theme_choice(author))
        html = self.client.get(reverse('accounts:profile')).content.decode()
        self.assertRegex(html, rf'<option value="charter:{row.pk}" data-key="custom-light" selected>Labo X — à moi')

        # Privé : l'autre compte ne le voit ni ne le choisit.
        self.assertEqual([], charter_choices(reader))
        self.client.force_login(reader)
        theme_url = reverse('accounts:profile-theme')
        self.assertEqual(400, self.client.post(theme_url, json.dumps({'theme': f'charter:{row.pk}'}),
                                               content_type='application/json').status_code)
        manage = reverse('accounts:profile-theme-charter-manage')
        self.assertEqual(404, self.client.post(manage, json.dumps({'pk': row.pk, 'action': 'share', 'scope': 'public'}),
                                               content_type='application/json').status_code)

        # Partagé par son auteur, par le service commun : visible, choisi, mais pas à lui.
        self.client.force_login(author)
        self.assertTrue(self.client.post(manage, json.dumps({'pk': row.pk, 'action': 'share', 'scope': 'public'}),
                                         content_type='application/json').json()['success'])
        self.assertEqual(['partagé par charter-author'], [c['provenance'] for c in charter_choices(reader)])
        self.client.force_login(reader)
        chosen = self.client.post(theme_url, json.dumps({'theme': f'charter:{row.pk}'}),
                                  content_type='application/json').json()
        self.assertEqual(expected, chosen['css'])
        for action in ('share', 'delete', 'promote'):
            with self.subTest(refused=action):
                self.assertEqual(403, self.client.post(manage, json.dumps({'pk': row.pk, 'action': action, 'scope': 'private'}),
                                                       content_type='application/json').status_code)

        # Promu par un admin : système, sans propriétaire, l'auteur gardé pour l'attribution.
        self.client.force_login(admin)
        self.assertTrue(self.client.post(manage, json.dumps({'pk': row.pk, 'action': 'promote'}),
                                         content_type='application/json').json()['success'])
        row.refresh_from_db()
        self.assertEqual((None, 'public', 'charter-author', 'charter-admin'),
                         (row.owner_id, row.visibility, row.source['proposed_by'], row.source['promoted_by']))
        self.assertEqual(['Système'], [c['provenance'] for c in charter_choices(reader)])

        # Retiré : qui l'avait choisi retombe sur sa couleur d'accent, jamais sur une page sans thème.
        self.assertTrue(self.client.post(manage, json.dumps({'pk': row.pk, 'action': 'delete'}),
                                         content_type='application/json').json()['success'])
        self.assertEqual(css_block('custom-light', 'light', '#0d6efd'), self._context(reader)['theme_generated_css'])

    def test_promoting_a_row_keeps_its_first_author_and_refuses_a_mandatory_owner(self):
        # La règle d'`ingest.promote`, pour une LIGNE : l'auteur d'origine n'est jamais écrasé.
        from wama.common.manifests.ownership import promote_owned_row
        from wama.common.models import UserFunction, UserTheme
        author, _reader, admin = self._accounts()
        row = UserTheme.objects.create(owner=author, name='T', base='light', accent='#2f2a85',
                                       source={'proposed_by': 'first-author'})
        promote_owned_row(row, by=admin)
        row.refresh_from_db()
        self.assertEqual((None, 'public', 'first-author', 'charter-admin'),
                         (row.owner_id, row.visibility, row.source['proposed_by'], row.source['promoted_by']))
        with self.assertRaises(ValueError):
            promote_owned_row(UserFunction(owner=author), by=admin)

    def test_another_choice_leaves_the_charter(self):
        from wama.common.models import UserTheme
        from wama.common.themes import profile_choice, save_theme_choice, theme_charter
        author, _reader, _admin = self._accounts()
        row = UserTheme.objects.create(owner=author, name='Labo', base='dark', accent='#16a34a')
        save_theme_choice(author, f'charter:{row.pk}')
        self.assertEqual((row, f'charter:{row.pk}'), (theme_charter(author), profile_choice(author)))
        save_theme_choice(author, 'custom-dark', '#dc2626')
        self.assertEqual((None, 'custom-dark'), (theme_charter(author), profile_choice(author)))
        from wama.common.theme_generator import css_block
        self.assertEqual(css_block('custom-dark', 'dark', '#dc2626'), self._context(author)['theme_generated_css'])

    def test_the_charter_modal_lives_at_body_level(self):
        """Logée dans le contenu de la page, une modale passe SOUS son voile (mesuré au navigateur
        le 2026-10-20 : le voile interceptait chaque clic) — sa place est `extra_modals`."""
        source = (ROOT / 'wama' / 'accounts' / 'templates' / 'accounts' / 'profile.html').read_text(encoding='utf-8')
        block = source.split('{% block extra_modals %}', 1)[1].split('{% endblock %}', 1)[0]
        self.assertIn('id="charterModal"', block)

    def test_the_read_rejects_what_is_not_a_charter(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse
        author, _reader, _admin = self._accounts()
        self.client.force_login(author)
        url = reverse('accounts:profile-theme-charter-read')
        self.assertEqual(400, self.client.post(url, {}).status_code)
        self.assertEqual(400, self.client.post(url, {'charter': SimpleUploadedFile('x.exe', b'MZ')}).status_code)

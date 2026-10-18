"""CONTRAST — a text never has the colour of its background (2026-10-16, asked by Fabien : « parfois
le texte est écrit de la même couleur que le fond et est illisible »).

Two halves, because neither sees what the other does :
  • the BROWSER measures the real colours (nightly `common.contrast`, and `<app>.preview` on a queue
    with cards, the panel and the viewer) — `ui_smoke_contrast`, axe-core's `color-contrast` rule ;
  • the CODE refuses, at commit time, the recurring mistake that needs no browser to be seen : a
    dark-text class (`text-dark`, `text-black`, `link-dark`, `btn-outline-dark`) on an element
    without a light background — black on the dark theme ; and its mirror since the light theme
    (2026-10-18) : a light-text class without a dark background, or a dark surface written in a class.
Here : the code guard, the pure parts of the measure, and the wiring."""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
DARK = re.compile(r'\b(text-dark|text-black|link-dark|btn-outline-dark)\b')
#: Fonds clairs FIXES — ceux qui ne suivent pas le mode. `bg-body` en est sorti le 2026-10-17 :
#: depuis que le sombre repose sur le mode natif de Bootstrap, il est sombre.
LIGHT = re.compile(r'\b(bg-(warning|info|light|white|success|primary|danger|secondary)'
                   r'|btn-(warning|info|light|success))\b')
#: A class string : `class="…"`, or a JS literal that holds classes.
CHUNK = re.compile(r'class="([^"]*)"|class=\'([^\']*)\'|\'([^\'\n]*)\'|"([^"\n]*)"|`([^`]*)`')
#: Twins of the sandbox are COPIES regenerated from their source : measured there.
TWIN = re.compile(r'^wama/[a-z_]+_\d\d/')

#: (file, dark class) → why it IS readable : the light background comes from a PARENT, which a
#: line of code cannot show. An exemption that no longer matches anything fails too.
EXEMPT = {
    ('wama/anonymizer/static/anonymizer/js/right_panel.js', 'link-dark'):
        "lien posé DANS le badge `bg-warning text-dark` de l'état SAM3",
}
#: (Le `btn-outline-dark` posé dans une `alert-warning` du transcriber en est sorti le 2026-10-17 :
#: le fond d'une alerte suit le mode, il est sombre depuis l'étape 2 des thèmes — le bouton est
#: devenu `btn-outline-warning`.)


def _dark_without_light():
    found = []
    for base in ('wama', 'wama_lab', 'wama_data'):
        for path in (ROOT / base).rglob('*'):
            rel = path.relative_to(ROOT).as_posix()
            if path.suffix not in ('.html', '.js') or 'vendors' in path.parts or TWIN.match(rel):
                continue
            for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
                if not DARK.search(line):
                    continue
                for m in CHUNK.finditer(line):
                    chunk = next(g for g in m.groups() if g is not None)
                    if DARK.search(chunk) and not LIGHT.search(chunk):
                        found.append((rel, DARK.search(chunk).group(1), chunk.strip()[:100]))
    return found


class DarkTextNeedsALightBackgroundTest(SimpleTestCase):

    def test_no_dark_text_class_without_a_light_background(self):
        offenders = [f'{rel} : {cls} — « {chunk} »' for rel, cls, chunk in _dark_without_light()
                     if (rel, cls) not in EXEMPT]
        self.assertEqual([], offenders, 'black on the dark theme : give the element a light '
                                        'background, or a light text class')

    def test_every_exemption_still_matches_and_says_why(self):
        seen = {(rel, cls) for rel, cls, _chunk in _dark_without_light()}
        for key, why in EXEMPT.items():
            with self.subTest(exemption=key):
                self.assertIn(key, seen, 'an exemption that no longer matches anything is removed')
                self.assertTrue(why.strip())

    def test_the_guard_sees_a_dark_text_on_the_dark_theme(self):
        """Counter-proof on a line written for it : the instrument is not blind."""
        line = '<span class="small text-dark">illisible</span> <span class="badge bg-warning text-dark">ok</span>'
        hits = [next(g for g in m.groups() if g is not None) for m in CHUNK.finditer(line)]
        flagged = [c for c in hits if DARK.search(c) and not LIGHT.search(c)]
        self.assertEqual(['small text-dark'], flagged)


#: Le sens inverse (étape 4 des thèmes, 2026-10-18) : un texte CLAIR fixe exige un fond SOMBRE
#: fixe, sinon il disparaît sur le thème clair ; et un fond sombre fixe ne suit aucun thème.
LIGHT_TEXT = re.compile(r'(?<![\w-])(text-white|text-white-50|text-light|link-light|btn-outline-light)(?![\w-])')
DARK_GROUND = re.compile(r'(?<![\w-])(?:(?:bg|text-bg)-(?:primary|secondary|success|danger|black|\$\{)'
                         r'|btn-(?:primary|secondary|success|danger|dark|\$\{))')
#: Classes qui écrivent le sombre dans la page : leur équivalent suit le mode (`bg-body`,
#: `text-body-emphasis`, `.table` seule, menu et croix natifs, `btn-outline-emphasis`).
DARK_ONLY = re.compile(r'(?<![\w-])(bg-dark|table-dark|dropdown-menu-dark|btn-close-white|navbar-dark)(?![\w-])')
QUOTED = re.compile(r'"[^"\n]*"|\'[^\'\n]*\'|`[^`]*`')
#: (fichier, classe) → pourquoi le texte clair y est LISIBLE : le fond sombre vient d'un PARENT.
LIGHT_EXEMPT = {
    ('wama/model_manager/templates/model_manager/index.html', 'text-white'):
        "dans le voile de chargement, rgba(--wama-shadow-rgb, .7) : sombre dans tous les thèmes",
    ('wama/media_library/templates/media_library/index.html', 'text-white'):
        "toast dont media-library.js pose le fond (bg-success / bg-danger)",
    ('wama/common/utils/state_presentation.py', 'text-white-50'):
        "classe de texte d'un badge, posée avec le fond `bg-secondary` du même tuple",
}


def _theme_fixed_tones():
    """[(fichier, classe, extrait)] des textes clairs sans fond sombre et des fonds sombres fixes."""
    found = []
    for base in ('wama', 'wama_lab', 'wama_data'):
        for path in (ROOT / base).rglob('*'):
            rel = path.relative_to(ROOT).as_posix()
            if (path.suffix not in ('.html', '.js', '.py') or 'vendors' in path.parts or TWIN.match(rel)
                    or '/docs/' in rel or '/tests' in rel or path.name.startswith('tests')):
                continue
            for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
                if not (LIGHT_TEXT.search(line) or DARK_ONLY.search(line)):
                    continue
                for m in QUOTED.finditer(line):
                    chunk = m.group(0)
                    for hit in DARK_ONLY.finditer(chunk):
                        found.append((rel, hit.group(1), chunk.strip()[:100]))
                    if not DARK_GROUND.search(chunk):
                        for hit in LIGHT_TEXT.finditer(chunk):
                            found.append((rel, hit.group(1), chunk.strip()[:100]))
    return found


class LightTextNeedsADarkBackgroundTest(SimpleTestCase):

    def test_no_light_text_without_a_dark_background_and_no_fixed_dark_surface(self):
        offenders = [f'{rel} : {cls} — « {chunk} »' for rel, cls, chunk in _theme_fixed_tones()
                     if (rel, cls) not in LIGHT_EXEMPT]
        self.assertEqual([], offenders, 'white on the light theme : read a class that follows the mode '
                                        '(text-body-emphasis, text-body-secondary, bg-body…)')

    def test_every_light_exemption_still_matches_and_says_why(self):
        seen = {(rel, cls) for rel, cls, _chunk in _theme_fixed_tones()}
        for key, why in LIGHT_EXEMPT.items():
            with self.subTest(exemption=key):
                self.assertIn(key, seen, 'an exemption that no longer matches anything is removed')
                self.assertTrue(why.strip())

    def test_the_guard_sees_both_directions(self):
        """Contre-épreuve : texte blanc sans fond, fond sombre fixe — et un badge plein accepté."""
        line = ('<p class="text-white-50">x</p><div class="card bg-dark">y</div>'
                '<span class="badge bg-success text-white">ok</span>')
        hits = []
        for m in QUOTED.finditer(line):
            chunk = m.group(0)
            hits += [h.group(1) for h in DARK_ONLY.finditer(chunk)]
            if not DARK_GROUND.search(chunk):
                hits += [h.group(1) for h in LIGHT_TEXT.finditer(chunk)]
        self.assertEqual(['text-white-50', 'bg-dark'], hits)


class ContrastVerdictTest(SimpleTestCase):

    def test_a_node_is_named_by_its_component_not_by_its_rank(self):
        from wama.common.services.ui_smoke_contrast import signature
        self.assertEqual('span.wama-filter-count',
                         signature('<span class="wama-filter-count" id="fcCount">141</span>'))
        self.assertEqual('div.asset-meta', signature('<div class="asset-meta text-truncate">x</div>',
                                                     '.asset-card[data-id="39"] > .asset-meta'))
        self.assertEqual('.asset-body', signature('<b>2 Mo</b>', '.card > .asset-body:nth-child(3)'))

    def test_axe_ratios_are_read_whether_numbers_or_text(self):
        """axe gives `contrastRatio` as a number and `expectedContrastRatio` as « 4.5:1 » — read
        as a float, the first run of the scenario stopped on it."""
        from wama.common.services.ui_smoke_contrast import _number
        self.assertEqual([2.83, 4.5, 3.0, None, None],
                         [_number(2.83), _number('4.5:1'), _number('3:1'), _number(None), _number('')])

    def test_only_a_text_of_the_background_colour_fails(self):
        from wama.common.services.ui_smoke_contrast import ILLEGIBLE, contrast_verdict
        node = lambda ratio, sig: {'ratio': ratio, 'signature': sig, 'fg': '#222', 'bg': '#212529'}  # noqa: E731
        faults, weak = contrast_verdict([node(1.1, 'span.a'), node(1.2, 'span.a'), node(2.8, 'span.b'),
                                         node(2.9, 'span.b'), node(ILLEGIBLE, 'span.c')], 'page')
        self.assertEqual(1, len(faults), 'one fault per illegible COMPONENT, not per node')
        self.assertIn('span.a', faults[0])
        self.assertEqual({'span.b': 2, 'span.c': 1}, dict(weak), 'weak texts are listed, not failed')


class ContrastWiringTest(SimpleTestCase):

    def test_the_nightly_scenario_is_registered(self):
        from wama.common.services import nightly_tests
        from wama.common.services.ui_smoke_contrast import register_contrast_scenarios
        register_contrast_scenarios()
        self.assertIn('common.contrast', {s.id for s in nightly_tests.REGISTRY})

    def test_the_preview_scenario_measures_the_queue_and_the_viewer(self):
        source = (ROOT / 'wama' / 'common' / 'services' / 'ui_smoke_preview.py').read_text(encoding='utf-8')
        self.assertIn("_check_contrast(page, 'file et volet'", source)
        self.assertIn("context='#wamaMediaPreviewModal'", source)

    def test_axe_core_entered_by_the_library_route(self):
        """Its engine is a library : declared in the corpus (registry Library, page Licences),
        installed by `install_library` — never fetched by the scenario."""
        manifest = json.loads((ROOT / 'manifests' / 'libraries' / 'axe-playwright-python.json')
                              .read_text(encoding='utf-8'))
        self.assertEqual('axe-playwright-python==0.1.8', manifest['body']['install']['pip'])
        self.assertIn('MPL-2.0', manifest['body']['identity']['license'], 'axe-core itself')
        module = (ROOT / 'wama' / 'common' / 'services' / 'ui_smoke_contrast.py').read_text(encoding='utf-8')
        self.assertIn('from axe_playwright_python.base import AXE_SCRIPT', module)
        self.assertNotRegex(module, r'https?://', 'no engine fetched from the network')

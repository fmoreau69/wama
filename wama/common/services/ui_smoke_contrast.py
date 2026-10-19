"""Scénario nocturne `common.contrast` — un texte ne doit jamais avoir la couleur de son fond.

Demande de Fabien (2026-10-16) : *« parfois le texte est écrit de la même couleur que le fond et
est illisible »*. Le défaut est RÉCURRENT (texte gris sur fond sombre, `text-dark` sur le thème
sombre) et aucun test ne le voyait : une couleur RÉELLE se décide dans le navigateur — classes
Bootstrap, variables du thème, styles posés par le JS, fond hérité d'un parent —, jamais dans une
source. D'où une mesure au NAVIGATEUR, par la règle `color-contrast` d'axe-core (la référence
du domaine ; paquet `axe-playwright-python`, entré par la route `library`, qui l'embarque — il
n'est jamais servi aux pages, seul le navigateur des scénarios l'injecte).

LE VERDICT, et pourquoi deux régimes :
  • rapport < `ILLEGIBLE` (1,5) : le texte a (presque) la couleur du fond → ÉCHEC ;
  • sous le seuil WCAG (4,5 ; 3 pour un grand texte) : un texte FAIBLE → listé, sans échec. Le
    compter en échec ferait un rouge permanent, que plus personne ne lirait. Il est regroupé par
    COMPOSANT (`signature` : balise + première classe), pas par nœud — une médiathèque de 22 voix
    n'est pas 22 défauts, et un compte par nœud varierait d'une nuit à l'autre avec les données.

CHAQUE THÈME déclaré (`common/themes.py`) est joué, posé comme `base.html` le pose : une
couleur juste dans le sombre peut disparaître dans le clair, et c'est ce scénario qui le verra.

La mesure (`measure_contrast`) est aussi jouée par `<app>.preview` sur les états que seule une
file HABITÉE montre : cards, volet de l'élément sélectionné, visionneuse ouverte.

Mesuré le jour de l'écriture (site réel, compte de test, 33 pages) : aucun texte illisible ; deux
composants communs sous 3:1 — le compteur de la barre de filtres (`#6c757d` sur `#2b3035`, 2,83,
sur toutes les pages catalogue) et la ligne méta des cards de la médiathèque (`#666`, 2,98) —,
corrigés le même jour à leur domicile CSS.
"""
import re
from collections import Counter

from .ui_smoke import BASE_URL, _motif_skip, _test_session_key, discoverable_apps
from .ui_smoke_matching import _cookie

#: Sous ce rapport, le texte a (presque) la couleur de son fond : un ÉCHEC.
ILLEGIBLE = 1.5
PAGE_TIMEOUT_MS = 60000

#: La règle seule, et les seules violations : les « incomplets » d'axe (un texte sur une image,
#: une vidéo, un dégradé) ne se tranchent pas par un calcul de couleur.
_RUN = """async (context) => {
    const options = {runOnly: {type: 'rule', values: ['color-contrast']}, resultTypes: ['violations']};
    const found = await axe.run(context ? document.querySelector(context) || document : document, options);
    return found.violations.flatMap(v => v.nodes).map(n => ({
        target: n.target.join(' '), html: n.html.slice(0, 300),
        data: ((n.any || [])[0] || {}).data || {}}));
}"""


def _axe_script() -> str:
    from axe_playwright_python.base import AXE_SCRIPT
    return AXE_SCRIPT


def signature(html: str, target: str = '') -> str:
    """Le COMPOSANT d'un nœud : sa balise et sa première classe (`span.wama-filter-count`), sinon
    le dernier maillon de son sélecteur sans rang ni attribut. Pure (`tests_contrast`)."""
    m = re.match(r'\s*<([a-zA-Z0-9-]+)([^>]*)>', html or '')
    if m:
        classes = re.search(r'\bclass\s*=\s*["\']([^"\']*)["\']', m.group(2))
        first = (classes.group(1).split() or [''])[0] if classes else ''
        if first and '{' not in first:
            return f"{m.group(1).lower()}.{first}"
    last = (target or '').split('>')[-1].strip()
    return re.sub(r':nth-[a-z-]+\([^)]*\)|\[[^\]]*\]', '', last) or (m.group(1).lower() if m else '?')


def _number(value):
    """Un rapport d'axe : un nombre (`contrastRatio`) ou un texte (`expectedContrastRatio`,
    « 4.5:1 ») — sa valeur, ou None. Pure (`tests_contrast`)."""
    m = re.match(r'\s*([0-9]+(?:\.[0-9]+)?)', str(value if value is not None else ''))
    return float(m.group(1)) if m else None


def measure_contrast(page, context: str = '') -> list:
    """Les textes sous leur seuil de contraste dans `page` (ou dans le seul `context`, un
    sélecteur — la visionneuse ouverte) : `[{ratio, expected, fg, bg, size, signature, target}]`."""
    page.evaluate(_axe_script())
    nodes = page.evaluate(_RUN, context or None)
    out = []
    for node in nodes:
        data = node.get('data') or {}
        out.append({'ratio': _number(data.get('contrastRatio')) or 0.0,
                    'expected': _number(data.get('expectedContrastRatio')),
                    'fg': data.get('fgColor'), 'bg': data.get('bgColor'),
                    'size': data.get('fontSize'),
                    'signature': signature(node.get('html'), node.get('target')),
                    'target': node.get('target')})
    return out


def contrast_verdict(nodes, where: str) -> tuple:
    """(défauts, composants faibles) — un défaut par composant ILLISIBLE (rapport < `ILLEGIBLE`),
    et le compte des composants simplement faibles. Pure (`tests_contrast`)."""
    illegible = {}
    weak = Counter()
    for n in nodes:
        if n['ratio'] < ILLEGIBLE:
            illegible.setdefault(n['signature'], n)
        else:
            weak[n['signature']] += 1
    faults = [f"{where} : texte ILLISIBLE {sig} — {n['fg']} sur {n['bg']} (rapport {n['ratio']:.2f})"
              for sig, n in sorted(illegible.items())]
    return faults, weak


def contrast_pages() -> list:
    """Les pages mesurées : la page de chaque app RÉELLE (les jumelles sont des copies) et chaque
    page du menu du compte, d'après leurs déclarations — aucune liste à tenir ici."""
    from django.urls import reverse

    from wama.common.app_registry import APP_CATALOG, account_pages
    from wama.common.sandbox import non_sandbox_apps
    real = set(non_sandbox_apps(APP_CATALOG))
    pages = [(label, path) for label, path in discoverable_apps() if label in real]
    for page in account_pages():
        if page['url_name']:
            pages.append((f"compte · {page['label']}", reverse(page['url_name'])))
    return pages


#: Le thème posé comme `base.html` le pose : les deux attributs de <html>, rien d'autre.
_APPLY_THEME = """([key, bootstrap]) => {
    document.documentElement.setAttribute('data-wama-theme', key);
    document.documentElement.setAttribute('data-bs-theme', bootstrap);
}"""


def apply_theme(page, theme):
    """Pose `theme` sur la page mesurée comme `base.html` le pose. Un thème GÉNÉRÉ reçoit en plus
    le bloc qu'un compte a pour la couleur par défaut ; le générateur tient le contraste de TOUTE
    graine (`tests_theme.GeneratedThemeTest`)."""
    from wama.common.themes import DEFAULT_ACCENT, generated_css
    page.evaluate(_APPLY_THEME, [theme.key, theme.bootstrap])
    if theme.generated:
        page.add_style_tag(content=generated_css(theme.key, DEFAULT_ACCENT))


def check_contrast():
    """Chaque page mesurée, dans CHAQUE thème déclaré (`common/themes.py`) : aucun texte
    illisible. (ok, détail)."""
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario
    from wama.common.themes import THEMES

    token = _test_session_key()
    if not token:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    faults, weak, measured, skipped = [], Counter(), 0, []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(viewport={'width': 1600, 'height': 1000})
            context.add_cookies(_cookie(token))
            page = context.new_page()
            for theme in THEMES:
                for name, path in contrast_pages():
                    where = name if len(THEMES) == 1 else f"{name} [{theme.label}]"
                    try:
                        response = page.goto(f"{BASE_URL.rstrip('/')}{path}", wait_until='networkidle',
                                             timeout=PAGE_TIMEOUT_MS)
                    except Exception as exc:
                        skipped.append(f"{where} ({_motif_skip(exc)})")
                        continue
                    if not response or response.status != 200:
                        continue        # page refusée au compte de test : son droit, pas un défaut
                    apply_theme(page, theme)
                    page.wait_for_timeout(600)
                    page_faults, page_weak = contrast_verdict(measure_contrast(page), where)
                    faults += page_faults
                    weak.update(page_weak)
                    measured += 1
        finally:
            browser.close()
    if not measured:
        raise SkipScenario("aucune page mesurée : " + '; '.join(skipped[:5]))
    weak_text = ', '.join(f"{sig} ×{n}" for sig, n in weak.most_common(8)) or 'aucun'
    if faults:
        return False, ' ; '.join(faults)
    themes = ', '.join(t.label for t in THEMES)
    return True, (f"{measured} pages mesurées (thème : {themes}) : aucun texte illisible (rapport < {ILLEGIBLE}) ; "
                  f"composants faibles (sous le seuil WCAG) : {weak_text}"
                  + (f" ; non mesurées : {', '.join(skipped)}" if skipped else ''))


def register_contrast_scenarios():
    from wama.common.services.nightly_tests import register
    register(
        id="common.contrast", app="common", stage="ui",
        description=("Contraste : aucun texte de la couleur de son fond (axe-core, règle "
                     "color-contrast) sur la page de chaque app et chaque page du menu du compte ; "
                     "les composants faibles sont listés"),
        run=lambda ctx: check_contrast(),
        timeout_s=600, vram_gb=0.0,
    )

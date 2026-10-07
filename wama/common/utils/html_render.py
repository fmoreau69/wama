"""
html_render — Rendu HTML → PDF FIDÈLE, brique COMMUNE réutilisable.

Capacité générique (pas propre au converter) : rendre une page web / du HTML en
PDF. Utilisable par le converter, le describer (description visuelle d'une page
web à venir), les exports stylés, les miniatures, etc.

Route à 2 moteurs :
  1. Chromium headless (Playwright) — PRÉFÉRÉ : CSS moderne complet
     (clamp/place-items/box-shadow/var…), exécution du JS, et breakpoints
     responsive (media=screen) → la page reflow proprement dans A4 sans coupe.
  2. WeasyPrint — fallback : CSS partiel, pas de JS, mais aucune dépendance
     navigateur (serveur non provisionné = marche quand même).

Le navigateur n'est PAS un modèle IA : il vit dans le cache Playwright par défaut
(`~/.cache/ms-playwright`, régénérable), surchargeable via PLAYWRIGHT_BROWSERS_PATH.
Provisioning : `playwright install --with-deps chromium` (voir start_wama_prod.sh).
"""
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Force visible le contenu à « révélation au scroll » (IntersectionObserver / AOS /
# .reveal…) qui démarre en opacity:0. Partagé par les deux moteurs.
_REVEAL_SELECTORS_CSS = (
    '[class*="reveal"],[class*="fade"],[class*="scroll-"],'
    '[data-reveal],[data-aos],.aos-init,.wow{'
    'opacity:1!important;transform:none!important;'
    'animation:none!important;visibility:visible!important}'
)


def _find_chromium_executable():
    """Localise le binaire Chromium complet téléchargé par Playwright.

    Playwright ≥1.5x privilégie `chrome-headless-shell` (téléchargement séparé,
    parfois KO derrière proxy) ; on cible d'abord le Chromium complet, utilisable
    en headless. Cherche dans PLAYWRIGHT_BROWSERS_PATH (si défini), sinon le cache
    par défaut. Retourne None si rien trouvé.
    """
    import glob
    bases = []
    if os.environ.get('PLAYWRIGHT_BROWSERS_PATH'):
        bases.append(os.environ['PLAYWRIGHT_BROWSERS_PATH'])
    bases.append(os.path.expanduser('~/.cache/ms-playwright'))
    for base in bases:
        for pat in ('chromium-*/chrome-linux*/chrome',
                    'chromium_headless_shell-*/*/chrome-headless-shell'):
            hits = sorted(glob.glob(os.path.join(base, pat)))
            if hits:
                return hits[-1]
    return None


#: Pilote Gallium D3D12 de Mesa — c'est LUI que `GALLIUM_DRIVER=d3d12` charge ; il parle au GPU
#: Windows par `/dev/dxg` et `/usr/lib/wsl/lib/libd3d12.so`. ⚠ Mesuré le 2026-09-30 : il n'est
#: PAS dans `/usr/lib/wsl/lib/` (ma 1ʳᵉ version le cherchait là et rendait toujours False).
_MESA_D3D12_DRIVERS = ('/usr/lib/x86_64-linux-gnu/dri/d3d12_dri.so', '/usr/lib/dri/d3d12_dri.so')


def _wsl_gpu_available() -> bool:
    """Vrai si le pilote D3D12 de WSL est là : Chromium peut alors rendre sur le VRAI GPU."""
    from wama.common.utils.ffmpeg_utils import is_wsl
    return (is_wsl() and os.path.exists('/dev/dxg')
            and any(os.path.exists(p) for p in _MESA_D3D12_DRIVERS))


def launch_chromium(playwright, gpu: bool = False, extra_args=()):
    """Chromium headless (Playwright sync) — lanceur COMMUN, extrait au 2ᵉ consommateur.

    Consommateurs : le rendu HTML → PDF (ci-dessous, `gpu=False`) et le rendu vidéo d'un avatar
    3D (`backends/talkinghead_backend.py`, `gpu=True`, 2026-09-30).

    `gpu=True` : sous WSL, WebGL passe par le pilote D3D12 (`--use-angle=gl-egl` +
    `GALLIUM_DRIVER=d3d12`). MESURÉ le 2026-09-30 : renderer `D3D12 (NVIDIA GeForce RTX 4090)`,
    TalkingHead à 60 i/s en 1280×720 — contre SwiftShader (CPU) par défaut, ~5,7 i/s. Les autres
    chemins essayés (`--use-angle=vulkan`, `--use-gl=egl`) retombent sur SwiftShader/llvmpipe ou
    bloquent. Hors WSL (ou pilote absent), on reste sur le défaut : plus lent, jamais cassé.
    """
    exe = _find_chromium_executable()
    args = ['--no-sandbox', *extra_args]
    env = None
    if gpu and _wsl_gpu_available():
        args += ['--use-angle=gl-egl', '--ignore-gpu-blocklist', '--enable-gpu']
        env = {**os.environ, 'GALLIUM_DRIVER': 'd3d12'}
        # ⚠ MESURÉ (2026-09-30, 4 cas croisés) : le Chromium COMPLET reste sur SwiftShader avec
        # ces mêmes drapeaux ; le `chrome-headless-shell` par défaut de Playwright prend la 4090
        # (avec ou sans `--no-sandbox`). En mode GPU on laisse donc Playwright choisir son binaire.
        exe = None
    elif not gpu:
        args.append('--disable-gpu')
    kwargs = {'args': args}
    if env:
        kwargs['env'] = env
    if exe:
        kwargs['executable_path'] = exe
    return playwright.chromium.launch(**kwargs)


def _html_to_pdf_chromium(input_path: str, output_path: str) -> bool:
    """HTML → PDF via Chromium headless (Playwright) — rendu FIDÈLE.

    Retourne False si Playwright/navigateur indisponible (→ fallback WeasyPrint),
    SANS lever : un serveur non encore provisionné reste fonctionnel.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    src_url = 'file://' + os.path.abspath(input_path)
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p, gpu=False)
            try:
                page = browser.new_page(viewport={'width': 820, 'height': 1123})
                page.goto(src_url, wait_until='networkidle', timeout=30000)
                # Reveals au scroll → visibles (déterministe) + scroll intégral pour
                # déclencher tout IntersectionObserver restant.
                page.add_style_tag(content=_REVEAL_SELECTORS_CSS)
                page.evaluate(
                    "()=>new Promise(r=>{let y=0;const t=setInterval(()=>{"
                    "window.scrollBy(0,600);y+=600;"
                    "if(y>=document.body.scrollHeight){clearInterval(t);r()}},20)})"
                )
                page.wait_for_timeout(300)
                page.emulate_media(media='screen')   # applique les breakpoints responsive
                page.pdf(path=output_path, format='A4', print_background=True,
                         margin={'top': '0', 'bottom': '0', 'left': '0', 'right': '0'})
            finally:
                browser.close()
    except Exception as e:  # navigateur absent, libs OS manquantes, timeout…
        logger.warning(f"Chromium HTML→PDF indisponible ({e}) → fallback WeasyPrint")
        return False
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        return False
    return True


def _html_to_pdf_weasyprint(input_path: str, output_path: str) -> bool:
    """HTML → PDF via WeasyPrint (moteur CSS, SVG inline natif) — fallback.

    Sans dépendance navigateur ni LaTeX/rsvg-convert. CSS moderne partiel et pas
    de JS (les reveals sont forcés visibles par la feuille d'impression).
    Retourne False si WeasyPrint absent.
    """
    try:
        from weasyprint import HTML, CSS
    except ImportError:
        return False
    _reveal_css = CSS(string=_REVEAL_SELECTORS_CSS)
    # base_url = dossier source → résout les chemins relatifs (CSS/images locaux)
    HTML(filename=input_path, base_url=os.path.dirname(input_path)).write_pdf(
        output_path, stylesheets=[_reveal_css])
    if not os.path.exists(output_path):
        raise RuntimeError(f"WeasyPrint n'a produit aucun fichier : {output_path}")
    return True


#: Les commandes d'une présentation « canvas » (barre du haut, barre du bas, aide) : hors du PDF.
_SLIDES_CHROME_CSS = '#hud-top,#hud-bottom,#progress,#help{display:none!important}'

#: Un document en pages A4 : fond blanc (la marge d'impression ne prend pas le fond de la page), une
#: figure, une image ou une ligne de tableau ne se coupe pas entre deux pages.
_DOCUMENT_PRINT_CSS = ('html,body{background:#fff!important}'
                       'figure,img,svg,tr,pre,blockquote{break-inside:avoid}h1,h2,h3{break-after:avoid}')

#: Ce qui est FIXÉ à l'écran (bouton de retour, bouton d'export…) se répéterait sur chaque page.
_HIDE_FIXED_JS = """() => document.querySelectorAll('body *').forEach(el => {
  if (getComputedStyle(el).position === 'fixed') el.style.setProperty('display', 'none', 'important');
})"""

#: Une étape de présentation, posée SANS vol, et attendue jusqu'à `settled` (`wama-presentation.js`).
_GO_STEP_JS = """i => new Promise(r => {
  const h = e => { if (e.detail.settled) { document.removeEventListener('wama:step', h); r(); } };
  document.addEventListener('wama:step', h);
  window.WamaPrez.go(i, {instant: true});
})"""


def render_page_to_pdf(html: str, output_path: str, *, fetch, path: str = '/', slides: bool = False,
                       origin: str = 'http://wama.page') -> bool:
    """Une PAGE de WAMA (HTML déjà rendu) → PDF, par Chromium headless, sans passer par le serveur.

    Tout ce que la page demande à son origine (statiques, JSON) passe par `fetch(path_et_requête)`, qui
    rend `(statut, type, octets)` : l'appelant sert depuis le disque et ses vues, en processus. Le
    serveur ne s'appelle donc jamais lui-même (un worker unique s'y bloquerait).

    `slides=False` : document en A4, comme `render_html_to_pdf`. `slides=True` : présentation au moteur
    « canvas » (`window.WamaPrez`) — une page 16:9 par étape, image de l'étape posée sans vol, commandes
    masquées. WebGL sur le PROCESSEUR (SwiftShader) : jamais de carte graphique pour un export.
    Retourne False si Chromium est indisponible.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    def serve(route):
        url = route.request.url
        if not url.startswith(origin):
            return route.abort()          # aucune sortie réseau : la page est rendue hors ligne
        if url.split('?')[0].split('#')[0] == origin + path:
            return route.fulfill(status=200, content_type='text/html; charset=utf-8', body=html)
        status, ctype, body = fetch(url[len(origin):])
        return route.fulfill(status=status, content_type=ctype, body=body)

    try:
        with sync_playwright() as p:
            browser = launch_chromium(p, gpu=False, extra_args=('--enable-unsafe-swiftshader',))
            try:
                size = {'width': 1600, 'height': 900} if slides else {'width': 820, 'height': 1123}
                ctx = browser.new_context(viewport=size, color_scheme='light', reduced_motion='reduce')
                ctx.route('**/*', serve)
                page = ctx.new_page()
                page.goto(origin + path, wait_until='networkidle', timeout=60000)
                if not slides:
                    page.add_style_tag(content=_REVEAL_SELECTORS_CSS + _DOCUMENT_PRINT_CSS)
                    page.evaluate(_HIDE_FIXED_JS)
                    page.emulate_media(media='screen')
                    page.pdf(path=output_path, format='A4', print_background=True,
                             margin={'top': '10mm', 'bottom': '10mm', 'left': '0', 'right': '0'})
                else:
                    import base64
                    page.add_style_tag(content=_SLIDES_CHROME_CSS)
                    shots = []
                    for i in range(page.evaluate('window.WamaPrez.steps.length')):
                        page.evaluate(_GO_STEP_JS, i)
                        page.wait_for_timeout(700)      # une scène 3D s'accroche à `settled`, puis rend
                        shots.append(base64.b64encode(page.screenshot(type='jpeg', quality=88)).decode())
                    book = ctx.new_page()
                    book.set_content(
                        '<style>@page{size:1600px 900px;margin:0}body{margin:0}'
                        'img{display:block;width:1600px;height:900px;break-after:page}</style>'
                        + ''.join(f'<img src="data:image/jpeg;base64,{s}">' for s in shots))
                    book.pdf(path=output_path, width='1600px', height='900px', print_background=True,
                             margin={'top': '0', 'bottom': '0', 'left': '0', 'right': '0'})
            finally:
                browser.close()
    except Exception as e:  # navigateur absent, libs OS manquantes, timeout…
        logger.warning(f"Page → PDF indisponible ({e})")
        return False
    return os.path.exists(output_path) and os.path.getsize(output_path) > 0


def render_html_to_pdf(input_path: str, output_path: str) -> bool:
    """HTML → PDF fidèle : Chromium headless (préféré) → WeasyPrint (fallback).

    Brique COMMUNE. Retourne True si un moteur a produit le PDF, False sinon
    (l'appelant peut alors tenter une dernière route, ex. pandoc).
    """
    if _html_to_pdf_chromium(input_path, output_path):
        logger.info(f"HTML → PDF (Chromium, rendu fidèle) : {input_path} → {output_path}")
        return True
    if _html_to_pdf_weasyprint(input_path, output_path):
        logger.info(f"HTML → PDF (WeasyPrint, fallback) : {input_path} → {output_path}")
        return True
    return False

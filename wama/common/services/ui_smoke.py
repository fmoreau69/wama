"""
Smoke UI nocturne : charge chaque page d'app dans un vrai navigateur et vérifie qu'elle vit.

POURQUOI. Une erreur JS casse SILENCIEUSEMENT une page entière : le navigateur arrête le script,
et il n'y a RIEN dans les logs serveur. `scripts/check_js.sh` (node --check) n'attrape que la
syntaxe — pas un `MediaPicker has already been declared` ni un `X is not defined` au chargement.
La première exécution manuelle de cette passe (2026-07-30) a trouvé une double inclusion de
brique globale sur deux apps, sur des pages utilisées quotidiennement sans que personne ne voie
rien. C'est le mode de panne le plus coûteux du projet.

TROIS COUCHES, ET UNE SEULE DÉCIDE.
1. **Barrière déterministe** (elle seule fait échouer) : HTTP 200, **zéro erreur console**,
   présence d'un sélecteur clé. Reproductible, échoue toujours pareil, coût nul.
2. **Diff de capture** contre une référence : dit OÙ ça a bougé. Ne fait PAS échouer — une file
   d'attente, une barre de ressources ou une date changent d'une nuit à l'autre, en faire un
   critère produirait du bruit qu'on apprendrait à ignorer.
3. **Triage par modèle vision local** : dit QUOI, en français, et UNIQUEMENT sur les captures qui
   ont bougé. Il n'est pas juge — un VLM affirme volontiers qu'une page cassée « semble
   correcte », et sa réponse varie d'une nuit à l'autre. Il te fait lire trois phrases au lieu
   d'ouvrir dix captures. Même précaution que `bench_describer` : le juge final reste humain.

Sous WSL2, où vivent le serveur ET les navigateurs Playwright (`~/.cache/ms-playwright`).
"""
from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings

BASE_URL = os.environ.get('WAMA_UI_SMOKE_BASE', 'http://127.0.0.1:8000')
SHOTS_DIR = Path(settings.BASE_DIR) / 'logs' / 'ui_smoke'
REF_DIR = SHOTS_DIR / 'reference'
CUR_DIR = SHOTS_DIR / 'current'

# Au-delà de ce ratio de pixels changés, la capture part au triage VLM (elle ne casse rien).
DIFF_TRIAGE_RATIO = 0.02
# Modèle vision : défaut de `bench_describer`, installé. Résidence courte → les scénarios UI
# s'enchaînent sans repayer le chargement, et le modèle expire tout seul après la série.
VLM_MODEL = os.environ.get('WAMA_UI_SMOKE_VLM', 'gemma4:12b')
VLM_KEEP_ALIVE = '120s'

# Erreurs console à ignorer : bruit d'environnement, pas des régressions applicatives.
IGNORED_CONSOLE = (
    'favicon',                    # 404 d'icône, sans effet fonctionnel
    'ERR_INTERNET_DISCONNECTED',  # poste hors ligne (assets locaux, cf. règle « pas de CDN »)
)


def _viewport_screenshot(url, png_path, selector=None, timeout_ms=45000):
    """Charge `url`, retourne (status, erreurs_js, selector_trouvé). Écrit la capture."""
    from playwright.sync_api import sync_playwright

    errors, status, found = [], None, None
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1500, 'height': 1000})
            page.on('console', lambda m: errors.append(f"console.{m.type}: {m.text}")
                    if m.type == 'error' else None)
            page.on('pageerror', lambda e: errors.append(f"pageerror: {e}"))
            resp = page.goto(url, wait_until='networkidle', timeout=timeout_ms)
            status = resp.status if resp else None
            if selector:
                found = page.locator(selector).count() > 0
            page.screenshot(path=str(png_path), full_page=False)
        finally:
            browser.close()
    keep = [e for e in errors if not any(tok in e for tok in IGNORED_CONSOLE)]
    return status, keep, found


def _diff_ratio(current: Path, reference: Path):
    """Part de pixels différents entre deux captures. None si pas comparable."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return None
    if not reference.exists():
        return None
    try:
        a = Image.open(current).convert('RGB')
        b = Image.open(reference).convert('RGB')
        if a.size != b.size:
            return 1.0                       # changement de gabarit = à regarder
        diff = ImageChops.difference(a, b).convert('L')
        changed = sum(1 for px in diff.getdata() if px > 24)
        return changed / float(a.size[0] * a.size[1])
    except Exception:
        return None


def _vlm_triage(png_path: Path, app: str):
    """Description en français de ce que MONTRE la capture. Jamais un verdict."""
    from wama.model_manager.services.vision_probe import describe_image_ollama

    res = describe_image_ollama(
        str(png_path), model=VLM_MODEL, timeout=180, keep_alive=VLM_KEEP_ALIVE,
        prompt=(f"Cette capture est la page de l'application « {app} » d'une plateforme web. "
                "Signale UNIQUEMENT ce qui semble cassé : zone vide qui devrait être remplie, "
                "texte qui déborde ou tronqué, éléments superposés, message d'erreur visible. "
                "Si rien ne cloche, réponds exactement « RAS ». Trois phrases maximum."))
    if not res.get('ok'):
        return f"triage VLM indisponible ({res.get('error')})"
    return (res.get('description') or '').strip()


def check_app_page(app: str, url_path: str, selector: str | None = None):
    """
    Scénario UI d'une app. Retourne (ok, detail) — contrat `Scenario.run`.

    Seule la couche 1 décide du succès. Les couches 2 et 3 enrichissent `detail`.
    """
    from wama.common.services.nightly_tests import SkipScenario

    url = f"{BASE_URL.rstrip('/')}{url_path}"
    try:
        status, errors, found = _viewport_screenshot(url, CUR_DIR / f"{app}.png", selector)
    except Exception as e:
        # Serveur éteint ou navigateur absent = dépendance manquante, pas une régression.
        raise SkipScenario(f"page injoignable ({type(e).__name__}: {str(e)[:120]})")

    # ── Couche 1 : la barrière ────────────────────────────────────────────────
    problems = []
    if status != 200:
        problems.append(f"HTTP {status}")
    if errors:
        problems.append(f"{len(errors)} erreur(s) JS : " + " | ".join(errors[:3]))
    if selector and not found:
        problems.append(f"sélecteur absent : {selector}")

    # ── Couches 2 et 3 : où, puis quoi ────────────────────────────────────────
    extra = ""
    cur, ref = CUR_DIR / f"{app}.png", REF_DIR / f"{app}.png"
    ratio = _diff_ratio(cur, ref)
    if ratio is None and not ref.exists():
        REF_DIR.mkdir(parents=True, exist_ok=True)
        try:
            ref.write_bytes(cur.read_bytes())
            extra = " ; référence de capture créée"
        except OSError:
            pass
    elif ratio is not None and ratio > DIFF_TRIAGE_RATIO:
        extra = f" ; capture modifiée à {ratio:.1%} → {_vlm_triage(cur, app)}"

    if problems:
        return False, "; ".join(problems) + extra
    return True, f"page OK (HTTP 200, 0 erreur JS){extra}"


def discoverable_apps():
    """
    Apps exposant une page d'index, DÉDUITES des URLs — aucune liste en dur à maintenir.
    Retourne [(label, chemin)].
    """
    from django.apps import apps as django_apps
    from django.urls import NoReverseMatch, reverse

    out = []
    for cfg in django_apps.get_app_configs():
        if not (cfg.name or '').startswith('wama.'):
            continue
        try:
            out.append((cfg.label, reverse(f"{cfg.label}:index")))
        except NoReverseMatch:
            continue
    return sorted(out)


def register_ui_scenarios():
    """Enregistre un scénario `<app>.ui` par app disposant d'une page d'index."""
    from wama.common.services.nightly_tests import register

    for label, path in discoverable_apps():
        register(
            id=f"{label}.ui", app=label, stage="ui",
            description=f"Page {label} : HTTP 200, zéro erreur console JS",
            # Sélecteur MESURÉ sur les 13 pages (2026-07-31), pas supposé : `#appTabsContent`
            # vient du gabarit commun (10 apps) ; media_library, model_manager et studio ont
            # leur propre gabarit et n'ont que `.container-fluid`. La liste CSS couvre les deux
            # familles et atteste que la page a bien rendu sa coquille de contenu.
            run=(lambda p=path, a=label: (
                lambda ctx: check_app_page(a, p, selector='#appTabsContent, .container-fluid')
            ))(),
            timeout_s=120, vram_gb=0.0,
        )

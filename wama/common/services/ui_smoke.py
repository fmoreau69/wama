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

⚠ CRON : exporter `OLLAMA_HOST` (Ollama tourne sur l'hôte WINDOWS ; `127.0.0.1` depuis WSL2 ne
l'atteint pas). Sans lui, les couches 1 et 2 fonctionnent mais le triage échoue silencieusement
en « triage VLM indisponible » — piège rencontré deux fois pendant la mise au point.

CALIBRATION (2026-07-31) : deux passages consécutifs avec des références fraîches donnent
0 déclenchement sur 13 — le diff est stable, donc le VLM ne coûte rien les nuits sans
changement. Si un changement d'UI est VOULU, supprimer les références concernées : elles se
recréent au passage suivant (sinon le triage se déclenche chaque nuit et le signal se dilue).
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


def _session_keys():
    """Clés de session existantes — photo prise AVANT le passage."""
    try:
        from django.contrib.sessions.models import Session
        return set(Session.objects.values_list('session_key', flat=True))
    except Exception:
        return set()


def _drop_new_sessions(before: set):
    """
    Supprime les sessions créées PAR ce passage, sans jamais toucher celle d'un utilisateur.

    Une page en crée PLUSIEURS (chaque requête sans cookie en ouvre une) : viser la seule clé du
    cookie du navigateur ne nettoyait presque rien (mesuré : +8 lignes malgré la suppression).
    On supprime donc toutes les clés APPARUES pendant le passage — mais **uniquement les
    anonymes** : une session portant `_auth_user_id` appartient à quelqu'un de connecté, et la
    supprimer déconnecterait un utilisateur réel qui travaillerait pendant le passage. Un test ne
    doit jamais causer ça.
    """
    try:
        from django.contrib.sessions.models import Session
        new = Session.objects.exclude(session_key__in=before)
        doomed = [s.session_key for s in new if not s.get_decoded().get('_auth_user_id')]
        return Session.objects.filter(session_key__in=doomed).delete()[0] if doomed else 0
    except Exception:
        return 0


def _exercise_page(url, png_path, selector=None, timeout_ms=45000):
    """
    Charge `url`, PARCOURT LES ONGLETS, écrit la capture.

    Pourquoi interagir : charger une page ne teste que le rendu initial, or la majorité des
    erreurs JS vivent dans les GESTIONNAIRES d'événements — elles n'apparaissent qu'au clic.
    Les onglets sont le seul geste réellement commun (mesuré : présents sur 10 des 13 apps).

    Retourne (status, erreurs_js, sélecteur_trouvé, nb_onglets_parcourus, session_supprimée).
    """
    from playwright.sync_api import sync_playwright

    errors, status, found, tabs_done = [], None, None, 0
    png_path.parent.mkdir(parents=True, exist_ok=True)
    sessions_before = _session_keys()
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

            # Onglets : le seul geste réellement commun aux apps. Deux précautions, toutes deux
            # apprises en mesurant (2026-07-31) :
            #  - beaucoup d'onglets sont MASQUÉS au repos (describer : 4 visibles sur 7) — cliquer
            #    un élément invisible n'est pas un geste utilisateur ;
            #  - nos propres clics MUTENT le DOM (changer de mode masque les onglets suivants :
            #    l'imager a 6 onglets visibles au chargement, plus autant après le 4e clic).
            # D'où : on revérifie la visibilité juste avant chaque clic, et un échec n'est une
            # ERREUR que si l'onglet est TOUJOURS visible après coup — sinon c'est notre propre
            # navigation qui l'a escamoté. Une barrière qui crie au loup ne serait pas relue.
            tabs = page.locator('[data-bs-toggle="tab"]')
            for i in range(min(tabs.count(), 8)):          # borne : pas de page à 30 onglets
                tab = tabs.nth(i)
                try:
                    if not tab.is_visible():
                        continue
                    tab.click(timeout=4000)
                    page.wait_for_timeout(250)             # laisse le gestionnaire s'exécuter
                    tabs_done += 1
                except Exception as e:
                    still_there = False
                    try:
                        still_there = tab.is_visible()
                    except Exception:
                        pass
                    if still_there:
                        errors.append(f"onglet {i} visible mais non cliquable: {type(e).__name__}")
            if tabs_done:
                page.wait_for_timeout(400)                 # laisse remonter une erreur tardive

            page.screenshot(path=str(png_path), full_page=False)
        finally:
            browser.close()
    dropped = _drop_new_sessions(sessions_before)
    keep = [e for e in errors if not any(tok in e for tok in IGNORED_CONSOLE)]
    return status, keep, found, tabs_done, dropped


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
        status, errors, found, tabs, dropped = _exercise_page(
            url, CUR_DIR / f"{app}.png", selector)
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

    gestes = f"{tabs} onglet(s) parcouru(s)" if tabs else "aucun onglet"
    trace = f" ; {dropped} session(s) nettoyée(s)" if dropped else ""
    if problems:
        return False, "; ".join(problems) + f" [{gestes}]" + extra + trace
    return True, f"page OK (HTTP 200, 0 erreur JS, {gestes}){extra}{trace}"


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

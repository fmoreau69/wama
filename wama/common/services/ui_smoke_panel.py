"""Scénarios nocturnes `ui` — le VOLET de réglages reflète la card sélectionnée, puis la FILE.

Né du portage du 2026-10-11 (volets de l'avatarizer, du synthesizer et de l'enhancer rendus du
schéma, `WamaParams.render(context:'panel')`). La règle du volet droit est celle de Fabien :
aucune sélection = réglages de la FILE, card sélectionnée = réglages de la CARD. Aucun test Python
ne la voit — elle vit dans le navigateur, entre le rendu du volet, ses options chargées après coup
et l'applicateur de l'inspecteur. Et elle casse SANS erreur : le 2026-10-11, une liste du
catalogue liée deux fois retombait sur « auto » au lieu de la valeur mémorisée (corrigé à la
brique, `wama-params.js`), et rien ne l'a dit avant une sonde.

CE QU'IL MESURE, sans connaître aucun schéma : les champs GÉNÉRÉS du volet (`[data-param]`).
  1. relevé du volet avant toute sélection (réglages de file) ;
  2. sélection d'une card : chaque champ qui a son pendant dans le ⚙ de la card (lecteur commun
     `WamaInspector.gearValues`) en montre la valeur ;
  3. désélection par le ✕ : le volet revient à son relevé.
⚠ Il ne MODIFIE aucun réglage : changer un champ du volet écrirait les préférences du compte de
test chez les apps qui enregistrent au geste. La card témoin porte donc les réglages de file —
la mesure dit qu'une valeur est APPLIQUÉE et RENDUE, pas qu'elle diffère. Le cas « card ≠ file »
a été mesuré au portage par une sonde qui posait les colonnes en base.

Module à part d'`ui_smoke.py` (même raison qu'`ui_smoke_states`) ; il en réutilise les briques et
ne redéfinit rien. ⚠ Tout l'ORM est HORS du contexte Playwright (`SynchronousOnlyOperation`).
"""
from .ui_smoke import (BASE_URL, _clic_de_deselection, _exiger_la_page, _garde_de_montage,
                       _monter_un_lot, _motif_skip, _test_session_key, _total_nettoye,
                       discoverable_apps)
from .ui_smoke_matching import _cookie

#: Les champs générés du volet droit et leur valeur, normalisée (case → 'true'/'false').
JS_PANEL = """() => {
    const host = document.getElementById('wama-right-panel');
    if (!host) return null;
    const out = {};
    host.querySelectorAll('[data-param]').forEach(el => {
        const name = el.getAttribute('data-param');
        if (el.type === 'radio') { if (el.checked) out[name] = el.value; return; }
        out[name] = el.type === 'checkbox' ? String(el.checked) : String(el.value);
    });
    return out;
}"""

#: Sélectionne la première card visible (lot déplié comme le ferait son chevron) par un clic DOM
#: sur la card elle-même — la délégation remonte par `closest`, la card n'est pas une zone ignorée.
#: Rend l'id et ce que le ⚙ de la card dit des champs du volet.
JS_SELECT = """(names) => {
    document.querySelectorAll('.batch-group .collapse').forEach(c => c.classList.add('show'));
    const visible = e => { const r = e.getBoundingClientRect(); return r.width > 4 && r.height > 4; };
    const card = Array.from(document.querySelectorAll('.wama-card[data-id]:not(.is-batch)'))
                      .find(visible);
    if (!card) return null;
    const gear = window.WamaInspector && window.WamaInspector.gearValues
        ? window.WamaInspector.gearValues(card, names) : {};
    card.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
    return {id: card.dataset.id, gear: gear};
}"""


#: Le live sert en DEBUG depuis `/mnt/d` : une page de file y dépasse 45 s (mesuré le 11/10, 9 délais
#: sur 23 au premier passage). La mesure porte sur le volet, pas sur la vitesse de la page.
PAGE_TIMEOUT_MS = 90000


def _evaluate(page, script, arg=None):
    """`page.evaluate`, relu (trois fois au plus) si la page s'est rechargée sous la mesure — le montage d'un
    lot et certaines files rechargent la page (« Execution context was destroyed », 7 sur 23 au
    premier passage). Ce n'est pas un défaut du volet : on attend la page neuve et on relit."""
    for attempt in range(3):
        try:
            return page.evaluate(script, arg) if arg is not None else page.evaluate(script)
        except Exception as exc:
            if not _reloaded(exc) or attempt == 2:
                raise
            page.wait_for_load_state('networkidle', timeout=PAGE_TIMEOUT_MS)
            page.wait_for_timeout(2000)


def _reloaded(exc) -> bool:
    """La page s'est-elle rechargée sous la mesure ? (et non : le volet est-il faux)."""
    return 'context was destroyed' in str(exc)


def _same(shown, expected) -> bool:
    """Même valeur, à la forme près : `1` / `1.0`, `True` / `true`."""
    a, b = str(shown).strip().lower(), str(expected).strip().lower()
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except ValueError:
        return False


def check_app_panel_reflect(app: str, url_path: str):
    """Card sélectionnée → ses réglages au volet ; ✕ → les réglages de file. (ok, détail)."""
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario

    url = f"{BASE_URL.rstrip('/')}{url_path}"
    token = _test_session_key(app)
    if not token:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    detail = ''
    with _garde_de_montage(app, 'panel_reflect') as cleaned:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                context = browser.new_context(viewport={'width': 1600, 'height': 1000})
                context.add_cookies(_cookie(token))
                page = context.new_page()
                js_errors = []
                page.on('pageerror', lambda e: js_errors.append(str(e)[:160]))
                resp = page.goto(url, wait_until='networkidle', timeout=PAGE_TIMEOUT_MS)
                wrong_page = _exiger_la_page(page, resp, url)
                if wrong_page:
                    return wrong_page
                page.wait_for_timeout(2000)       # options du catalogue, arrivées après coup
                before = _evaluate(page, JS_PANEL)
                if not before:
                    raise SkipScenario("aucun champ GÉNÉRÉ (`data-param`) dans le volet droit : "
                                       "volet écrit à la main, rien à mesurer ici")
                selection = _evaluate(page, JS_SELECT, list(before))
                if not selection:
                    _monter_un_lot(page, app, n=2)
                    page.goto(url, wait_until='networkidle', timeout=PAGE_TIMEOUT_MS)
                    page.wait_for_timeout(2000)
                    before = _evaluate(page, JS_PANEL)
                    selection = _evaluate(page, JS_SELECT, list(before))
                if not selection:
                    raise SkipScenario("aucune card à sélectionner, même après le montage")
                page.wait_for_timeout(1500)
                shown = _evaluate(page, JS_PANEL)
                # Une valeur VIDE du ⚙ ne porte rien à refléter : colonne nullable (le curseur de
                # qualité — vide = hériter de la cascade) ou réglage que la card ne pose pas. Le
                # volet montre alors son défaut, et c'est juste (composer, enhancer_01, 11/10).
                gear = {k: v for k, v in (selection.get('gear') or {}).items()
                        if v not in (None, '') and k in shown}
                if not gear:
                    raise SkipScenario(f"le ⚙ de la card #{selection['id']} ne porte aucun des "
                                       f"{len(before)} champs générés du volet")
                wrong = {k: (shown[k], v) for k, v in gear.items() if not _same(shown[k], v)}
                if wrong:
                    return False, (f"card #{selection['id']} sélectionnée : le volet ne montre pas "
                                   f"ses réglages — {wrong} (affiché, réglage de la card)")
                mode, why = _clic_de_deselection(page)
                if mode is None:
                    return False, f"card #{selection['id']} : désélection impossible ({why})"
                page.wait_for_timeout(1200)
                after = _evaluate(page, JS_PANEL)
                drift = {k: (after.get(k), v) for k, v in before.items()
                         if not _same(after.get(k), v)}
                if drift:
                    return False, (f"✕ après la card #{selection['id']} : le volet ne revient pas "
                                   f"aux réglages de file — {drift} (affiché, avant sélection)")
                if js_errors:
                    return False, f"volet juste mais JS en erreur : {' | '.join(js_errors)}"
                detail = (f"card #{selection['id']} : {len(gear)}/{len(before)} champ(s) du volet "
                          f"reflètent son ⚙, puis ✕ → réglages de file retrouvés"
                          + ('' if mode == 'clic réel' else f" [{mode}]"))
            except SkipScenario:
                raise
            except Exception as exc:
                # Rechargé sous une brique partagée (montage d'un lot, désélection) : la mesure
                # n'a pas eu lieu — le DIRE, jamais le compter comme un verdict sur le volet.
                if _reloaded(exc):
                    raise SkipScenario("page rechargée par l'app pendant la mesure (montage ou "
                                       "rafraîchissement de la file) — volet NON mesuré ce passage")
                # Page jamais au repos réseau : le motif COMMUN, qui nomme l'adresse en vol.
                if 'Timeout' in type(exc).__name__ and 'goto' in str(exc):
                    raise SkipScenario(_motif_skip(exc))
                raise
            finally:
                browser.close()
    if cleaned:
        detail += f" ; {_total_nettoye(cleaned)} objet(s) de montage nettoyé(s)"
    return True, detail


def register_panel_reflect_scenarios():
    """Enregistre un scénario `<app>.panel_reflect` par app disposant d'un index."""
    from wama.common.services.nightly_tests import register

    for label, path in discoverable_apps():
        register(
            id=f"{label}.panel_reflect", app=label, stage="ui",
            description=(f"Volet {label} : la card sélectionnée y montre ses réglages, le ✕ y "
                         f"remet ceux de la file (champs générés du schéma)"),
            run=(lambda p=path, a=label: (lambda ctx: check_app_panel_reflect(a, p)))(),
            timeout_s=180, vram_gb=0.0,
        )

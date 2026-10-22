"""Scénarios nocturnes `ui` — les SCÈNES 3D des registres (`common/scenes.py`, 2026-10-21).

Un scénario par scène déclarée sur la page commune (`common:scene`) — licences, modèles, et toute
scène qu'un domaine déclarera ensuite, sans une ligne de plus ici (`common.scene.<clé>.ui`). La
constellation des utilisateurs, qui garde son adresse, a le sien (`accounts.constellation.ui`).

Pourquoi au navigateur : la page ne rend rien côté serveur ; ses faits arrivent par la route de
données et tout le reste naît dans la brique JS. Une importmap cassée, une déclaration que la
brique ne sait pas lire, une exception dans la mise en espace : la page répondrait 200 et resterait
un fond noir.

CE QU'IL MESURE, pour chaque scène :
  1. la page de son registre porte le bouton « Constellation », qui y mène ;
  2. la scène se forme : la ligne de mesures est remplie, une étiquette par nœud du contrat ;
  3. chercher le premier nœud visible le choisit : le volet porte son nom, et « Les plus proches » ;
     Échap rend la légende ; la légende filtre (ne garder qu'une catégorie, puis tout montrer) ;
     l'icône globale des mains apparaît, les allume sur une webcam factice et les éteint (modèle
     absent : la vignette le dit) ;
  4. chaque couche s'éteint et se rallume, chaque coloration s'applique, un poids change ;
et sur tout le parcours, zéro erreur JS et aucune requête POST (la scène ne fait que LIRE).
⚠ Le compte de test reçoit le niveau administrateur le temps du passage (comme la constellation
des utilisateurs) : ce scénario mesure la SCÈNE, les droits ont leurs tests (`tests_scenes`).
"""
from .ui_smoke import BASE_URL, _drop_new_sessions, _exiger_la_page, _session_keys
from .ui_smoke_accounts import GL_ARGS, PAGE_TIMEOUT_MS, SCENE_TIMEOUT_MS, _admin_session
from .ui_smoke_matching import _cookie

JS_STATE = """() => {
    const shown = sel => [...document.querySelectorAll(sel)].filter(e => e.style.display !== 'none');
    const panel = document.querySelector('.wc-panel');
    return {
        canvas: !!document.querySelector('.wc-canvas canvas'),
        stats: document.querySelector('.wc-stats').textContent.trim(),
        labels: document.querySelectorAll('.wc-label:not(.sphere):not(.core)').length,
        shownLabels: shown('.wc-label:not(.sphere):not(.core)').length,
        title: (panel.querySelector('h2') || {}).textContent || '',
        sections: [...panel.querySelectorAll('h3')].map(h => h.textContent),
        legend: panel.classList.contains('is-legend'),
    };
}"""


JS_COUNT = """() => {
    const b = document.querySelector('.wc-stats b');
    const box = document.querySelector('.wc-filters');
    return { first: b ? Number(b.textContent) : null, stats: document.querySelector('.wc-stats').textContent.trim(),
             box: !!box && !box.hidden, rows: document.querySelectorAll('.wc-panel [data-filter]').length };
}"""


#: Une WEBCAM factice (une mire, sans main) et l'accès accordé sans demande : de quoi éprouver la
#: chaîne des mains entière — caméra, moteurs WebAssembly, modèle servi, reconnaissance qui tourne.
FAKE_CAMERA_ARGS = ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']


def check_hands(page):
    """Les mains (interface GLOBALE `wama-hands-ui.js`, 2026-10-22) — `None` si le geste tient,
    sinon la faute. La scène s'est déclarée cible : l'icône de la barre du haut est VISIBLE et
    allume la vignette ; avec le modèle installé, la reconnaissance tourne sur la mire et demande
    une main ; sans lui, la vignette le DIT et nomme la page où l'installer ; l'icône les éteint."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    if not page.locator('#wamaHandsToggle').is_visible():
        return "mains : l'icône de la barre du haut reste cachée — la scène ne s'est pas déclarée cible"
    page.click('#wamaHandsToggle')
    try:
        page.wait_for_function(
            "() => { const s = document.querySelector('.wc-hands-status'); "
            "return s && /Montrez|installé|Caméra|démarrer|sécurisée/.test(s.textContent); }", timeout=60000)
    except PlaywrightTimeout:
        return f"mains : la vignette n'a rien dit en 60 s (« {page.locator('.wc-hands-status').inner_text()} »)"
    status = page.locator('.wc-hands-status').inner_text()
    if "n'est pas installé" in status:
        if not page.locator('.wc-hands-status a').count():
            return "mains : le modèle manque et la vignette ne dit pas où l'installer"
    elif 'Montrez' not in status:
        return f"mains : « {status} »"
    page.click('#wamaHandsToggle')
    page.wait_for_timeout(500)
    if not page.evaluate("() => document.querySelector('.wama-hands').hidden"):
        return "mains : l'icône ne les éteint pas"
    return None


JS_PINCH = """async (sel) => {
    const el = document.querySelector(sel);
    if (!el) return 'absent';
    const r = el.getBoundingClientRect();
    const m = await import('wama/hands-ui');
    m.applyGesture({ mode: 'pinch', pointer: { x: (r.left + r.width / 2) / innerWidth, y: (r.top + r.height / 2) / innerHeight }, click: true });
    return 'ok';
}"""


def check_hand_pointer(page):
    """Le PINCEMENT clique ce qui est sous le pointeur, partout dans la page (interface globale,
    `applyGesture` — le point d'entrée de la caméra, rejoué sans main devant l'objectif) : sur une
    ligne de légende, un filtre se pose ; sur « Tout montrer », il s'en va. `None` si le geste tient."""
    if page.evaluate(JS_PINCH, '.wc-panel [data-filter]') != 'ok':
        return "pointeur : aucune ligne de légende à pincer"
    page.wait_for_timeout(800)
    if page.evaluate("() => document.querySelector('.wc-filters').hidden"):
        return "pointeur : le pincement sur une ligne de légende ne pose aucun filtre"
    page.evaluate(JS_PINCH, '.wc-filters [data-clear="@all"]')
    page.wait_for_timeout(800)
    if not page.evaluate("() => document.querySelector('.wc-filters').hidden"):
        return "pointeur : le pincement sur « Tout montrer » ne retire pas le filtre"
    return None


def check_legend_filter(page):
    """Le filtre de la légende (brique commune, 2026-10-21) — `None` si le geste tient, sinon la
    faute. « ◎ » de la première ligne : ne garder que sa catégorie ; le compte ne peut que baisser
    et le HUD rappelle le filtre ; « Tout montrer » rend l'état de départ."""
    before = page.evaluate(JS_COUNT)
    if not before['rows']:
        return "la légende ne porte aucune ligne filtrante"
    page.click('.wc-panel [data-filter] [data-only]', force=True)
    page.wait_for_timeout(800)
    only = page.evaluate(JS_COUNT)
    if not only['box'] or only['first'] is None or only['first'] > before['first']:
        return f"filtre « ne garder que » : avant {before['stats']!r}, après {only['stats']!r}, rappel {only['box']}"
    page.click('.wc-filters [data-clear="@all"]', force=True)
    page.wait_for_timeout(800)
    after = page.evaluate(JS_COUNT)
    if after['stats'] != before['stats'] or after['box']:
        return f"« Tout montrer » : {after['stats']!r} au lieu de {before['stats']!r}"
    return None


def check_scene(key):
    """(ok, détail) du parcours d'une scène de la page commune."""
    from django.contrib.auth import get_user_model
    from django.urls import reverse
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    from wama.common.registries import REGISTRIES
    from wama.common.scenes import get_scene, page_url, scene_data
    from wama.common.services.nightly_tests import SkipScenario

    scene = get_scene(key)
    sessions_before = _session_keys()
    granted = _admin_session()
    if granted is None:
        raise SkipScenario("compte de test absent")
    user, previous_tier, session = granted
    faults, steps, js_errors, posts = [], [], [], []
    base = BASE_URL.rstrip('/')
    try:
        # Le contrat, lu AVANT le navigateur (aucune lecture ORM sous `sync_playwright`).
        contract = scene_data(scene, get_user_model().objects.get(pk=user.pk))
        layers_on = {l['key'] for l in scene.layers if l.get('on')}
        visible = [n for n in contract['nodes'] if not n.get('layer') or n['layer'] in layers_on]
        registry = REGISTRIES.get(scene.registry)
        registry_url = f"{base}{reverse(registry.url_name)}" if registry and registry.url_name else ''
        with sync_playwright() as p:
            browser = p.chromium.launch(args=GL_ARGS + FAKE_CAMERA_ARGS)
            try:
                ctx = browser.new_context(viewport={'width': 1600, 'height': 950}, permissions=['camera'])
                ctx.add_cookies(_cookie(session.session_key))
                page = ctx.new_page()
                page.on('pageerror', lambda e: js_errors.append(f"pageerror: {e}"[:200]))
                page.on('console', lambda m: js_errors.append(f"console: {m.text}"[:200])
                        if m.type == 'error' else None)
                page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)

                # 1. Le bouton, depuis la page du registre.
                target = page_url(scene)
                if registry_url:
                    resp = page.goto(registry_url, wait_until='domcontentloaded', timeout=PAGE_TIMEOUT_MS)
                    wrong = _exiger_la_page(page, resp, registry_url)
                    if wrong:
                        return wrong
                    link = page.locator(f'a[href="{target}"]')
                    if not link.count():
                        return False, f"la page du registre « {scene.registry} » ne porte pas le bouton de sa scène"
                    # Quitter la page du registre interrompt ses propres relevés (« Failed to
                    # fetch » de ses pollers) : ce n'est pas un défaut. On n'en garde que les
                    # exceptions non rattrapées ; le décompte de la scène part de zéro.
                    kept = [e for e in js_errors if e.startswith('pageerror')]
                    link.first.click()
                    page.wait_for_url(f"**{target}", timeout=PAGE_TIMEOUT_MS)
                    js_errors[:] = kept
                    steps.append('bouton suivi depuis la page du registre')
                else:
                    page.goto(f"{base}{target}", wait_until='domcontentloaded', timeout=PAGE_TIMEOUT_MS)
                try:
                    page.wait_for_function(
                        "(loading) => { const s = document.querySelector('.wc-stats'); "
                        "return s && s.textContent.trim() && s.textContent.trim() !== loading; }",
                        arg=scene.loading, timeout=SCENE_TIMEOUT_MS)
                except PlaywrightTimeout:
                    stats = page.locator('.wc-stats').inner_text()
                    return False, (f"la scène ne s'est pas formée en {SCENE_TIMEOUT_MS // 1000} s "
                                   f"(mesures : « {stats} ») — erreurs JS : {js_errors[:3]}")
                page.wait_for_timeout(1500)

                # 2. Formée : une étiquette par nœud du contrat.
                s = page.evaluate(JS_STATE)
                if not s['canvas']:
                    faults.append("aucune toile WebGL dans la scène")
                if s['labels'] != len(contract['nodes']):
                    faults.append(f"{s['labels']} étiquettes pour {len(contract['nodes'])} nœuds au contrat")
                if 'indisponible' in s['stats']:
                    # La brique rattrape ce qui casse sa mise en espace et l'écrit à la place des
                    # mesures : la scène est un fond noir, le reste du parcours n'a plus de sens.
                    return False, f"scène non formée : « {s['stats']} » — erreurs JS : {js_errors[:3]}"
                steps.append(f"{len(visible)} nœud(s) visibles, mesures « {s['stats']} »")

                # 3. Choisir le premier nœud visible par la recherche, puis Échap.
                if visible:
                    first = visible[0]['name']
                    page.fill('.wc-search input', first)
                    page.press('.wc-search input', 'Enter')
                    page.wait_for_timeout(1200)
                    v = page.evaluate(JS_STATE)
                    if v['title'] != first or v['legend'] or scene.nearest_title not in v['sections']:
                        faults.append(f"volet après recherche de « {first} » : {v['title']!r}, {v['sections']}")
                    page.keyboard.press('Escape')
                    page.wait_for_timeout(600)
                    if not page.evaluate(JS_STATE)['legend']:
                        faults.append("Échap ne rend pas la légende")
                    steps.append('nœud choisi par la recherche, Échap')

                # 3bis. Filtrer depuis la légende : ne garder qu'une catégorie, puis tout montrer.
                fault = check_legend_filter(page)
                if fault:
                    faults.append(fault)
                else:
                    steps.append('filtre de la légende posé puis retiré')

                # 3ter. Les mains, sur la webcam factice.
                fault = check_hands(page)
                if fault:
                    faults.append(fault)
                else:
                    steps.append('mains allumées puis éteintes')
                fault = check_hand_pointer(page)
                if fault:
                    faults.append(fault)
                else:
                    steps.append('pincement : filtre posé puis retiré')

                # 4. Couches, colorations, un poids.
                for layer in scene.layers:
                    for _ in range(2):
                        page.click(f'[data-layer="{layer["key"]}"]', force=True)
                        page.wait_for_timeout(250)
                for c in scene.colorings:
                    page.click(f'[data-color="{c["key"]}"]', force=True)
                    page.wait_for_timeout(250)
                if scene.factors:
                    moved = page.evaluate("(k) => { const i = document.querySelector('[data-weight=\"' + k + '\"] input'); "
                                          "if (!i) return false; i.value = 0; i.dispatchEvent(new Event('input')); return true; }",
                                          scene.factors[0]['key'])
                    if not moved:
                        faults.append(f"aucun curseur pour le facteur « {scene.factors[0]['key']} »")
                    page.wait_for_timeout(600)
                steps.append(f"{len(scene.layers)} couche(s), {len(scene.colorings)} coloration(s), un poids")
            finally:
                browser.close()
    finally:
        from wama.accounts.permissions import set_account_tier
        set_account_tier(user, previous_tier)
        session.delete()
        _drop_new_sessions(sessions_before)
    if js_errors:
        faults.append(f"erreurs JS : {js_errors[:4]}")
    if posts:
        faults.append(f"la page a envoyé {len(posts)} POST : {posts[:3]}")
    return (not faults), ' · '.join(faults or steps)


def register_scene_scenarios():
    """Enregistre `common.scene.<clé>.ui` pour chaque scène de la page commune."""
    from wama.common.scenes import SCENES
    from wama.common.services.nightly_tests import register
    for key, scene in SCENES.items():
        if scene.page_url_name:
            continue                         # la scène garde son adresse et son scénario
        register(
            id=f"common.scene.{key}.ui", app='common', stage="ui",
            description=(f"Scène 3D « {scene.page_title} » : bouton depuis la page du registre, scène "
                         "formée (une étiquette par nœud), recherche → volet, Échap, couches, "
                         "colorations, poids — zéro erreur JS, aucun POST"),
            run=lambda ctx, k=key: check_scene(k),
            timeout_s=180, vram_gb=0.0,
        )

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
     Échap rend la légende ;
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
            browser = p.chromium.launch(args=GL_ARGS)
            try:
                ctx = browser.new_context(viewport={'width': 1600, 'height': 950})
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

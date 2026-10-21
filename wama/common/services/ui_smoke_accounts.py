"""Scénario nocturne `ui` — la CONSTELLATION des utilisateurs (`accounts:user-constellation`, 2026-10-20).

Pourquoi au navigateur : la page est une scène three.js qui ne rend rien côté serveur — ses faits
arrivent par `accounts:user-constellation-data` et tout le reste (étoiles, sphères, volet) naît dans
le module JS. Une importmap cassée, un `import` qui ne résout plus, une exception dans la mise en
espace : la page répondrait 200 et resterait un fond noir, sans qu'aucun test Python ne le voie.

CE QU'IL MESURE, en geste d'administrateur :
  1. la gestion des utilisateurs porte le lien, et le suivre mène à la constellation ;
  2. la scène se forme : la ligne de mesures est remplie, une étoile par personne du jeu de faits
     (comptes de test masqués par défaut), et chaque sphère d'unité a son étiquette ;
  3. chercher une personne la choisit : le volet porte son nom et ses sept rubriques ; Échap rend
     la légende ;
  4. la couche « Comptes de test » ajoute leurs étoiles, un poids changé ne casse rien ;
  5. la frame « Droits · Constellation » de la présentation charge la même page intégrée, qui se
     forme, noms masqués ;
  6. au téléphone (390 px), aucun défilement horizontal ;
et sur tout le parcours, zéro erreur JS et aucune requête POST (la page ne fait que LIRE).

⚠ Les comptes de test ne sont pas administrateurs (`nightly_tests.TEST_USERNAMES`) : le NIVEAU
administrateur est PRÊTÉ à `wama_pw_smoke` le temps du passage (`set_account_tier`) et son niveau
rendu dans le `finally` — jamais une session forgée sur un compte réel (skill `smoke`, page
réservée aux admins). Il prêtait le groupe `admin`, qui ne fait plus d'administrateur depuis le
2026-10-21 (le niveau du profil est la seule définition).
"""
from .ui_smoke import BASE_URL, _drop_new_sessions, _exiger_la_page, _session_keys
from .ui_smoke_matching import _cookie

ACCOUNT = 'wama_pw_smoke'
PAGE_TIMEOUT_MS = 90000
#: Le temps laissé à la scène pour charger ses faits et se former (mesuré : ~2 s).
SCENE_TIMEOUT_MS = 30000
#: Chromium sans écran : WebGL par le rendu logiciel, sinon la scène affiche son repli « WebGL indisponible ».
GL_ARGS = ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist']

JS_SCENE = """async (src) => {
    const facts = await (await fetch(src, {credentials: 'same-origin'})).json();
    const shown = sel => [...document.querySelectorAll(sel)].filter(e => e.style.display !== 'none');
    return {
        canvas: !!document.querySelector('#uc-canvas canvas'),
        stats: document.getElementById('uc-stats').textContent.trim(),
        stars: document.querySelectorAll('.uc-label:not(.sphere):not(.core)').length,
        spheres: shown('.uc-label.sphere').length,
        persons: facts.users.filter(u => u.kind === 'person').length,
        users: facts.users.length,
        first: (facts.users.find(u => u.kind === 'person') || {}).username || null,
        firstName: (facts.users.find(u => u.kind === 'person') || {}).name || null,
    };
}"""
JS_PANEL = """() => ({
    title: (document.querySelector('#uc-panel h2') || {}).textContent || '',
    sections: [...document.querySelectorAll('#uc-panel h3')].length,
    legend: document.getElementById('uc-panel').classList.contains('is-legend'),
})"""


def _admin_session():
    """(user, previous_tier, session) — la session du compte de test, le niveau administrateur prêté."""
    from importlib import import_module

    from django.conf import settings
    from django.contrib.auth import get_user_model

    from wama.accounts.permissions import set_account_tier, user_tier

    user = get_user_model().objects.filter(username=ACCOUNT, is_active=True).first()
    if user is None:
        return None
    previous_tier = user_tier(user)
    set_account_tier(user, 'admin')
    session = import_module(settings.SESSION_ENGINE).SessionStore()
    session['_auth_user_id'] = str(user.pk)
    session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
    session['_auth_user_hash'] = user.get_session_auth_hash()
    session.create()
    return user, previous_tier, session


def check_constellation():
    """(ok, détail) du parcours de la constellation, en administrateur."""
    from django.urls import reverse
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario

    users_url = f"{BASE_URL.rstrip('/')}{reverse('accounts:user-management')}"
    page_path = reverse('accounts:user-constellation')
    data_path = reverse('accounts:user-constellation-data')
    sessions_before = _session_keys()
    granted = _admin_session()
    if granted is None:
        raise SkipScenario(f"compte de test `{ACCOUNT}` absent")
    user, previous_tier, session = granted
    faults, steps, js_errors, posts = [], [], [], []
    try:
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

                # 1. Le lien, depuis la gestion des utilisateurs.
                resp = page.goto(users_url, wait_until='domcontentloaded', timeout=PAGE_TIMEOUT_MS)
                wrong = _exiger_la_page(page, resp, users_url)
                if wrong:
                    return wrong
                link = page.locator(f'a[href="{page_path}"]')
                if not link.count():
                    return False, "la gestion des utilisateurs ne porte pas le lien de la constellation"
                link.first.click()
                page.wait_for_url(f"**{page_path}", timeout=PAGE_TIMEOUT_MS)
                try:
                    page.wait_for_function(
                        "() => /personne/.test(document.getElementById('uc-stats').textContent)",
                        timeout=SCENE_TIMEOUT_MS)
                except PlaywrightTimeout:
                    # Le défaut que ce scénario existe pour voir : une page 200 au fond noir. Le
                    # verdict nomme la cause (l'erreur JS), pas seulement un délai dépassé.
                    stats = page.locator('#uc-stats').inner_text()
                    return False, (f"la scène ne s'est pas formée en {SCENE_TIMEOUT_MS // 1000} s "
                                   f"(mesures : « {stats} ») — erreurs JS : {js_errors[:3]}")
                page.wait_for_timeout(1500)
                steps.append('lien suivi depuis « Users »')

                # 2. La scène est formée.
                s = page.evaluate(JS_SCENE, data_path)
                if not s['canvas']:
                    faults.append("aucune toile WebGL dans la scène")
                if s['stars'] != s['users']:
                    faults.append(f"{s['stars']} étoiles pour {s['users']} comptes au jeu de faits")
                if not s['stats'].startswith(str(s['persons'])):
                    faults.append(f"mesures « {s['stats']} » : attendu {s['persons']} personnes")
                steps.append(f"{s['persons']} personnes, {s['spheres']} sphère(s) étiquetée(s)")

                # 3. Choisir une personne par la recherche, puis revenir à la légende.
                if s['first']:
                    page.fill('#uc-search', s['first'])
                    page.press('#uc-search', 'Enter')
                    page.wait_for_timeout(1200)
                    v = page.evaluate(JS_PANEL)
                    if v['title'] != s['firstName'] or v['sections'] < 7 or v['legend']:
                        faults.append(f"volet après recherche de {s['first']} : {v}")
                    page.keyboard.press('Escape')
                    page.wait_for_timeout(600)
                    if not page.evaluate(JS_PANEL)['legend']:
                        faults.append("Échap ne rend pas la légende")
                    steps.append('personne choisie par la recherche, Échap')

                # 4. Comptes de test, puis un poids changé.
                page.click('[data-layer="tests"]', force=True)
                page.wait_for_timeout(800)
                stats = page.locator('#uc-stats').inner_text()
                if not stats.startswith(str(s['users'])):
                    faults.append(f"couche « Comptes de test » : « {stats} », attendu {s['users']}")
                page.evaluate("() => { const i = document.getElementById('uc-w-share'); "
                              "i.value = 6; i.dispatchEvent(new Event('input')); }")
                page.wait_for_timeout(800)
                steps.append('couche des comptes de test, poids des partages')

                # 5. La frame de la présentation : la même page intégrée, chargée à l'arrivée,
                #    formée, noms masqués.
                page.goto(f"{BASE_URL.rstrip('/')}{reverse('presentation')}#constellation",
                          wait_until='domcontentloaded', timeout=PAGE_TIMEOUT_MS)
                embedded = page.frame_locator('#constellation iframe')
                try:
                    embedded.locator('#uc-stats').filter(has_text='personne').wait_for(
                        timeout=SCENE_TIMEOUT_MS)
                    masked = 'on' not in (embedded.locator('[data-layer="names"]')
                                          .get_attribute('class') or '')
                    if not masked:
                        faults.append("présentation : les noms ne sont pas masqués par défaut")
                    steps.append('frame de la présentation formée, noms masqués')
                except PlaywrightTimeout:
                    faults.append("présentation : la constellation intégrée ne s'est pas formée "
                                  f"(iframe src : {page.locator('#constellation iframe').get_attribute('src')})")

                # 6. Téléphone.
                page.goto(f"{BASE_URL.rstrip('/')}{page_path}", wait_until='domcontentloaded',
                          timeout=PAGE_TIMEOUT_MS)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.wait_for_timeout(800)
                overflow = page.evaluate(
                    "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
                if overflow > 0:
                    faults.append(f"téléphone : défilement horizontal de {overflow} px")
                steps.append('téléphone 390 px')
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


def register_account_scenarios():
    """Enregistre `accounts.constellation.ui`."""
    from wama.common.services.nightly_tests import register
    register(
        id="accounts.constellation.ui", app="accounts", stage="ui",
        description=("Constellation des utilisateurs : lien depuis « Users », scène formée (une étoile "
                     "par compte), recherche → volet de la personne, Échap, couche des comptes de "
                     "test, poids, frame de la présentation (noms masqués), téléphone — zéro erreur "
                     "JS, aucun POST"),
        run=lambda ctx: check_constellation(),
        timeout_s=180, vram_gb=0.0,
    )

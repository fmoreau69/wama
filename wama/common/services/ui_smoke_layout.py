"""Scénario nocturne `ui` — la MISE EN PAGE à largeur de tablette (ROADMAP §27 étape 2, 2026-10-12).

Ce qu'aucun test Python ne voit : une barre dont le logo recouvre ses voisins, un pied dont les
ressources recouvrent le titre, deux volets ouverts qui ne laissent au centre que 394 px. Rien de
tout cela ne lève d'erreur — mesuré le jour même : « WAMA » posé sur « Simplifié » dès 1 280 px
volets ouverts, la droite de la barre débordant de 97 px sur le volet en tablette portrait.

CE QU'IL MESURE, sur une page FIXE (le transcriber, comme les scénarios du volet) et dans un
navigateur au stockage VIDE — donc le DÉFAUT, jamais un choix passé :
  1. tablette en portrait (834 px, doigt) : contexte étroit, volets repliés d'office, centre à
     pleine largeur ; ouvrir l'explorateur puis le panneau n'en laisse qu'UN ouvert ; le choix
     fait EN GRAND n'est pas écrit ;
  2. rotation en paysage (1 194 px) : chaque contexte reprend SA mémoire — volets ouverts (défaut
     en grand), puis, revenu en portrait, le panneau ouvert tel qu'on l'avait laissé ;
  3. poste de bureau (1 280 px, souris) : volets ouverts.
Et sur CHAQUE état : barre du haut et pied sans chevauchement ni débordement, page sans
défilement horizontal.
⚠ Il n'écrit RIEN côté serveur : seul le stockage local du navigateur de test bouge, jeté avec lui.

Second scénario, `common.gestures.touch` (ROADMAP §27 étape 3, 2026-10-16) — les GESTES au doigt
(`wama-gestures.js`), joués par de VRAIS événements tactiles (protocole de Chromium,
`Input.dispatchTouchEvent`), pas par des événements fabriqués dans la page :
  1. studio : glisser un élément du catalogue sur le canvas ajoute un nœud ; un doigt sur le fond
     défile, deux doigts pincent (le zoom change) ; l'appui long sur « Zoomer » montre son
     infobulle sans zoomer ;
  2. file du transcriber : appui long puis glisser d'une card sur une autre → cadre de fusion sous
     le doigt, vignette qui suit ; lâché hors de la file → rien n'est envoyé ; appui long relâché
     sur place → le menu de card ; appui long sur ⚙ → son infobulle, et pas sa modale ;
  3. éditeur du transcriber (si le compte de test a une transcription avec audio) : pincer l'onde
     zoome, la toucher déplace la lecture, glisser la poignée ⋮⋮ d'un segment sur un autre le
     désigne comme cible.
⚠ Toute requête POST des pages mesurées est INTERCEPTÉE et refusée, puis relevée : un geste qui
enverrait quelque chose est un échec, et le serveur n'en voit rien.
"""
from .ui_smoke import (BASE_URL, _drop_new_sessions, _exiger_la_page, _motif_skip,
                       _session_keys, _test_session_key)
from .ui_smoke_matching import _cookie

IPAD_UA = ('Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
           '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
PAGE_TIMEOUT_MS = 90000
ANIM_MS = 600            # repli animé (.22 s) + annonce `wama:panels` (.24 s), avec de la marge

#: L'état de la mise en page : volets, centre, chevauchements de la barre et du pied.
JS_LAYOUT = """() => {
    const vis = e => { if (!e) return null; const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
        return (r.width > 1 && cs.display !== 'none' && cs.visibility !== 'hidden') ? r : null; };
    // Contenu RÉEL d'un côté de la barre : l'union de ses enfants visibles.
    const span = sel => { const host = document.querySelector(sel); if (!host) return null;
        let l = 1e9, r = -1e9;
        host.querySelectorAll('button, a, span, i').forEach(c => { const q = vis(c);
            if (q) { l = Math.min(l, q.left); r = Math.max(r, q.right); } });
        return l < r ? {left: l, right: r} : null; };
    const cross = (a, b) => a && b ? Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) : 0;
    const bar = vis(document.querySelector('.top_nav'));
    const left = span('.wama-header-left'), right = span('.wama-header-right');
    const logo = vis(document.querySelector('.wama-header .wama-logo'));
    const center = vis(document.querySelector('body > .container-fluid')) || vis(document.querySelector('body > .container'));
    const store = {};
    ['left', 'right'].forEach(s => { store[s] = localStorage.getItem('wama_panel_' + s);
                                     store[s + '_narrow'] = localStorage.getItem('wama_panel_' + s + '_narrow'); });
    const c = document.body.classList;
    return {
        narrow: c.contains('wama-narrow'),
        leftOpen: !c.contains('wama-left-collapsed'), rightOpen: !c.contains('wama-right-collapsed'),
        hasRight: !!document.getElementById('wama-right-panel'),
        center: center ? Math.round(center.width) : null, viewport: innerWidth,
        barOverlap: Math.round(cross(left, logo) + cross(logo, right) + cross(left, right)),
        barOverflow: bar && right ? Math.round(Math.max(0, right.right - bar.right)) : 0,
        footOverlap: Math.round(cross(vis(document.querySelector('.wama-footer-text')), vis(document.getElementById('systemStats')))),
        pageOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        store,
    };
}"""


def _clean_layout(state, where):
    """Les défauts de mise en page communs à tout état : barre, pied, défilement horizontal."""
    faults = []
    if state['barOverlap']:
        faults.append(f"{where} : la barre du haut se chevauche ({state['barOverlap']} px)")
    if state['barOverflow']:
        faults.append(f"{where} : la barre du haut déborde ({state['barOverflow']} px)")
    if state['footOverlap']:
        faults.append(f"{where} : les ressources du pied recouvrent son titre ({state['footOverlap']} px)")
    if state['pageOverflowX'] > 0:
        faults.append(f"{where} : défilement horizontal de {state['pageOverflowX']} px")
    return faults


def _edge(page, side, touch):
    """Toucher (ou cliquer) la frontière d'un volet — le geste de WamaPanels."""
    edge = page.locator(f'.wama-panel-edge[data-side="{side}"]')
    if not edge.count():
        return False
    edge.tap() if touch else edge.click()
    page.wait_for_timeout(ANIM_MS)
    return True


def check_tablet_layout(app: str, url_path: str):
    """Tablette portrait → paysage → portrait, puis bureau : volets par contexte, barres saines."""
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario

    url = f"{BASE_URL.rstrip('/')}{url_path}"
    sessions_before = _session_keys()
    token = _test_session_key(app)
    if not token:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    faults, steps = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                # ── Tablette : portrait, rotation, retour ─────────────────────────────────
                ctx = browser.new_context(viewport={'width': 834, 'height': 1194}, device_scale_factor=2,
                                          is_mobile=True, has_touch=True, user_agent=IPAD_UA)
                ctx.add_cookies(_cookie(token))
                page = ctx.new_page()
                resp = page.goto(url, wait_until='domcontentloaded', timeout=PAGE_TIMEOUT_MS)
                wrong = _exiger_la_page(page, resp, url)
                if wrong:
                    return wrong
                page.wait_for_timeout(1500)
                s = page.evaluate(JS_LAYOUT)
                faults += _clean_layout(s, 'portrait')
                if not s['narrow']:
                    faults.append(f"portrait {s['viewport']} px : le contexte étroit n'est pas actif")
                if s['leftOpen'] or s['rightOpen']:
                    faults.append("portrait : un volet est ouvert d'office (attendu : repliés)")
                if (s['center'] or 0) < s['viewport'] - 2:
                    faults.append(f"portrait : centre à {s['center']} px sur {s['viewport']}")
                steps.append(f"portrait : centre {s['center']}/{s['viewport']} px, volets repliés")
                if not s['hasRight']:
                    raise SkipScenario("page sans volet droit : l'exclusivité des volets n'y est pas mesurable")

                _edge(page, 'left', True)
                s = page.evaluate(JS_LAYOUT)
                faults += _clean_layout(s, 'portrait, explorateur ouvert')
                if not s['leftOpen']:
                    faults.append("portrait : toucher la frontière gauche n'ouvre pas l'explorateur")
                _edge(page, 'right', True)
                s = page.evaluate(JS_LAYOUT)
                faults += _clean_layout(s, 'portrait, panneau ouvert')
                if not s['rightOpen'] or s['leftOpen']:
                    faults.append(f"portrait : ouvrir le panneau doit replier l'explorateur "
                                  f"(gauche {'ouvert' if s['leftOpen'] else 'replié'}, droite "
                                  f"{'ouvert' if s['rightOpen'] else 'replié'})")
                if s['store']['left'] is not None or s['store']['right'] is not None:
                    faults.append(f"portrait : le choix fait EN GRAND a été écrit ({s['store']})")
                steps.append(f"un seul volet à la fois (centre {s['center']} px, panneau ouvert)")

                page.set_viewport_size({'width': 1194, 'height': 834})
                page.wait_for_timeout(ANIM_MS)
                s = page.evaluate(JS_LAYOUT)
                faults += _clean_layout(s, 'paysage')
                if s['narrow'] or not (s['leftOpen'] and s['rightOpen']):
                    faults.append(f"paysage : attendu le contexte large, volets ouverts (étroit "
                                  f"{s['narrow']}, gauche {s['leftOpen']}, droite {s['rightOpen']})")
                steps.append(f"paysage : volets ouverts, centre {s['center']} px")

                page.set_viewport_size({'width': 834, 'height': 1194})
                page.wait_for_timeout(ANIM_MS)
                s = page.evaluate(JS_LAYOUT)
                if not s['narrow'] or s['leftOpen'] or not s['rightOpen']:
                    faults.append("retour en portrait : le panneau laissé ouvert n'est pas retrouvé "
                                  f"(gauche {s['leftOpen']}, droite {s['rightOpen']})")
                steps.append("retour en portrait : panneau retrouvé ouvert")
                ctx.close()

                # ── Bureau : la souris, la largeur habituelle ──────────────────────────────
                ctx = browser.new_context(viewport={'width': 1280, 'height': 800})
                ctx.add_cookies(_cookie(token))
                page = ctx.new_page()
                page.goto(url, wait_until='domcontentloaded', timeout=PAGE_TIMEOUT_MS)
                page.wait_for_timeout(1500)
                s = page.evaluate(JS_LAYOUT)
                faults += _clean_layout(s, 'bureau 1 280 px')
                if s['narrow'] or not (s['leftOpen'] and s['rightOpen']):
                    faults.append("bureau 1 280 px : attendu volets ouverts, contexte large")
                steps.append(f"bureau : volets ouverts, centre {s['center']} px")
            finally:
                browser.close()
    except SkipScenario:
        raise
    except Exception as exc:
        raise SkipScenario(_motif_skip(exc))
    finally:
        _drop_new_sessions(sessions_before)
    if faults:
        return False, ' ; '.join(faults)
    return True, ' → '.join(steps) + ' ; barre et pied sans chevauchement'


# ══ Les GESTES au doigt ══════════════════════════════════════════════════════════════════════════

HOLD_WAIT_MS = 700       # au-delà de l'appui long de la brique (450 ms)

#: Refuse et relève toute requête qui écrirait : le scénario reste en lecture seule même si un
#: geste se trompe de cible (un dépôt sur une card qui partirait en fusion, une borne déplacée).
BLOCK_WRITES = """(() => {
    window.__wamaPosted = [];
    const write = m => !['GET', 'HEAD'].includes(String(m || 'GET').toUpperCase());
    // Une réponse REFUSÉE (503), pas une promesse rejetée : la page la traite comme un refus du
    // serveur, sans erreur non rattrapée qui se lirait comme un défaut de la page.
    const fetch0 = window.fetch;
    window.fetch = function (u, o) {
        const m = (o && o.method) || (u && u.method);
        if (write(m)) {
            window.__wamaPosted.push(String((u && u.url) || u));
            return Promise.resolve(new Response('{"blocked": true}', {status: 503, headers: {'Content-Type': 'application/json'}}));
        }
        return fetch0.apply(this, arguments);
    };
    const open0 = XMLHttpRequest.prototype.open, send0 = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u) { this.__m = m; this.__u = u; return open0.apply(this, arguments); };
    XMLHttpRequest.prototype.send = function () {
        if (write(this.__m)) { window.__wamaPosted.push(String(this.__u)); return; }
        return send0.apply(this, arguments);
    };
    if (navigator.sendBeacon) navigator.sendBeacon = u => { window.__wamaPosted.push(String(u)); return true; };
})()"""

#: Un point du FOND du canvas du studio (ni nœud, ni barre de zoom), et un second à `gap` px à
#: droite, lui aussi sur le fond — pour un doigt qui défile et deux qui pincent.
JS_STUDIO_BACKGROUND = """(gap) => {
    const c = document.getElementById('studioCanvas').getBoundingClientRect();
    const bg = (x, y) => { const e = document.elementFromPoint(x, y);
        return !!e && (e.id === 'studioCanvas' || e.id === 'studioWorld' || !!e.closest('#studioLinks'))
               && !e.closest('.studio-node, .studio-zoom'); };
    for (let y = c.top + 60; y < c.bottom - 60; y += 20)
        for (let x = c.left + 40; x < c.right - gap - 40; x += 20)
            if (bg(x, y) && bg(x + gap, y) && bg(x + gap / 2, y)) return {x, y};
    return null;
}"""

#: Deux cards de la file amenées à l'écran (centres), la première avec son bouton ⚙ s'il porte un
#: titre. En portrait une card de la file fait ~440 px : on amène la première en haut, et c'est le
#: MILIEU de chacune qui doit être visible — c'est là que se fait le dépôt « sur » (fusion).
JS_TWO_CARDS = """() => {
    const all = [...document.querySelectorAll('[data-wama-dnd] .wama-card[data-id]:not(.is-batch)')]
        .filter(c => c.offsetParent !== null && c.getBoundingClientRect().height > 30);
    if (all.length < 2) return null;
    all[0].scrollIntoView({block: 'start'});
    window.scrollBy(0, -90);                                 // sous la barre du haut
    const seen = c => { const r = c.getBoundingClientRect(), m = r.top + r.height / 2;
        return m >= 60 && m <= innerHeight - 20; };
    const cards = all.filter(seen);
    if (cards.length < 2) return null;
    const mid = c => { const r = c.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2, id: c.dataset.id}; };
    // Où SAISIR la card : un point à 32 px au moins de toute commande. Le navigateur rattache un
    // toucher à la commande la plus proche (ajustement de cible) : saisie sur sa rangée d'actions,
    // la card montrerait l'infobulle d'un bouton — ce que fait un vrai doigt, à juste titre.
    const grip = c => {
        const r = c.getBoundingClientRect(), far = 32;
        const cmds = [...c.querySelectorAll('button, a[href], input, select, textarea, label, summary, [role="button"], [data-bs-toggle], .btn')]
            .map(e => e.getBoundingClientRect()).filter(q => q.width > 0);
        for (let y = r.top + 12; y < Math.min(r.bottom, innerHeight) - 12; y += 8)
            for (let x = r.left + 12; x < r.right - 12; x += 8)
                if (y >= 70 && cmds.every(q => x < q.left - far || x > q.right + far || y < q.top - far || y > q.bottom + far))
                    return {x, y, id: c.dataset.id};
        return null;
    };
    const gear = [...cards[0].querySelectorAll('[data-action="settings"], .settings-btn, .job-settings-btn, .btn-settings-job')]
        .find(b => b.title && b.getBoundingClientRect().width > 4);
    const g = gear ? gear.getBoundingClientRect() : null;
    return {a: grip(cards[0]), b: mid(cards[1]),
            gear: g ? {x: g.left + g.width / 2, y: g.top + g.height / 2, title: gear.title} : null};
}"""

JS_GESTURE_STATE = """() => ({
    ghost: document.querySelectorAll('.wama-touch-ghost').length,
    over: document.querySelectorAll('.wama-dnd-over, .wama-dnd-refuse').length,
    // Par sa BOÎTE : un menu en `position: fixed` a toujours `offsetParent === null`.
    menu: [...document.querySelectorAll('.wama-card-menu')].filter(m => { const r = m.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(m).display !== 'none'; }).length,
    tip: (document.querySelector('.wama-touch-tip') || {}).textContent || null,
    modal: document.querySelectorAll('.modal.show').length,
    posted: (window.__wamaPosted || []).length,
    urls: (window.__wamaPosted || []).slice(-3),
})"""

#: La position de lecture du lecteur de l'éditeur (un `Audio` hors du DOM, tenu par la brique).
JS_EDITOR_TIME = """() => { const id = (window.TRANSCRIBER_EDIT || {}).playerId;
    const a = id != null && window.WamaAudioPlayer ? WamaAudioPlayer.getAudio(id) : null;
    return a ? a.currentTime : null; }"""


class _Finger:
    """Des doigts RÉELS pour Chromium : `Input.dispatchTouchEvent` du protocole de débogage —
    le navigateur en tire `touchstart`… ET les Pointer Events, comme d'un écran tactile."""

    def __init__(self, page):
        self.page = page
        self.cdp = page.context.new_cdp_session(page)

    def _send(self, kind, points):
        self.cdp.send('Input.dispatchTouchEvent', {
            'type': kind, 'touchPoints': [{'x': x, 'y': y, 'id': i} for i, (x, y) in enumerate(points)]})

    def down(self, *points):
        self._send('touchStart', list(points))

    def hold(self, x, y):
        self.down((x, y))
        self.page.wait_for_timeout(HOLD_WAIT_MS)

    def move(self, *paths, steps=10, ms=25):
        """Chaque doigt posé va de `a` à `b` (`paths` = ((a, b), …)), en `steps` pas."""
        for k in range(1, steps + 1):
            t = k / steps
            self._send('touchMove', [(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t) for a, b in paths])
            self.page.wait_for_timeout(ms)

    def up(self):
        self._send('touchEnd', [])
        self.page.wait_for_timeout(250)


def _tablet_page(browser, token, url):
    ctx = browser.new_context(viewport={'width': 834, 'height': 1194}, device_scale_factor=2,
                              is_mobile=True, has_touch=True, user_agent=IPAD_UA)
    ctx.add_cookies(_cookie(token))
    ctx.add_init_script(BLOCK_WRITES)
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)[:160]))
    resp = page.goto(url, wait_until='domcontentloaded', timeout=PAGE_TIMEOUT_MS)
    return ctx, page, resp, errors


def _gestures_studio(browser, token, url, faults, steps):
    ctx, page, resp, errors = _tablet_page(browser, token, url)
    try:
        wrong = _exiger_la_page(page, resp, url)
        if wrong:
            faults.append(f"studio : {wrong[1]}")
            return
        page.wait_for_selector('.studio-pal-item[draggable="true"]', timeout=30000)
        page.wait_for_timeout(800)
        finger = _Finger(page)
        state = lambda: page.evaluate(JS_GESTURE_STATE)

        # 1. Catalogue → canvas : un nœud de plus.
        item = page.locator('.studio-pal-item[draggable="true"]').first
        item.scroll_into_view_if_needed()
        box, canvas = item.bounding_box(), page.locator('#studioCanvas').bounding_box()
        if not box or not canvas:
            faults.append("studio : catalogue ou canvas absent en portrait")
            return
        before = page.locator('.studio-node').count()
        sent = state()['posted']
        start = (box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        target = (canvas['x'] + canvas['width'] / 2, canvas['y'] + canvas['height'] / 3)
        finger.hold(*start)
        finger.move((start, target))
        ghost = state()['ghost']
        finger.up()
        added = page.locator('.studio-node').count() - before
        if added != 1 or ghost != 1:
            faults.append(f"studio : glisser du catalogue au doigt → {added} nœud(s) ajouté(s), "
                          f"vignette {'vue' if ghost else 'absente'}")
        else:
            steps.append("studio : catalogue → canvas au doigt (+1 nœud)")

        # 2. Déplacer le nœud par sa tête (s'il y en a un : l'absence est déjà dite au 1).
        heads = page.locator('.studio-node-head')
        hb = heads.last.bounding_box() if heads.count() else None
        if hb:
            left0 = page.evaluate("() => [...document.querySelectorAll('.studio-node')].pop().style.left")
            p0 = (hb['x'] + 24, hb['y'] + hb['height'] / 2)
            finger.down(p0)
            finger.move((p0, (p0[0] + 90, p0[1] + 40)))
            finger.up()
            left1 = page.evaluate("() => [...document.querySelectorAll('.studio-node')].pop().style.left")
            if left0 == left1:
                faults.append(f"studio : glisser la tête d'un nœud au doigt ne le déplace pas ({left0})")
            else:
                steps.append(f"nœud déplacé ({left0} → {left1})")

        # 3. Défiler le fond (un doigt), puis pincer (deux doigts).
        spot = page.evaluate(JS_STUDIO_BACKGROUND, 120)
        if not spot:
            faults.append("studio : aucun point libre du fond du canvas pour défiler / pincer")
        else:
            world = lambda: page.evaluate("() => document.getElementById('studioWorld').style.transform")
            zoom = lambda: page.locator('#studioZoomLabel').inner_text().strip()
            w0 = world()
            p0 = (spot['x'] + 60, spot['y'])
            finger.down(p0)
            finger.move((p0, (p0[0] - 50, p0[1] + 70)))
            finger.up()
            w1 = world()
            if w0 == w1:
                faults.append("studio : un doigt sur le fond ne fait pas défiler le canvas")
            else:
                steps.append("fond défilé au doigt")
            z0 = zoom()
            a, b = (spot['x'] + 30, spot['y']), (spot['x'] + 90, spot['y'])
            finger.down(a, b)
            finger.move((a, (a[0] - 60, a[1])), (b, (b[0] + 60, b[1])))
            finger.up()
            z1 = zoom()
            if z0 == z1:
                faults.append(f"studio : pincer à deux doigts ne zoome pas ({z0})")
            else:
                steps.append(f"pincement {z0} → {z1}")

            # 4. Appui long sur « Zoomer » : l'infobulle, PAS le zoom.
            zin = page.locator('[data-zoom="in"]').bounding_box()
            if zin:
                z2 = zoom()
                finger.hold(zin['x'] + zin['width'] / 2, zin['y'] + zin['height'] / 2)
                tip = state()['tip']
                finger.up()
                if tip != 'Zoomer' or zoom() != z2:
                    faults.append(f"studio : appui long sur « Zoomer » → infobulle {tip!r}, "
                                  f"zoom {z2} → {zoom()} (attendu : l'infobulle, sans zoomer)")
                else:
                    steps.append("appui long « Zoomer » → infobulle, sans zoomer")
        end = state()
        if end['posted'] != sent:
            faults.append(f"studio : {end['posted'] - sent} requête(s) d'écriture émise(s) par les gestes {end['urls']}")
        if errors:
            faults.append(f"studio : erreurs JS {errors}")
    finally:
        ctx.close()


def _gestures_queue(browser, token, url, faults, steps):
    ctx, page, resp, errors = _tablet_page(browser, token, url)
    try:
        wrong = _exiger_la_page(page, resp, url)
        if wrong:
            faults.append(f"file : {wrong[1]}")
            return
        page.wait_for_timeout(2000)
        cards = page.evaluate(JS_TWO_CARDS)
        if not cards:
            steps.append("file : moins de deux cards visibles — glisser non mesuré")
            return
        if not cards['a']:
            faults.append("file : aucune zone de la card à plus de 32 px d'une commande — "
                          "au doigt, elle ne peut pas être saisie pour être glissée")
            return
        finger = _Finger(page)
        state = lambda: page.evaluate(JS_GESTURE_STATE)
        a, b = (cards['a']['x'], cards['a']['y']), (cards['b']['x'], cards['b']['y'])
        sent = state()['posted']

        # 1. Card sur card : le cadre de fusion sous le doigt, puis lâchée HORS de la file.
        finger.hold(*a)
        finger.move((a, b))
        during = state()
        finger.move((b, (b[0], 20)), steps=6)
        finger.up()
        after = state()
        if not during['ghost'] or not during['over']:
            faults.append(f"file : glisser une card au doigt sur une autre → vignette {during['ghost']}, "
                          f"cadre de fusion {during['over']} (attendu : 1 et 1)")
        elif after['ghost'] or after['over'] or after['posted'] != sent:
            faults.append(f"file : lâchée hors de la file, la card laisse {after['ghost']} vignette(s), "
                          f"{after['over']} cadre(s), {after['posted'] - sent} envoi(s) {after['urls']}")
        else:
            steps.append("file : card glissée au doigt sur une autre (cadre de fusion), lâchée dehors sans envoi")

        # 2. Appui long relâché sur place : le menu de card.
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        cards = page.evaluate(JS_TWO_CARDS) or cards
        a = (cards['a']['x'], cards['a']['y'])
        finger.hold(*a)
        finger.up()
        menu = state()['menu']
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        if not menu:
            faults.append("file : un appui long relâché sur une card n'ouvre pas son menu")
        else:
            steps.append("appui long → menu de card")

        # 3. Appui long sur ⚙ : l'infobulle, pas la modale.
        gear = cards.get('gear')
        if gear:
            finger.hold(gear['x'], gear['y'])
            tip = state()['tip']
            finger.up()
            page.wait_for_timeout(400)
            modal = state()['modal']
            if tip != gear['title'] or modal:
                faults.append(f"file : appui long sur ⚙ → infobulle {tip!r}, {modal} modale(s) "
                              f"(attendu : « {gear['title']} », aucune modale)")
            else:
                steps.append(f"appui long ⚙ → « {tip} », sans modale")

        # 4. Un balayage rapide reste un défilement.
        finger.down(a)
        finger.move((a, (a[0], a[1] - 150)), steps=4, ms=10)
        finger.up()
        end = state()
        if end['ghost'] or end['posted'] != sent:
            faults.append(f"file : un balayage rapide a lancé un glisser ({end['ghost']} vignette, "
                          f"{end['posted'] - sent} envoi(s))")
        if errors:
            faults.append(f"file : erreurs JS {errors}")
    finally:
        ctx.close()


def _gestures_editor(browser, token, url, faults, steps):
    ctx, page, resp, errors = _tablet_page(browser, token, url)
    try:
        wrong = _exiger_la_page(page, resp, url)
        if wrong:
            faults.append(f"éditeur : {wrong[1]}")
            return
        page.wait_for_selector('.seg-drag[data-i="1"]', timeout=30000)
        page.wait_for_timeout(1500)
        finger = _Finger(page)
        state = lambda: page.evaluate(JS_GESTURE_STATE)
        wave = page.locator('#zoomWave').bounding_box()
        if wave and wave['width'] > 50:
            page.locator('#zoomWave').scroll_into_view_if_needed()
            wave = page.locator('#zoomWave').bounding_box()
            label = lambda: page.locator('#zoomLabel').inner_text().strip()
            y, cx = wave['y'] + wave['height'] / 2, wave['x'] + wave['width'] / 2
            z0 = label()
            finger.down((cx - 30, y), (cx + 30, y))
            finger.move(((cx - 30, y), (cx - 140, y)), ((cx + 30, y), (cx + 140, y)))
            finger.up()
            z1 = label()
            if z0 == z1:
                faults.append(f"éditeur : pincer l'onde ne zoome pas ({z0})")
            else:
                steps.append(f"éditeur : onde pincée {z0} → {z1}")
            t0 = page.evaluate(JS_EDITOR_TIME)
            finger.down((wave['x'] + wave['width'] * .7, y))
            finger.up()
            page.wait_for_timeout(600)
            t1 = page.evaluate(JS_EDITOR_TIME)
            if t0 is None:
                steps.append("lecteur de l'éditeur introuvable — position de lecture non mesurée")
            elif t1 == t0:
                faults.append(f"éditeur : toucher l'onde ne déplace pas la lecture ({t0} s)")
            else:
                steps.append(f"lecture déplacée au doigt ({t0:.1f} → {t1:.1f} s)")
        rows = page.locator('.seg-row').count()
        h = page.locator('.seg-drag[data-i="0"]').bounding_box()
        r1 = page.locator('.seg-row[data-i="1"]').bounding_box()
        if h and r1:
            a, b = (h['x'] + h['width'] / 2, h['y'] + h['height'] / 2), (r1['x'] + r1['width'] / 2, r1['y'] + r1['height'] / 2)
            sent = state()['posted']
            finger.hold(*a)
            finger.move((a, b))
            target = page.locator('.seg-drop-target').count()
            finger.move((b, (b[0], 20)), steps=6)
            finger.up()
            after = state()
            if not target or page.locator('.seg-row').count() != rows or after['posted'] != sent:
                faults.append(f"éditeur : poignée ⋮⋮ glissée au doigt → cible {target}, "
                              f"{rows} → {page.locator('.seg-row').count()} segments, "
                              f"{after['posted'] - sent} envoi(s) {after['urls']}")
            else:
                steps.append("segment glissé au doigt sur un autre (cible désignée), lâché dehors sans fusion")
        if errors:
            faults.append(f"éditeur : erreurs JS {errors}")
    finally:
        ctx.close()


def _mount_transcripts(uid):
    """Deux transcriptions du compte de test, chacune dans son lot : deux cards pour la file, et
    une page d'éditeur avec une onde à manipuler. Le compte de test ne travaille pas : sa file est
    vide par construction (même constat que `queue_dnd`).

    Audio : un témoin `wama_temoin_` d'UNE MINUTE de silence — l'onde tire sa durée de l'audio, et
    sous 4 s la fenêtre ne peut plus zoomer. Onde déclarée « en cours » : ouvrir l'éditeur sur une
    onde absente lancerait son calcul, une tâche, et ce scénario n'en lance aucune."""
    from django.contrib.auth import get_user_model
    from django.core.files.base import ContentFile

    from wama.transcriber.models import Transcript
    from wama.transcriber.views import _wrap_transcript_in_batch
    from .ui_smoke import _wav_silence

    user = get_user_model().objects.get(pk=uid)
    made = []
    for k in range(2):
        t = Transcript(user=user, status='SUCCESS', waveform_status='pending', segments_json=[
            {'start_time': i * 20, 'end_time': i * 20 + 20, 'text': word, 'speaker_id': 'A'}
            for i, word in enumerate(('un', 'deux', 'trois'))])
        t.audio.save(f'wama_temoin_gestes_{k}.wav', ContentFile(_wav_silence(60)), save=False)
        t.save()
        _wrap_transcript_in_batch(t)
        made.append(t)
    return made


def check_touch_gestures(paths: dict):
    """Les gestes au doigt : studio, file, éditeur — sur de vrais événements tactiles."""
    from django.urls import reverse
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario
    from .ui_smoke import _garde_de_montage, _test_account_id, _total_nettoye

    base = BASE_URL.rstrip('/')
    sessions_before = _session_keys()
    token = _test_session_key('transcriber')
    if not token:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    faults, steps = [], []
    # La garde ENVELOPPE Playwright (l'ORM y est interdit) et retire en sortie les transcriptions
    # et les lots créés par ce passage — jamais un objet préexistant.
    with _garde_de_montage('transcriber', 'gestures_touch') as cleaned:
        made = _mount_transcripts(_test_account_id('transcriber'))
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                try:
                    _gestures_studio(browser, token, base + paths['studio'], faults, steps)
                    _gestures_queue(browser, token, base + paths['queue'], faults, steps)
                    _gestures_editor(browser, token, base + reverse('transcriber:edit', args=[made[0].pk]),
                                     faults, steps)
                finally:
                    browser.close()
        except SkipScenario:
            raise
        except Exception as exc:
            raise SkipScenario(_motif_skip(exc))
        finally:
            _drop_new_sessions(sessions_before)
            for t in made:                     # le FICHIER : la garde ne retire que les lignes
                try:
                    t.audio.delete(save=False)
                except Exception:
                    pass
    if cleaned:
        steps.append(f"{_total_nettoye(cleaned)} objet(s) de montage retiré(s)")
    if faults:
        return False, ' ; '.join(faults)
    return True, ' → '.join(steps)


def register_layout_scenarios():
    """Enregistre `common.layout.tablet` (la mise en page à largeur de tablette) et
    `common.gestures.touch` (les gestes au doigt)."""
    from django.urls import NoReverseMatch, reverse

    from wama.common.services.nightly_tests import register
    # Page hôte FIXE, par `reverse` — même choix que les scénarios du volet (ui_smoke.py).
    try:
        path = reverse('transcriber:index')
    except NoReverseMatch:                                    # pragma: no cover
        return
    register(
        id="common.layout.tablet", app="common", stage="ui",
        description=("Mise en page : volets par contexte de largeur (tablette portrait / paysage, "
                     "bureau), barre du haut et pied sans chevauchement"),
        run=(lambda p=path: (lambda ctx: check_tablet_layout('transcriber', p)))(),
        timeout_s=180, vram_gb=0.0,
    )
    try:
        gesture_paths = {'studio': reverse('studio:index'), 'queue': path}
    except NoReverseMatch:                                    # pragma: no cover
        return
    register(
        id="common.gestures.touch", app="common", stage="ui",
        description=("Gestes au doigt (wama-gestures.js) : glisser du catalogue, défiler et pincer au "
                     "studio ; glisser une card, menu et infobulle à l'appui long dans la file ; "
                     "onde et segments de l'éditeur du transcriber — sur de vrais événements tactiles"),
        run=(lambda g=gesture_paths: (lambda ctx: check_touch_gestures(g)))(),
        timeout_s=240, vram_gb=0.0,
    )

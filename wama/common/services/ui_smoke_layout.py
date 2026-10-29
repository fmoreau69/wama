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
  4. arbre de fichiers : l'appui long ouvre son menu ; cloche : outils visibles sans survol ;
     la case des cards au doigt (deux touchers → deux sélectionnées) ; la liste qui défile au bord
     pendant un glisser ; l'outil Bornes de l'onde (une borne glissée demande son recalage).
⚠ Toute requête POST des pages mesurées est INTERCEPTÉE et refusée, puis relevée : un geste qui
enverrait quelque chose est un échec, et le serveur n'en voit rien.

Troisième scénario, `common.gestures.mouse` — les MÊMES pages à la souris, la garde du PC : le
canvas du studio et l'onde passent par la brique depuis le 2026-10-16, la case et le survol des
cards sont neufs ; ce qui marchait doit marcher encore.
"""
from .ui_smoke import (BASE_URL, _drop_new_sessions, _exiger_la_page, _motif_skip,
                       _session_keys, _test_session_key)
from .ui_smoke_matching import _cookie

IPAD_UA = ('Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 '
           '(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
#: L'iPad Pro 11 en portrait (le paysage en échange les côtés) — lu par la tablette et les écrans.
IPAD_PORTRAIT = {'width': 834, 'height': 1194}
IPAD_LANDSCAPE = {'width': IPAD_PORTRAIT['height'], 'height': IPAD_PORTRAIT['width']}
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


def _ipad_context(browser, token):
    """UN profil tablette pour les deux scénarios : iPad Pro 11 en portrait, doigt, compte de test."""
    ctx = browser.new_context(viewport=dict(IPAD_PORTRAIT), device_scale_factor=2,
                              is_mobile=True, has_touch=True, user_agent=IPAD_UA)
    ctx.add_cookies(_cookie(token))
    return ctx


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
                ctx = _ipad_context(browser, token)
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

                page.set_viewport_size(dict(IPAD_LANDSCAPE))
                page.wait_for_timeout(ANIM_MS)
                s = page.evaluate(JS_LAYOUT)
                faults += _clean_layout(s, 'paysage')
                if s['narrow'] or not (s['leftOpen'] and s['rightOpen']):
                    faults.append(f"paysage : attendu le contexte large, volets ouverts (étroit "
                                  f"{s['narrow']}, gauche {s['leftOpen']}, droite {s['rightOpen']})")
                steps.append(f"paysage : volets ouverts, centre {s['center']} px")

                page.set_viewport_size(dict(IPAD_PORTRAIT))
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
    // Ce que l'écriture refusée AURAIT envoyé (adresse et corps texte) : un scénario juge ce
    // qu'une page enregistre sans que le serveur en voie rien.
    window.__wamaBodies = [];
    const write = m => !['GET', 'HEAD'].includes(String(m || 'GET').toUpperCase());
    const keep = (u, b) => { window.__wamaPosted.push(u); window.__wamaBodies.push({url: u, body: typeof b === 'string' ? b : ''}); };
    // Une réponse REFUSÉE (503), pas une promesse rejetée : la page la traite comme un refus du
    // serveur, sans erreur non rattrapée qui se lirait comme un défaut de la page.
    const fetch0 = window.fetch;
    window.fetch = function (u, o) {
        const m = (o && o.method) || (u && u.method);
        if (write(m)) {
            keep(String((u && u.url) || u), o && o.body);
            return Promise.resolve(new Response('{"blocked": true}', {status: 503, headers: {'Content-Type': 'application/json'}}));
        }
        return fetch0.apply(this, arguments);
    };
    const open0 = XMLHttpRequest.prototype.open, send0 = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u) { this.__m = m; this.__u = u; return open0.apply(this, arguments); };
    XMLHttpRequest.prototype.send = function (b) {
        if (write(this.__m)) { keep(String(this.__u), b); return; }
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
        // Les commandes au sens de la BRIQUE (une seule liste, lue dans la page).
        const cmds = [...c.querySelectorAll((window.WamaGestures || {}).INTERACTIVE || 'button, a[href]')]
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

#: Les cards de la file : leur case (visibilité, cochée, taille), leur sélection, leur survol.
JS_CARDS_STATE = """() => [...document.querySelectorAll('[data-wama-dnd] .wama-card[data-id]:not(.is-batch)')]
    .filter(c => c.offsetParent !== null).map(c => { const b = c.querySelector('.wama-select-box'), s = getComputedStyle(c);
        return {id: c.dataset.id, box: b ? getComputedStyle(b).opacity : null, checked: b && b.getAttribute('aria-checked'),
                w: b ? Math.round(b.getBoundingClientRect().width) : 0, sel: c.classList.contains('wama-dnd-selected'),
                hover: s.boxShadow.indexOf('rgba(13, 202, 240') >= 0 && s.backgroundImage.indexOf('linear-gradient') >= 0}; })"""

#: Le défilement de la LISTE des cards : son premier ancêtre qui défile (dans WAMA, le conteneur
#: de la page — la page elle-même ne défile pas).
JS_LIST_SCROLL = """() => { const c = document.querySelector('[data-wama-dnd] .wama-card[data-id]');
    for (let e = c; e; e = e.parentElement) { const o = getComputedStyle(e).overflowY;
        if ((o === 'auto' || o === 'scroll') && e.scrollHeight > e.clientHeight + 1) return Math.round(e.scrollTop); }
    return Math.round(scrollY); }"""

def _wait_player(page, timeout_ms=20000):
    """Attend que le lecteur de l'éditeur ait ses métadonnées (sans quoi il ne se positionne pas)."""
    try:
        page.wait_for_function("""() => { const id = """ + JS_EDITOR_PLAYER + """;
            const a = id && window.WamaAudioPlayer ? WamaAudioPlayer.getAudio(id) : null;
            return !!a && a.readyState >= 1; }""", timeout=timeout_ms)
    except Exception:
        pass                                   # la mesure qui suit le dira (position inchangée)


def _wait_time_change(page, before, timeout_ms=3000):
    """La position de lecture une fois qu'elle a bougé (ou la dernière lue après `timeout_ms`)."""
    now = page.evaluate(JS_EDITOR_TIME)
    for _ in range(timeout_ms // 150):
        if now != before:
            break
        page.wait_for_timeout(150)
        now = page.evaluate(JS_EDITOR_TIME)
    return now


#: La première notification du panneau de la cloche : outils, pastille, « Ouvrir », taille d'un outil.
JS_BELL_STATE = """() => { const it = document.querySelector('.wn-item'); if (!it) return null;
    const st = s => { const e = it.querySelector(s); if (!e) return null; const c = getComputedStyle(e);
        return c.display === 'none' ? 'none' : c.opacity; };
    const tool = it.querySelector('.wn-tool');
    return {tools: st('.wn-tools'), dot: st('.wn-dot'), go: st('.wn-go'),
            toolW: tool ? Math.round(tool.getBoundingClientRect().width) : 0}; }"""

#: L'onde fenêtrée, son zoom et l'outil Bornes de la page de correction — la LIGNE DE TEMPS
#: commune depuis le redécoupage du 2026-10-21 (`wama-timeline.js`, brique `media_timeline`,
#: ROUTE §F3b) ; le matin même encore des options du transport.
EDITOR_WAVE = '[data-timeline="wave"]'
EDITOR_ZOOM = '[data-timeline="zoom-label"]'
EDITOR_TOOL = '[data-timeline="boundaries"]'

#: L'identifiant du lecteur de la page de correction — une SURFACE depuis le 2026-10-21 (ROUTE
#: §F3b) : celui que la brique de transport donne au lecteur commun, `surface-<pk>-audio`.
JS_EDITOR_PLAYER = """(() => { const c = document.getElementById('wama-surface-config');
    return c ? 'surface-' + JSON.parse(c.textContent).pk + '-audio' : null; })()"""

#: La position de lecture du lecteur de l'éditeur (un `Audio` hors du DOM, tenu par la brique).
JS_EDITOR_TIME = """() => { const id = """ + JS_EDITOR_PLAYER + """;
    const a = id && window.WamaAudioPlayer ? WamaAudioPlayer.getAudio(id) : null;
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
    ctx = _ipad_context(browser, token)
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

        # 5. La CASE au doigt : toujours visible, deux touchers → deux cards sélectionnées.
        page.keyboard.press('Escape')
        boxes = page.evaluate(JS_CARDS_STATE)
        if len(boxes) < 2 or not all(c['box'] == '1' for c in boxes):
            faults.append(f"file : au doigt, les cases ne sont pas toutes visibles ({[c['box'] for c in boxes]})")
        for c in boxes[:2]:
            box = page.locator(f'[data-wama-dnd] .wama-card[data-id="{c["id"]}"] .wama-select-box')
            box.scroll_into_view_if_needed()
            box.tap()
            page.wait_for_timeout(250)
        ticked = [c for c in page.evaluate(JS_CARDS_STATE) if c['checked'] == 'true' and c['sel']]
        if len(ticked) != 2:
            faults.append(f"file : toucher deux cases sélectionne {len(ticked)} card(s) au lieu de 2")
        else:
            steps.append(f"deux cases touchées → 2 sélectionnées ({boxes[0]['w']} px)")
        page.keyboard.press('Escape')

        # 6. Pendant un glisser, la liste DÉFILE quand le doigt approche du bas de l'écran — jusque
        #    sur le pied de page fixe. Dans WAMA ce n'est pas la page qui défile mais son
        #    conteneur : on lit le défilement de la LISTE de la card.
        cards = page.evaluate(JS_TWO_CARDS) or cards
        a = (cards['a']['x'], cards['a']['y'])
        y0 = page.evaluate(JS_LIST_SCROLL)
        finger.hold(*a)
        edge = (a[0], page.evaluate("() => innerHeight") - 8)
        finger.move((a, edge))
        page.wait_for_timeout(900)                       # le défilement avance au rythme de l'écran
        y1 = page.evaluate(JS_LIST_SCROLL)
        finger.move((edge, (a[0], 20)), steps=6)
        finger.up()
        end = state()
        if y1 <= y0:
            faults.append(f"file : au bord bas pendant un glisser, la liste ne défile pas ({y0} → {y1} px)")
        elif end['posted'] != sent or end['ghost']:
            faults.append(f"file : glisser avec défilement → {end['posted'] - sent} envoi(s), {end['ghost']} vignette(s)")
        else:
            steps.append(f"au bord, la liste défile pendant le glisser ({y0} → {y1} px)")
        if errors:
            faults.append(f"file : erreurs JS {errors}")
    finally:
        ctx.close()


def _gestures_tree_and_bell(browser, token, url, faults, steps):
    """Au doigt : l'appui long sur l'arbre ouvre son menu (l'iPad n'émet pas de clic droit), et
    le panneau de la cloche montre ses outils sans survol."""
    ctx, page, resp, errors = _tablet_page(browser, token, url)
    try:
        wrong = _exiger_la_page(page, resp, url)
        if wrong:
            faults.append(f"arbre : {wrong[1]}")
            return
        page.wait_for_timeout(1500)
        finger = _Finger(page)
        _edge(page, 'left', True)                       # en portrait, l'explorateur est replié
        # « Temporaires », comme le scénario du menu de l'arbre : la racine « Mes fichiers » n'a pas de menu.
        anchor = page.locator('#filemanager-tree .jstree-anchor:text-is("Temporaires")').first
        # Les attentes des scénarios de l'arbre (`ui_smoke_menus`) : l'arbre se charge à la
        # demande, lentement sur un serveur chargé. Son CHARGEMENT est leur affaire ; ici, s'il
        # ne vient pas, le geste n'est pas mesuré — ce n'est pas un défaut du geste.
        try:
            page.wait_for_selector('#filemanager-tree .jstree-anchor', timeout=30000)
            anchor.wait_for(timeout=15000)
            loaded = True
        except Exception:
            steps.append("arbre non chargé à temps — appui long sur l'arbre non mesuré")
            loaded = False
        if loaded:
            box = anchor.bounding_box()
            finger.hold(box['x'] + min(40, box['width'] / 2), box['y'] + box['height'] / 2)
            finger.up()
            menu = page.evaluate(JS_GESTURE_STATE)['menu']
            page.keyboard.press('Escape')
            page.wait_for_timeout(200)
            if not menu:
                faults.append(f"arbre : un appui long sur « {anchor.inner_text().strip()} » n'ouvre pas son menu")
            else:
                steps.append("arbre : appui long → menu")

        page.locator('#wamaNotificationsLink').tap()
        try:
            page.wait_for_selector('.wn-item', timeout=15000)
        except Exception:
            faults.append("cloche : le panneau ne montre aucune notification au doigt")
            return
        page.wait_for_timeout(300)
        bell = page.evaluate(JS_BELL_STATE)
        if bell['tools'] != '1' or bell['dot'] not in (None, 'none') or bell['toolW'] < 44:
            faults.append(f"cloche : au doigt, outils {bell['tools']} (attendu 1), pastille {bell['dot']} "
                          f"(attendu absente), outil {bell['toolW']} px (attendu ≥ 44)")
        else:
            steps.append(f"cloche : outils visibles au doigt ({bell['toolW']} px), pastille cédée")
        if errors:
            faults.append(f"arbre / cloche : erreurs JS {errors}")
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
        wave = page.locator(EDITOR_WAVE).bounding_box()
        if wave and wave['width'] > 50:
            page.locator(EDITOR_WAVE).scroll_into_view_if_needed()
            wave = page.locator(EDITOR_WAVE).bounding_box()
            label = lambda: page.locator(EDITOR_ZOOM).inner_text().strip()
            y, cx = wave['y'] + wave['height'] / 2, wave['x'] + wave['width'] / 2
            # Outil Bornes, vue ENTIÈRE (avant le pincement) : la jonction des segments 1 et 2 est
            # au tiers de l'onde (20 s sur 60). La déplacer au doigt demande le recalage au serveur
            # — l'écriture est interceptée : la requête relevée EST la preuve du geste.
            tool = page.locator(EDITOR_TOOL)
            if tool.count():
                tool.tap()
                page.wait_for_timeout(200)
                sent = state()['posted']
                bx = wave['x'] + wave['width'] / 3
                finger.down((bx, y))
                finger.move(((bx, y), (bx + 40, y)), steps=6)
                # Le doigt s'IMMOBILISE avant d'être levé, comme qui pose une borne : levé en plein
                # mouvement, il lance une inertie, et le navigateur prend le toucher suivant pour
                # l'arrêter — sans clic (mesuré le 2026-10-16 : l'outil ne se refermait pas 2 fois
                # sur 3 ; immobile, 4/4).
                page.wait_for_timeout(250)
                finger.up()
                page.wait_for_timeout(500)
                after = state()
                retimed = [u for u in after['urls'] if '/retime/' in u]
                if after['posted'] - sent != 1 or not retimed:
                    faults.append(f"éditeur : outil Bornes, borne glissée au doigt → {after['posted'] - sent} "
                                  f"envoi(s) {after['urls']} (attendu : un recalage)")
                else:
                    steps.append("éditeur : borne déplacée au doigt (recalage demandé)")
                tool.tap()                                  # l'outil se referme
                page.wait_for_timeout(200)
            z0 = label()
            finger.down((cx - 30, y), (cx + 30, y))
            finger.move(((cx - 30, y), (cx - 140, y)), ((cx + 30, y), (cx + 140, y)))
            finger.up()
            z1 = label()
            if z0 == z1:
                faults.append(f"éditeur : pincer l'onde ne zoome pas ({z0})")
            else:
                steps.append(f"éditeur : onde pincée {z0} → {z1}")
            # Le lecteur ne pose une position qu'une fois les MÉTADONNÉES de l'audio chargées : sur
            # un serveur chargé, 600 ms ne suffisaient pas (faux rouge du 2026-10-16, rejoué vert
            # pas à pas). On attend le lecteur, puis la position, sans délai fixe.
            _wait_player(page)
            t0 = page.evaluate(JS_EDITOR_TIME)
            finger.down((wave['x'] + wave['width'] * .7, y))
            finger.up()
            t1 = _wait_time_change(page, t0, timeout_ms=8000)
            if t0 is None:
                steps.append("lecteur de l'éditeur introuvable — position de lecture non mesurée")
            elif t1 == t0:
                diag = page.evaluate("""() => { const id = """ + JS_EDITOR_PLAYER + """;
                    const a = window.WamaAudioPlayer && id ? WamaAudioPlayer.getAudio(id) : null;
                    const b = document.querySelector('""" + EDITOR_TOOL + """');
                    return {tool: b && b.getAttribute('aria-pressed'), ready: a && a.readyState,
                            preload: a && a.preload, net: a && a.networkState,
                            zoom: (document.querySelector('""" + EDITOR_ZOOM + """') || {}).textContent}; }""")
                faults.append(f"éditeur : toucher l'onde ne déplace pas la lecture ({t0} s ; {diag})")
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


def _mount_transcripts(uid, count=3, gap=False, corrected=False):
    """`count` transcriptions du compte de test, chacune dans son lot : des cards pour la file, et
    une page d'éditeur avec une onde à manipuler. Le compte de test ne travaille pas : sa file est
    vide par construction (même constat que `queue_dnd`).

    Audio : un témoin `wama_temoin_` d'UNE MINUTE de silence — l'onde tire sa durée de l'audio, et
    sous 4 s la fenêtre ne peut plus zoomer. Onde déclarée « en cours » (`waveform.hold_dense_peaks`) :
    ouvrir l'éditeur sur une onde absente lancerait son calcul, une tâche, et ce scénario n'en lance
    aucune.
    `gap` : le dernier segment s'arrête à 50 s, un SILENCE reste à la fin (l'outil Bornes y crée un
    segment). `corrected` : une correction existe déjà, qui diffère de la sortie ASR par le premier
    texte (« un. ») — la page propose alors de charger la dernière transcription."""
    from django.contrib.auth import get_user_model
    from django.core.files.base import ContentFile

    from wama.common.utils.waveform import hold_dense_peaks
    from wama.transcriber.models import Transcript
    from wama.transcriber.views import _wrap_transcript_in_batch
    from .ui_smoke import _wav_silence

    user = get_user_model().objects.get(pk=uid)
    made = []
    # Trois : une plage Maj a besoin d'une card entre deux, et une file qui DÉPASSE l'écran
    # (en portrait une card fait ~440 px) est ce qui permet de mesurer le défilement au bord.
    for k in range(count):
        segments = [{'start_time': i * 20, 'end_time': i * 20 + 20, 'text': word, 'speaker_id': 'A'}
                    for i, word in enumerate(('un', 'deux', 'trois'))]
        if gap:
            segments[-1]['end_time'] = 50
        t = Transcript(user=user, status='SUCCESS', segments_json=segments)
        if corrected:
            t.corrected_segments_json = [dict(s, text='un.') if i == 0 else dict(s)
                                         for i, s in enumerate(segments)]
            t.correction_status = 'draft'
        t.audio.save(f'wama_temoin_gestes_{k}.wav', ContentFile(_wav_silence(60)), save=False)
        t.save()
        hold_dense_peaks(t.audio.name)
        _wrap_transcript_in_batch(t)
        made.append(t)
    return made


def _run_gestures(paths: dict, parts, label: str):
    """Le montage COMMUN des deux scénarios de gestes : trois transcriptions du compte de test (des
    cards, une onde) et une notification témoin (le panneau de la cloche), tout retiré en sortie.
    `parts(browser, token, urls, faults, steps)` joue les gestes. Rend (ok, détail)."""
    from django.contrib.auth import get_user_model
    from django.urls import reverse
    from playwright.sync_api import sync_playwright

    from wama.common.models import Notification
    from wama.common.services.nightly_tests import SkipScenario
    from wama.common.utils.notifications import notify_in_app
    from .ui_smoke import _garde_de_montage, _test_account_id, _total_nettoye

    base = BASE_URL.rstrip('/')
    sessions_before = _session_keys()
    token, uid = _test_session_key('transcriber'), _test_account_id('transcriber')
    if not (token and uid):
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    faults, steps = [], []
    kind = f'smoke_{label}'
    # La garde ENVELOPPE Playwright (l'ORM y est interdit) et retire en sortie les transcriptions
    # et les lots créés par ce passage — jamais un objet préexistant.
    with _garde_de_montage('transcriber', label) as cleaned:
        made = _mount_transcripts(uid)
        notify_in_app([get_user_model().objects.get(pk=uid)], kind, 'Témoin : gestes', url=paths['queue'])
        urls = {k: base + v for k, v in paths.items()}
        urls['editor'] = base + reverse('common:surface', args=['transcriber', 'correct', made[0].pk])
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                try:
                    parts(browser, token, urls, faults, steps)
                finally:
                    browser.close()
        except SkipScenario:
            raise
        except Exception as exc:
            raise SkipScenario(_motif_skip(exc))
        finally:
            _drop_new_sessions(sessions_before)
            Notification.objects.filter(recipient_id=uid, kind=kind).delete()
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


def check_touch_gestures(paths: dict):
    """Les gestes au doigt : studio, file, arbre, cloche, éditeur — sur de vrais événements tactiles."""
    def parts(browser, token, urls, faults, steps):
        _gestures_studio(browser, token, urls['studio'], faults, steps)
        _gestures_queue(browser, token, urls['queue'], faults, steps)
        _gestures_tree_and_bell(browser, token, urls['queue'], faults, steps)
        _gestures_editor(browser, token, urls['editor'], faults, steps)
    return _run_gestures(paths, parts, 'gestures_touch')


# ══ Les mêmes pages À LA SOURIS : la garde du PC ═════════════════════════════════════════════════
#
# Le canvas du studio et l'onde du transcriber passent par `WamaGestures.track` depuis le
# 2026-10-16 (ils écrivaient leurs mousedown/mousemove/mouseup) ; la case et le survol des cards
# sont neufs. Ce qui marchait au PC doit marcher encore — c'est CE scénario qui le dit chaque nuit.

def _desktop_page(browser, token, url, page_hook=None):
    """`page_hook(page)` : posé avant l'ouverture (une contre-épreuve y réécrit un fichier servi)."""
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
    ctx.add_cookies(_cookie(token))
    ctx.add_init_script(BLOCK_WRITES)
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)[:160]))
    if page_hook:
        page_hook(page)
    resp = page.goto(url, wait_until='domcontentloaded', timeout=PAGE_TIMEOUT_MS)
    return ctx, page, resp, errors


def _mouse_studio(browser, token, url, faults, steps):
    ctx, page, resp, errors = _desktop_page(browser, token, url)
    try:
        wrong = _exiger_la_page(page, resp, url)
        if wrong:
            faults.append(f"studio : {wrong[1]}")
            return
        page.wait_for_selector('.studio-pal-item[draggable="true"]', timeout=30000)
        page.wait_for_timeout(800)
        # Le glisser NATIF de la souris (la brique n'y touche pas).
        page.locator('.studio-pal-item[draggable="true"]').first.drag_to(
            page.locator('#studioCanvas'), target_position={'x': 200, 'y': 150})
        page.wait_for_timeout(300)
        if page.locator('.studio-node').count() != 1:
            faults.append("studio (souris) : le glisser du catalogue n'ajoute pas de nœud")
            return
        node = lambda: page.evaluate("() => { const n = document.querySelector('.studio-node'); return [n.style.left, n.style.top]; }")
        world = lambda: page.evaluate("() => document.getElementById('studioWorld').style.transform")
        zoom = lambda: page.locator('#studioZoomLabel').inner_text().strip()
        selected = lambda: page.evaluate("() => document.querySelectorAll('.studio-node.selected, .studio-node.is-selected').length")
        hb = page.locator('.studio-node-head').first.bounding_box()
        n0 = node()
        page.mouse.move(hb['x'] + 20, hb['y'] + hb['height'] / 2)
        page.mouse.down(); page.mouse.move(hb['x'] + 120, hb['y'] + 60, steps=8); page.mouse.up()
        checks = [(node() != n0, f"nœud déplacé ({n0} → {node()})")]
        spot = page.evaluate(JS_STUDIO_BACKGROUND, 120)
        w0 = world()
        page.mouse.move(spot['x'], spot['y']); page.mouse.down()
        page.mouse.move(spot['x'] + 70, spot['y'] + 40, steps=8); page.mouse.up()
        w1 = world()
        checks.append((w1 != w0, "fond défilé au bouton gauche"))
        checks.append((selected() >= 1, "un défilement ne désélectionne pas"))
        spot = page.evaluate(JS_STUDIO_BACKGROUND, 120)
        page.mouse.move(spot['x'], spot['y']); page.mouse.down(button='middle')
        page.mouse.move(spot['x'] - 60, spot['y'] - 30, steps=8); page.mouse.up(button='middle')
        checks.append((world() != w1, "fond défilé au bouton du milieu"))
        z0 = zoom()
        spot = page.evaluate(JS_STUDIO_BACKGROUND, 120)
        page.mouse.move(spot['x'], spot['y'])           # sur le canvas : le bouton du milieu a pu l'en sortir
        page.mouse.wheel(0, -300)
        page.wait_for_timeout(200)
        checks.append((zoom() != z0, f"molette {z0} → {zoom()}"))
        # Un port de sortie arme un lien ; Échap l'abandonne (clavier commun, 2026-10-29).
        out_dot = page.locator('.studio-node .dot[data-side="out"]').first
        if out_dot.count():
            out_dot.click()
            page.wait_for_timeout(200)
            armed = page.locator('.dot.is-armed').count()
            page.keyboard.press('Escape')
            page.wait_for_timeout(200)
            left = page.locator('.dot.is-armed').count()
            checks.append((armed == 1 and left == 0, f"un port armé, Échap abandonne le lien ({armed} → {left})"))
        spot = page.evaluate(JS_STUDIO_BACKGROUND, 120)
        page.mouse.click(spot['x'], spot['y'])
        page.wait_for_timeout(200)
        checks.append((selected() == 0, "clic sur le fond → désélection"))
        checks.append((page.locator('.wama-touch-tip').count() == 0, "aucune infobulle tactile à la souris"))
        _collect('studio (souris)', checks, errors, faults, steps)
    finally:
        ctx.close()


def _mouse_queue(browser, token, url, faults, steps):
    ctx, page, resp, errors = _desktop_page(browser, token, url)
    try:
        wrong = _exiger_la_page(page, resp, url)
        if wrong:
            faults.append(f"file (souris) : {wrong[1]}")
            return
        page.wait_for_timeout(2500)
        cards = page.evaluate(JS_CARDS_STATE)
        if len(cards) < 3:
            faults.append(f"file (souris) : {len(cards)} card(s) visible(s), 3 attendues")
            return
        ids = [c['id'] for c in cards]
        card = lambda i: page.locator(f'[data-wama-dnd] .wama-card[data-id="{i}"]')
        box = lambda i: card(i).locator('.wama-select-box')
        by_id = lambda: {c['id']: c for c in page.evaluate(JS_CARDS_STATE)}
        page.mouse.move(2, 450)
        page.wait_for_timeout(300)
        rest = by_id()
        checks = [(all(c['box'] == '0' and not c['hover'] for c in rest.values()),
                   "au repos : cases cachées, aucun survol")]
        card(ids[0]).locator('.wcv3-head').hover()
        page.wait_for_timeout(300)
        s = by_id()
        checks.append((s[ids[0]]['hover'] and s[ids[0]]['box'] == '1' and not s[ids[1]]['hover']
                       and s[ids[1]]['box'] == '0', "survol : la card se teinte et montre SA case, pas les autres"))
        card(ids[0]).locator('.wcv3-head').click(position={'x': 60, 'y': 4})
        page.wait_for_timeout(250)
        page.mouse.move(2, 450)
        page.wait_for_timeout(250)
        s = by_id()
        checks.append((s[ids[0]]['checked'] == 'true' and s[ids[1]]['checked'] == 'false'
                       and s[ids[1]]['box'] == '1', "clic sur la card → cochée seule, les autres cases visibles"))
        card(ids[0]).locator('.wcv3-head').hover()
        page.wait_for_timeout(250)
        checks.append((not by_id()[ids[0]]['hover'], "une card sélectionnée ne prend pas la teinte du survol"))
        # Sans case, les gestes qui suivent n'ont rien à toucher : l'absence se DIT (un locator
        # absent attendrait 30 s et ferait passer le défaut pour un serveur indisponible).
        if not all(box(i).count() for i in ids):
            checks.append((False, "des cards sans case de sélection"))
            page.keyboard.press('Escape')
            _collect('file (souris)', checks, errors, faults, steps)
            return
        box(ids[1]).focus()
        page.keyboard.press(' ')
        page.wait_for_timeout(250)
        s = by_id()
        checks.append((s[ids[0]]['checked'] == 'true' and s[ids[1]]['checked'] == 'true',
                       "Espace sur une case → ajoutée"))
        page.keyboard.press('Escape')
        page.wait_for_timeout(250)
        box(ids[0]).click()
        box(ids[2]).click(modifiers=['Shift'])
        page.wait_for_timeout(250)
        checks.append((sum(1 for c in by_id().values() if c['checked'] == 'true') == 3,
                       "case puis Maj+case → la plage (3)"))
        box(ids[1]).click()
        page.wait_for_timeout(250)
        checks.append((by_id()[ids[1]]['checked'] == 'false', "recocher une case → retirée"))
        page.keyboard.press('Escape')
        _collect('file (souris)', checks, errors, faults, steps)
    finally:
        ctx.close()


def _mouse_editor_and_bell(browser, token, urls, faults, steps):
    ctx, page, resp, errors = _desktop_page(browser, token, urls['editor'])
    try:
        wrong = _exiger_la_page(page, resp, urls['editor'])
        if wrong:
            faults.append(f"éditeur (souris) : {wrong[1]}")
            return
        page.wait_for_selector('.seg-drag[data-i="1"]', timeout=30000)
        page.wait_for_timeout(1500)
        wave = page.locator(EDITOR_WAVE)
        wave.scroll_into_view_if_needed()
        wb = wave.bounding_box()
        y = wb['y'] + wb['height'] / 2
        label = lambda: page.locator(EDITOR_ZOOM).inner_text().strip()
        z0 = label()
        page.mouse.move(wb['x'] + wb['width'] / 2, y)
        page.mouse.wheel(0, -200)
        page.wait_for_timeout(200)
        checks = [(label() != z0, f"molette sur l'onde {z0} → {label()}")]
        _wait_player(page)
        t0 = page.evaluate(JS_EDITOR_TIME)
        page.mouse.move(wb['x'] + wb['width'] * .5, y); page.mouse.down()
        page.mouse.move(wb['x'] + wb['width'] * .3, y, steps=8); page.mouse.up()
        page.wait_for_timeout(300)
        t1 = page.evaluate(JS_EDITOR_TIME)
        checks.append((t1 == t0, "glisser l'onde ne déplace pas la lecture"))
        page.mouse.click(wb['x'] + wb['width'] * .8, y)
        checks.append((_wait_time_change(page, t1) != t1, "clic sur l'onde → lecture déplacée"))
        _collect('éditeur (souris)', checks, errors, faults, steps)
    finally:
        ctx.close()

    ctx, page, resp, errors = _desktop_page(browser, token, urls['queue'])
    try:
        page.wait_for_timeout(1500)
        page.click('#wamaNotificationsLink')
        page.wait_for_selector('.wn-item', timeout=15000)
        page.mouse.move(2, 600)
        page.wait_for_timeout(300)
        rest = page.evaluate(JS_BELL_STATE)
        page.hover('.wn-item .wn-title')
        page.wait_for_timeout(300)
        hover = page.evaluate(JS_BELL_STATE)
        checks = [(rest['tools'] == '0' and rest['dot'] in (None, '1'), f"cloche au repos : outils cachés ({rest})"),
                  (hover['tools'] == '1' and hover['dot'] in (None, '0'), f"cloche au survol : outils montrés ({hover})")]
        _collect('cloche (souris)', checks, errors, faults, steps)
    finally:
        ctx.close()


def _collect(where, checks, errors, faults, steps):
    """Range des (ok, libellé) : les ratés en défauts, le reste en une étape."""
    bad = [label for ok, label in checks if not ok]
    if errors:
        bad.append(f"erreurs JS {errors}")
    if bad:
        faults.append(f"{where} : " + ' ; '.join(bad))
    else:
        steps.append(f"{where} : {len(checks)}/{len(checks)}")


def check_mouse_gestures(paths: dict):
    """Les mêmes pages à la SOURIS : studio, file (case, survol), onde, cloche."""
    def parts(browser, token, urls, faults, steps):
        _mouse_studio(browser, token, urls['studio'], faults, steps)
        _mouse_queue(browser, token, urls['queue'], faults, steps)
        _mouse_editor_and_bell(browser, token, urls, faults, steps)
    return _run_gestures(paths, parts, 'gestures_mouse')


#: La mesure d'un process dans la bande de SA card : le badge, le bouton « Relancer avec ».
_PROC_CHECK_JS = """([pk, process]) => {
    const card = document.querySelector('.wama-card[data-id="' + pk + '"]');
    const row = card && card.querySelector('.wcv3-proc[data-process="' + process + '"]');
    const shown = el => !!(el && el.offsetParent !== null);
    const badge = row && row.querySelector('.wcv3-proc-check');
    const suggest = row && row.querySelector('.wcv3-proc-suggest');
    return {card: !!card, row: !!row, badge: shown(badge), text: badge ? badge.textContent : '',
            title: badge ? (badge.title || '') : '', suggest: shown(suggest)}; }"""


def check_process_check_relaunch(path: str, page_hook=None):
    """La garde (b) « sortie insuffisante » vue dans la FILE (2026-10-22 ; scénario ajouté à la
    revérification du 2026-10-27) — (ok, détail).

    Une transcription du compte de test dont le process porte une mesure qui dit « court », écrite
    par l'écrivain commun (`process_runs.annotate`, celui de `result_evaluation.run_checks`), avec
    le réglage que propose le tirage LOCAL réel (`_local_alternative`, la sortie venant d'un
    modèle distant). Dans la page : la bande de la card montre la mesure et « Relancer avec » ;
    le clic ÉCRIT le réglage par la route de la card (requête réelle) puis joue le ▶ de CE
    process — ce lancement est INTERCEPTÉ et relevé, aucune transcription ne part.
    `page_hook(page)` : posé avant l'ouverture (la contre-épreuve y réécrit un fichier servi)."""
    import re

    from django.urls import reverse
    from playwright.sync_api import sync_playwright

    from wama.common.services import process_runs
    from wama.common.services.nightly_tests import SkipScenario
    from wama.common.services.process_pipeline import app_pipeline
    from wama.common.services.result_evaluation import CHECKS, _local_alternative
    from .ui_smoke import _deplier_autour, _garde_de_montage, _test_account_id, _total_nettoye

    pipeline = app_pipeline('transcriber')
    spec = next((s for s in (pipeline.specs if pipeline else ()) if s.checks), None)
    if spec is None:
        raise SkipScenario("aucun process du transcriber ne déclare de mesure (`ProcessSpec.checks`)")
    token, uid = _test_session_key('transcriber'), _test_account_id('transcriber')
    if not (token and uid):
        raise SkipScenario("aucun compte de test disponible")
    remote = 'albert:whisper-large-v3'
    sessions_before = _session_keys()
    launches, steps, faults = [], [], []
    with _garde_de_montage('transcriber', 'process_check') as cleaned:
        (item,) = _mount_transcripts(uid, count=1)
        try:
            suggestion = _local_alternative('transcriber', item, remote)
            if not suggestion:
                raise SkipScenario(f"aucun modèle local à proposer à la place de {remote}")
            key = spec.checks[0]
            process_runs.start(item, spec.key, process_key='transcriber', task_id='smoke-check')
            process_runs.succeed(item, spec.key, model_key=remote)
            process_runs.annotate(item, spec.key, checks=[{
                'key': key, 'label': CHECKS[key].label, 'value': 0.5, 'short': True,
                'message': 'témoin : 50 % seulement, du texte manque', 'suggest': suggestion}])
            before = getattr(item, suggestion['field'])
            with sync_playwright() as p:
                browser = p.chromium.launch()
                try:
                    context = browser.new_context(viewport={'width': 1500, 'height': 1000})
                    context.add_cookies(_cookie(token))
                    page = context.new_page()
                    page.set_default_timeout(15000)
                    errors = []
                    page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))

                    def intercept(route):
                        launches.append(route.request.url)
                        route.fulfill(status=200, content_type='application/json',
                                      body='{"success": true}')
                    page.route(re.compile(rf'/start/{item.pk}/'), intercept)
                    if page_hook:
                        page_hook(page)
                    page.goto(BASE_URL.rstrip('/') + path, wait_until='load', timeout=PAGE_TIMEOUT_MS)
                    selector = f'.wama-card[data-id="{item.pk}"]'
                    page.wait_for_selector(selector, state='attached', timeout=30000)
                    _deplier_autour(page, selector)
                    page.wait_for_timeout(800)
                    shown = page.evaluate(_PROC_CHECK_JS, [item.pk, spec.key])
                    if not (shown['badge'] and shown['suggest'] and '50' in shown['text'] + shown['title']):
                        faults.append(f"bande : la mesure ou « Relancer avec » manque ({shown})")
                    else:
                        steps.append("bande : la mesure et « Relancer avec » sur la ligne du process")
                        page.locator(f'{selector} .wcv3-proc-suggest').first.click()
                        # Attendre le LANCEMENT, pas une durée : sur un serveur lent l'écriture
                        # du réglage dépassait 2,5 s et le scénario concluait trop tôt
                        # (mesuré le 2026-10-29 sur le serveur jetable, une fois sur deux).
                        for _ in range(60):
                            if launches:
                                break
                            page.wait_for_timeout(250)
                    if errors:
                        faults.append(f"erreurs JS {errors[:3]}")
                finally:
                    browser.close()
            item.refresh_from_db()
            after = getattr(item, suggestion['field'])
            wanted = rf'/start/{item.pk}/{spec.key}/'
            if steps and (after != suggestion['value'] or not any(re.search(wanted, u) for u in launches)):
                faults.append(f"« Relancer avec » : réglage {before!r} → {after!r} (attendu "
                              f"{suggestion['value']!r}), lancement(s) relevé(s) {launches}")
            elif steps:
                steps.append(f"« Relancer avec » : réglage écrit ({suggestion['value']}), puis le ▶ "
                             f"de « {spec.label or spec.key} » seul (intercepté, rien lancé)")
        finally:
            _drop_new_sessions(sessions_before)
            process_runs.forget(item)
            try:
                item.audio.delete(save=False)
            except Exception:
                pass
    if cleaned:
        steps.append(f"{_total_nettoye(cleaned)} objet(s) de montage retiré(s)")
    if faults:
        return False, ' ; '.join(faults)
    return True, ' → '.join(steps)


#: Le chat de l'accueil et le bouton des volets, tels qu'on les voit.
_PHONE_HOME_JS = """() => {
    const box = sel => { const e = document.querySelector(sel); if (!e) return null;
        const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
        return (r.width > 1 && cs.display !== 'none' && cs.visibility !== 'hidden' && !e.hidden)
            ? {left: r.left, right: r.right, top: r.top, width: r.width} : null; };
    const sw = document.querySelector('[data-wama-panels-switch]');
    return {chat: box('#ai-chat textarea'), attach: box('#ai-chat [data-assistant-attach]'),
            viewport: innerWidth,
            switchShown: box('[data-wama-panels-switch]'),
            switchIcon: sw && sw.querySelector('i') ? sw.querySelector('i').className : '',
            deposits: [...document.querySelectorAll('#ai-chat .wama-assistant-deposit')].map(c => c.textContent.trim())};
}"""


def check_phone_home(url_path: str, page_hook=None):
    """L'ACCUEIL À LARGEUR DE TÉLÉPHONE (2026-10-27, décision de Fabien : le mode simplifié est
    retiré, son usage se porte au mode normal) — (ok, détail).

    Sur un téléphone (390 px, doigt), stockage vide : le contexte étroit replie les deux volets,
    le chat de l'accueil est à pleine largeur, sans défilement horizontal ni barre qui déborde ;
    « Joindre » ouvre le SÉLECTEUR du système et le fichier choisi part par le dépôt commun
    (envoi INTERCEPTÉ : rien n'est écrit) puis s'affiche en pastille ; le bouton des volets de
    l'en-tête en rouvre un (le droit, celui de l'assistant), puis les replie. Au bureau, il replie
    les deux, puis reprend sa forme quand chacun est rouvert par sa frontière. `page_hook(page)` :
    posé sur chaque page avant son ouverture (la contre-épreuve y réécrit le code servi)."""
    import json as _json
    import re

    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario

    url = f"{BASE_URL.rstrip('/')}{url_path}"
    sessions_before = _session_keys()
    token = _test_session_key()
    if not token:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    faults, steps, uploads = [], [], []

    def fake_upload(route):
        uploads.append(route.request.method)
        route.fulfill(status=200, content_type='application/json',
                      body=_json.dumps({'uploaded': [{'path': 'temp/joint.txt', 'name': 'joint.txt'}]}))

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                ctx = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=3,
                                          is_mobile=True, has_touch=True)
                ctx.add_cookies(_cookie(token))
                page = ctx.new_page()
                page.route(re.compile(r'.*/filemanager/api/upload/.*'), fake_upload)
                if page_hook:
                    page_hook(page)
                resp = page.goto(url, wait_until='domcontentloaded', timeout=PAGE_TIMEOUT_MS)
                wrong = _exiger_la_page(page, resp, url)
                if wrong:
                    return wrong
                page.wait_for_timeout(1500)
                s, h = page.evaluate(JS_LAYOUT), page.evaluate(_PHONE_HOME_JS)
                faults += _clean_layout(s, 'téléphone 390 px')
                if not s['narrow'] or s['leftOpen'] or s['rightOpen']:
                    faults.append(f"téléphone : attendu le contexte étroit, volets repliés (étroit "
                                  f"{s['narrow']}, gauche {s['leftOpen']}, droite {s['rightOpen']})")
                if not h['chat'] or h['chat']['width'] < 150:
                    faults.append(f"téléphone : la saisie du chat n'est pas utilisable ({h['chat']})")
                if not h['attach'] or h['attach']['right'] > h['viewport']:
                    faults.append(f"téléphone : « Joindre » n'est pas à l'écran ({h['attach']})")
                steps.append(f"téléphone : volets repliés, saisie {round((h['chat'] or {}).get('width', 0))} px, "
                             f"« Joindre » visible")
                if h['attach']:
                    with page.expect_file_chooser(timeout=8000) as chooser:
                        page.locator('#ai-chat [data-assistant-attach]').tap()
                    chooser.value.set_files(files=[{'name': 'joint.txt', 'mimeType': 'text/plain',
                                                    'buffer': b'WAMA'}])
                    page.wait_for_timeout(800)
                    h = page.evaluate(_PHONE_HOME_JS)
                    if uploads != ['POST'] or not any('joint.txt' in d for d in h['deposits']):
                        faults.append(f"« Joindre » : le fichier choisi n'est pas déposé (envois "
                                      f"{uploads}, pastilles {h['deposits']})")
                    steps.append("« Joindre » : sélecteur du système, dépôt commun, pastille")
                if not h['switchShown']:
                    faults.append("téléphone : le bouton des volets n'est pas dans l'en-tête")
                else:
                    page.locator('[data-wama-panels-switch]').tap()
                    page.wait_for_timeout(ANIM_MS)
                    s = page.evaluate(JS_LAYOUT)
                    if s['leftOpen'] or (s['hasRight'] and not s['rightOpen']):
                        faults.append(f"téléphone : le bouton des volets doit rouvrir le seul volet "
                                      f"droit (gauche {s['leftOpen']}, droite {s['rightOpen']})")
                    page.locator('[data-wama-panels-switch]').tap()
                    page.wait_for_timeout(ANIM_MS)
                    s = page.evaluate(JS_LAYOUT)
                    if s['leftOpen'] or s['rightOpen']:
                        faults.append("téléphone : un second toucher doit replier les volets")
                    steps.append("bouton des volets : le volet droit, puis repliés")
                ctx.close()

                ctx = browser.new_context(viewport={'width': 1280, 'height': 800})
                ctx.add_cookies(_cookie(token))
                page = ctx.new_page()
                if page_hook:
                    page_hook(page)
                page.goto(url, wait_until='domcontentloaded', timeout=PAGE_TIMEOUT_MS)
                page.wait_for_timeout(1500)
                page.locator('[data-wama-panels-switch]').click()
                page.wait_for_timeout(ANIM_MS)
                s, h = page.evaluate(JS_LAYOUT), page.evaluate(_PHONE_HOME_JS)
                if s['leftOpen'] or s['rightOpen'] or 'fa-expand' not in h['switchIcon']:
                    faults.append(f"bureau : le bouton doit replier les deux volets et changer de forme "
                                  f"(gauche {s['leftOpen']}, droite {s['rightOpen']}, {h['switchIcon']})")
                _edge(page, 'left', False)
                h = page.evaluate(_PHONE_HOME_JS)
                if 'fa-expand' not in h['switchIcon']:
                    faults.append("bureau : un seul volet rouvert, le bouton doit garder sa forme « repliés »")
                _edge(page, 'right', False)
                s, h = page.evaluate(JS_LAYOUT), page.evaluate(_PHONE_HOME_JS)
                if not (s['leftOpen'] and s['rightOpen']) or 'fa-table-columns' not in h['switchIcon']:
                    faults.append(f"bureau : les deux volets rouverts, le bouton reprend sa forme "
                                  f"({s['leftOpen']}, {s['rightOpen']}, {h['switchIcon']})")
                faults += _clean_layout(s, 'bureau 1 280 px')
                steps.append("bureau : repliés d'un geste, rouverts un par un, le bouton suit")
            finally:
                browser.close()
    except SkipScenario:
        raise
    except Exception as error:
        faults.append(f"interrompu : {type(error).__name__} — {str(error).splitlines()[0][:200]}")
    finally:
        _drop_new_sessions(sessions_before)
    if faults:
        return False, ' ; '.join(faults)
    return True, ' → '.join(steps)


#: Les ÉCRANS du relevé du 2026-10-28 (`ROADMAP §27`) : (nom, largeur, hauteur, densité, tactile).
SCREENS = (
    ('21:9 3440', 3440, 1440, 1, False),
    ('21:9 2560', 2560, 1080, 1, False),
    ('4K à 150 %', 2560, 1440, 1.5, False),
    ('Full HD', 1920, 1080, 1, False),
    ('portable', 1366, 768, 1, False),
    ('tablette paysage', IPAD_LANDSCAPE['width'], IPAD_LANDSCAPE['height'], 2, True),
    ('tablette portrait', IPAD_PORTRAIT['width'], IPAD_PORTRAIT['height'], 2, True),
    ('téléphone', 390, 844, 3, True),
)

#: Les éléments VISIBLES qui sortent de l'écran par la droite : un bouton qu'on ne peut plus
#: atteindre, une barre qui fait défiler son conteneur de côté. Ce qu'un ancêtre coupe EXPRÈS
#: (`overflow: hidden | clip` — un texte abrégé) n'en est pas.
JS_OUT_OF_SCREEN = """() => {
    const vw = document.documentElement.clientWidth, out = [];
    const cut = e => { for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) {
        const x = getComputedStyle(a).overflowX; if (x === 'hidden' || x === 'clip') return true; }
        return false; };
    for (const e of document.body.querySelectorAll('*')) {
        const r = e.getBoundingClientRect();
        if (r.width < 1 || r.right <= vw + 2) continue;
        if (e.checkVisibility && !e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) continue;
        if (cut(e)) continue;
        out.push((e.id ? '#' + e.id : e.tagName.toLowerCase() + [...e.classList].slice(0, 2).map(c => '.' + c).join(''))
                 + ' +' + Math.round(r.right - vw) + ' px');
        if (out.length >= 3) break;
    }
    return out; }"""


def check_screen_layouts(paths: dict, page_hook=None):
    """La MISE EN PAGE de l'écran 21:9 au téléphone (2026-10-28, question de Fabien : « toute l'UI
    de WAMA sera bien propre quel que soit l'écran ») — (ok, détail).

    Sur chaque écran de `SCREENS` et chaque page de `paths` ({libellé: chemin}) : ni chevauchement
    de la barre du haut ou du pied, ni débordement, ni défilement horizontal (les mesures de
    `common.layout.tablet`), et aucun élément VISIBLE hors de l'écran (`JS_OUT_OF_SCREEN`). Rien
    n'est écrit : la page est seulement lue. `page_hook(page)` : posé sur chaque page (contre-épreuve)."""
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario

    sessions_before = _session_keys()
    token = _test_session_key()
    if not token:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    faults, measured = [], 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for name, width, height, density, touch in SCREENS:
                    ctx = browser.new_context(viewport={'width': width, 'height': height},
                                              device_scale_factor=density, has_touch=touch,
                                              is_mobile=touch and width < 768)
                    ctx.add_cookies(_cookie(token))
                    page = ctx.new_page()
                    if page_hook:
                        page_hook(page)
                    for label, path in paths.items():
                        url = f"{BASE_URL.rstrip('/')}{path}"
                        try:
                            resp = page.goto(url, wait_until='load', timeout=PAGE_TIMEOUT_MS)
                        except Exception as error:
                            faults.append(f"{name} · {label} : {type(error).__name__}")
                            continue
                        if resp is None or resp.status != 200:
                            continue                  # une page refusée au compte n'est pas mesurée
                        page.wait_for_timeout(1200)
                        faults += _clean_layout(page.evaluate(JS_LAYOUT), f"{name} · {label}")
                        out = page.evaluate(JS_OUT_OF_SCREEN)
                        if out:
                            faults.append(f"{name} · {label} : hors de l'écran {out}")
                        measured += 1
                    ctx.close()
            finally:
                browser.close()
    except SkipScenario:
        raise
    except Exception as error:
        faults.append(f"interrompu : {type(error).__name__} — {str(error).splitlines()[0][:200]}")
    finally:
        _drop_new_sessions(sessions_before)
    detail = f"{len(SCREENS)} écrans × {len(paths)} pages ({measured} mesurées)"
    if faults:
        return False, detail + ' — ' + ' ; '.join(faults[:12]) + (f' (+{len(faults) - 12})' if len(faults) > 12 else '')
    return True, detail


def screen_pages() -> dict:
    """Les pages du relevé des écrans : l'accueil, le journal, le calendrier, et l'index de chaque
    app que WAMA découvre (`ui_smoke.discoverable_apps`) — aucune nommée ici."""
    from django.urls import NoReverseMatch, reverse

    from .ui_smoke import discoverable_apps
    pages = {}
    for label, name in (('accueil', 'home'), ('journal', 'common:journal'), ('calendrier', 'common:calendar')):
        try:
            pages[label] = reverse(name)
        except NoReverseMatch:
            pass
    pages.update(dict(discoverable_apps()))
    return pages


#: Ce que voit l'utilisateur d'une file : la card choisie, celle de premier plan en pile, la
#: sélection multiple, une modale, le panneau des notifications.
_KEYS_STATE_JS = """() => ({
    selected: [...document.querySelectorAll('.inspector-selected')].map(e => e.dataset.id || 'lot'),
    stack: [...document.querySelectorAll('.is-stack-focus')].map(e => e.dataset.id),
    multi: document.querySelectorAll('.wama-dnd-selected').length,
    modal: !!document.querySelector('.modal.show'),
    panel: !!(document.getElementById('wama-notifications-panel')
              && !document.getElementById('wama-notifications-panel').hidden),
})"""


def check_keyboard_owners(path: str, page_hook=None):
    """Une touche, UN propriétaire (clavier commun `wama-keys.js`, 2026-10-29) — (ok, détail).

    Les trois défauts mesurés le 29/10 avant lui, sur la file du transcriber : ↓ dans le panneau
    des notifications déplaçait aussi la card choisie ; Échap qui le fermait la désélectionnait et
    vidait la sélection multiple ; Échap qui fermait une modale vidait cette sélection. Et le geste
    qui doit RESTER : en pile, ↓ déplace la card choisie et la pile la suit. Témoins : quatre
    transcriptions du compte de test ; les écritures de la page sont refusées (`BLOCK_WRITES`) ; la
    liste des notifications est SIMULÉE dans le seul navigateur du scénario.
    `page_hook(page)` : posé avant l'ouverture (la contre-épreuve y réécrit un fichier servi)."""
    import json
    import re

    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario
    from .ui_smoke import _garde_de_montage, _test_account_id, _total_nettoye

    token, uid = _test_session_key('transcriber'), _test_account_id('transcriber')
    if not (token and uid):
        raise SkipScenario("aucun compte de test disponible")
    fake = {'items': [{'id': 900001 + i, 'title': f'Témoin {i}', 'body': '', 'read': False,
                       'tone': 'neutral', 'icon': 'fa-bell', 'actions': [],
                       'created_at': '2026-10-29T10:0%d:00Z' % i} for i in range(3)],
            'unread': 3, 'total': 3}
    sessions_before = _session_keys()
    checks, steps = [], []
    with _garde_de_montage('transcriber', 'keyboard_owners') as cleaned:
        made = _mount_transcripts(uid, count=4)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                try:
                    ctx, page, resp, errors = _desktop_page(browser, token, BASE_URL.rstrip('/') + path,
                                                            page_hook)
                    ctx.route(re.compile(r'/common/api/notifications/'),
                              lambda r: r.fulfill(status=200, content_type='application/json',
                                                  body=json.dumps(fake))
                              if r.request.method == 'GET' else r.continue_())
                    card = '.wama-card[data-id]:not(.is-batch)'
                    page.wait_for_selector(card, timeout=30000)
                    page.wait_for_timeout(1200)
                    state = lambda: page.evaluate(_KEYS_STATE_JS)

                    # 1. En pile, ↓ : la card choisie avance, la pile la suit.
                    stack_btn = page.locator('.wama-stack-btn >> visible=true').first
                    stack_btn.click()
                    page.wait_for_timeout(400)
                    page.locator(card).first.click(position={'x': 30, 'y': 12})
                    page.wait_for_timeout(400)
                    page.evaluate("() => document.activeElement && document.activeElement.blur()")
                    s0 = state()
                    page.keyboard.press('ArrowDown')
                    page.wait_for_timeout(500)
                    s = state()
                    checks.append((s['selected'] and s['selected'] != s0['selected'] and s['stack'] == s['selected'],
                                   f"en pile, ↓ : la card choisie avance et la pile la suit "
                                   f"({s0['selected']} → {s['selected']}, pile {s['stack']})"))
                    stack_btn.click()
                    page.wait_for_timeout(400)

                    # 2. Le panneau des notifications garde ses touches.
                    page.locator(card).first.click(position={'x': 30, 'y': 12})
                    page.wait_for_timeout(300)
                    page.click('#wamaNotificationsLink')
                    page.wait_for_selector('.wn-row', timeout=10000)
                    page.wait_for_timeout(300)
                    s0 = state()
                    page.keyboard.press('ArrowDown')
                    page.wait_for_timeout(300)
                    s = state()
                    checks.append((s0['panel'] and s['selected'] == s0['selected'],
                                   f"↓ dans le panneau des notifications ne déplace pas la card "
                                   f"({s0['selected']} → {s['selected']})"))
                    page.keyboard.press('Escape')
                    page.wait_for_timeout(300)
                    s2 = state()
                    checks.append((not s2['panel'] and s2['selected'] == s0['selected'] and s2['multi'] == s0['multi'],
                                   f"Échap ferme le panneau, rien d'autre (card {s2['selected']}, "
                                   f"sélection {s0['multi']} → {s2['multi']})"))

                    # 3. Échap qui ferme une modale garde la sélection multiple.
                    page.locator(card).nth(0).click(position={'x': 30, 'y': 12})
                    page.locator(card).nth(1).click(position={'x': 30, 'y': 12}, modifiers=['Control'])
                    page.wait_for_timeout(300)
                    s0 = state()
                    page.locator(f'{card} .settings-btn >> visible=true').first.click()
                    page.wait_for_selector('.modal.show', timeout=10000)
                    page.wait_for_timeout(500)
                    page.keyboard.press('Escape')
                    page.wait_for_timeout(600)
                    s = state()
                    checks.append((s0['multi'] == 2 and not s['modal'] and s['multi'] == 2,
                                   f"Échap ferme la modale et garde la sélection ({s0['multi']} → {s['multi']})"))

                    # 4. Hors couche, Échap reste l'abandon de la sélection.
                    page.evaluate("() => document.activeElement && document.activeElement.blur()")
                    page.keyboard.press('Escape')
                    page.wait_for_timeout(300)
                    s = state()
                    checks.append((s['multi'] == 0, f"hors couche, Échap relâche la sélection ({s['multi']})"))
                    if errors:
                        checks.append((False, f"erreurs JS {errors[:3]}"))
                    ctx.close()
                finally:
                    browser.close()
        except SkipScenario:
            raise
        except Exception as exc:
            raise SkipScenario(_motif_skip(exc))
        finally:
            _drop_new_sessions(sessions_before)
            for t in made:
                try:
                    t.audio.delete(save=False)
                except Exception:
                    pass
    if cleaned:
        steps.append(f"{_total_nettoye(cleaned)} objet(s) de montage retiré(s)")
    faults = [label for ok, label in checks if not ok]
    if faults:
        return False, ' ; '.join(faults)
    return True, f"{len(checks)}/{len(checks)} : " + ' → '.join([label for _, label in checks] + steps)


def register_layout_scenarios():
    """Enregistre `common.layout.tablet` (la mise en page à largeur de tablette), `common.layout.
    screens` (de l'écran 21:9 au téléphone), `common.gestures.touch` (les gestes au doigt) et
    `common.gestures.mouse` (les mêmes à la souris)."""
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
    register(
        id="common.layout.phone", app="common", stage="ui",
        description=("Accueil à largeur de téléphone (le mode simplifié retiré le 2026-10-27) : volets "
                     "repliés, chat utilisable, « Joindre » par le sélecteur du système (envoi "
                     "intercepté), bouton des volets de l'en-tête — et au bureau, repliés d'un geste, "
                     "rouverts un par un"),
        run=(lambda h=reverse('home'): (lambda ctx: check_phone_home(h)))(),
        timeout_s=180, vram_gb=0.0,
    )
    register(
        id="common.layout.screens", app="common", stage="ui",
        description=("Mise en page de l'écran 21:9 au téléphone (8 écrans) sur l'accueil, le journal, "
                     "le calendrier et chaque app : barre et pied sans chevauchement, aucun défilement "
                     "horizontal, aucun élément visible hors de l'écran"),
        run=lambda ctx: check_screen_layouts(screen_pages()),
        timeout_s=1200, vram_gb=0.0,
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
        timeout_s=300, vram_gb=0.0,
    )
    register(
        id="common.gestures.mouse", app="common", stage="ui",
        description=("Les mêmes pages à la SOURIS, garde du PC : studio (catalogue, nœud, fond aux boutons "
                     "gauche et du milieu, molette, désélection), file (survol commun, case au clic, à "
                     "Espace, plage Maj), onde du transcriber, panneau de la cloche"),
        run=(lambda g=gesture_paths: (lambda ctx: check_mouse_gestures(g)))(),
        timeout_s=240, vram_gb=0.0,
    )
    register(
        id="common.keyboard_owners", app="common", stage="ui",
        description=("Une touche, UN propriétaire (clavier commun `wama-keys.js`) dans la file : en pile "
                     "↓ déplace la card choisie et la pile la suit ; le panneau des notifications garde "
                     "↓ et Échap ; Échap qui ferme une modale garde la sélection multiple, hors couche "
                     "il la relâche — liste des notifications simulée, écritures refusées"),
        run=(lambda p=path: (lambda ctx: check_keyboard_owners(p)))(),
        timeout_s=180, vram_gb=0.0,
    )
    register(
        id="transcriber.process_check_relaunch", app="transcriber", stage="ui",
        description=("Garde (b) dans la file : la bande des process d'une card montre la mesure "
                     "« sortie insuffisante » de son process et « Relancer avec » ; le clic écrit "
                     "le réglage proposé (le modèle local) puis joue le ▶ de CE process — lancement "
                     "intercepté, aucune transcription ne part"),
        run=(lambda p=path: (lambda ctx: check_process_check_relaunch(p)))(),
        timeout_s=180, vram_gb=0.0,
    )

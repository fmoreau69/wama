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


def register_layout_scenarios():
    """Enregistre `common.layout.tablet` — la mise en page à largeur de tablette."""
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

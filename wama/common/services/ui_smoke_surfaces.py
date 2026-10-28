"""
Smoke nocturne des SURFACES — chaque page d'édition déclarée s'ouvre sur un élément témoin, sans
erreur, et chaque brique y est CAPTURÉE pour le catalogue des briques UI (2026-10-18, décision de
Fabien : « une petite prévisualisation de la brique pour qu'on sache rapidement de quoi il
s'agit », la vignette qui s'agrandit au clic).

POURQUOI UN TÉMOIN. Le compte de test ne travaille pas : il n'avait AUCUN élément sur les trois
surfaces (mesuré ce jour-là), et une surface ne s'ouvre que sur un élément qui porte ce qu'elle
édite. Aucun chemin de création commun n'est sans effet de bord (`add_to_composer` LANCE la
génération, le Writer n'a pas de triade) : chaque surface DÉCLARE donc son témoin
(`Surface.witness`, une donnée — écrite aussi au manifeste d'une app générée), et le contenu des
champs fichiers vient de la fabrique de témoins du harnais (`ui_smoke.witness_sample`). Rien ne
nomme une app ici : le scénario parcourt les surfaces déclarées.

CE QUI EST ÉCRIT, ET CE QUI NE L'EST PAS. Les éléments témoins vivent le temps du passage, sous
la garde de montage commune (`_garde_de_montage` : ce que le passage a créé, fichiers compris,
jamais un objet préexistant). Les vignettes, elles, RESTENT : c'est leur raison d'être
(`surfaces.thumbnail_path`, sous `STATIC_ROOT`, non versionnées). Aucune tâche n'est lancée.

Des BRIQUES seules (2026-10-19, « trois niveaux », `ROUTE §F3b`) : un mécanisme n'a pas de
vignette, il se voit dans la brique qu'il compose.
"""
from __future__ import annotations

from contextlib import ExitStack

from .ui_smoke import (BASE_URL, IGNORED_CONSOLE, _drop_new_sessions, _garde_de_montage,
                       _in_plain_thread, _session_keys, _test_account_id, _test_session_key,
                       _total_nettoye, witness_sample)
from .ui_smoke_matching import _cookie

#: Les emplacements d'une surface, repérés par l'identifiant que gridstack porte
#: (`el.gridstackNode.id`, `wama-brick-layout.js`) — lu dans la page plutôt que posé par le noyau.
_TAG_SLOTS_JS = """() => {
    const out = [];
    document.querySelectorAll('.grid-stack-item').forEach(el => {
        const id = el.gridstackNode && el.gridstackNode.id;
        if (id) { el.setAttribute('data-capture-slot', id); out.push(id); }
    });
    return out; }"""


def _witness_surfaces():
    """Les surfaces qui déclarent un témoin, et ce qui empêche d'en fabriquer un (par surface)."""
    from wama.common.surfaces import SURFACES, load_all
    load_all()
    ready, refused = [], []
    for surface in SURFACES.values():
        if not surface.witness:
            continue
        problems = surface.witness_problems()
        (refused if problems else ready).append((surface, problems))
    return [s for s, _p in ready], [p for _s, problems in refused for p in problems]


def mount_witness(surface, user_id: int):
    """L'élément témoin d'une surface, pour le compte de test : les valeurs déclarées, les champs
    FICHIER remplis par la fabrique de témoins (`wama_temoin_*` : le balayage les reconnaît).
    Rend son pk, ou lève `ValueError` avec la raison que la surface donne de ne pas s'ouvrir."""
    from django.contrib.auth import get_user_model
    from django.core.files.base import ContentFile
    from django.db.models import FileField

    model = surface.model_class()
    item = model(user=get_user_model().objects.get(pk=user_id))
    for name, value in surface.witness.items():
        if isinstance(model._meta.get_field(name), FileField):
            content, ext = witness_sample(value)
            getattr(item, name).save(f'wama_temoin_brique_{surface.key}_{name}{ext}',
                                     ContentFile(content), save=False)
        else:
            setattr(item, name, value)
    item.save()
    ok, reason = surface.can_open(item)
    if not ok:
        raise ValueError(f"surface {surface.id} : le témoin ne l'ouvre pas — {reason}")
    return item.pk


def _capture_surface(context, token, surface, pk, captured, opened, faults, reverse):
    """Ouvre UNE surface sur son témoin et capture celles de ses briques pas encore capturées.

    ⚠ Pas de `networkidle` : une surface temporelle interroge le serveur EN CONTINU (suivi du
    rendu, pics de l'onde) — le réseau ne se tait jamais, mesuré le 2026-10-18 sur la partition du
    composer (45 s d'attente, puis échec). On attend que les briques soient MONTÉES."""
    context.add_cookies(_cookie(token))
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
    page.on('console', lambda m: errors.append(f'console: {m.text}') if m.type == 'error' else None)
    url = BASE_URL.rstrip('/') + reverse('common:surface', args=[surface.app, surface.key, pk])
    response = page.goto(url, wait_until='load', timeout=45000)
    if not response or response.status != 200:
        faults.append(f"{surface.id} : HTTP {getattr(response, 'status', None)}")
        return
    page.wait_for_selector('.grid-stack-item .wama-brick-body', timeout=20000)
    page.wait_for_timeout(2500)                          # le temps que les briques dessinent
    slots = page.evaluate(_TAG_SLOTS_JS)
    errors = [e for e in errors if not any(t in e for t in IGNORED_CONSOLE)]
    if errors:
        faults.append(f"{surface.id} : erreurs JS {errors[:3]}")
    opened.append(surface.id)
    for slot in surface.slots:
        # La présentation de RÉFÉRENCE d'une brique est un emplacement sans options : « Texte en
        # sections » renommé « Source ABC » sur la partition ne dit pas ce que la brique est
        # d'ordinaire (vu à la 1ʳᵉ capture, 2026-10-18). Rang 0 = sans options, gardé s'il existe.
        rank = 1 if slot.options else 0
        if slot.id not in slots or captured.get(slot.brick, (2,))[0] <= rank:
            continue
        shot = page.locator(f'[data-capture-slot="{slot.id}"]').screenshot()
        captured[slot.brick] = (rank, surface.id, shot)


def capture_brick_thumbnails():
    """Ouvre chaque surface sur son témoin et capture ses briques — (ok, détail).

    Échec : une surface qui ne s'ouvre pas, une erreur JS, un témoin déclaré mais refusé. Une
    brique montée sur plusieurs surfaces garde sa présentation de RÉFÉRENCE (un emplacement sans
    options), sinon la première vue ; les vignettes ne s'écrivent qu'à la fin du passage."""
    from django.urls import reverse
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario
    from wama.common.surfaces import thumbnail_path

    surfaces, refused = _witness_surfaces()
    if not surfaces and not refused:
        raise SkipScenario("aucune surface ne déclare de témoin (`Surface.witness`)")
    faults, captured, opened = list(refused), {}, []
    sessions_before = _session_keys()
    with ExitStack() as guards:
        cleaned = [guards.enter_context(_garde_de_montage(app, 'surfaces'))
                   for app in sorted({s.app for s in surfaces})]
        plan = []
        for surface in surfaces:
            token, uid = _test_session_key(surface.app), _test_account_id(surface.app)
            if not (token and uid):
                faults.append(f"{surface.id} : aucun compte de test disponible")
                continue
            try:
                pk = _in_plain_thread(mount_witness, surface, uid)
            except Exception as error:
                faults.append(str(error))
                continue
            plan.append((surface, token, pk))
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for surface, token, pk in plan:
                    context = browser.new_context(viewport={'width': 1500, 'height': 1000})
                    try:
                        _capture_surface(context, token, surface, pk, captured, opened, faults,
                                         reverse)
                    except Exception as error:           # une surface en échec n'arrête pas les autres
                        faults.append(f"{surface.id} : {type(error).__name__} — {str(error)[:200]}")
                    finally:
                        context.close()
            finally:
                browser.close()
    for brick, (_rank, _surface, shot) in captured.items():
        target = thumbnail_path(brick)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(shot)
    dropped = _drop_new_sessions(sessions_before)
    detail = (f"{len(opened)} surface(s) ouverte(s) sur leur témoin ({', '.join(opened) or '—'}) ; "
              f"{len(captured)} brique(s) capturée(s) : "
              + ', '.join(f'{b} ← {s}' for b, (_r, s, _shot) in sorted(captured.items()))
              + f" ; {sum(_total_nettoye(c) for c in cleaned)} objet(s) témoin(s) retiré(s)"
              + (f", {dropped} session(s) de test closes" if dropped else ''))
    if faults:
        return False, ' ; '.join(faults) + ' — ' + detail
    return True, detail


#: Ce que la page dit de sa grille : figée, places des emplacements (et leur ZONE : la grille ou
#: la colonne du volet, 2026-10-21), titres visibles, poignées.
_GRID_STATE_JS = """() => {
    const root = document.querySelector('.wama-surface-grid');
    const panel = document.querySelector('.wama-surface-panel');
    const seen = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    const places = {};
    [[root, 'grid'], [panel, 'panel']].forEach(([zoneRoot, zone]) => {
        if (!zoneRoot) return;
        zoneRoot.querySelectorAll(':scope > .grid-stack-item').forEach(el => {
            const n = el.gridstackNode;
            if (n && n.id) places[n.id] = {x: n.x, y: n.y, w: n.w, h: n.h, zone: zone};
        });
    });
    const freeze = document.querySelector('[data-act="freeze"]');
    const reset = document.querySelector('[data-act="layout"]');
    // Les DEUX zones comptent : figer, c'est figer la grille ET la colonne du volet.
    const zones = [root, panel].filter(Boolean);
    const all = s => zones.reduce((n, z) => n + [...z.querySelectorAll(s)].filter(seen).length, 0);
    return {
        static: zones.every(z => z.classList.contains('grid-stack-static')),
        loose: zones.every(z => !z.classList.contains('grid-stack-static')),
        frozen: !!document.querySelector('.wama-surface-page.is-frozen')
                && (!panel || panel.classList.contains('is-frozen')),
        columns: root.gridstack ? root.gridstack.getColumn() : null,
        places: places,
        heads: all('.wama-brick-head'),
        bareHeads: all('.wama-brick-head:not(.has-tools)'),
        // PRÉSENTES, pas visibles : gridstack ne les montre qu'au survol ; une grille figée les retire.
        handles: zones.reduce((n, z) => n + z.querySelectorAll('.ui-resizable-handle').length, 0),
        freezeText: freeze ? freeze.textContent.trim() : null,
        resetDisabled: reset ? reset.disabled : null,
    }; }"""

#: Un geste de gridstack lui-même (son `update`, qui émet `change` comme un glisser) : l'emplacement
#: `id` prend la place `place`.
_MOVE_JS = """([id, place]) => {
    const root = document.querySelector('.wama-surface-grid');
    const el = [...root.querySelectorAll('.grid-stack-item')].find(e => e.gridstackNode && e.gridstackNode.id === id);
    root.gridstack.update(el, place);
    return !!el; }"""

#: Le même élément passé de la grille à la COLONNE du volet, par gridstack lui-même (ce que fait
#: un glisser d'une zone à l'autre : `removed` d'un côté, `added` de l'autre). Marqué avant : on
#: vérifie après coup que c'est bien le même élément, la brique n'étant jamais remontée.
_TO_PANEL_JS = """([id, h]) => {
    const root = document.querySelector('.wama-surface-grid');
    const panel = document.querySelector('.wama-surface-panel');
    const el = [...root.querySelectorAll('.grid-stack-item')].find(e => e.gridstackNode && e.gridstackNode.id === id);
    if (!el || !panel) return false;
    el.dataset.smokeMoved = id;
    root.gridstack.removeWidget(el, false);
    panel.appendChild(el);
    panel.gridstack.makeWidget(el, {id: id, x: 0, y: 0, w: 1, h: h});
    return true; }"""

#: L'élément marqué est-il toujours là, et dans quelle zone ?
_MOVED_JS = """(id) => { const el = document.querySelector('[data-smoke-moved="' + id + '"]');
    return el ? (el.closest('.wama-surface-panel') ? 'panel' : 'grid') : null; }"""


def check_surface_layout(page_hook=None):
    """La DISPOSITION par compte d'une surface (2026-10-21, demande de Fabien) — (ok, détail).

    Sur une surface témoin qui porte le panneau Actions : elle s'ouvre FIGÉE (verrouillée par défaut
    pour tous) ; « Modifier » rend la main ; un panneau agrandi est gardé au serveur, un panneau
    passé dans la COLONNE du volet aussi, avec sa zone, sans être remonté ; « Figer » fige les deux
    zones (plus de poignée, titres sans outils masqués, « Disposition par défaut » inactif) et
    survit au rechargement ; « Disposition par défaut » rend la disposition DÉCLARÉE (gardée vide),
    le panneau revenu dans sa zone ; sur une fenêtre de téléphone la grille s'empile sur une colonne
    sans rien réécrire. Le réglage du compte de test est rendu tel qu'il était en sortie.
    `page_hook(page)` : posé sur chaque page avant son ouverture (la contre-épreuve y réécrit le
    noyau servi)."""
    return _on_layout_witness(_layout_gestures, page_hook)


def check_surface_stack(page_hook=None):
    """EMPILER et ÉPINGLER (2026-10-26, demande de Fabien : « empiler des briques pour les
    compacter en une seule, uniquement en affichage », et les garder à un bord) — (ok, détail).

    Sur la même surface témoin, disposition modifiable : deux panneaux empilés en UN (les mêmes
    éléments, gardés au serveur) ; le panneau épinglé en bas (entre l'en-tête et le pied, la page
    s'en écarte), puis à gauche (une colonne fixe sous l'en-tête) ; le rechargement le rend tel
    quel ; descendre la tête change la tête et l'épinglage la suit ; détacher rend deux panneaux ;
    « Dans la page » le désépingle. Puis (revérification du 2026-10-27) : FIGÉE, la pile épinglée
    reste à son bord sans ses outils d'atelier, et l'épingle quitte les panneaux ordinaires ;
    « Disposition par défaut » défait les piles et GARDE l'épinglage (une préférence de lecture) ;
    sur un téléphone la colonne reste dans la page sans rien réécrire. Et (2026-10-27, le cadre
    des bords) la GARDE PERMANENTE après chaque geste et chaque ouverture — rien d'épinglé hors de
    la zone sûre mesurée sur l'en-tête, le pied et les volets réels, aucune brique écrasée —, plus
    la pile épinglée retouchée (un 3ᵉ panneau empilé puis détaché, la page rechargée) qui garde sa
    bande. Mêmes garanties de sortie que `check_surface_layout`."""
    return _on_layout_witness(_stack_gestures, page_hook)


def _on_layout_witness(gestures, page_hook=None):
    """La charpente commune des scénarios de DISPOSITION : la surface témoin qui porte le panneau
    Actions, le compte de test, le réglage de disposition du compte rendu tel qu'il était en
    sortie ; `gestures(page, url, surface, declared, stored, verdict, errors)` joue les gestes."""
    from django.urls import reverse
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario
    from wama.common.utils.user_settings import get_user_app_setting, save_user_app_settings

    surfaces, _refused = _witness_surfaces()
    candidates = [s for s in surfaces if any(slot.brick == 'surface_actions' for slot in s.slots)]
    if not candidates:
        raise SkipScenario("aucune surface témoin ne porte le panneau Actions")
    surface = sorted(candidates, key=lambda s: s.id)[0]
    token, uid = _test_session_key(surface.app), _test_account_id(surface.app)
    if not (token and uid):
        raise SkipScenario("aucun compte de test disponible")
    name = f'surface_layout.{surface.key}'

    def stored():
        from django.contrib.auth import get_user_model
        return get_user_app_setting(get_user_model().objects.get(pk=uid), surface.app, name)

    def restore(value):
        from django.contrib.auth import get_user_model

        from wama.common.utils.user_settings import clear_user_app_settings
        user = get_user_model().objects.get(pk=uid)
        if value is None:
            clear_user_app_settings(user, surface.app, [name])
        else:
            save_user_app_settings(user, surface.app, {name: value})

    before = _in_plain_thread(stored)
    verdicts = []

    def verdict(ok, text):
        verdicts.append((bool(ok), text))

    sessions_before = _session_keys()
    try:
        with _garde_de_montage(surface.app, 'surfaces'):
            pk = _in_plain_thread(mount_witness, surface, uid)
            _in_plain_thread(restore, None)          # le passage part de la disposition déclarée
            declared = {s.id: {'x': s.x, 'y': s.y, 'w': s.w, 'h': s.h, 'zone': s.zone}
                        for s in surface.slots}
            url = BASE_URL.rstrip('/') + reverse('common:surface', args=[surface.app, surface.key, pk])
            with sync_playwright() as p:
                browser = p.chromium.launch()
                try:
                    context = browser.new_context(viewport={'width': 1500, 'height': 1000})
                    context.add_cookies(_cookie(token))
                    page = context.new_page()
                    page.set_default_timeout(10000)
                    errors = []
                    page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
                    if page_hook:
                        page_hook(page)
                    gestures(page, url, surface, declared, stored, verdict, errors)
                finally:
                    browser.close()
    finally:
        _in_plain_thread(restore, before)
        _drop_new_sessions(sessions_before)
    failed = [text for ok, text in verdicts if not ok]
    detail = f"{surface.id} : {len(verdicts) - len(failed)}/{len(verdicts)} gestes"
    return (not failed), detail + (f" — ÉCHECS : {failed}" if failed else '')


def _layout_gestures(page, url, surface, declared, stored, verdict, errors):
    """Les gestes de `check_surface_layout`, dans l'ordre ; un geste qui ne peut plus se faire
    (bouton inactif, page qui ne monte pas) est un verdict rouge, pas une exception."""

    def open_page():
        page.goto(url, wait_until='load', timeout=45000)
        page.wait_for_selector('[data-act="freeze"]', timeout=20000)
        page.wait_for_timeout(800)
        return page.evaluate(_GRID_STATE_JS)

    def settle():
        page.wait_for_timeout(900)                   # la garde part 300 ms après le geste
        return _in_plain_thread(stored)

    try:
        state = open_page()
        verdict(state['static'] and state['frozen'] and state['handles'] == 0
                and state['freezeText'] == 'Modifier la disposition' and state['places'] == declared,
                f"ouverture : verrouillée, disposition déclarée ({state})")

        page.click('[data-act="freeze"]')
        state = page.evaluate(_GRID_STATE_JS)
        kept = settle() or {}
        verdict(state['loose'] and not state['frozen'] and state['handles'] > 0
                and state['bareHeads'] > 0 and not state['resetDisabled'] and kept.get('frozen') is False,
                f"« Modifier » : la main est rendue ({state}, {kept})")

        moved_id = surface.slots[0].id
        target = dict(declared[moved_id], h=declared[moved_id]['h'] + 2)
        page.evaluate(_MOVE_JS, [moved_id, target])
        kept = settle() or {}
        verdict((kept.get('slots') or {}).get(moved_id) == target and not kept.get('frozen'),
                f"panneau agrandi → gardé au serveur ({kept})")

        to_panel = next(s.id for s in surface.slots if s.brick == 'surface_actions')
        moved = page.evaluate(_TO_PANEL_JS, [to_panel, declared[to_panel]['h']])
        kept = settle() or {}
        in_panel = (kept.get('slots') or {}).get(to_panel) or {}
        verdict(moved and in_panel.get('zone') == 'panel' and (in_panel.get('x'), in_panel.get('w')) == (0, 1)
                and page.evaluate(_MOVED_JS, to_panel) == 'panel',
                f"panneau passé dans la colonne du volet → gardé avec sa zone, même élément ({in_panel})")

        page.click('[data-act="freeze"]')
        state = page.evaluate(_GRID_STATE_JS)
        kept = settle() or {}
        verdict(state['static'] and state['frozen'] and state['handles'] == 0
                and state['bareHeads'] == 0 and state['resetDisabled']
                and state['freezeText'] == 'Modifier la disposition' and kept.get('frozen') is True,
                f"« Figer » : les deux zones figées, titres sans outils masqués ({state}, {kept})")

        state = open_page()
        verdict(state['static'] and state['frozen'] and state['places'].get(moved_id) == target
                and (state['places'].get(to_panel) or {}).get('zone') == 'panel',
                f"rechargement : toujours figée, places et zone gardées ({state['places']})")

        page.click('[data-act="freeze"]')
        settle()
        page.evaluate("(id) => { const n = [...document.querySelectorAll('.grid-stack-item')]"
                      ".find(e => e.gridstackNode && e.gridstackNode.id === id); "
                      "if (n) n.dataset.smokeMoved = id; }", to_panel)
        page.click('[data-act="layout"]')
        state = page.evaluate(_GRID_STATE_JS)
        kept = settle() or {}
        verdict(state['places'] == declared and kept.get('slots') is None
                and page.evaluate(_MOVED_JS, to_panel) == declared[to_panel]['zone'],
                f"« Disposition par défaut » : la disposition déclarée, gardée vide, le panneau "
                f"rendu à sa zone sans être remonté ({kept})")

        page.evaluate(_MOVE_JS, [moved_id, target])
        kept_wide = settle()
        page.set_viewport_size({'width': 600, 'height': 900})
        state = open_page()
        kept = settle()
        verdict(state['columns'] == 1 and kept == kept_wide,
                f"téléphone : une colonne, rien de réécrit ({state['columns']} col., {kept})")
    except Exception as error:
        verdict(False, f"geste interrompu : {type(error).__name__} — {str(error).splitlines()[0][:200]}")
    shown = [e for e in errors if not any(t in e for t in IGNORED_CONSOLE)]
    verdict(not shown, f"aucune erreur JS ({shown[:3]})")


#: Ce que la page dit de ses PANNEAUX (2026-10-26) : les briques de chacun (une pile en a
#: plusieurs), son bord épinglé, sa boîte à l'écran ; l'en-tête, le pied, la marge des volets et
#: celle que la page laisse aux bords épinglés.
_STACK_STATE_JS = """() => {
    const panels = {};
    // Par `data-panel` : un panneau ÉPINGLÉ a quitté la grille pour la région de son bord, il n'a
    // plus de nœud gridstack.
    document.querySelectorAll('.grid-stack > .grid-stack-item, .wama-dock-row > .grid-stack-item').forEach(el => {
        const id = el.dataset.panel || (el.gridstackNode && el.gridstackNode.id);
        if (!id) return;
        const r = el.getBoundingClientRect();
        panels[id] = {
            sections: [...el.querySelectorAll('.wama-brick-section')].map(s => s.dataset.slot),
            // Gardé à l'écran = rangé dans le cadre FIXE des bords (2026-10-27), pas fixe lui-même.
            docked: el.dataset.docked || '', fixed: !!el.closest('.wama-dock-frame')
                && getComputedStyle(el.closest('.wama-dock-frame')).position === 'fixed',
            rect: [r.left, r.top, r.right, r.bottom].map(Math.round)};
    });
    const value = (el, v) => parseFloat(getComputedStyle(el).getPropertyValue(v)) || 0;
    const pageEl = document.querySelector('.wama-surface-page');
    const root = document.querySelector('.wama-surface-grid');
    return {panels: panels, viewport: [innerWidth, innerHeight],
            rows: root && root.gridstack ? root.gridstack.getRow() : null,
            header: value(document.body, '--fm-header-height') || 50,
            footer: value(document.body, '--fm-footer-height') || 40,
            gutterLeft: value(document.body, '--wama-left-gutter'),
            padLeft: parseFloat(getComputedStyle(pageEl).paddingLeft),
            padBottom: parseFloat(getComputedStyle(pageEl).paddingBottom)}; }"""

#: La GARDE PERMANENTE des bords (2026-10-27, Fabien : « une garde permanente pour ne jamais avoir
#: d'élément masqué par le header ou le pied de page », et la même pour les volets) : la zone
#: sûre se MESURE sur les éléments réels — l'en-tête, le pied, chaque volet affiché —, jamais sur
#: les variables que le cadre lit (une variable fausse passerait alors des deux côtés). Chaque
#: panneau épinglé doit y tenir, et aucune de ses briques n'être écrasée sous son titre (la
#: bande retombée à une cellule, 46 px, après « Détacher » : le défaut relevé ce jour-là).
_SAFE_AREA_JS = """() => {
    const box = sel => {
        const el = document.querySelector(sel);
        if (!el || getComputedStyle(el).display === 'none') return null;
        const r = el.getBoundingClientRect();
        return r.width && r.height ? r : null;
    };
    const header = box('nav.wama-header'), footer = box('body > footer');
    const left = box('#filemanager-sidebar'), right = box('#wama-right-panel');
    const safe = {top: header ? header.bottom : 0, bottom: footer ? footer.top : innerHeight,
                  left: left ? Math.max(0, left.right) : 0,
                  right: right ? Math.min(innerWidth, right.left) : innerWidth};
    const faults = [];
    // Ce qui se VOIT d'un panneau épinglé est sa région (une bande trop haute y défile) : c'est
    // elle qui doit tenir dans la zone sûre.
    document.querySelectorAll('.wama-dock-region').forEach(region => {
        if (!region.children.length) return;
        const r = region.getBoundingClientRect();
        if (r.top < safe.top - 1 || r.bottom > safe.bottom + 1
                || r.left < safe.left - 1 || r.right > safe.right + 1) {
            faults.push(region.dataset.edge + ' hors de la zone sûre ' + JSON.stringify(
                [r.left, r.top, r.right, r.bottom].map(Math.round)) + ' / ' + JSON.stringify(safe));
        }
    });
    document.querySelectorAll('.wama-dock-row > .grid-stack-item').forEach(el => {
        el.querySelectorAll('.wama-brick-section').forEach(s => {
            const head = s.querySelector('.wama-brick-head');
            if (s.clientHeight < (head ? head.offsetHeight : 0) + 20) {
                faults.push(s.dataset.slot + ' écrasée (' + s.clientHeight + ' px)');
            }
        });
    });
    return faults; }"""

#: Le cadre des bords à l'écran (où viser un glisser).
_FRAME_BOX_JS = """() => { const r = document.querySelector('.wama-dock-frame').getBoundingClientRect();
    return {x: r.left, y: r.top, w: r.width, h: r.height}; }"""

#: Ce que montre un glisser en cours : la bande de bord active, le repère, la pastille.
_DROP_SHOWN_JS = """() => {
    const f = document.querySelector('.wama-dock-frame');
    const active = f.querySelector('.wama-dock-zone.is-active');
    const hint = f.querySelector('.wama-dock-hint'), chip = f.querySelector('.wama-dock-chip');
    return {dropping: f.classList.contains('is-dropping'), zone: active ? active.dataset.edge : '',
            hint: !!hint && getComputedStyle(hint).display !== 'none',
            chip: chip && getComputedStyle(chip).display !== 'none' ? chip.textContent : ''}; }"""

#: Marque une section (titre + corps d'une brique) pour vérifier ensuite que c'est la MÊME.
_MARK_SECTION_JS = """(id) => {
    const s = document.querySelector('.wama-brick-section[data-slot="' + id + '"]');
    if (s) s.dataset.smokeKept = id;
    return s ? s.querySelector('.wama-brick-title').textContent : null; }"""

#: Les outils d'un titre à l'écran : ceux de la pile (calques, flèches, détacher) et l'épingle.
_TOOLS_SHOWN_JS = """(id) => {
    const head = document.querySelector('.wama-brick-section[data-slot="' + id + '"] > .wama-brick-head');
    const shown = el => !!(el && el.offsetParent !== null && !el.hidden);
    return head ? {stack: shown(head.querySelector('.wama-brick-stack-tools')),
                   pin: shown(head.querySelector('.wama-brick-dock'))} : null; }"""

#: Les sections marquées sont-elles toutes dans un panneau d'empilement ?
_IN_SHELL_JS = """(ids) => ids.every(id => {
    const s = document.querySelector('[data-smoke-kept="' + id + '"]');
    return !!(s && s.closest('.wama-brick-stack-shell')); })"""


def _stack_gestures(page, url, surface, declared, stored, verdict, errors):
    """Les gestes de `check_surface_stack`, dans l'ordre ; un geste impossible est un verdict
    rouge. Les panneaux se pilotent par leurs BOUTONS et le menu commun — ce que fait la main."""
    first, second = [s.id for s in surface.slots if s.zone == 'grid'][:2]
    guarded = []

    def state():
        return page.evaluate(_STACK_STATE_JS)

    def guard(after):
        """La garde PERMANENTE, après CHAQUE geste et chaque ouverture — pas seulement après le
        premier épinglage, où elle seule était mesurée (le défaut du 2026-10-27 venait après)."""
        faults = page.evaluate(_SAFE_AREA_JS)
        guarded.append(after)
        if faults:
            verdict(False, f"zone sûre rompue après « {after} » : {faults[:3]}")

    # Les envois de la disposition EN VOL : lire la base avant leur réponse rendait des rouges
    # intermittents sur un serveur chargé (trois gestes différents en dix passages, le 2026-10-27 —
    # la page montrait le bon état, la base pas encore).
    inflight = {'n': 0}

    def _layout_post(request):
        return request.method == 'POST' and '/layout/' in request.url

    page.on('request', lambda r: inflight.update(n=inflight['n'] + 1) if _layout_post(r) else None)
    for done in ('requestfinished', 'requestfailed'):
        page.on(done, lambda r: inflight.update(n=inflight['n'] - 1) if _layout_post(r) else None)

    def settle(after='geste'):
        page.wait_for_timeout(600)                   # la garde part 300 ms après le geste
        for _ in range(100):                         # puis sa réponse, au plus 10 s
            if inflight['n'] <= 0:
                break
            page.wait_for_timeout(100)
        guard(after)
        return _in_plain_thread(stored) or {}

    def press(slot_id, icon):
        page.locator(f'.wama-brick-section[data-slot="{slot_id}"] > .wama-brick-head '
                     f'button:has(i.{icon})').first.click()

    def pick(text):
        page.locator('.wama-card-menu button.wama-cm-item', has_text=text).first.click()

    def drag(slot_id, to):
        """Glisse un panneau par son titre jusqu'à `to` (x, y) ; rend ce que la page MONTRAIT
        juste avant le lâcher (bande active, repère, pastille)."""
        title = page.locator(f'.wama-brick-section[data-slot="{slot_id}"] > .wama-brick-head '
                             f'.wama-brick-title').first
        b = title.bounding_box()
        page.mouse.move(b['x'] + 4, b['y'] + b['height'] / 2)
        page.mouse.down()
        page.mouse.move(to[0], to[1], steps=14)
        page.wait_for_timeout(250)
        shown = page.evaluate(_DROP_SHOWN_JS)
        page.mouse.up()
        return shown

    def open_page():
        page.goto(url, wait_until='load', timeout=45000)
        page.wait_for_selector('[data-act="freeze"]', timeout=20000)
        page.wait_for_timeout(800)
        guard('ouverture')

    try:
        open_page()
        page.click('[data-act="freeze"]')            # disposition modifiable
        before = settle()
        page.evaluate(_MARK_SECTION_JS, first)
        title = page.evaluate(_MARK_SECTION_JS, second)

        # EMPILER DANS LA PAGE par le TITRE (2026-10-28, Fabien : « créer un empilement de briques
        # […] au lieu de figer puis empiler ») : glisser le titre d'un panneau sur celui d'un autre
        # les empile là, à la place qu'avait la cible quand on l'a visée — la pile s'épingle
        # ensuite d'un seul geste. Puis « Détacher » rend l'état d'avant au reste du scénario.
        head = page.locator(f'.wama-brick-section[data-slot="{first}"] > .wama-brick-head').first.bounding_box()
        shown = drag(second, (head['x'] + head['width'] * 0.4, head['y'] + head['height'] / 2))
        kept, now = settle('empiler par le titre'), state()
        origin = ((before.get('slots') or {}).get(first)
                  or next({'x': s.x, 'y': s.y} for s in surface.slots if s.id == first))
        place = (kept.get('slots') or {}).get(first) or {}
        verdict(shown.get('hint') and 'Empiler' in shown.get('chip', '')
                and (now['panels'].get(first) or {}).get('sections') == [first, second]
                and [e['id'] for e in (kept.get('stacks') or {}).get(first, [])] == [first, second]
                and (place.get('x'), place.get('y')) == (origin['x'], origin['y']),
                f"glisser un titre sur un titre de la page : empilés à la place de la cible "
                f"({shown}, {kept.get('stacks')}, place {place} / {origin})")
        press(second, 'fa-object-ungroup')
        settle('détacher')
        press(first, 'fa-layer-group')
        pick(title)
        kept, now = settle(), state()
        same = page.evaluate(_IN_SHELL_JS, [first, second])
        verdict((now['panels'].get(first) or {}).get('sections') == [first, second]
                and second not in now['panels'] and same
                and [e['id'] for e in (kept.get('stacks') or {}).get(first, [])] == [first, second],
                f"empiler : un seul panneau, les MÊMES briques, gardé au serveur "
                f"({now['panels'].get(first)}, {kept.get('stacks')})")

        rows_before = now['rows']
        press(first, 'fa-thumbtack')
        pick('En bas de la fenêtre')
        kept, now = settle(), state()
        box = now['panels'][first]
        verdict(now['rows'] < rows_before and (kept.get('slots') or {}).get(first),
                f"la page se referme derrière le panneau épinglé ({rows_before} → {now['rows']} "
                f"rangées) et sa place reste gardée ({(kept.get('slots') or {}).get(first)})")
        height = box['rect'][3] - box['rect'][1]
        verdict(box['fixed'] and box['docked'] == 'bottom'
                and box['rect'][3] <= now['viewport'][1] - now['footer'] + 1
                and box['rect'][1] >= now['header'] - 1
                and abs(now['padBottom'] - (32 + height)) <= 2
                and kept.get('docked') == {'bottom': [[first]]},
                f"épinglé en bas : au-dessus du pied, la page s'en écarte ({box}, pied "
                f"{now['footer']}, marge {now['padBottom']}, {kept.get('docked')})")

        press(first, 'fa-thumbtack')
        pick('À gauche')
        kept, now = settle(), state()
        box = now['panels'][first]
        verdict(box['fixed'] and box['docked'] == 'left'
                and box['rect'][0] >= now['gutterLeft'] - 1 and box['rect'][1] >= now['header'] - 1
                and box['rect'][3] <= now['viewport'][1] - now['footer'] + 1
                and abs(now['padLeft'] - (box['rect'][2] - box['rect'][0])) <= 2
                and kept.get('docked') == {'left': [[first]]},
                f"épinglé à gauche : une colonne fixe sous l'en-tête, la page s'en écarte ({box}, "
                f"volet {now['gutterLeft']}, marge {now['padLeft']}, {kept.get('docked')})")

        open_page()
        now = state()
        verdict((now['panels'].get(first) or {}).get('sections') == [first, second]
                and now['panels'][first]['docked'] == 'left',
                f"rechargement : la pile et son bord rendus tels quels ({now['panels'].get(first)})")

        press(first, 'fa-chevron-down')
        kept, now = settle(), state()
        verdict((now['panels'].get(second) or {}).get('sections') == [second, first]
                and now['panels'][second]['docked'] == 'left'
                and kept.get('docked') == {'left': [[second]]} and list(kept.get('stacks') or {}) == [second],
                f"descendre la tête : la nouvelle tête porte la pile et l'épinglage "
                f"({now['panels'].get(second)}, {kept.get('docked')})")

        press(first, 'fa-object-ungroup')
        kept, now = settle(), state()
        verdict((now['panels'].get(first) or {}).get('sections') == [first]
                and (now['panels'].get(second) or {}).get('sections') == [second]
                and not kept.get('stacks') and now['panels'][second]['docked'] == 'left',
                f"détacher : deux panneaux, l'épinglage reste au panneau ({kept.get('stacks')})")

        press(second, 'fa-thumbtack')
        pick('Dans la page')
        kept, now = settle(), state()
        verdict(not now['panels'][second]['fixed'] and not kept.get('docked') and now['padLeft'] == 0,
                f"« Dans la page » : désépinglé, plus de marge ({now['panels'][second]}, "
                f"{kept.get('docked')})")

        # FIGÉE : la pile épinglée reste à son bord, ses outils d'atelier disparaissent, et
        # l'épingle ne reste qu'au panneau épinglé — un panneau ordinaire n'en porte plus.
        third = next(s.id for s in surface.slots if s.id not in (first, second))
        press(first, 'fa-layer-group')
        pick(title)
        press(first, 'fa-thumbtack')
        pick('En bas de la fenêtre')
        settle()
        page.click('[data-act="freeze"]')
        kept, now = settle(), state()
        head, other = page.evaluate(_TOOLS_SHOWN_JS, first), page.evaluate(_TOOLS_SHOWN_JS, third)
        verdict(now['panels'][first]['fixed'] and now['panels'][first]['sections'] == [first, second]
                and head == {'stack': False, 'pin': True} and other and not other['pin']
                and kept.get('frozen') is True and kept.get('docked') == {'bottom': [[first]]},
                f"figée : la pile reste épinglée, outils de pile masqués, épingle au seul panneau "
                f"épinglé ({head}, {third} : {other}, {kept.get('docked')})")

        # « Disposition par défaut » défait les PILES (un geste de disposition) ; l'épinglage, une
        # préférence de LECTURE, reste au panneau qui le portait.
        page.click('[data-act="freeze"]')
        settle()
        page.click('[data-act="layout"]')
        kept, now = settle(), state()
        verdict((now['panels'].get(first) or {}).get('sections') == [first]
                and (now['panels'].get(second) or {}).get('sections') == [second]
                and not kept.get('stacks') and kept.get('slots') is None
                and kept.get('docked') == {'bottom': [[first]]} and now['panels'][first]['fixed'],
                f"« Disposition par défaut » : piles défaites, l'épinglage gardé "
                f"({kept.get('stacks')}, {kept.get('docked')})")

        # Une pile ÉPINGLÉE qu'on retouche garde sa bande (2026-10-27, relevé par Fabien) :
        # empiler un troisième panneau, le détacher, recharger — la bande retombait à une cellule
        # (46 px), écrasée sur le pied, sa hauteur MESURÉE sur un panneau reconstruit à l'instant.
        third_title = page.evaluate(_MARK_SECTION_JS, third)
        press(first, 'fa-layer-group')
        pick(title)
        settle('empiler dans la pile épinglée')
        press(first, 'fa-layer-group')
        pick(third_title)
        full = state()['panels'].get(first) or {}
        settle('empiler un troisième panneau')
        press(third, 'fa-object-ungroup')
        settle('détacher le troisième')
        after = state()['panels'].get(first) or {}
        open_page()
        reloaded = state()['panels'].get(first) or {}
        tall = [b['rect'][3] - b['rect'][1] if b.get('rect') else 0 for b in (after, reloaded)]
        verdict(full.get('sections') == [first, second, third]
                and after.get('sections') == [first, second] == reloaded.get('sections')
                and after.get('fixed') and reloaded.get('fixed')
                and min(tall) > 2 * 46 and abs(tall[0] - tall[1]) <= 2,
                f"pile épinglée retouchée : sa bande garde sa hauteur après « Détacher » et au "
                f"rechargement ({tall} px ; piles {full.get('sections')} → {after.get('sections')} → "
                f"{reloaded.get('sections')} ; fixe {after.get('fixed')}/{reloaded.get('fixed')})")

        # À CÔTÉ (2026-10-27, Fabien : un petit élément « se placerait à côté, collé au
        # transport ») : un panneau rejoint la LIGNE d'un panneau épinglé — même bande, même
        # hauteur, à sa droite, gardé comme une ligne ; puis il revient dans la page.
        press(third, 'fa-thumbtack')
        pick('À côté de')
        kept, now = settle('épingler à côté'), state()
        a, b = now['panels'].get(first) or {}, now['panels'].get(third) or {}
        verdict(a.get('fixed') and b.get('fixed') and b.get('docked') == 'bottom'
                and abs(a['rect'][1] - b['rect'][1]) <= 1 and abs(a['rect'][3] - b['rect'][3]) <= 1
                and b['rect'][0] >= a['rect'][2] - 1
                and kept.get('docked') == {'bottom': [[first, third]]},
                f"à côté : la même ligne de la bande, collé à droite ({a.get('rect')}, "
                f"{b.get('rect')}, {kept.get('docked')})")

        # RETAILLER sur place (2026-10-28, Fabien) : la poignée de la ligne, tirée de deux cellules
        # vers le bas — la ligne rétrécit, s'aligne sur la grille, et la place de son PREMIER
        # panneau garde la hauteur (celle qu'il retrouvera rendu à la page).
        def row_height(box):
            return box['rect'][3] - box['rect'][1]
        grip = page.locator('.wama-dock-region[data-edge="bottom"] .wama-dock-resize').first.bounding_box()
        gx, gy = grip['x'] + grip['width'] / 2, grip['y'] + grip['height'] / 2
        page.mouse.move(gx, gy)
        page.mouse.down()
        page.mouse.move(gx, gy + 2 * 46, steps=8)
        page.mouse.up()
        want = round((row_height(a) - 2 * 46) / 46)
        kept, now = settle('retailler la ligne'), state()
        a, b = now['panels'].get(first) or {}, now['panels'].get(third) or {}
        verdict(((kept.get('slots') or {}).get(first) or {}).get('h') == want
                and abs(row_height(a) - want * 46) <= 2 and abs(row_height(b) - row_height(a)) <= 1,
                f"retailler une ligne épinglée par sa poignée : alignée sur la grille, gardée "
                f"({((kept.get('slots') or {}).get(first) or {}).get('h')} rangées, voulu {want} ; "
                f"{row_height(a)} / {row_height(b)} px)")

        # La taille du PREMIER panneau (2026-10-28, Fabien : la taille du plus grand laissait un
        # vide sous le transport) : posé à côté d'un panneau plus BAS, un panneau prend sa hauteur.
        press(third, 'fa-thumbtack')
        pick('Dans la page')
        settle('rendre à la page')
        press(third, 'fa-thumbtack')
        pick('En bas de la fenêtre')
        settle('épingler seul')
        press(first, 'fa-thumbtack')
        pick(f'À côté de « {third_title}')
        kept, now = settle('à côté d’un panneau plus bas'), state()
        a, b = now['panels'].get(first) or {}, now['panels'].get(third) or {}
        low = ((kept.get('slots') or {}).get(third) or {}).get('h', 0) * 46
        verdict(kept.get('docked') == {'bottom': [[third, first]]} and low
                and abs(row_height(b) - low) <= 2 and abs(row_height(a) - row_height(b)) <= 1,
                f"la ligne prend la taille de son premier panneau, pas du plus grand "
                f"({row_height(b)} / {row_height(a)} px, premier {low} px, {kept.get('docked')})")
        press(third, 'fa-thumbtack')
        pick('Dans la page')
        settle('rendre à la page')

        # Le GLISSER-DÉPOSER (2026-10-27, Fabien : « par simple drag&drop aux extrémités de la
        # zone centrale, on visualise directement si l'élément va se fixer ») : les mêmes gestes
        # que les menus, à la souris — au bord, à côté, rendu à la page, empilé.
        frame = lambda: page.evaluate(_FRAME_BOX_JS)
        f = frame()
        shown = drag(third, (f['x'] + f['w'] / 2, f['y'] + 8))
        kept, now = settle('glisser au bord du haut'), state()
        verdict(shown.get('dropping') and shown.get('zone') == 'top' and 'haut' in shown.get('chip', '')
                and (now['panels'].get(third) or {}).get('docked') == 'top'
                and kept.get('docked') == {'top': [[third]], 'bottom': [[first]]},
                f"glisser au bord : la bande du haut s'éclaire, la pastille le dit, lâché il s'y "
                f"épingle ({shown}, {kept.get('docked')})")
        box = now['panels'][first]['rect']
        shown = drag(third, (box[2] - (box[2] - box[0]) * 0.1, (box[1] + box[3]) / 2))
        kept, now = settle('glisser à côté'), state()
        verdict(shown.get('hint') and 'À côté' in shown.get('chip', '')
                and kept.get('docked') == {'bottom': [[first, third]]},
                f"glisser sur le côté d'un panneau épinglé : à côté, dans sa ligne ({shown}, "
                f"{kept.get('docked')})")
        f = frame()
        shown = drag(third, (f['x'] + f['w'] / 2, f['y'] + f['h'] * 0.4))
        kept, now = settle('glisser dans la page'), state()
        verdict('page' in shown.get('chip', '') and kept.get('docked') == {'bottom': [[first]]}
                and not (now['panels'].get(third) or {}).get('fixed'),
                f"un panneau épinglé glissé dans la page y revient ({shown}, {kept.get('docked')})")
        box = now['panels'][first]['rect']
        shown = drag(third, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2))
        kept, now = settle('glisser au centre'), state()
        verdict(shown.get('hint') and 'Empiler' in shown.get('chip', '')
                and [e['id'] for e in (kept.get('stacks') or {}).get(first, [])] == [first, second, third]
                and (now['panels'].get(first) or {}).get('fixed'),
                f"glisser au centre d'un panneau épinglé : empilé dedans ({shown}, "
                f"{kept.get('stacks')})")

        # Téléphone : une colonne fixe n'y a pas sa place — le panneau reste dans la page, et
        # rien n'est réécrit (le bord reste gardé pour la fenêtre large).
        press(first, 'fa-thumbtack')
        pick('À gauche')
        kept_wide = settle()
        page.set_viewport_size({'width': 600, 'height': 900})
        open_page()
        kept, now = settle(), state()
        verdict(not (now['panels'].get(first) or {}).get('fixed') and now['padLeft'] == 0
                and kept == kept_wide and kept.get('docked') == {'left': [[first]]},
                f"téléphone : la colonne reste dans la page, rien de réécrit "
                f"({now['panels'].get(first)}, {kept.get('docked')}, marge {now['padLeft']}, "
                f"réécrit : { {k: (kept_wide.get(k), kept.get(k)) for k in set(kept) | set(kept_wide) if kept.get(k) != kept_wide.get(k)} })")
    except Exception as error:
        verdict(False, f"geste interrompu : {type(error).__name__} — {str(error).splitlines()[0][:200]}")
    verdict(len(guarded) >= 15,f"garde permanente : zone sûre mesurée après {len(guarded)} gestes "
                                f"et ouvertures")
    shown = [e for e in errors if not any(t in e for t in IGNORED_CONSOLE)]
    verdict(not shown, f"aucune erreur JS ({shown[:3]})")


def check_panel_layout(page_hook=None):
    """Le VOLET d'une page en briques (2026-10-28, `WAMA_VOLETS §3-ter` étape ②) — (ok, détail).

    Sur la page du journal (une page commune : aucune app nommée), avec le compte de test : le
    volet s'ouvre tel qu'avant, sans grille ni ses fichiers ; le cadenas en fait une colonne de
    panneaux, chaque section dans le sien, gardée par compte ; une section que la page masque
    (l'aperçu, les infos) retire son panneau SANS sortir du document — l'inspecteur la retrouve —
    et revient à son rang quel que soit l'ordre où la page les montre ; une card cliquée montre
    l'aperçu ; un panneau épinglé en bas tient entre le pied et le volet, et le reste au
    rechargement ; « Disposition par défaut » garde l'épinglage ; « Dans la page » le rend à la
    colonne ; figé puis rechargé, le volet redevient celui d'avant. Le réglage du compte est rendu
    tel qu'il était en sortie. `page_hook(page)` : posé avant l'ouverture (contre-épreuve)."""
    from django.urls import reverse
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario
    from wama.common.utils.user_settings import (clear_user_app_settings, get_user_app_setting,
                                                 save_user_app_settings)
    from wama.common.utils.volet import LAYOUT_SETTING

    token, uid = _test_session_key(), _test_account_id()
    if not (token and uid):
        raise SkipScenario("aucun compte de test disponible")
    key = 'common'                       # la clé de page du journal (`volet.page_key`)

    def account():
        from django.contrib.auth import get_user_model
        return get_user_model().objects.get(pk=uid)

    def stored():
        return get_user_app_setting(account(), key, LAYOUT_SETTING)

    def restore(value):
        if value is None:
            clear_user_app_settings(account(), key, [LAYOUT_SETTING])
        else:
            save_user_app_settings(account(), key, {LAYOUT_SETTING: value})

    before = _in_plain_thread(stored)
    verdicts = []

    def verdict(ok, text):
        verdicts.append((bool(ok), text))

    sessions_before = _session_keys()
    try:
        _in_plain_thread(restore, None)          # le passage part du volet jamais disposé
        url = BASE_URL.rstrip('/') + reverse('common:journal')
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                context = browser.new_context(viewport={'width': 1500, 'height': 1000})
                context.add_cookies(_cookie(token))
                page = context.new_page()
                page.set_default_timeout(10000)
                errors = []
                page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
                if page_hook:
                    page_hook(page)
                _panel_gestures(page, url, stored, verdict, errors)
            finally:
                browser.close()
    finally:
        _in_plain_thread(restore, before)
        _drop_new_sessions(sessions_before)
    failed = [text for ok, text in verdicts if not ok]
    detail = f"volet du journal : {len(verdicts) - len(failed)}/{len(verdicts)} gestes"
    return (not failed), detail + (f" — ÉCHECS : {failed}" if failed else '')


#: L'état du volet en briques tel que la page le montre : les panneaux de la colonne dans l'ordre
#: de la grille, le panneau de chaque section et ce qui est épinglé.
_PANEL_STATE_JS = """() => {
    const col = document.querySelector('.wama-panel-column');
    const ids = {preview: 'media-section', info: 'info-section'};
    const panels = col ? Array.from(col.querySelectorAll(':scope > .grid-stack-item'))
        .filter(el => el.gridstackNode).sort((a, b) => a.gridstackNode.y - b.gridstackNode.y)
        .map(el => el.dataset.panel) : [];
    const docked = Array.from(document.querySelectorAll('.wama-dock-row > .grid-stack-item:not([hidden])'))
        .map(el => { const r = el.getBoundingClientRect();
                     return {panel: el.dataset.panel, edge: el.dataset.docked, left: r.left, right: r.right,
                             top: r.top, bottom: r.bottom}; });
    const foot = document.querySelector('body > footer'), volet = document.getElementById('wama-right-panel');
    return {column: !!col, grid: !!window.GridStack, lock: !!document.querySelector('.wama-panel-tools'),
            panels: panels, docked: docked,
            inDocument: Object.values(ids).every(id => !!document.getElementById(id)),
            unwrapped: Array.from(document.querySelectorAll('#wama-right-panel .right-panel-section'))
                .filter(s => !s.closest('.grid-stack-item') && s.offsetParent).map(s => s.id),
            footerTop: foot ? foot.getBoundingClientRect().top : null,
            voletLeft: volet ? volet.getBoundingClientRect().left : null};
}"""


def _panel_gestures(page, url, stored, verdict, errors):
    """Les gestes de `check_panel_layout`, dans l'ordre ; un geste impossible est un verdict rouge."""

    def state():
        return page.evaluate(_PANEL_STATE_JS)

    def open_page():
        page.goto(url, wait_until='load', timeout=45000)
        page.wait_for_timeout(1200)

    def lock():
        page.click('.wama-panel-tools button[aria-pressed]')
        page.wait_for_timeout(900)

    def show(ids, display):
        for element in ids:
            # Une section sortie du document n'est plus montrable : le verdict « toujours dans la
            # page » l'a déjà dit, la suite continue.
            page.evaluate("([id, d]) => { const el = document.getElementById(id); "
                          "if (el) el.style.display = d; }", [element, display])
            page.wait_for_timeout(120)

    def pin_menu(panel, choice):
        button = page.locator(f'.grid-stack-item[data-panel="{panel}"] .wama-brick-dock').first
        button.click()
        page.wait_for_timeout(300)
        page.get_by_text(choice).first.click()
        page.wait_for_timeout(900)

    open_page()
    s = state()
    verdict(s['lock'] and not s['column'] and not s['grid'],
            f"ouvert tel qu'avant : cadenas, ni colonne ni grille chargée ({s})")
    lock()
    s = state()
    verdict(s['column'] and s['panels'] and not s['unwrapped'],
            f"le cadenas fait une colonne de panneaux, chaque section dans le sien ({s})")
    page.wait_for_timeout(500)
    kept = _in_plain_thread(stored) or {}
    verdict(kept.get('frozen') is False, f"rendu modifiable, gardé au serveur ({kept})")
    verdict('preview' not in s['panels'] and 'info' not in s['panels'] and s['inDocument'],
            f"aperçu et infos masqués : pas de panneau, mais toujours dans la page ({s['panels']})")
    # L'ordre de l'inspecteur d'abord (l'aperçu, puis les infos) : retirés ensemble au montage,
    # les deux avaient la même rangée — c'est leur RANG qui les remet dans l'ordre.
    show(['media-section', 'info-section'], '')
    first = state()['panels']
    show(['media-section', 'info-section'], 'none')
    show(['info-section', 'media-section'], '')
    second = state()['panels']
    ok = all('preview' in p and 'info' in p and p.index('preview') < p.index('info')
             for p in (first, second))
    verdict(ok, f"aperçu puis infos, quel que soit l'ordre où la page les montre ({first} / {second})")
    show(['media-section', 'info-section'], 'none')
    card = page.query_selector('[data-preview-url][data-id]')
    if card:
        card.click(position={'x': 30, 'y': 12})
        page.wait_for_timeout(2000)
        verdict('preview' in state()['panels'], f"une card cliquée montre l'aperçu ({state()['panels']})")
        page.keyboard.press('Escape')
        page.wait_for_timeout(800)
    target = state()['panels'][0]
    pin_menu(target, 'En bas de la fenêtre')
    s = state()
    dock = next((d for d in s['docked'] if d['panel'] == target), None)
    verdict(dock and dock['edge'] == 'bottom' and dock['bottom'] <= s['footerTop'] + 1
            and dock['right'] <= s['voletLeft'] + 1 and target not in s['panels'],
            f"« {target} » épinglé en bas, entre le pied et le volet ({dock})")
    page.wait_for_timeout(500)
    kept = _in_plain_thread(stored) or {}
    verdict(kept.get('docked') == {'bottom': [[target]]}, f"épinglage gardé au serveur ({kept})")
    open_page()
    s = state()
    verdict(s['column'] and any(d['panel'] == target for d in s['docked']),
            f"rechargé : disposé, toujours épinglé ({s['docked']})")
    page.click('.wama-panel-tools button[title^="Disposition par"]')
    page.wait_for_timeout(900)
    s = state()
    verdict(any(d['panel'] == target for d in s['docked']),
            f"« Disposition par défaut » garde l'épinglage ({s['docked']})")
    pin_menu(target, 'Dans la page')
    s = state()
    verdict(target in s['panels'] and not s['docked'], f"« Dans la page » le rend à la colonne ({s})")
    lock()
    page.wait_for_timeout(500)
    kept = _in_plain_thread(stored) or {}
    open_page()
    s = state()
    verdict(kept.get('frozen') is True and not s['column'] and not s['grid'],
            f"figé puis rechargé : le volet d'avant ({kept}, {s})")
    shown = [e for e in errors if not any(t in e for t in IGNORED_CONSOLE)]
    verdict(not shown, f"aucune erreur JS ({shown[:3]})")


def register_surface_scenarios():
    """Les scénarios communs des surfaces (vignettes de briques, disposition) — aucun GPU."""
    from wama.common.services.nightly_tests import register

    register(
        id='common.ui_bricks_capture', app='common', stage='ui',
        description=("Surfaces : chaque page d'édition déclarée s'ouvre sur son élément témoin "
                     "sans erreur JS, et chaque brique y est capturée — les vignettes du "
                     "catalogue des briques UI (aucune tâche lancée, témoins retirés en sortie)"),
        run=lambda ctx: capture_brick_thumbnails(),
        timeout_s=300, vram_gb=0.0,
    )
    register(
        id='common.surface_layout', app='common', stage='ui',
        description=("Surfaces : la disposition s'ouvre verrouillée, se rend modifiable, se garde "
                     "par compte — un panneau passé dans la colonne du volet garde sa zone —, se "
                     "FIGE (deux zones immobiles, rendu fini, survit au rechargement) et revient à "
                     "la disposition déclarée ; une colonne sur téléphone sans rien réécrire"),
        run=lambda ctx: check_surface_layout(),
        timeout_s=240, vram_gb=0.0,
    )
    register(
        id='common.surface_stack', app='common', stage='ui',
        description=("Surfaces : deux panneaux EMPILÉS en un (les mêmes briques, gardé par compte), "
                     "épinglé en bas puis à gauche (entre l'en-tête et le pied, la page s'en "
                     "écarte), rendu tel quel au rechargement ; la tête descendue garde "
                     "l'épinglage ; détacher rend deux panneaux ; « Dans la page » désépingle ; "
                     "figée, la pile reste épinglée sans outils d'atelier ; « Disposition par "
                     "défaut » défait les piles et garde l'épinglage ; téléphone : la colonne "
                     "reste dans la page ; après CHAQUE geste, rien d'épinglé sous l'en-tête, le "
                     "pied ou un volet, aucune brique écrasée — une pile épinglée retouchée garde "
                     "sa bande ; « à côté » sur une ligne ; GLISSER à la souris : au bord, à côté, "
                     "rendu à la page, empilé, chacun annoncé avant le lâcher"),
        run=lambda ctx: check_surface_stack(),
        timeout_s=240, vram_gb=0.0,
    )
    register(
        id='common.panel_layout', app='common', stage='ui',
        description=("Volet d'une page en briques : ouvert tel qu'avant (ni grille ni ses "
                     "fichiers), le cadenas en fait une colonne de panneaux gardée par compte ; une "
                     "section masquée retire son panneau sans quitter la page et revient à son rang "
                     "(aperçu puis infos, dans les deux ordres) ; épinglé en bas entre le pied et le "
                     "volet, gardé au rechargement et par « Disposition par défaut » ; « Dans la "
                     "page » le rend ; figé puis rechargé, le volet d'avant"),
        run=lambda ctx: check_panel_layout(),
        timeout_s=240, vram_gb=0.0,
    )

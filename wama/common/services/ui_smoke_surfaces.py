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
#: (`el.gridstackNode.id`, `wama-surface.js`) — lu dans la page plutôt que posé par le noyau.
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
                    _layout_gestures(page, url, surface, declared, stored, verdict, errors)
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

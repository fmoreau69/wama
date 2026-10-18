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

Les briques constitutives seules (décision du même jour) : les composants SYSTÈME de la page
attendent qu'on déclare où les cadrer.
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


def register_surface_scenarios():
    """Le scénario commun des surfaces et des vignettes de briques — aucun GPU."""
    from wama.common.services.nightly_tests import register

    register(
        id='common.ui_bricks_capture', app='common', stage='ui',
        description=("Surfaces : chaque page d'édition déclarée s'ouvre sur son élément témoin "
                     "sans erreur JS, et chaque brique y est capturée — les vignettes du "
                     "catalogue des briques UI (aucune tâche lancée, témoins retirés en sortie)"),
        run=lambda ctx: capture_brick_thumbnails(),
        timeout_s=300, vram_gb=0.0,
    )

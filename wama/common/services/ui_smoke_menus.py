"""Scénarios nocturnes `ui` — les MENUS : contextuel (cascade, clavier), « Envoyer vers » de l'arbre,
état de la médiathèque dans le menu d'une card, clavier du sous-menu « Bac à sable ».

Versés le 2026-09-14 de la sonde de session `sonde_menus_v4.py`, à la question de Fabien : « tu as
ajouté tous les tests nécessaires, y compris pour les menus contextuels ? ». Non : le COMPORTEMENT
n'était attesté que par une sonde de bloc-notes — qui meurt avec la session. Ce qu'elle a trouvé en
une soirée le justifie : un menu refermé 7 ms après son ouverture par un `scroll` programmatique,
deux apps offertes pour un dossier sans rien déclarer, et ↓ détourné par Bootstrap dans
« Bac à sable ». Aucun test Python ne voit ça : les briques s'exécutent SERVIES.

Module à part d'`ui_smoke.py` (même raison qu'`ui_smoke_matching`) ; il en réutilise les briques et
ne redéfinit rien. ⚠ Tout l'ORM est HORS du contexte Playwright (`SynchronousOnlyOperation`).
"""
from pathlib import Path

from django.conf import settings

from .ui_smoke import (BASE_URL, IGNORED_CONSOLE, _drop_new_sessions, _exiger_la_page,
                       _fichier_temoin, _session_keys, _test_account_id, _test_session_key,
                       accept_dialogs, set_delete_files)
from .ui_smoke_matching import _bilan, _cookie, _retirer

ARBRE = '#filemanager-tree'
#: L'arbre est un volet de `base.html` : n'importe quelle page d'app le porte. Le converter ne
#: mobilise aucun modèle — rien de lourd ne se charge pour atteindre le volet.
PAGE = '/converter/'

JS_ACTIF = """() => { const a = document.activeElement;
    return {texte: (a.textContent || '').trim().slice(0, 40), menu: a.classList.contains('wama-card-menu'),
            dans_sous: !!a.closest('.wama-cm-sous'), id: a.id || ''}; }"""
JS_SOUS = """() => [...document.querySelectorAll('.wama-cm-sous .wama-cm-item')]
    .map(b => [b.textContent.trim(), (b.querySelector('i') || {}).className || ''])"""


def _temoin(folder: Path, nom: str, ext: str) -> Path:
    """Un fichier témoin VALIDE pour `ext` (brique `_fichier_temoin`), déposé sous `nom`."""
    source = _fichier_temoin(ext)
    cible = folder / nom
    cible.write_bytes(source.read_bytes())
    source.unlink(missing_ok=True)
    return cible


def _ouvrir(p, jeton):
    """Navigateur + page authentifiée, avec le relevé d'erreurs. Rend `(navigateur, page, erreurs)`.
    Les confirmations (`window.confirm`) sont ACCEPTÉES : le retrait de la médiathèque en demande une."""
    nav = p.chromium.launch()
    ctx = nav.new_context(viewport={'width': 1500, 'height': 1000})
    ctx.add_cookies(_cookie(jeton))
    page = ctx.new_page()
    errors = []
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    page.on('pageerror', lambda e: errors.append(f'PAGEERROR {e}'))
    accept_dialogs(page)
    return nav, page, errors


def _console(errors):
    garde = [x for x in errors if not any(tok in x for tok in IGNORED_CONSOLE)]
    return (not garde, f'console : {len(garde)} erreur(s) {garde[:1]}')


def _attendre_sous(page):
    """Le sous-menu est résolu au serveur : on attend la FIN du chargement, jamais un délai fixe."""
    page.wait_for_selector('.wama-cm-sous', timeout=5000)
    page.wait_for_function("() => !document.querySelector('.wama-cm-sous .fa-spinner')", timeout=15000)


def _arbre_pret(page, noms):
    page.wait_for_selector(f'{ARBRE} .jstree-anchor', timeout=30000)
    page.evaluate("() => jQuery('#filemanager-tree').jstree(true).open_node('temp')")
    for nom in noms:
        page.wait_for_selector(f'{ARBRE} .jstree-anchor:text-is("{nom}")', timeout=15000)
    page.wait_for_timeout(600)          # fin de l'animation d'ouverture du dossier


def _fermer_menus(page):
    for _ in range(3):
        page.keyboard.press('Escape')
    page.wait_for_timeout(150)


def _sortie_converter(uid, nom):
    """Un job converter TERMINÉ dont la sortie est un VRAI fichier sous le dossier de sortie de
    l'app — la forme que l'arbre liste et que l'adapter déclare. Rend `(job, chemin_absolu)`.
    Partagé par les scénarios C et E (2026-09-18) : deux semis divergents auraient mesuré deux
    formes de sortie. ⚠ ORM : à appeler HORS du contexte Playwright."""
    from wama.common.models import JOB_STATUS_CHOICES
    from wama.common.utils.media_paths import app_media_dir
    from wama.converter.models import ConversionJob

    # `JOB_STATUS_CHOICES` ne porte que `SUCCESS` : les deux autres branches étaient une
    # défensive sans objet, et `DONE` a été retiré du vocabulaire le 2026-09-18.
    fini = next(c for c, _ in JOB_STATUS_CHOICES if c == 'SUCCESS')
    rel = f"{app_media_dir('converter', uid, 'output')}/{nom}"
    sortie = Path(settings.MEDIA_ROOT) / rel
    sortie.parent.mkdir(parents=True, exist_ok=True)
    source = _fichier_temoin(sortie.suffix)
    sortie.write_bytes(source.read_bytes())
    source.unlink(missing_ok=True)
    job = ConversionJob.objects.create(user_id=uid, input_filename=nom, media_type='image',
                                       output_format=sortie.suffix.lstrip('.'), status=fini,
                                       progress=100)
    job.output_file.name = rel
    job.save(update_fields=['output_file'])
    return job, sortie


# ═══════════════════════════════════════════════════════════════════════════════════════════
# A. CLAVIER dans le menu contextuel (brique commune, surface : l'arbre de fichiers)
# ═══════════════════════════════════════════════════════════════════════════════════════════

def check_tree_menu_keyboard():
    """Le menu de l'arbre se parcourt au clavier. (ok, detail)"""
    from playwright.sync_api import sync_playwright
    from wama.common.services.nightly_tests import SkipScenario

    jeton, uid = _test_session_key('converter'), _test_account_id('converter')
    if not (jeton and uid):
        raise SkipScenario('aucun compte de test disponible')
    folder = Path(settings.MEDIA_ROOT) / f'users/{uid}/temp'
    folder.mkdir(parents=True, exist_ok=True)
    temoin = _temoin(folder, 'wama_temoin_menu_clavier.png', '.png')
    before, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, jeton)
            try:
                resp = page.goto(BASE_URL + PAGE, wait_until='networkidle', timeout=60000)
                arrivee = _exiger_la_page(page, resp, PAGE)
                if arrivee:
                    return arrivee
                _arbre_pret(page, [temoin.name])
                page.click(f'{ARBRE} .jstree-anchor:text-is("{temoin.name}")', button='right')
                page.wait_for_timeout(300)
                verdicts.append((page.evaluate(JS_ACTIF)['menu'], "le menu prend le focus à l'ouverture"))

                vus = []
                for _ in range(12):
                    page.keyboard.press('ArrowDown')
                    vus.append(page.evaluate(JS_ACTIF)['texte'])
                    if vus[-1].startswith('Envoyer vers'):
                        break
                verdicts.append((vus[-1].startswith('Envoyer vers'), f'↓ parcourt les entrées : {vus}'))

                page.keyboard.press('ArrowRight')
                # Le GESTE mesuré : un → qui n'ouvre rien doit rendre un VERDICT nommé, pas une
                # exception de délai (contre-épreuve du 14/09 sur l'ancien code : « Timeout »).
                try:
                    _attendre_sous(page)
                except Exception:
                    verdicts.append((False, '→ n\'ouvre AUCUN sous-menu (navigation au clavier absente)'))
                    verdicts.append(_console(errors))
                    return _bilan(verdicts)
                page.wait_for_timeout(200)
                a = page.evaluate(JS_ACTIF)
                verdicts.append((a['dans_sous'], f"→ ouvre le sous-menu ET y entre (focus « {a['texte']} »)"))

                page.keyboard.press('ArrowLeft')
                page.wait_for_timeout(150)
                n_sous = page.evaluate("document.querySelectorAll('.wama-cm-sous').length")
                a = page.evaluate(JS_ACTIF)
                verdicts.append((n_sous == 0 and a['texte'].startswith('Envoyer vers'),
                                 f"← remonte (sous-menus {n_sous}, focus « {a['texte']} »)"))

                page.keyboard.press('Escape')
                page.wait_for_timeout(150)
                n_menus = page.evaluate("document.querySelectorAll('.wama-card-menu').length")
                a = page.evaluate(JS_ACTIF)
                verdicts.append((n_menus == 0 and a['id'].endswith('_anchor'),
                                 f"Échap ferme et rend le focus au fichier (menus {n_menus}, focus #{a['id']})"))
                verdicts.append(_console(errors))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(before)
        temoin.unlink(missing_ok=True)
    return _bilan(verdicts)


# ═══════════════════════════════════════════════════════════════════════════════════════════
# B. « ENVOYER VERS » de l'arbre = le résolveur SERVEUR (fichier, sélection, dossier)
# ═══════════════════════════════════════════════════════════════════════════════════════════

def check_tree_send_to_menus():
    """Les sous-menus « Envoyer vers » de l'arbre montrent EXACTEMENT ce que rend le serveur. (ok, detail)

    L'attendu est calculé AVANT le navigateur par `send_to` lui-même : le scénario ne compare pas
    le menu à une liste recopiée — il vérifie que l'arbre n'a plus de dérivation à lui.
    """
    from django.contrib.auth import get_user_model
    from playwright.sync_api import sync_playwright
    from wama.common.services.nightly_tests import SkipScenario
    from wama.common.services.send_to import destinations, destinations_dossier

    jeton, uid = _test_session_key('converter'), _test_account_id('converter')
    if not (jeton and uid):
        raise SkipScenario('aucun compte de test disponible')
    user = get_user_model().objects.get(pk=uid)
    folder = Path(settings.MEDIA_ROOT) / f'users/{uid}/temp'
    folder.mkdir(parents=True, exist_ok=True)
    t_png = _temoin(folder, 'wama_temoin_envoi_a.png', '.png')
    t_wav = _temoin(folder, 'wama_temoin_envoi_b.wav', '.wav')
    rel = lambda f: f'users/{uid}/temp/{f.name}'
    attendu_fichier = [d['libelle'] for d in destinations(user, [rel(t_png)])]
    attendu_selection = [f"{d['libelle']} ({len(d['acceptes'])}/2 fichiers)"
                         for d in destinations(user, [rel(t_png), rel(t_wav)], partiel=True)]
    attendu_dossier = [d['libelle'] for d in destinations_dossier(user)]
    before, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, jeton)
            try:
                resp = page.goto(BASE_URL + PAGE, wait_until='networkidle', timeout=60000)
                arrivee = _exiger_la_page(page, resp, PAGE)
                if arrivee:
                    return arrivee
                _arbre_pret(page, [t_png.name, t_wav.name])
                a_png = f'{ARBRE} .jstree-anchor:text-is("{t_png.name}")'

                page.click(a_png, button='right')
                page.hover('.wama-card-menu .wama-cm-item:has-text("Envoyer vers")')
                _attendre_sous(page)
                vu = [e[0] for e in page.evaluate(JS_SOUS)]
                verdicts.append((bool(attendu_fichier) and vu == attendu_fichier,
                                 f'fichier .png : menu {vu} / serveur {attendu_fichier}'))
                _fermer_menus(page)

                page.evaluate("""([a, b]) => { const t = jQuery('#filemanager-tree').jstree(true);
                    const id = n => [...document.querySelectorAll('#filemanager-tree .jstree-anchor')]
                        .find(x => x.textContent.trim() === n).closest('.jstree-node').id;
                    t.deselect_all(); t.select_node([id(a), id(b)]); }""", [t_png.name, t_wav.name])
                page.click(a_png, button='right')
                page.wait_for_timeout(200)
                entree = page.evaluate("""() => [...document.querySelectorAll('.wama-card-menu .wama-cm-item')]
                    .map(b => b.textContent.trim()).find(t => t.startsWith('Envoyer'))""")
                titre = page.evaluate("() => (document.querySelector('.wama-cm-titre') || {}).textContent || ''")
                verdicts.append((entree == 'Envoyer 2 fichier(s) vers…' and titre.startswith('2 '),
                                 f'sélection de 2 : entrée « {entree} », titre « {titre} »'))
                page.hover('.wama-card-menu .wama-cm-item:has-text("Envoyer 2")')
                _attendre_sous(page)
                vu = [e[0] for e in page.evaluate(JS_SOUS)]
                verdicts.append((bool(attendu_selection) and vu == attendu_selection,
                                 f'sélection png+wav (partiel ANNONCÉ) : menu {vu} / serveur {attendu_selection}'))
                _fermer_menus(page)

                page.click(f'{ARBRE} .jstree-anchor:text-is("Temporaires")', button='right')
                page.hover('.wama-card-menu .wama-cm-item:has-text("Envoyer dossier vers")')
                _attendre_sous(page)
                vu = [e[0] for e in page.evaluate(JS_SOUS)]
                verdicts.append((bool(attendu_dossier) and vu == attendu_dossier,
                                 f'dossier : menu {vu} / serveur {attendu_dossier}'))
                _fermer_menus(page)
                verdicts.append(_console(errors))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(before)
        t_png.unlink(missing_ok=True)
        t_wav.unlink(missing_ok=True)
    return _bilan(verdicts)


# ═══════════════════════════════════════════════════════════════════════════════════════════
# C. MÉDIATHÈQUE dans le menu d'une CARD : + → rangé → ✓ → retrait
# ═══════════════════════════════════════════════════════════════════════════════════════════

def check_card_menu_library_state():
    """Le sous-menu médiathèque d'une card DIT l'état persisté et permet le retrait. (ok, detail)

    Sème un job converter TERMINÉ avec une sortie, range, vérifie la coche, retire, puis contrôle
    en base que la copie a disparu et que la sortie de l'app est intacte. Nettoie tout.
    """
    from playwright.sync_api import sync_playwright
    from wama.common.services.nightly_tests import SkipScenario
    from wama.converter.models import ConversionJob
    from wama.media_library.models import UserAsset

    jeton, uid = _test_session_key('converter'), _test_account_id('converter')
    if not (jeton and uid):
        raise SkipScenario('aucun compte de test disponible')
    job, sortie = _sortie_converter(uid, 'wama_temoin_menu_mediatheque.png')
    assets_avant = set(UserAsset.objects.filter(user_id=uid).values_list('id', flat=True))
    carte = f'.wama-card[data-id="{job.id}"]:not(.is-batch)'
    before, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, jeton)
            try:
                resp = page.goto(BASE_URL + PAGE, wait_until='networkidle', timeout=60000)
                arrivee = _exiger_la_page(page, resp, PAGE)
                if arrivee:
                    return arrivee
                verdicts += _cycle_mediatheque(page, carte, attendus=None)
                verdicts.append(_console(errors))
            finally:
                nav.close()
        # En base, HORS du navigateur : la copie a disparu, la sortie de l'app est intacte.
        restants = UserAsset.objects.filter(source_app='converter', source_pk=job.pk).count()
        verdicts.append((restants == 0, f'base : {restants} asset(s) encore rangé(s) depuis le job'))
        verdicts.append((sortie.exists(), "la sortie de l'app n'a pas été touchée par le retrait"))
    finally:
        _drop_new_sessions(before)
        for asset in UserAsset.objects.filter(user_id=uid).exclude(id__in=assets_avant):
            _retirer(asset)
        ConversionJob.objects.filter(pk=job.pk).delete()
        sortie.unlink(missing_ok=True)
    return _bilan(verdicts)


def _cycle_mediatheque(page, carte, attendus=None):
    """Le CYCLE du sous-menu « Ajouter à la médiathèque… » d'une card : + → rangé → ✓ → retrait.
    Partagé par le scénario C (converter, rôles) et F (transcriber, formats — 2026-09-18) : le
    menu ne sait rien de l'archétype, le cycle non plus. `attendus` : libellés que le sous-menu
    doit montrer AVANT tout rangement (None = seulement « au moins un + »). Rend des verdicts."""
    verdicts = []
    page.wait_for_selector(carte, timeout=20000)

    def sous_menu():
        page.click(carte, button='right')
        page.hover('.wama-card-menu .wama-cm-item:has-text("Ajouter à la médiathèque")')
        _attendre_sous(page)
        return page.evaluate(JS_SOUS)

    e1 = sous_menu()
    plus = [lib for lib, ic in e1 if 'fa-plus' in ic]
    verdicts.append((bool(plus) and not any('fa-check' in ic for _, ic in e1),
                     f'avant : aucune entrée cochée {e1}'))
    if attendus is not None:
        verdicts.append((plus == list(attendus), f'entrées offertes {plus} / attendu {list(attendus)}'))
    if plus:
        page.click(f'.wama-cm-sous .wama-cm-item:has-text("{plus[0]}")')
        page.wait_for_timeout(1500)
        e2 = sous_menu()
        coche = page.query_selector('.wama-cm-sous .wama-cm-item:has(i.fa-check)')
        verdicts.append((coche is not None and any(lib == plus[0] and 'fa-check' in ic
                                                  for lib, ic in e2),
                         f'après rangement : « {plus[0]} » est COCHÉ {e2}'))
        # Sans coche, pas de retrait à cliquer : on le DIT au lieu d'attendre 30 s un
        # sélecteur absent (la contre-épreuve sur un serveur ancien finissait en délai).
        if coche is not None:
            coche.click()
            page.wait_for_timeout(1500)
            e3 = sous_menu()
            verdicts.append((not any('fa-check' in ic for _, ic in e3),
                             f'après retrait (confirmé) : plus de coche {e3}'))
        else:
            verdicts.append((False, 'retrait non jouable : aucune coche à cliquer'))
        _fermer_menus(page)
    return verdicts


# ═══════════════════════════════════════════════════════════════════════════════════════════
# F. MÉDIATHÈQUE d'une app LATE-BINDING (transcriber) : les FORMATS du ⬇, rendus à la demande
# ═══════════════════════════════════════════════════════════════════════════════════════════

def check_card_menu_library_late_binding():
    """Sur une card transcriber, le sous-menu médiathèque offre les FORMATS du bouton ⬇ (document),
    range un rendu, coche, retire — et l'asset rangé est bien le rendu du builder. (ok, detail)

    2026-09-18 (relevé de Fabien : « il y a les apps early et late binding »). Avant : « Rien à
    ranger » sur un transcript terminé. L'attendu vient d'`export_choices`, pas d'une liste.
    """
    from playwright.sync_api import sync_playwright
    from wama.common.services.nightly_tests import SkipScenario
    from wama.media_library.models import UserAsset
    from wama.media_library.services import export_choices
    from wama.transcriber.models import Transcript

    page_app = '/transcriber/'
    jeton, uid = _test_session_key('transcriber'), _test_account_id('transcriber')
    if not (jeton and uid):
        raise SkipScenario('aucun compte de test disponible')
    t = Transcript.objects.create(user_id=uid, text='Témoin de menu médiathèque late-binding.',
                                  status='SUCCESS')
    attendus = [c['label'] for c in export_choices('transcriber', {'result_text': t.text})]
    assets_avant = set(UserAsset.objects.filter(user_id=uid).values_list('id', flat=True))
    carte = f'.wama-card[data-id="{t.id}"]:not(.is-batch)'
    before, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, jeton)
            try:
                resp = page.goto(BASE_URL + page_app, wait_until='networkidle', timeout=60000)
                arrivee = _exiger_la_page(page, resp, page_app)
                if arrivee:
                    return arrivee
                verdicts += _cycle_mediatheque(page, carte, attendus=attendus)
                verdicts.append(_console(errors))
            finally:
                nav.close()
        restants = UserAsset.objects.filter(source_app='transcriber', source_pk=t.pk).count()
        verdicts.append((restants == 0, f'base : {restants} asset(s) encore rangé(s) depuis le transcript'))
    finally:
        _drop_new_sessions(before)
        for asset in UserAsset.objects.filter(user_id=uid).exclude(id__in=assets_avant):
            _retirer(asset)
        Transcript.objects.filter(pk=t.pk).delete()
    return _bilan(verdicts)


# ═══════════════════════════════════════════════════════════════════════════════════════════
# E. GESTES D'ÉLÉMENT dans l'ARBRE : sur un fichier de SORTIE, les mêmes que sur la card
# ═══════════════════════════════════════════════════════════════════════════════════════════

JS_RACINE = """() => [...document.querySelectorAll('.wama-card-menu:not(.wama-cm-sous) .wama-cm-item')]
    .map(b => b.textContent.trim())"""
JS_ATTENTE = "() => !!document.querySelector('.wama-card-menu:not(.wama-cm-sous) .wama-cm-attente')"
GESTES_D_ELEMENT = ('Partager…', 'Ajouter à la médiathèque…', 'Ajouter au RAG')


def check_tree_item_menu():
    """L'arbre offre, sur un fichier de SORTIE, les gestes d'élément du menu « … » — et rien de
    tel sur un dépôt temporaire. (ok, detail)

    2026-09-18 (demande de Fabien). L'attendu n'est pas recopié : il est RELEVÉ sur la card du
    même job, sur la même page — l'arbre doit montrer la même liste (moins « Envoyer vers… »,
    qu'il possède déjà par chemin), résolue au serveur APRÈS l'ouverture du menu.
    """
    from playwright.sync_api import sync_playwright
    from wama.common.services.nightly_tests import SkipScenario
    from wama.converter.models import ConversionJob
    from wama.common.utils.detail_registry import DetailRegistry
    from wama.media_library.models import ASSET_TYPES
    from wama.media_library.services import admissible_roles

    jeton, uid = _test_session_key('converter'), _test_account_id('converter')
    if not (jeton and uid):
        raise SkipScenario('aucun compte de test disponible')
    job, sortie = _sortie_converter(uid, 'wama_temoin_menu_element.png')
    dossier_temp = Path(settings.MEDIA_ROOT) / f'users/{uid}/temp'
    dossier_temp.mkdir(parents=True, exist_ok=True)
    temoin_temp = _temoin(dossier_temp, 'wama_temoin_menu_temp.png', '.png')
    carte = f'.wama-card[data-id="{job.id}"]:not(.is-batch)'
    libelles = dict(ASSET_TYPES)
    # Extension PUIS rôle déclaré par l'app (converter déclare « image ») — la MÊME fonction
    # que la route, pas une liste recopiée.
    detail = DetailRegistry.get('converter')['adapter'](job)
    roles_attendus = [libelles.get(t, t) for t in admissible_roles(detail, sortie.name)]
    before, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, jeton)
            try:
                resp = page.goto(BASE_URL + PAGE, wait_until='networkidle', timeout=60000)
                arrivee = _exiger_la_page(page, resp, PAGE)
                if arrivee:
                    return arrivee

                # ① L'attendu, relevé sur la CARD du même job (même page, même brique).
                page.wait_for_selector(carte, timeout=20000)
                page.click(carte, button='right')
                page.wait_for_timeout(300)
                sur_card = page.evaluate(JS_RACINE)
                _fermer_menus(page)
                attendu = [e for e in sur_card if e in GESTES_D_ELEMENT]
                verdicts.append((attendu == list(GESTES_D_ELEMENT),
                                 f'la card offre les 3 gestes d’élément : {sur_card}'))

                # ② L'arbre : le fichier de sortie, dans Converter › Output (chargé à la demande).
                _arbre_pret(page, [temoin_temp.name])
                page.evaluate("""() => { const t = jQuery('#filemanager-tree').jstree(true);
                    t.open_node('converter', () => t.open_node('converter_output')); }""")
                ancre = f'{ARBRE} .jstree-anchor:text-is("{sortie.name}")'
                page.wait_for_selector(ancre, timeout=20000)
                page.wait_for_timeout(400)
                page.click(ancre, button='right')
                page.wait_for_selector('.wama-card-menu', timeout=5000)
                verdicts.append((page.evaluate(JS_ATTENTE),
                                 'le menu s’ouvre TOUT DE SUITE, sur « Recherche… » pour les gestes d’élément'))
                page.wait_for_function(
                    "() => !document.querySelector('.wama-card-menu:not(.wama-cm-sous) .fa-spinner')",
                    timeout=15000)
                page.wait_for_timeout(200)
                sur_arbre = page.evaluate(JS_RACINE)
                verdicts.append(([e for e in sur_arbre if e in GESTES_D_ELEMENT] == attendu,
                                 f'arbre (sortie) : {sur_arbre} — mêmes gestes que la card {attendu}'))
                i_envoi = next((i for i, e in enumerate(sur_arbre) if e.startswith('Envoyer vers')), -1)
                i_part = sur_arbre.index('Partager…') if 'Partager…' in sur_arbre else -1
                verdicts.append((0 <= i_envoi < i_part,
                                 f'« Envoyer vers… » (déjà là) garde sa place, les gestes d’élément suivent ({i_envoi} < {i_part})'))

                # ③ Le sous-menu médiathèque de l'arbre = les rôles que le serveur admet pour CE fichier.
                page.hover('.wama-card-menu .wama-cm-item:has-text("Ajouter à la médiathèque")')
                _attendre_sous(page)
                roles = [lib for lib, _ in page.evaluate(JS_SOUS)]
                verdicts.append((roles == roles_attendus,
                                 f'rôles du sous-menu {roles} / serveur {roles_attendus}'))
                _fermer_menus(page)

                # ④ Contre-épreuve : un dépôt TEMPORAIRE n'a ni « Recherche… » ni geste d'élément.
                page.click(f'{ARBRE} .jstree-anchor:text-is("{temoin_temp.name}")', button='right')
                page.wait_for_timeout(500)
                sur_temp = page.evaluate(JS_RACINE)
                verdicts.append((not page.evaluate(JS_ATTENTE)
                                 and not any(e in GESTES_D_ELEMENT for e in sur_temp),
                                 f'temp : ni attente ni geste d’élément {sur_temp}'))
                _fermer_menus(page)
                verdicts.append(_console(errors))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(before)
        ConversionJob.objects.filter(pk=job.pk).delete()
        sortie.unlink(missing_ok=True)
        temoin_temp.unlink(missing_ok=True)
    return _bilan(verdicts)


# ═══════════════════════════════════════════════════════════════════════════════════════════
# D. CLAVIER du sous-menu « Bac à sable » (menu « Applications », compte développeur)
# ═══════════════════════════════════════════════════════════════════════════════════════════

def check_nav_sandbox_keyboard():
    """Le sous-menu « Bac à sable » se parcourt au clavier SANS que Bootstrap le détourne. (ok, detail)"""
    from playwright.sync_api import sync_playwright
    from wama.common.app_registry import APP_CATALOG
    from wama.common.services.nightly_tests import SkipScenario

    if 'converter_01' not in APP_CATALOG:
        raise SkipScenario("aucune jumelle de bac à sable installée : le sous-menu n'existe pas")
    jeton = _test_session_key('converter_01')          # routé vers le compte DÉVELOPPEUR
    if not jeton:
        raise SkipScenario('aucun compte de test développeur disponible')
    etat_js = """() => { const a = document.activeElement, s = document.querySelector('.wama-nav-sous-menu');
        return {texte: (a.textContent || '').trim().slice(0, 40), dans_sous: !!a.closest('.wama-nav-sous-menu'),
                sous_visible: !!s && s.classList.contains('show'),
                apps_ouvert: document.querySelector('.wama-apps-menu').classList.contains('show')}; }"""
    before, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, jeton)
            try:
                resp = page.goto(BASE_URL + PAGE, wait_until='networkidle', timeout=60000)
                arrivee = _exiger_la_page(page, resp, PAGE)
                if arrivee:
                    return arrivee
                if not page.query_selector('[data-wama-nav-sous]'):
                    raise SkipScenario("le compte développeur ne voit aucun groupe « Bac à sable »")
                page.click('#appsDropdown')
                page.wait_for_timeout(300)
                page.focus('[data-wama-nav-sous] > .dropdown-item')
                page.keyboard.press('ArrowRight')
                page.wait_for_timeout(200)
                e = page.evaluate(etat_js)
                verdicts.append((e['dans_sous'] and e['sous_visible'], f'→ ouvre et entre : {e}'))
                premier = e['texte']
                page.keyboard.press('ArrowDown')
                e = page.evaluate(etat_js)
                verdicts.append((e['dans_sous'] and e['texte'] != premier,
                                 f'↓ reste DANS le sous-menu (Bootstrap ne le détourne pas) : {e}'))
                page.keyboard.press('ArrowLeft')
                page.wait_for_timeout(200)
                e = page.evaluate(etat_js)
                verdicts.append((not e['dans_sous'] and not e['sous_visible'] and e['apps_ouvert'],
                                 f'← referme et revient au déclencheur, « Applications » ouvert : {e}'))
                verdicts.append(_console(errors))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(before)
    return _bilan(verdicts)


def check_tree_delete_in_use():
    """Supprimer un fichier qu'une card UTILISE : WAMA le DIT, demande confirmation, détache. (ok, detail)

    Le geste posé par D20 (décision de Fabien du 2026-09-23 : *« il faut le prévenir que son fichier
    est utilisé par une ou des cards et lui demander s'il est sûr »*). Les contrats Python
    l'attestent côté serveur ; ici on le JOUE — deux boîtes de dialogue, dont la seconde NOMME le
    nombre de cards, et un refus qui laisse le fichier en place.

    ⚠ Ce scénario a sa propre politique de dialogue : `_ouvrir` accepte TOUT, ce qui rendrait le
    refus inobservable. Il enregistre les messages et décide selon leur contenu.
    """
    from django.contrib.auth import get_user_model
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario

    jeton, uid = _test_session_key('converter'), _test_account_id('converter')
    if not (jeton and uid):
        raise SkipScenario('aucun compte de test disponible')
    user = get_user_model().objects.get(pk=uid)
    folder = Path(settings.MEDIA_ROOT) / f'users/{uid}/temp'
    folder.mkdir(parents=True, exist_ok=True)
    temoin = _temoin(folder, 'wama_temoin_suppr_utilise.mp4', '.mp4')
    rel = f'users/{uid}/temp/{temoin.name}'

    # ORM HORS du contexte Playwright : une card qui DÉSIGNE le témoin (elle ne le possède pas).
    from wama.converter.models import ConversionJob
    job = ConversionJob.objects.create(user=user, input_filename=temoin.name, media_type='video',
                                       output_format='', status='PENDING')
    job.input_file.name = rel
    job.save(update_fields=['input_file'])

    before, verdicts, dialogues = _session_keys(), [], []

    def _dialogue(d, refuser_le_second):
        dialogues.append(d.message)
        utilise = 'utilisent ce fichier' in d.message
        d.dismiss() if (utilise and refuser_le_second) else d.accept()

    try:
        with sync_playwright() as p:
            nav = p.chromium.launch()
            ctx = nav.new_context(viewport={'width': 1500, 'height': 1000})
            ctx.add_cookies(_cookie(jeton))
            page = ctx.new_page()
            errors = []
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            page.on('pageerror', lambda e: errors.append(f'PAGEERROR {e}'))
            refusal = {'actif': True}
            page.on('dialog', lambda d: _dialogue(d, refusal['actif']))
            try:
                resp = page.goto(BASE_URL + PAGE, wait_until='networkidle', timeout=60000)
                arrivee = _exiger_la_page(page, resp, PAGE)
                if arrivee:
                    return arrivee
                _arbre_pret(page, [temoin.name])
                ancre = f'{ARBRE} .jstree-anchor:text-is("{temoin.name}")'

                # ① REFUS : deux dialogues, le second dit combien de cards, et rien ne part.
                page.click(ancre, button='right')
                page.click('.wama-card-menu .wama-cm-item:has-text("Supprimer")')
                page.wait_for_timeout(1500)
                prevenu = [m for m in dialogues if 'utilisent ce fichier' in m]
                verdicts.append((bool(prevenu), f'prévenu : {prevenu[:1] or dialogues}'))
                verdicts.append((temoin.exists(), 'refus : le fichier reste sur le disque'))

                # ② ACCEPTATION : le fichier part, la card reste (détachée).
                refusal['actif'] = False
                dialogues.clear()
                page.click(ancre, button='right')
                page.click('.wama-card-menu .wama-cm-item:has-text("Supprimer")')
                page.wait_for_timeout(2000)
                verdicts.append((not temoin.exists(), 'confirmé : le fichier est supprimé'))
                verdicts.append((len(dialogues) >= 2,
                                 f'{len(dialogues)} dialogue(s) à la confirmation'))
                verdicts.append(_console(errors))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(before)
        temoin.unlink(missing_ok=True)

    # Après le navigateur (ORM) : la card a SURVÉCU, et son entrée est vide.
    job.refresh_from_db()
    verdicts.append((bool(ConversionJob.objects.filter(pk=job.pk).exists()),
                     'la card survit à la suppression de son fichier'))
    verdicts.append((not job.input_file.name,
                     f'la card est DÉTACHÉE (entrée « {job.input_file.name} »)'))
    # Ménage : `_retirer` vise un asset (`.file`) — ici l'entrée est justement VIDE, et le fichier
    # est déjà parti ; la ligne témoin suffit.
    ConversionJob.objects.filter(pk=job.pk).delete()
    return _bilan(verdicts)


def check_released_files():
    """Retirer la DERNIÈRE card d'un fichier demande s'il faut le supprimer aussi (case décochée) ;
    gardé, il est dit en rouge dans ses informations ; un retrait hors confirmation l'annonce. (ok, detail)

    Décisions de Fabien du 2026-09-30 (`MEDIA_STORAGE_TIERING` D34) puis du 2026-10-01 (la question
    posée DANS la confirmation, case décochée par défaut). Les contrats Python attestent la règle
    sur les 10 apps ; ici on JOUE la chaîne servie, quatre témoins du converter :
      ① card qui POSSÈDE son fichier, case COCHÉE → fichier supprimé, rien d'annoncé ensuite ;
      ② idem, case laissée DÉCOCHÉE → fichier gardé, pas ré-annoncé, informations EN ROUGE ;
      ③ card qui ne fait que DÉSIGNER un fichier du temp → aucune case proposée, fichier intact ;
      ④ retrait HORS confirmation (POST direct, comme l'assistant) → annonce → « Supprimer ».
    """
    from django.contrib.auth import get_user_model
    from playwright.sync_api import sync_playwright

    from wama.common.models import ReleasedFile
    from wama.common.services.nightly_tests import SkipScenario
    from wama.common.utils.media_paths import app_media_dir
    from wama.converter.models import ConversionJob

    session_token, uid = _test_session_key('converter'), _test_account_id('converter')
    if not (session_token and uid):
        raise SkipScenario('aucun compte de test disponible')
    user = get_user_model().objects.get(pk=uid)
    home = app_media_dir('converter', uid, 'input')
    folder = Path(settings.MEDIA_ROOT) / home
    folder.mkdir(parents=True, exist_ok=True)

    temp = Path(settings.MEDIA_ROOT) / f'users/{uid}/temp'
    temp.mkdir(parents=True, exist_ok=True)

    # ORM HORS du contexte Playwright : trois cards qui POSSÈDENT leur entrée (domicile de l'app),
    # une qui DÉSIGNE un fichier du temp de l'utilisateur.
    witnesses = []
    for name, where, rel_dir in (('wama_temoin_libere_suppr.mp4', folder, home),
                                 ('wama_temoin_libere_garde.mp4', folder, home),
                                 ('wama_temoin_libere_designe.mp4', temp, f'users/{uid}/temp'),
                                 ('wama_temoin_libere_direct.mp4', folder, home)):
        path = _temoin(where, name, '.mp4')
        job = ConversionJob.objects.create(user=user, input_filename=name, media_type='video',
                                           output_format='', status='PENDING')
        job.input_file.name = f'{rel_dir}/{name}'
        job.save(update_fields=['input_file'])
        witnesses.append((job, path, f'{rel_dir}/{name}'))
    ((gone_job, gone_path, _r1), (kept_job, kept_path, kept_rel),
     (ref_job, ref_path, _r3), (direct_job, direct_path, _r4)) = witnesses
    before, verdicts = _session_keys(), []
    announce = '#wama-released-files [data-released-files]'
    button = "`.wama-card[data-id='${pk}'] .delete-btn[data-delete-url]`"
    remove = f"(pk) => document.querySelector({button})?.click()"
    seen = "() => (window.__wamaConfirmSeen || []).splice(0)"

    def removed(page, pk):
        page.wait_for_function(f"(pk) => !document.querySelector({button})", arg=pk, timeout=15000)
        page.wait_for_timeout(1200)          # la décision sur les fichiers, puis l'annonce éventuelle

    try:
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, session_token)
            try:
                resp = page.goto(BASE_URL + PAGE, wait_until='networkidle', timeout=60000)
                refused_page = _exiger_la_page(page, resp, PAGE)
                if refused_page:
                    return refused_page
                page.evaluate(seen)
                # ① Dernière card du fichier, case COCHÉE : le fichier part avec elle.
                set_delete_files(page, True)
                page.evaluate(remove, gone_job.pk)
                removed(page, gone_job.pk)
                asked = page.evaluate(seen)
                verdicts.append((len(asked) == 1 and asked[0]['option'],
                                 f'la confirmation propose « supprimer aussi le fichier » ({asked})'))
                verdicts.append((not gone_path.exists(), 'case cochée : le fichier est supprimé'))
                verdicts.append((page.locator(announce).count() == 0, 'rien d’annoncé ensuite'))

                # ② Case laissée DÉCOCHÉE : gardé, pas ré-annoncé, dit en rouge.
                set_delete_files(page, False)
                page.evaluate(remove, kept_job.pk)
                removed(page, kept_job.pk)
                page.evaluate(seen)
                verdicts.append((kept_path.exists(), 'case décochée : le fichier est gardé'))
                verdicts.append((page.locator(announce).count() == 0,
                                 'gardé à la confirmation : pas annoncé une seconde fois'))
                page.evaluate('(path) => FileManager.showInfo(path)', kept_rel)
                page.wait_for_selector('#fileInfoModal.show', timeout=10000)
                red = page.locator('#fileInfoModal .file-info-table td.text-danger')
                verdicts.append((red.count() == 1 and 'aucune card' in red.inner_text(),
                                 'informations du fichier : inutilisé, en rouge'))
                page.click('#fileInfoModal [data-bs-dismiss="modal"]')
                page.wait_for_selector('#fileInfoModal', state='hidden', timeout=10000)
                # …et il figure dans l'onglet « Inutilisés » de la médiathèque, d'où on le supprime
                # par son bouton de ligne (2026-10-01).
                kept_row = f'#unusedList [data-unused-row="{ReleasedFile.objects.get(path=kept_rel).pk}"]'
                page.goto(BASE_URL + '/media-library/?tab=unused', wait_until='networkidle', timeout=60000)
                page.wait_for_selector(kept_row, timeout=15000)
                verdicts.append((kept_path.name in page.inner_text(kept_row),
                                 'onglet « Inutilisés » de la médiathèque : le fichier y figure'))
                page.click(f'{kept_row} [data-unused-delete]')
                page.wait_for_selector(kept_row, state='detached', timeout=15000)
                verdicts.append((not kept_path.exists(), 'supprimé depuis la liste, un par un'))
                page.goto(BASE_URL + PAGE, wait_until='networkidle', timeout=60000)

                # ③ Card qui ne fait que DÉSIGNER : rien à proposer, rien de touché.
                set_delete_files(page, True)
                page.evaluate(remove, ref_job.pk)
                removed(page, ref_job.pk)
                asked = page.evaluate(seen)
                verdicts.append((len(asked) == 1 and not asked[0]['option'],
                                 f'fichier seulement désigné : aucune case ({asked})'))
                verdicts.append((ref_path.exists(), 'le fichier du temp est intact'))

                # ④ Retrait HORS confirmation (POST direct, comme l'assistant) : l'annonce le dit.
                page.evaluate("""(pk) => {
                    const b = document.querySelector(`.wama-card[data-id='${pk}'] .delete-btn[data-delete-url]`);
                    const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
                    return fetch(b.dataset.deleteUrl, {method: 'POST', headers: {'X-CSRFToken': csrf,
                        'Content-Type': 'application/json'}, body: '{}'}).then(() => WamaFM.deleted());
                }""", direct_job.pk)
                page.wait_for_selector(announce, timeout=15000)
                text = page.inner_text(announce)
                verdicts.append((direct_path.name in text and direct_path.exists(),
                                 f'retrait hors confirmation : annoncé, fichier gardé (« {text[:80]} »)'))
                page.click(f'{announce} [data-released-delete]')
                page.wait_for_selector(announce, state='detached', timeout=10000)
                verdicts.append((not direct_path.exists(), '« Supprimer » de l’annonce supprime le fichier'))
                verdicts.append(_console(errors))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(before)
        for job, path, rel in witnesses:
            ConversionJob.objects.filter(pk=job.pk).delete()
            ReleasedFile.objects.filter(path=rel).delete()
            path.unlink(missing_ok=True)
    return _bilan(verdicts)


def check_received_card_duplicate():
    """⧉ sur une card REÇUE crée une card À SOI : privée, ses fichiers copiés chez soi, l'original
    intact (2026-10-01, `WAMA_COLLABORATION §3bis`, mode lecture). (ok, detail)

    Joué sur le DESCRIBER : sa file passe par la brique commune (`batch_common`), qui montre les
    lots partagés. (La file du converter, construite à part, montre aussi les cards reçues depuis
    le 2026-10-02 : geste `common.received_card_visible` ci-dessous.)
    Le propriétaire est le compte de test DÉVELOPPEUR ; sa card témoin n'est publique que le temps
    du geste (repassée privée puis supprimée au nettoyage). Le destinataire est le compte de test.
    """
    from django.contrib.auth import get_user_model
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario, get_test_dev_user
    from wama.common.services.sharing import partager
    from wama.common.utils.media_paths import app_media_dir
    from wama.describer.models import BatchDescription, Description
    from wama.describer.views import _wrap_description_in_batch

    page_path = '/describer/'
    session_token, uid = _test_session_key('describer'), _test_account_id('describer')
    owner = get_test_dev_user()
    if not (session_token and uid and owner) or owner.pk == uid:
        raise SkipScenario('deux comptes de test distincts sont nécessaires')
    requester = get_user_model().objects.get(pk=uid)
    owner_home = app_media_dir('describer', owner.pk, 'input')
    folder = Path(settings.MEDIA_ROOT) / owner_home
    folder.mkdir(parents=True, exist_ok=True)
    name = 'wama_temoin_card_recue.txt'
    source = _temoin(folder, name, '.txt')
    item = Description.objects.create(user=owner, filename=name)
    item.input_file.name = f'{owner_home}/{name}'
    item.save(update_fields=['input_file'])
    # Un VRAI partage : la card dans son lot (la file se construit à partir des lots), partagée par
    # le service commun — qui pose la visibilité sur la card ET sur son lot.
    owner_batch = _wrap_description_in_batch(item)
    partager(owner, item, 'public')
    before_ids = set(Description.objects.filter(user=requester).values_list('pk', flat=True))
    before, verdicts, copies = _session_keys(), [], []
    button = f".wama-card[data-id='{item.pk}'] .duplicate-btn"
    try:
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, session_token)
            try:
                resp = page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                refused_page = _exiger_la_page(page, resp, page_path)
                if refused_page:
                    return refused_page
                shown = page.locator(button).count() > 0
                verdicts.append((shown, 'la card reçue est dans la file du destinataire, avec ⧉'))
                if shown:
                    page.evaluate(f"() => document.querySelector(\"{button}\").click()")
                    page.wait_for_timeout(3500)
                verdicts.append(_console(errors))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(before)
        copies = list(Description.objects.filter(user=requester).exclude(pk__in=before_ids))
        partager(owner, item, 'private')
    copy = copies[0] if len(copies) == 1 else None
    verdicts.append((copy is not None, f'{len(copies)} copie(s) créée(s) chez le destinataire'))
    if copy is not None:
        copied = Path(settings.MEDIA_ROOT) / copy.input_file.name if copy.input_file else None
        verdicts.append((copy.visibility == 'private', 'la copie naît privée'))
        verdicts.append((bool(copied) and copied.exists()
                         and copy.input_file.name.startswith(app_media_dir('describer', uid, '')),
                         f'son fichier est une copie chez le destinataire ({copy.input_file.name})'))
    verdicts.append((source.exists(), 'le fichier du propriétaire est intact'))
    # Ménage : les lignes témoins (lots compris) et leurs fichiers.
    for c in copies:
        path = Path(settings.MEDIA_ROOT) / c.input_file.name if c.input_file else None
        BatchDescription.objects.filter(user=requester, items__description=c).delete()
        Description.objects.filter(pk=c.pk).delete()
        if path:
            path.unlink(missing_ok=True)
    Description.objects.filter(pk=item.pk).delete()
    BatchDescription.objects.filter(pk=owner_batch.pk).delete()
    source.unlink(missing_ok=True)
    return _bilan(verdicts)


def check_received_card_visible():
    """Une card REÇUE est dans la file du CONVERTER du destinataire, s'y rafraîchit et se
    télécharge ; il ne peut pas la supprimer ; repassée privée, elle disparaît. (ok, detail)

    Le converter construit sa file à part (FK directe job→lot, pas `batch_common`) : c'est la file
    qui ne montrait que les cards du propriétaire jusqu'au 2026-10-02 (`WAMA_COLLABORATION
    §3bis.1`). Le rafraîchissement (`card_html`) est mesuré parce que c'est lui qui répondait 404
    au destinataire dans quatre autres apps — la file listait, la card refusait.
    Propriétaire : le compte de test DÉVELOPPEUR ; destinataire : le compte de test.
    """
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario, get_test_dev_user
    from wama.common.services.sharing import partager
    from wama.converter.models import ConversionJob

    page_path = '/converter/'
    session_token, uid = _test_session_key('converter'), _test_account_id('converter')
    owner = get_test_dev_user()
    if not (session_token and uid and owner) or owner.pk == uid:
        raise SkipScenario('deux comptes de test distincts sont nécessaires')
    job, output = _sortie_converter(owner.pk, 'wama_temoin_card_recue_converter.png')
    partager(owner, job, 'public')
    card = f".wama-card[data-id='{job.pk}']"
    fetch_status = """([url, method]) => {
        const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
        return fetch(url, {method, headers: {'X-CSRFToken': csrf}}).then(r => r.status);
    }"""
    before, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, session_token)
            try:
                resp = page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                refused_page = _exiger_la_page(page, resp, page_path)
                if refused_page:
                    return refused_page
                verdicts.append((page.locator(card).count() == 1,
                                 'la card reçue est dans la file du destinataire'))
                refreshed = page.evaluate(fetch_status, [f'{page_path}card/{job.pk}/html/', 'GET'])
                verdicts.append((refreshed == 200, f'son fragment se rafraîchit ({refreshed})'))
                fetched = page.evaluate(fetch_status, [f'{page_path}{job.pk}/download/', 'GET'])
                verdicts.append((fetched == 200, f'son résultat se télécharge ({fetched})'))
                # Console relevée AVANT la sonde de refus : le navigateur journalise le 403 attendu
                # comme une erreur de ressource.
                verdicts.append(_console(errors))
                refused = page.evaluate(fetch_status, [f'{page_path}{job.pk}/delete/', 'POST'])
                verdicts.append((refused in (403, 404), f'il ne peut pas la supprimer ({refused})'))
            finally:
                nav.close()
        # Contre-épreuve : repassée PRIVÉE, elle sort de sa file.
        partager(owner, job, 'private')
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, session_token)
            try:
                page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                verdicts.append((page.locator(card).count() == 0,
                                 'repassée privée, elle n’est plus dans sa file'))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(before)
        still_there = ConversionJob.objects.filter(pk=job.pk).exists()
        ConversionJob.objects.filter(pk=job.pk).delete()
        output.unlink(missing_ok=True)
    verdicts.append((still_there, 'la card du propriétaire est intacte'))
    return _bilan(verdicts)


def check_received_entry_arrangement():
    """Le RANGEMENT chez le destinataire par le VRAI chemin (2026-10-02, `WAMA_COLLABORATION
    §3bis.2`) : la card reçue est marquée « Reçue de … » ; son menu offre « Retirer de ma file » et
    pas les gestes du propriétaire ; retirée, elle quitte la file SANS rechargement ; au retour sur
    la page, « Réafficher » sous la barre la remet. L'élément du propriétaire n'est jamais touché.
    (ok, detail)

    Joué sur le DESCRIBER (file commune `build_batches_list`). Propriétaire : le compte de test
    DÉVELOPPEUR ; destinataire : le compte de test. ⚠ Pas de `accept_dialogs` à craindre : le geste
    n'ouvre aucune boîte.
    """
    from django.contrib.auth import get_user_model
    from playwright.sync_api import sync_playwright

    from wama.common.models import ReceivedEntry
    from wama.common.services.nightly_tests import SkipScenario, get_test_dev_user
    from wama.common.services.sharing import partager
    from wama.common.utils.media_paths import app_media_dir
    from wama.describer.models import BatchDescription, Description
    from wama.describer.views import _wrap_description_in_batch

    page_path = '/describer/'
    session_token, uid = _test_session_key('describer'), _test_account_id('describer')
    owner = get_test_dev_user()
    if not (session_token and uid and owner) or owner.pk == uid:
        raise SkipScenario('deux comptes de test distincts sont nécessaires')
    requester = get_user_model().objects.get(pk=uid)
    home = app_media_dir('describer', owner.pk, 'input')
    folder = Path(settings.MEDIA_ROOT) / home
    folder.mkdir(parents=True, exist_ok=True)
    name = 'wama_temoin_rangement.txt'
    source = _temoin(folder, name, '.txt')
    item = Description.objects.create(user=owner, filename=name)
    item.input_file.name = f'{home}/{name}'
    item.save(update_fields=['input_file'])
    owner_batch = _wrap_description_in_batch(item)
    partager(owner, item, 'public')
    card = f".wama-card[data-id='{item.pk}']"
    menu = '.wama-card-menu .wama-cm-item'
    before, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, session_token)
            try:
                resp = page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                refused_page = _exiger_la_page(page, resp, page_path)
                if refused_page:
                    return refused_page
                label = page.evaluate(
                    f"() => getComputedStyle(document.querySelector(\"{card}\"), '::before').content")
                verdicts.append(('Reçue de' in (label or ''), f'la card est marquée « reçue » ({label})'))
                page.evaluate("() => { window.__wamaNoReload = 'meme-page'; }")
                page.locator(card).first.click(button='right')
                page.wait_for_selector('.wama-card-menu', timeout=10000)
                remove = page.locator(f'{menu}:has-text("de ma file")')
                verdicts.append((remove.count() == 1, 'le menu propose « Retirer … de ma file »'))
                owner_only = page.locator(f'{menu}:has-text("Partager"), {menu}:has-text("Transférer")')
                verdicts.append((owner_only.count() == 0,
                                 f'ni « Partager » ni « Transférer » ({owner_only.count()})'))
                if remove.count() == 1:
                    remove.first.click()
                    page.wait_for_selector(card, state='detached', timeout=15000)
                verdicts.append((page.evaluate("() => window.__wamaNoReload") == 'meme-page',
                                 'elle quitte la file sans rechargement'))
                page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                page.wait_for_selector('[data-reception-hidden]', timeout=15000)
                verdicts.append((page.locator(card).count() == 0,
                                 'au retour sur la page, elle n’y est plus'))
                page.click('[data-reception-hidden] [data-reception-show-all]')
                page.wait_for_selector(card, timeout=20000)
                verdicts.append((True, '« Réafficher » la remet dans la file'))
                verdicts.append(_console(errors))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(before)
        partager(owner, item, 'private')
    verdicts.append((Description.objects.filter(pk=item.pk, user=owner).exists() and source.exists(),
                     'l’élément du propriétaire et son fichier sont intacts'))
    # Ménage : la ligne de rangement, le témoin, son lot, son fichier.
    ReceivedEntry.objects.filter(recipient=requester).filter(
        object_type=BatchDescription._meta.label, object_id=owner_batch.pk).delete()
    Description.objects.filter(pk=item.pk).delete()
    BatchDescription.objects.filter(pk=owner_batch.pk).delete()
    source.unlink(missing_ok=True)
    return _bilan(verdicts)


def check_received_card_readonly_and_request():
    """Card REÇUE en LECTURE SEULE, puis demande de PROPRIÉTÉ jusqu'à son acceptation (2026-10-03,
    décisions de Fabien). (ok, detail)

    Destinataire (compte de test, sur le describer) : la pastille dit « Lecture seule » ; ▶ et 🗑
    ouvrent l'encart au lieu d'agir ; ⚙ s'ouvre en CONSULTATION (bandeau, rien à enregistrer) ;
    « Mon accès » coche la lecture, grise les modes à venir, et la demande de propriété part.
    Propriétaire (compte de test DÉVELOPPEUR, pages communes) : la notification surgit en bas à
    droite ; « Ouvrir » mène à la demande ; « Accepter » lui cède la card.
    """
    from django.contrib.auth import get_user_model
    from playwright.sync_api import sync_playwright

    from wama.common.models import Notification, ObjectGrant, ReceivedEntry
    from wama.common.services.nightly_tests import SkipScenario, get_test_dev_user
    from wama.common.services.sharing import partager
    from wama.common.utils.media_paths import app_media_dir
    from wama.describer.models import BatchDescription, Description
    from wama.describer.views import _wrap_description_in_batch

    page_path = '/describer/'
    recipient_token, uid = _test_session_key('describer'), _test_account_id('describer')
    owner_token = _test_session_key('describer_01')          # le compte DÉVELOPPEUR
    owner = get_test_dev_user()
    if not (recipient_token and owner_token and uid and owner) or owner.pk == uid:
        raise SkipScenario('deux comptes de test distincts sont nécessaires')
    requester = get_user_model().objects.get(pk=uid)
    home = app_media_dir('describer', owner.pk, 'input')
    folder = Path(settings.MEDIA_ROOT) / home
    folder.mkdir(parents=True, exist_ok=True)
    name = 'wama_temoin_lecture_seule.txt'
    source = _temoin(folder, name, '.txt')
    item = Description.objects.create(user=owner, filename=name)
    item.input_file.name = f'{home}/{name}'
    item.save(update_fields=['input_file'])
    owner_batch = _wrap_description_in_batch(item)
    partager(owner, item, 'public')
    status_before = item.status
    card = f".wama-card[data-id='{item.pk}']"
    notice = '.wama-readonly-notice'
    before, verdicts, grant = _session_keys(), [], None
    try:
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, recipient_token)
            try:
                resp = page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                refused_page = _exiger_la_page(page, resp, page_path)
                if refused_page:
                    return refused_page
                label = page.evaluate(
                    f"() => getComputedStyle(document.querySelector(\"{card}\"), '::before').content")
                verdicts.append(('Lecture seule' in (label or ''), f'pastille : {label}'))
                for selector, what in (('.wama-cycle-btn', '▶'), ('.delete-btn', '🗑')):
                    page.locator(f'{card} {selector}').first.click()
                    shown = page.locator(notice).count() == 1 and 'Lecture seule' in page.inner_text(notice)
                    verdicts.append((shown, f'{what} ouvre l’encart « lecture seule »'))
                    page.keyboard.press('Escape')
                page.locator(f'{card} .settings-btn').first.click()
                page.wait_for_selector('.modal.show [data-wama-ro-banner]', timeout=15000)
                verdicts.append((page.locator('.modal.show .save-settings-btn:visible').count() == 0,
                                 '⚙ en consultation : rien à enregistrer'))
                page.locator('.modal.show [data-bs-dismiss="modal"]').first.click()
                page.wait_for_selector('.modal.show', state='detached', timeout=10000)
                page.locator(card).first.click(button='right')
                page.locator('.wama-card-menu .wama-cm-item:has-text("Mon accès")').first.click()
                page.wait_for_selector('.wama-cm-sous .wama-cm-item:has-text("propriétaire")',
                                       timeout=15000)
                texts = page.locator('.wama-cm-sous .wama-cm-item').all_inner_texts()
                verdicts.append((any('Lecture seule' in t and 'votre accès' in t for t in texts)
                                 and any('bientôt' in t for t in texts),
                                 f'« Mon accès » : lecture cochée, modes à venir grisés ({texts})'))
                page.locator('.wama-cm-sous .wama-cm-item:has-text("Demander à en devenir")').first.click()
                page.wait_for_timeout(1500)
                verdicts.append(_console(errors))
            finally:
                nav.close()
        grant = ObjectGrant.objects.filter(beneficiary=requester, object_id=item.pk,
                                           level=ObjectGrant.LEVEL_OWN).first()
        verdicts.append((grant is not None and grant.state == ObjectGrant.STATE_REQUESTED,
                         'la demande de propriété est enregistrée'))
        note = Notification.objects.filter(recipient=owner, kind='access_request').order_by('-pk').first()
        if grant is not None and note is not None:
            with sync_playwright() as p:
                nav, page, errors = _ouvrir(p, owner_token)
                try:
                    # La fenêtre en bas à droite montre ce qui est plus récent que le dernier vu.
                    page.add_init_script(
                        f"localStorage.setItem('wama.notifications.lastSeen', '{note.pk - 1}')")
                    page.goto(BASE_URL + '/common/notifications/', wait_until='networkidle', timeout=60000)
                    popup = page.locator(f'.wama-notif-popup[data-notification-id="{note.pk}"]')
                    popup.wait_for(timeout=15000)
                    verdicts.append(('demande' in popup.inner_text(),
                                     'la notification surgit en bas à droite'))
                    popup.locator('a:has-text("Ouvrir")').click()
                    page.wait_for_selector('[data-request-answer="1"]', timeout=15000)
                    page.click('[data-request-answer="1"]')
                    page.wait_for_selector('[data-request-answer]', state='detached', timeout=20000)
                    verdicts.append(('Accordé' in page.inner_text('[data-request-state]'),
                                     'la demande est accordée'))
                    verdicts.append(_console(errors))
                finally:
                    nav.close()
        item.refresh_from_db()
        verdicts.append((item.status == status_before, '▶ n’a rien lancé'))
        verdicts.append((item.user_id == requester.pk, 'acceptée, la card est au demandeur'))
    finally:
        _drop_new_sessions(before)
        # Ménage, MÊME sur un échec (un témoin resté en base fausse la mesure suivante) : la card
        # (chez l'un ou l'autre), son lot, la demande, les notifications, le fichier.
        item.refresh_from_db()
        moved = Path(settings.MEDIA_ROOT) / item.input_file.name if item.input_file else None
        ObjectGrant.objects.filter(object_id=item.pk, beneficiary=requester).delete()
        Notification.objects.filter(recipient__in=[owner, requester],
                                    kind__in=['access_request', 'card_transferred']).filter(
            body__contains=name).delete()
        ReceivedEntry.objects.filter(recipient=requester, object_id=owner_batch.pk).delete()
        BatchDescription.objects.filter(items__description=item).delete()
        Description.objects.filter(pk=item.pk).delete()
        BatchDescription.objects.filter(pk=owner_batch.pk).delete()
        for path in (source, moved):
            if path:
                path.unlink(missing_ok=True)
    return _bilan(verdicts)


def check_collaboration_cycle():
    """La COLLABORATION de bout en bout (2026-10-03, E1-E5 tranchées par Fabien). (ok, detail)

    Destinataire (compte de test, describer) : « Mon accès » → « Demander : Collaboration ».
    Propriétaire (compte DÉVELOPPEUR, pages communes) : la notification surgit, « Accepter ».
    Destinataire : la pastille dit « Collaboration », ⚙ s'ouvre EN ÉDITION (pas de bandeau de
    consultation, « Enregistrer » visible), 🗑 garde l'encart (la suppression reste au
    propriétaire). Propriétaire : « Mes partages » → « retirer ». Destinataire : de nouveau en
    lecture seule (E5 : effet immédiat).
    """
    from django.contrib.auth import get_user_model
    from playwright.sync_api import sync_playwright

    from wama.common.models import Notification, ObjectGrant, ReceivedEntry
    from wama.common.services.nightly_tests import SkipScenario, get_test_dev_user
    from wama.common.services.sharing import partager
    from wama.common.utils.media_paths import app_media_dir
    from wama.describer.models import BatchDescription, Description
    from wama.describer.views import _wrap_description_in_batch

    page_path = '/describer/'
    recipient_token, uid = _test_session_key('describer'), _test_account_id('describer')
    owner_token = _test_session_key('describer_01')
    owner = get_test_dev_user()
    if not (recipient_token and owner_token and uid and owner) or owner.pk == uid:
        raise SkipScenario('deux comptes de test distincts sont nécessaires')
    requester = get_user_model().objects.get(pk=uid)
    home = app_media_dir('describer', owner.pk, 'input')
    folder = Path(settings.MEDIA_ROOT) / home
    folder.mkdir(parents=True, exist_ok=True)
    name = 'wama_temoin_collaboration.txt'
    source = _temoin(folder, name, '.txt')
    item = Description.objects.create(user=owner, filename=name)
    item.input_file.name = f'{home}/{name}'
    item.save(update_fields=['input_file'])
    owner_batch = _wrap_description_in_batch(item)
    partager(owner, item, 'public')
    card = f".wama-card[data-id='{item.pk}']"
    label_js = f"() => getComputedStyle(document.querySelector(\"{card}\"), '::before').content"
    from django.utils import timezone
    started = timezone.now()
    before, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, recipient_token)
            try:
                resp = page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                refused_page = _exiger_la_page(page, resp, page_path)
                if refused_page:
                    return refused_page
                page.locator(card).first.click(button='right')
                page.locator('.wama-card-menu .wama-cm-item:has-text("Mon accès")').first.click()
                ask = page.locator('.wama-cm-sous .wama-cm-item:has-text("Demander : Collaboration")')
                ask.first.wait_for(timeout=15000)
                ask.first.click()
                page.wait_for_timeout(1500)
            finally:
                nav.close()
        grant = ObjectGrant.objects.filter(beneficiary=requester, level='collaborate',
                                           object_id=owner_batch.pk).first()
        verdicts.append((grant is not None and grant.state == 'requested',
                         'la demande de collaboration vise le lot et attend'))
        note = Notification.objects.filter(recipient=owner, kind='access_request').order_by('-pk').first()
        if grant is not None and note is not None:
            with sync_playwright() as p:
                nav, page, errors = _ouvrir(p, owner_token)
                try:
                    page.add_init_script(
                        f"localStorage.setItem('wama.notifications.lastSeen', '{note.pk - 1}')")
                    page.goto(BASE_URL + '/common/notifications/', wait_until='networkidle', timeout=60000)
                    popup = page.locator(f'.wama-notif-popup[data-notification-id="{note.pk}"]')
                    popup.wait_for(timeout=15000)
                    verdicts.append(('collaborer' in popup.inner_text(),
                                     'le propriétaire est prévenu en bas à droite'))
                    popup.locator('a:has-text("Ouvrir")').click()
                    page.wait_for_selector('[data-request-answer="1"]', timeout=15000)
                    page.click('[data-request-answer="1"]')
                    page.wait_for_selector('[data-request-answer]', state='detached', timeout=20000)
                finally:
                    nav.close()
            grant.refresh_from_db()
            verdicts.append((grant.state == 'granted', 'la collaboration est accordée'))
            with sync_playwright() as p:
                nav, page, errors = _ouvrir(p, recipient_token)
                try:
                    page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                    verdicts.append(('Collaboration' in (page.evaluate(label_js) or ''),
                                     'la pastille dit « Collaboration »'))
                    page.locator(f'{card} .settings-btn').first.click()
                    page.wait_for_selector('.modal.show', timeout=15000)
                    page.wait_for_timeout(800)
                    verdicts.append((page.locator('.modal.show [data-wama-ro-banner]').count() == 0
                                     and page.locator('.modal.show .save-settings-btn:visible').count() >= 1,
                                     '⚙ s’ouvre en ÉDITION (« Enregistrer » visible)'))
                    page.locator('.modal.show [data-bs-dismiss="modal"]').first.click()
                    page.wait_for_selector('.modal.show', state='detached', timeout=10000)
                    page.locator(f'{card} .delete-btn').first.click()
                    notice = page.locator('.wama-readonly-notice')
                    verdicts.append((notice.count() == 1 and 'Suppression réservée' in notice.inner_text(),
                                     '🗑 reste au propriétaire (encart)'))
                    verdicts.append(_console(errors))
                finally:
                    nav.close()
            with sync_playwright() as p:
                nav, page, errors = _ouvrir(p, owner_token)
                try:
                    page.goto(BASE_URL + '/common/shares/', wait_until='networkidle', timeout=60000)
                    page.click(f'[data-revoke="{grant.pk}"]')
                    page.wait_for_selector(f'[data-person="{grant.pk}"]', state='detached',
                                           timeout=15000)
                finally:
                    nav.close()
            grant.refresh_from_db()
            verdicts.append((grant.state == 'revoked', '« Mes partages » : le droit est retiré'))
            with sync_playwright() as p:
                nav, page, errors = _ouvrir(p, recipient_token)
                try:
                    page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                    verdicts.append(('Lecture seule' in (page.evaluate(label_js) or ''),
                                     'retiré : de nouveau en lecture seule (effet immédiat)'))
                finally:
                    nav.close()
    finally:
        _drop_new_sessions(before)
        partager(owner, item, 'private')
        ObjectGrant.objects.filter(beneficiary=requester, object_id__in=[item.pk, owner_batch.pk]).delete()
        Notification.objects.filter(recipient__in=[owner, requester], created_at__gte=started,
                                    kind__in=['access_request', 'access_granted',
                                              'access_revoked']).delete()
        ReceivedEntry.objects.filter(recipient=requester, object_id=owner_batch.pk).delete()
        Description.objects.filter(pk=item.pk).delete()
        BatchDescription.objects.filter(pk=owner_batch.pk).delete()
        source.unlink(missing_ok=True)
    return _bilan(verdicts)


def check_person_share_cycle():
    """PARTAGER À UNE PERSONNE de bout en bout (2026-10-06, `WAMA_COLLABORATION §3bis.2`). (ok, detail)

    Propriétaire (compte DÉVELOPPEUR, describer) : clic droit sur une card PRIVÉE → « Partager… »
    → « Avec une personne » : identifiant du destinataire, « Partager » ; la personne s'inscrit dans
    la modale. Destinataire (compte de test) : prévenu en bas à droite (N1), la card est dans SA
    file, marquée « Reçue de ». Propriétaire : « Mes partages » dit la personne et depuis quand,
    « retirer ». Destinataire : la card a quitté sa file (effet immédiat, lot compris).
    """
    from django.contrib.auth import get_user_model
    from playwright.sync_api import sync_playwright

    from wama.common.models import Notification, ObjectGrant, ReceivedEntry
    from wama.common.services.nightly_tests import SkipScenario, get_test_dev_user
    from wama.common.utils.media_paths import app_media_dir
    from wama.describer.models import BatchDescription, Description
    from wama.describer.views import _wrap_description_in_batch

    page_path = '/describer/'
    recipient_token, uid = _test_session_key('describer'), _test_account_id('describer')
    owner_token = _test_session_key('describer_01')
    owner = get_test_dev_user()
    if not (recipient_token and owner_token and uid and owner) or owner.pk == uid:
        raise SkipScenario('deux comptes de test distincts sont nécessaires')
    recipient = get_user_model().objects.get(pk=uid)
    home = app_media_dir('describer', owner.pk, 'input')
    folder = Path(settings.MEDIA_ROOT) / home
    folder.mkdir(parents=True, exist_ok=True)
    name = 'wama_temoin_partage_personne.txt'
    source = _temoin(folder, name, '.txt')
    item = Description.objects.create(user=owner, filename=name)
    item.input_file.name = f'{home}/{name}'
    item.save(update_fields=['input_file'])
    owner_batch = _wrap_description_in_batch(item)
    card = f".wama-card[data-id='{item.pk}']"
    label_js = f"() => getComputedStyle(document.querySelector(\"{card}\"), '::before').content"
    from django.utils import timezone
    started = timezone.now()
    before, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, recipient_token)
            try:
                page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                verdicts.append((page.locator(card).count() == 0,
                                 'privée : absente de la file du destinataire'))
            finally:
                nav.close()
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, owner_token)
            try:
                resp = page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                refused_page = _exiger_la_page(page, resp, page_path)
                if refused_page:
                    return refused_page
                page.locator(card).first.click(button='right')
                page.locator('.wama-card-menu .wama-cm-item:has-text("Partager…")').first.click()
                modal = '.wama-share-modal.show'
                page.wait_for_selector(f'{modal} [data-person-input]', timeout=15000)
                page.fill(f'{modal} [data-person-input]', recipient.username)
                page.select_option(f'{modal} [data-person-mode]', 'read')
                page.click(f'{modal} [data-person-add]')
                page.wait_for_selector(f'{modal} [data-person-row]', timeout=15000)
                verdicts.append((recipient.username in page.inner_text(f'{modal} [data-person-list]'),
                                 'la personne s’inscrit dans la modale'))
                verdicts.append(_console(errors))
            finally:
                nav.close()
        lines = ObjectGrant.objects.filter(beneficiary=recipient, state='granted', level='read')
        verdicts.append((lines.filter(object_id=item.pk).exists()
                         and lines.filter(object_id=owner_batch.pk).exists(),
                         'une ligne accordée sur la card ET son lot'))
        note = Notification.objects.filter(recipient=recipient, kind='share_received',
                                           created_at__gte=started).order_by('-pk').first()
        verdicts.append((note is not None, 'le destinataire est prévenu (share_received)'))
        with sync_playwright() as p:
            nav, page, errors = _ouvrir(p, recipient_token)
            try:
                if note is not None:
                    page.add_init_script(
                        f"localStorage.setItem('wama.notifications.lastSeen', '{note.pk - 1}')")
                page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                if note is not None:
                    popup = page.locator(f'.wama-notif-popup[data-notification-id="{note.pk}"]')
                    try:
                        popup.wait_for(timeout=15000)
                        shown = 'partage' in popup.inner_text()
                    except Exception:
                        shown = False
                    verdicts.append((shown, 'la notification surgit en bas à droite'))
                verdicts.append((page.locator(card).count() == 1, 'la card est dans SA file'))
                verdicts.append(('Reçue de' in (page.evaluate(label_js) or ''),
                                 'la pastille dit « Reçue de … »'))
                verdicts.append(_console(errors))
            finally:
                nav.close()
        batch_line = lines.filter(object_id=owner_batch.pk).first()
        if batch_line is not None:
            with sync_playwright() as p:
                nav, page, errors = _ouvrir(p, owner_token)
                try:
                    page.goto(BASE_URL + '/common/shares/', wait_until='networkidle', timeout=60000)
                    pill = page.locator(f'[data-person="{batch_line.pk}"]')
                    verdicts.append((pill.count() == 1 and 'depuis le' in pill.inner_text(),
                                     '« Mes partages » : la personne, depuis quand'))
                    page.click(f'[data-revoke="{batch_line.pk}"]')
                    page.wait_for_selector(f'[data-person="{batch_line.pk}"]', state='detached',
                                           timeout=15000)
                finally:
                    nav.close()
            verdicts.append((not ObjectGrant.in_force().filter(beneficiary=recipient,
                                                               object_id__in=[item.pk, owner_batch.pk])
                             .exists(), 'retiré : la card et son lot, ensemble'))
            with sync_playwright() as p:
                nav, page, errors = _ouvrir(p, recipient_token)
                try:
                    page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                    verdicts.append((page.locator(card).count() == 0,
                                     'retiré : la card quitte sa file (effet immédiat)'))
                finally:
                    nav.close()
    finally:
        _drop_new_sessions(before)
        ObjectGrant.objects.filter(beneficiary=recipient,
                                   object_id__in=[item.pk, owner_batch.pk]).delete()
        Notification.objects.filter(recipient__in=[owner, recipient], created_at__gte=started,
                                    kind__in=['share_received', 'access_revoked']).delete()
        ReceivedEntry.objects.filter(recipient=recipient, object_id=owner_batch.pk).delete()
        Description.objects.filter(pk=item.pk).delete()
        BatchDescription.objects.filter(pk=owner_batch.pk).delete()
        source.unlink(missing_ok=True)
    return _bilan(verdicts)


def check_card_transfer():
    """« Transférer à… » par le VRAI chemin : clic droit sur une card → entrée du menu → saisie du
    destinataire → la card QUITTE la file sans rechargement ; en base, elle est au destinataire,
    privée, son fichier déplacé chez lui (2026-10-01, `WAMA_COLLABORATION §3bis`). (ok, detail)

    ⚠ Pas de `accept_dialogs` ici : la réponse automatique validerait la boîte AVANT la saisie.
    Destinataire : le compte de test DÉVELOPPEUR ; le témoin est supprimé au nettoyage.
    """
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario, get_test_dev_user
    from wama.common.utils.media_paths import app_media_dir
    from wama.describer.models import BatchDescription, Description
    from wama.describer.views import _wrap_description_in_batch

    page_path = '/describer/'
    session_token, uid = _test_session_key('describer'), _test_account_id('describer')
    recipient = get_test_dev_user()
    if not (session_token and uid and recipient) or recipient.pk == uid:
        raise SkipScenario('deux comptes de test distincts sont nécessaires')
    from django.contrib.auth import get_user_model
    owner = get_user_model().objects.get(pk=uid)
    home = app_media_dir('describer', uid, 'input')
    folder = Path(settings.MEDIA_ROOT) / home
    folder.mkdir(parents=True, exist_ok=True)
    name = 'wama_temoin_transfert.txt'
    source = _temoin(folder, name, '.txt')
    item = Description.objects.create(user=owner, filename=name)
    item.input_file.name = f'{home}/{name}'
    item.save(update_fields=['input_file'])
    _wrap_description_in_batch(item)
    card = f".wama-card[data-id='{item.pk}']"
    before, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav = p.chromium.launch()
            ctx = nav.new_context(viewport={'width': 1500, 'height': 1000})
            ctx.add_cookies(_cookie(session_token))
            page = ctx.new_page()
            errors = []
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            page.on('pageerror', lambda e: errors.append(f'PAGEERROR {e}'))
            try:
                resp = page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                refused_page = _exiger_la_page(page, resp, page_path)
                if refused_page:
                    return refused_page
                page.evaluate("() => { window.__wamaNoReload = 'meme-page'; }")
                page.locator(card).first.click(button='right')
                entry = page.locator('.wama-card-menu .wama-cm-item:has-text("Transférer à")')
                verdicts.append((entry.count() == 1, 'le menu de la card propose « Transférer à… »'))
                entry.first.click()
                page.wait_for_selector('.wama-confirm.show [data-confirm-input]', timeout=10000)
                page.fill('.wama-confirm.show [data-confirm-input]', recipient.username)
                page.click('.wama-confirm.show [data-confirm-ok]')
                page.wait_for_selector(card, state='detached', timeout=15000)
                verdicts.append((page.evaluate("() => window.__wamaNoReload") == 'meme-page',
                                 'la card quitte la file sans rechargement'))
                verdicts.append(_console(errors))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(before)
    item.refresh_from_db()
    moved = Path(settings.MEDIA_ROOT) / item.input_file.name if item.input_file else None
    verdicts.append((item.user_id == recipient.pk and item.visibility == 'private',
                     'la card est au destinataire, privée'))
    verdicts.append((bool(moved) and moved.exists() and not source.exists()
                     and item.input_file.name.startswith(app_media_dir('describer', recipient.pk, '')),
                     f'son fichier a été DÉPLACÉ chez lui ({item.input_file.name})'))
    # Ménage : la card (et son lot éventuel chez le destinataire), le fichier.
    BatchDescription.objects.filter(items__description=item).delete()
    Description.objects.filter(pk=item.pk).delete()
    if moved:
        moved.unlink(missing_ok=True)
    source.unlink(missing_ok=True)
    return _bilan(verdicts)


def check_batch_transfer():
    """« Transférer le lot à… » depuis la card MÈRE : le groupe quitte la file sans rechargement ;
    en base, le lot ET ses deux cards sont au destinataire, leurs fichiers déplacés (2026-10-01).
    (ok, detail) — même montage et même réserve que `check_card_transfer`."""
    from django.contrib.auth import get_user_model
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario, get_test_dev_user
    from wama.common.utils.media_paths import app_media_dir
    from wama.describer.models import BatchDescription, BatchDescriptionItem, Description
    from wama.describer.views import _wrap_description_in_batch

    page_path = '/describer/'
    session_token, uid = _test_session_key('describer'), _test_account_id('describer')
    recipient = get_test_dev_user()
    if not (session_token and uid and recipient) or recipient.pk == uid:
        raise SkipScenario('deux comptes de test distincts sont nécessaires')
    owner = get_user_model().objects.get(pk=uid)
    home = app_media_dir('describer', uid, 'input')
    folder = Path(settings.MEDIA_ROOT) / home
    folder.mkdir(parents=True, exist_ok=True)
    items, sources = [], []
    for i in range(2):
        name = f'wama_temoin_lot_transfert_{i}.txt'
        sources.append(_temoin(folder, name, '.txt'))
        el = Description.objects.create(user=owner, filename=name)
        el.input_file.name = f'{home}/{name}'
        el.save(update_fields=['input_file'])
        items.append(el)
    lot = _wrap_description_in_batch(items[0])
    BatchDescriptionItem.objects.create(batch=lot, description=items[1], row_index=1)
    BatchDescription.objects.filter(pk=lot.pk).update(total=2)
    group = f".batch-group[data-batch-id='{lot.pk}']"
    before, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav = p.chromium.launch()
            ctx = nav.new_context(viewport={'width': 1500, 'height': 1000})
            ctx.add_cookies(_cookie(session_token))
            page = ctx.new_page()
            errors = []
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            page.on('pageerror', lambda e: errors.append(f'PAGEERROR {e}'))
            try:
                resp = page.goto(BASE_URL + page_path, wait_until='networkidle', timeout=60000)
                refused_page = _exiger_la_page(page, resp, page_path)
                if refused_page:
                    return refused_page
                page.evaluate("() => { window.__wamaNoReload = 'meme-page'; }")
                page.locator(f'{group} .wama-card.is-batch').first.click(button='right')
                entry = page.locator('.wama-card-menu .wama-cm-item:has-text("Transférer le lot")')
                verdicts.append((entry.count() == 1, 'le menu de la card mère propose « Transférer le lot à… »'))
                entry.first.click()
                page.wait_for_selector('.wama-confirm.show [data-confirm-input]', timeout=10000)
                page.fill('.wama-confirm.show [data-confirm-input]', recipient.username)
                page.click('.wama-confirm.show [data-confirm-ok]')
                page.wait_for_selector(group, state='detached', timeout=15000)
                verdicts.append((page.evaluate("() => window.__wamaNoReload") == 'meme-page',
                                 'le lot quitte la file sans rechargement'))
                verdicts.append(_console(errors))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(before)
    lot.refresh_from_db()
    for el in items:
        el.refresh_from_db()
    moved = [Path(settings.MEDIA_ROOT) / el.input_file.name for el in items if el.input_file]
    verdicts.append((lot.user_id == recipient.pk and all(el.user_id == recipient.pk for el in items),
                     'le lot et ses deux cards sont au destinataire'))
    verdicts.append((BatchDescriptionItem.objects.filter(batch=lot).count() == 2,
                     'le lot garde ses deux cards'))
    verdicts.append((len(moved) == 2 and all(m.exists() for m in moved)
                     and not any(s.exists() for s in sources),
                     'leurs fichiers ont été DÉPLACÉS chez lui'))
    # Ménage : le lot, ses cards, les fichiers.
    Description.objects.filter(pk__in=[el.pk for el in items]).delete()
    BatchDescription.objects.filter(pk=lot.pk).delete()
    for path in moved + sources:
        path.unlink(missing_ok=True)
    return _bilan(verdicts)


def register_menu_scenarios():
    from wama.common.services.nightly_tests import register
    register(id='common.tree_menu_keyboard', app='common', stage='ui',
             description="Menu contextuel de l'arbre au CLAVIER (focus, ↓, → entre, ← remonte, "
                         "Échap rend le focus)",
             run=lambda ctx: check_tree_menu_keyboard(), timeout_s=180)
    register(id='common.tree_send_to_menus', app='common', stage='ui',
             description="« Envoyer vers » de l'arbre = résolveur SERVEUR (fichier, sélection en "
                         "partiel annoncé, dossier)",
             run=lambda ctx: check_tree_send_to_menus(), timeout_s=240)
    register(id='media_library.card_menu_state', app='media_library', stage='ui',
             description='Menu « … » d\'une card : état médiathèque PERSISTÉ (+ → ✓) et retrait, '
                         'copie retirée, sortie intacte',
             run=lambda ctx: check_card_menu_library_state(), timeout_s=240)
    register(id='media_library.card_menu_late_binding', app='media_library', stage='ui',
             description='Menu « … » d\'une card LATE-BINDING (transcriber) : les FORMATS du ⬇ '
                         'en médiathèque, rendu → ✓ → retrait',
             run=lambda ctx: check_card_menu_library_late_binding(), timeout_s=240)
    register(id='common.tree_item_menu', app='common', stage='ui',
             description="Arbre : gestes d'élément du menu « … » (partager, médiathèque, RAG) sur un "
                         "fichier de SORTIE — mêmes entrées que la card, résolues au serveur après "
                         "l'ouverture ; rien de tel sur un dépôt temporaire",
             run=lambda ctx: check_tree_item_menu(), timeout_s=240)
    register(id='common.tree_delete_in_use', app='common', stage='ui',
             description="Arbre : supprimer un fichier qu'une card UTILISE prévient (combien de "
                         "cards), un refus ne supprime rien, une confirmation détache la card",
             run=lambda ctx: check_tree_delete_in_use(), timeout_s=240)
    register(id='common.released_files', app='common', stage='ui',
             description="Retirer la dernière card d'un fichier demande s'il faut le supprimer "
                         "(case décochée) ; gardé, il est dit en rouge ; seulement désigné, rien "
                         "n'est proposé ; un retrait hors confirmation l'annonce",
             run=lambda ctx: check_released_files(), timeout_s=240)
    register(id='common.received_card_duplicate', app='common', stage='ui',
             description="⧉ sur une card REÇUE crée une card à soi : privée, fichiers copiés chez "
                         "soi, original intact",
             run=lambda ctx: check_received_card_duplicate(), timeout_s=240)
    register(id='common.received_card_visible', app='common', stage='ui',
             description="Card REÇUE dans la file du converter : listée, rafraîchie, téléchargée, "
                         "pas supprimable par le destinataire ; repassée privée, elle disparaît",
             run=lambda ctx: check_received_card_visible(), timeout_s=240)
    register(id='common.received_entry_arrangement', app='common', stage='ui',
             description="Card REÇUE rangée par son destinataire : marquée « reçue », « Retirer de "
                         "ma file » sans rechargement, « Réafficher » la remet ; rien ne bouge chez "
                         "le propriétaire",
             run=lambda ctx: check_received_entry_arrangement(), timeout_s=240)
    register(id='common.received_card_readonly_request', app='common', stage='ui',
             description="Card REÇUE en lecture seule (▶ 🗑 → encart, ⚙ en consultation, « Mon "
                         "accès ») puis demande de propriété : notification en bas à droite chez "
                         "le propriétaire, « Accepter » lui cède la card",
             run=lambda ctx: check_received_card_readonly_and_request(), timeout_s=300)
    register(id='common.collaboration_cycle', app='common', stage='ui',
             description="Collaboration de bout en bout : demandée par « Mon accès », acceptée par "
                         "le propriétaire, ⚙ en édition, 🗑 réservée, retirée depuis « Mes partages »",
             run=lambda ctx: check_collaboration_cycle(), timeout_s=360)
    register(id='common.person_share_cycle', app='common', stage='ui',
             description="Partager à UNE PERSONNE depuis la card : le destinataire est prévenu, la "
                         "voit dans sa file ; « Mes partages » dit depuis quand, et le retrait la "
                         "lui retire (card et lot)",
             run=lambda ctx: check_person_share_cycle(), timeout_s=300)
    register(id='common.card_transfer', app='common', stage='ui',
             description="« Transférer à… » depuis le menu de la card : elle quitte la file sans "
                         "rechargement, appartient au destinataire, son fichier déplacé chez lui",
             run=lambda ctx: check_card_transfer(), timeout_s=240)
    register(id='common.batch_transfer', app='common', stage='ui',
             description="« Transférer le lot à… » depuis la card mère : le groupe quitte la file, "
                         "le lot et ses cards appartiennent au destinataire, fichiers déplacés",
             run=lambda ctx: check_batch_transfer(), timeout_s=240)
    register(id='common.nav_sandbox_keyboard', app='common', stage='ui',
             description='Sous-menu « Bac à sable » au CLAVIER, sans détournement par Bootstrap',
             run=lambda ctx: check_nav_sandbox_keyboard(), timeout_s=180)

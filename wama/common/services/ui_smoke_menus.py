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
                       _fichier_temoin, _session_keys, _test_account_id, _test_session_key)
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


def _temoin(dossier: Path, nom: str, ext: str) -> Path:
    """Un fichier témoin VALIDE pour `ext` (brique `_fichier_temoin`), déposé sous `nom`."""
    source = _fichier_temoin(ext)
    cible = dossier / nom
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
    erreurs = []
    page.on('console', lambda m: erreurs.append(m.text) if m.type == 'error' else None)
    page.on('pageerror', lambda e: erreurs.append(f'PAGEERROR {e}'))
    page.on('dialog', lambda d: d.accept())
    return nav, page, erreurs


def _console(erreurs):
    garde = [x for x in erreurs if not any(tok in x for tok in IGNORED_CONSOLE)]
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
    dossier = Path(settings.MEDIA_ROOT) / f'users/{uid}/temp'
    dossier.mkdir(parents=True, exist_ok=True)
    temoin = _temoin(dossier, 'wama_temoin_menu_clavier.png', '.png')
    avant, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, erreurs = _ouvrir(p, jeton)
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
                    verdicts.append(_console(erreurs))
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
                verdicts.append(_console(erreurs))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(avant)
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
    dossier = Path(settings.MEDIA_ROOT) / f'users/{uid}/temp'
    dossier.mkdir(parents=True, exist_ok=True)
    t_png = _temoin(dossier, 'wama_temoin_envoi_a.png', '.png')
    t_wav = _temoin(dossier, 'wama_temoin_envoi_b.wav', '.wav')
    rel = lambda f: f'users/{uid}/temp/{f.name}'
    attendu_fichier = [d['libelle'] for d in destinations(user, [rel(t_png)])]
    attendu_selection = [f"{d['libelle']} ({len(d['acceptes'])}/2 fichiers)"
                         for d in destinations(user, [rel(t_png), rel(t_wav)], partiel=True)]
    attendu_dossier = [d['libelle'] for d in destinations_dossier(user)]
    avant, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, erreurs = _ouvrir(p, jeton)
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
                verdicts.append(_console(erreurs))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(avant)
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
    from wama.common.models import JOB_STATUS_CHOICES
    from wama.common.services.nightly_tests import SkipScenario
    from wama.common.utils.media_paths import app_media_dir
    from wama.converter.models import ConversionJob
    from wama.media_library.models import UserAsset

    jeton, uid = _test_session_key('converter'), _test_account_id('converter')
    if not (jeton and uid):
        raise SkipScenario('aucun compte de test disponible')
    fini = next(c for c, _ in JOB_STATUS_CHOICES if c in ('SUCCESS', 'COMPLETED', 'DONE'))
    rel_sortie = f"{app_media_dir('converter', uid, 'output')}/wama_temoin_menu_mediatheque.png"
    sortie = Path(settings.MEDIA_ROOT) / rel_sortie
    sortie.parent.mkdir(parents=True, exist_ok=True)
    source = _fichier_temoin('.png')
    sortie.write_bytes(source.read_bytes())
    source.unlink(missing_ok=True)
    job = ConversionJob.objects.create(user_id=uid, input_filename=sortie.name, media_type='image',
                                       output_format='png', status=fini, progress=100)
    job.output_file.name = rel_sortie
    job.save(update_fields=['output_file'])
    assets_avant = set(UserAsset.objects.filter(user_id=uid).values_list('id', flat=True))
    carte = f'.wama-card[data-id="{job.id}"]:not(.is-batch)'
    avant, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, erreurs = _ouvrir(p, jeton)
            try:
                resp = page.goto(BASE_URL + PAGE, wait_until='networkidle', timeout=60000)
                arrivee = _exiger_la_page(page, resp, PAGE)
                if arrivee:
                    return arrivee
                page.wait_for_selector(carte, timeout=20000)

                def sous_menu():
                    page.click(carte, button='right')
                    page.hover('.wama-card-menu .wama-cm-item:has-text("Ajouter à la médiathèque")')
                    _attendre_sous(page)
                    return page.evaluate(JS_SOUS)

                e1 = sous_menu()
                plus = [lib for lib, ic in e1 if 'fa-plus' in ic]
                verdicts.append((bool(plus) and not any('fa-check' in ic for _, ic in e1),
                                 f'avant : aucun rôle coché {e1}'))
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
                verdicts.append(_console(erreurs))
            finally:
                nav.close()
        # En base, HORS du navigateur : la copie a disparu, la sortie de l'app est intacte.
        restants = UserAsset.objects.filter(source_app='converter', source_pk=job.pk).count()
        verdicts.append((restants == 0, f'base : {restants} asset(s) encore rangé(s) depuis le job'))
        verdicts.append((sortie.exists(), "la sortie de l'app n'a pas été touchée par le retrait"))
    finally:
        _drop_new_sessions(avant)
        for asset in UserAsset.objects.filter(user_id=uid).exclude(id__in=assets_avant):
            _retirer(asset)
        ConversionJob.objects.filter(pk=job.pk).delete()
        sortie.unlink(missing_ok=True)
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
    avant, verdicts = _session_keys(), []
    try:
        with sync_playwright() as p:
            nav, page, erreurs = _ouvrir(p, jeton)
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
                verdicts.append(_console(erreurs))
            finally:
                nav.close()
    finally:
        _drop_new_sessions(avant)
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
    register(id='common.nav_sandbox_keyboard', app='common', stage='ui',
             description='Sous-menu « Bac à sable » au CLAVIER, sans détournement par Bootstrap',
             run=lambda ctx: check_nav_sandbox_keyboard(), timeout_s=180)

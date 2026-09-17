"""Scénarios nocturnes `ui` — la COULEUR D'ÉTAT d'une card, telle qu'un navigateur la rend.

Né de la bascule du 2026-09-18 (marche P2, `ROUTE §10.6`) : la couleur d'état ne vient plus d'une
classe recopiée par onze gabarits, le générateur et quatre sites JS, mais de l'attribut
`data-status` que la card portait DÉJÀ. Aucun test Python ne voit ce changement : ils lisent des
sources, pas un rendu. Or ce qui compte ici est ce que l'utilisateur VOIT — et une règle CSS qui
ne gagne pas (spécificité, `!important` de Bootstrap) ne lève aucune erreur.

⚠ Le précédent est exactement celui-là : le 2026-09-02, le bord d'état restait GRIS sur toutes les
cards parce que `border-secondary` de Bootstrap est `!important` — défaut invisible autrement
qu'au `getComputedStyle`, et c'est ainsi qu'il avait été trouvé.

Module à part d'`ui_smoke.py` (même raison qu'`ui_smoke_matching` et `ui_smoke_menus`) ; il en
réutilise les briques et ne redéfinit rien. ⚠ Tout l'ORM est HORS du contexte Playwright
(`SynchronousOnlyOperation`).
"""
from .ui_smoke import (BASE_URL, IGNORED_CONSOLE, _LotRefuse, _drop_new_sessions,
                       _exiger_la_page, _monter_un_lot_par_gabarit, _session_keys,
                       _test_session_key)
from .ui_smoke_matching import _bilan, _cookie

#: Le converter ne mobilise AUCUN modèle : la page s'ouvre sans rien charger (même choix que
#: `ui_smoke_menus`). La couleur d'état est commune — l'app n'est qu'un support.
APP = 'converter'
PAGE = '/converter/'

#: Les cinq états et la couleur que le CSS commun leur donne (`app_modern.css`, bord gauche).
#: Écrites en `rgb(...)` : c'est la forme que rend `getComputedStyle`, jamais l'hexadécimal.
COULEURS = {
    'RUNNING':            'rgb(255, 193, 7)',    # ambre — en cours
    'SUCCESS':            'rgb(40, 167, 69)',    # vert — terminé
    'FAILURE':            'rgb(220, 53, 69)',    # rouge — échec
    'AWAITING_RESOURCES': 'rgb(253, 126, 20)',   # orange — décision Fabien 01/09
    'STALE':              'rgb(155, 89, 182)',   # violet — décision Fabien 17/09
}

#: Pose un état sur la PREMIÈRE card et rend la couleur de bord RÉELLEMENT calculée.
JS_COULEUR = """(etat) => {
    const c = document.querySelector('.wama-card[data-id]');
    if (!c) return null;
    c.setAttribute('data-status', etat);
    return getComputedStyle(c).borderLeftColor;
}"""

#: Contre-épreuve : l'ANCIENNE classe, SANS l'attribut. Elle ne doit plus rien colorer — sinon
#: une règle de classe a survécu quelque part (feuille d'app comprise) et la duplication vit
#: encore. On rend aussi la couleur « neutre » de référence (aucun état).
JS_CLASSE_MORTE = """() => {
    const c = document.querySelector('.wama-card[data-id]');
    if (!c) return null;
    c.setAttribute('data-status', '');
    const neutre = getComputedStyle(c).borderLeftColor;
    c.classList.add('processing', 'success', 'error', 'awaiting', 'stale');
    const avecClasses = getComputedStyle(c).borderLeftColor;
    c.classList.remove('processing', 'success', 'error', 'awaiting', 'stale');
    return { neutre, avecClasses };
}"""


def _ouvrir(p, jeton):
    """Navigateur + page authentifiée, avec le relevé d'erreurs. Rend `(navigateur, page, erreurs)`."""
    nav = p.chromium.launch()
    ctx = nav.new_context(viewport={'width': 1500, 'height': 1000})
    ctx.add_cookies(_cookie(jeton))
    page = ctx.new_page()
    erreurs = []
    page.on('console', lambda m: erreurs.append(m.text) if m.type == 'error' else None)
    page.on('pageerror', lambda e: erreurs.append(f'PAGEERROR {e}'))
    return nav, page, erreurs


def check_card_state_colors():
    """Les cinq états colorent la card, par l'ATTRIBUT, et l'ancienne classe ne colore plus.

    Une card RÉELLE de la file sert de support (semée par la voie de lot si la file est vide —
    la seule création dont le contrat garantit qu'elle ne démarre rien). On n'écrit AUCUN état
    en base : `STALE` n'est produit par aucune app média aujourd'hui (il faudra le gouverneur et
    la règle de péremption, marche P3), et y écrire une valeur hors du vocabulaire des files
    serait pire que ne rien mesurer. C'est bien le RENDU qui est éprouvé.
    """
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario
    from wama.converter.models import ConversionJob

    jeton = _test_session_key(APP)
    if not jeton:
        raise SkipScenario('aucun compte de test disponible')

    ids_avant = set(ConversionJob.objects.values_list('id', flat=True))   # ORM : hors Playwright
    sessions_avant, verdicts, nettoyes, semes = _session_keys(), [], 0, 0
    try:
        with sync_playwright() as p:
            nav, page, erreurs = _ouvrir(p, jeton)
            try:
                resp = page.goto(BASE_URL + PAGE, wait_until='networkidle', timeout=60000)
                arrivee = _exiger_la_page(page, resp, PAGE)
                if arrivee:
                    return arrivee

                # Il faut une card. On SÈME si la file est vide — sans quoi ce scénario
                # « passerait » en ne mesurant rien, ce qui est pire qu'un échec.
                if not page.query_selector('.wama-card[data-id]'):
                    try:
                        neufs, _d = _monter_un_lot_par_gabarit(page, APP)
                        semes = len(neufs or [])
                    except _LotRefuse as exc:
                        raise SkipScenario(f'file vide et semis refusé : {exc}')
                    page.goto(BASE_URL + PAGE, wait_until='networkidle', timeout=60000)
                    page.wait_for_timeout(800)
                if not page.query_selector('.wama-card[data-id]'):
                    raise SkipScenario('aucune card en file après semis — rien à mesurer')

                # ① chaque état donne SA couleur, mesurée sur le rendu
                rendus = {}
                for etat, attendue in COULEURS.items():
                    obtenue = page.evaluate(JS_COULEUR, etat)
                    rendus[etat] = obtenue
                    verdicts.append((obtenue == attendue,
                                     f'{etat} : bord {obtenue} (attendu {attendue})'))

                # ② les cinq couleurs sont DISTINCTES — deux états confondus à l'écran, c'est
                #    un état qu'on ne peut pas lire, même si chaque règle existe.
                verdicts.append((len(set(rendus.values())) == len(COULEURS),
                                 f'cinq couleurs distinctes : {sorted(set(rendus.values()))}'))

                # ③ CONTRE-ÉPREUVE : l'ancienne classe ne colore plus rien.
                mort = page.evaluate(JS_CLASSE_MORTE) or {}
                verdicts.append((mort.get('neutre') == mort.get('avecClasses'),
                                 f"classes d'état héritées sans attribut : bord "
                                 f"{mort.get('avecClasses')} vs {mort.get('neutre')} sans elles "
                                 f"— elles doivent être SANS effet"))

                garde = [x for x in erreurs if not any(t in x for t in IGNORED_CONSOLE)]
                verdicts.append((not garde, f'console : {len(garde)} erreur(s) {garde[:1]}'))
            finally:
                nav.close()
    except SkipScenario:
        raise
    except Exception as exc:
        raise SkipScenario(f'navigateur/serveur indisponible ({type(exc).__name__}: {str(exc)[:100]})')
    finally:
        _drop_new_sessions(sessions_avant)
        try:
            crees = set(ConversionJob.objects.values_list('id', flat=True)) - ids_avant
            if crees:
                ConversionJob.objects.filter(id__in=crees).delete()
                nettoyes = len(crees)
        except Exception:
            pass

    ok, detail = _bilan(verdicts, unite='mesures')
    if semes:
        detail += f' ; {semes} élément(s) semés'
    if nettoyes:
        detail += f' ; {nettoyes} nettoyé(s)'
    return ok, detail


def register_state_color_scenarios():
    from wama.common.services.nightly_tests import register
    register(id='common.card_state_color', app='common', stage='ui',
             description="Couleur d'état d'une card RENDUE : les 5 états par `data-status`, "
                         "distincts, et l'ancienne classe sans effet",
             run=lambda ctx: check_card_state_colors(), timeout_s=180)

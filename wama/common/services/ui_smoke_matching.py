"""Scénarios nocturnes `ui` — APPARIEMENT voix ↔ langue ↔ moteur, et médiathèque A′ + 3D.

Nés comme sondes de session (`sonde_double_sens*.py`, `sonde_3d.py`) les 12-13/09, versés ici
le 13/09 — une sonde qui reste dans un bloc-notes meurt avec la session ; le nocturne, lui, la
rejoue. Ce que ces gestes ont trouvé en une journée le justifie : le bloc d'appariement de
l'avatarizer était MORT (briques jamais chargées : `if (window.WamaModelCaps)` se taisait), une
voix clonée grisait « auto », et `three.core.js` manquait depuis trois semaines. Aucun test
Python ne peut voir ça : les briques s'exécutent SERVIES.

Module à part d'`ui_smoke.py` (5 300 lignes) ; il en réutilise les briques (compte de test,
verdict d'arrivée, témoins) et ne redéfinit rien.
"""
import os
from urllib.parse import urlparse

from django.conf import settings

from .ui_smoke import (BASE_URL, IGNORED_CONSOLE, _messages_a_l_ecran, _test_session_key,
                       _verdict_d_arrivee, _wav_silence)

# Les selects de modale (avatarizer) peuvent être hors écran : on pose `value` + `change` par
# JS, jamais `select_option` (qui exige la visibilité).
_JS_ETAT_MODELES = ("(mid) => Array.from(document.querySelectorAll('#' + mid + ' option'))"
                    ".filter(o => o.value).map(o => ({ v: o.value, disabled: o.disabled,"
                    " title: o.title || '', serveur: !!o.dataset.backendMissing }))")
_JS_OPTIONS = ("(id) => Array.from(document.querySelectorAll('#' + id + ' option'))"
               ".map(o => ({ v: o.value, hidden: o.hidden || o.disabled }))")
_JS_SET = ("([id, v]) => { const s = document.getElementById(id); if (!s) return null;"
           " s.value = v; s.dispatchEvent(new Event('change', {bubbles: true})); return s.value; }")


def _cookie(jeton):
    return [{'name': settings.SESSION_COOKIE_NAME, 'value': jeton,
             'domain': urlparse(BASE_URL).hostname, 'path': '/'}]


def _bilan(verdicts, unite='gestes'):
    echecs = [d for ok, d in verdicts if not ok]
    return (not echecs), (f'{len(verdicts) - len(echecs)}/{len(verdicts)} {unite}'
                          + (f' — ÉCHECS : {echecs}' if echecs else ''))


def _retirer(asset):
    """Fichier ET ligne — un `delete()` ORM ne retire pas le fichier (leçon du 02/09)."""
    try:
        chemin = asset.file.path
        type(asset).objects.filter(pk=asset.pk).delete()
        if os.path.isfile(chemin):
            os.remove(chemin)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════════════
# VOIX ↔ LANGUE ↔ MOTEUR : le DOUBLE SENS
# ═══════════════════════════════════════════════════════════════════════════════════════

def check_voice_language_matching(app: str, url_path: str, ids: dict):
    """Le double sens voix/langue ↔ modèle sur la page SERVIE de `app`. (ok, detail).

    A. une langue qu'un moteur ne parle pas (ni natif ni repli) le GRISE avec une raison qui
       nomme « Langue », jamais ne le cache ; revenir en `fr` le réactive ;
    B. une voix clonée (`ua_`) grise les moteurs sans clonage — et JAMAIS « auto » (la
       contrainte est portée au tirage, décision Fabien 13/09) ; `default` réactive ;
    C. un moteur sans clonage MASQUE les voix clonées ;
    D. un moteur restreint le select de langue (`langFilter`).
    Une voix-témoin `ua_` est semée sur le compte de test (il n'en a pas) et retirée.
    Les deux apps ne servent pas la voix pareil (select serveur / modale WamaParams) : chacune
    DÉCLARE ses ids, le geste est le même.

    `ids['open_item']` (2026-09-24) : les selects vivent dans la modale ⚙ d'un ÉLÉMENT, générée
    à l'ouverture par le cycle commun (`WamaParams.settingsModal`) — ils n'existent pas au
    chargement. Le geste monte alors un élément témoin (fabrique déclarée, compte de test,
    retiré en sortie), ouvre son ⚙ par un vrai clic, et mesure DANS la modale ouverte. Avant le
    portage, l'avatarizer servait une modale STATIQUE cachée : le geste lisait ses selects sans
    l'ouvrir — il mesurait des champs que l'utilisateur ne voyait qu'après un clic.
    """
    from playwright.sync_api import sync_playwright
    from django.core.files.base import ContentFile
    from wama.common.services.nightly_tests import SkipScenario, get_test_user
    from wama.media_library.models import UserAsset

    jeton = _test_session_key(app)
    if not jeton:
        raise SkipScenario('aucun compte de test disponible')
    M, V, L = ids['model'], ids['voice'], ids['language']
    temoin = UserAsset(user=get_test_user(), name='wama_temoin_voix_double_sens', asset_type='voice')
    temoin.file.save('wama_temoin_voix_double_sens.wav', ContentFile(_wav_silence()), save=True)
    # Élément témoin dont on ouvrira le ⚙ — créé HORS du contexte Playwright (ORM synchrone).
    element = ids['open_item'](get_test_user()) if ids.get('open_item') else None
    verdicts = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                ctx = browser.new_context(viewport={'width': 1500, 'height': 1100})
                ctx.add_cookies(_cookie(jeton))
                page = ctx.new_page()
                erreurs = []
                page.on('console', lambda m: erreurs.append(m.text) if m.type == 'error' else None)
                resp = page.goto(BASE_URL + url_path, wait_until='networkidle')
                v = _verdict_d_arrivee(page.url, _messages_a_l_ecran(page),
                                       resp.status if resp else None, url_path)
                if v is not None:
                    return v
                page.wait_for_timeout(1800)
                if element is not None:
                    # Le VRAI geste : clic sur le ⚙ de l'élément témoin, modale générée.
                    gear = f'.settings-btn[data-id="{element.pk}"]'
                    if not page.query_selector(gear):
                        return False, f'⚙ de l’élément témoin #{element.pk} absent de la file'
                    # Ouvrir, FERMER, rouvrir : la modale est détruite et recréée à chaque ouverture,
                    # et c'est sur la SECONDE instance qu'on mesure — le cas où des écouteurs d'une
                    # instance disparue viseraient les champs homonymes de la nouvelle.
                    for tour in (1, 2):
                        page.locator(gear).first.click(timeout=15000)
                        page.wait_for_selector('.modal.show', timeout=8000)
                        page.wait_for_timeout(1800)   # options du catalogue + capacités (asynchrones)
                        if tour == 1:
                            page.locator('.modal.show [data-bs-dismiss="modal"]').first.click()
                            page.wait_for_selector('.modal.show', state='detached', timeout=8000)
                            page.wait_for_timeout(500)
                if not page.evaluate("([m, v]) => !!document.getElementById(m) && !!document.getElementById(v)", [M, V]):
                    return False, f'selects {M}/{V} absents de la page'

                def etat():
                    return {m['v']: m for m in page.evaluate(_JS_ETAT_MODELES, M)}

                def set_(sid, val):
                    page.evaluate(_JS_SET, [sid, val])
                    page.wait_for_timeout(300)

                # A. langue → modèles
                set_(L, 'fr')
                libres = [k for k, m in etat().items() if not m['serveur'] and not m['disabled']]
                verdicts.append((bool(libres), f'A0 {len(libres)} moteur(s) actif(s) en fr'))
                meilleure, grises_max = None, []
                for lang in [o['v'] for o in page.evaluate(_JS_OPTIONS, L) if o['v'] and o['v'] != 'fr']:
                    set_(L, lang)
                    e = etat()
                    g = [k for k in libres if e[k]['disabled'] and 'Langue' in e[k]['title']]
                    if len(g) > len(grises_max):
                        meilleure, grises_max = lang, g
                verdicts.append((bool(grises_max), f'A1 langue {meilleure} grise {len(grises_max)} moteur(s) avec raison'))
                set_(L, 'fr')
                e = etat()
                verdicts.append((all(not e[k]['disabled'] for k in libres), 'A2 retour fr réactive'))
                # B. voix clonée → modèles (jamais « auto »)
                clonees = [o['v'] for o in page.evaluate(_JS_OPTIONS, V) if o['v'].startswith('ua_')]
                verdicts.append((bool(clonees), f'B0 voix clonée offerte : {clonees[:1]}'))
                if clonees:
                    set_(V, clonees[0])
                    e = etat()
                    g = [k for k in libres if e[k]['disabled']]
                    verdicts.append((bool(g), f'B1 voix {clonees[0]} grise {len(g)} moteur(s)'))
                    verdicts.append(('auto' not in g, 'B2 « auto » reste compatible'))
                    set_(V, 'default')
                    e = etat()
                    verdicts.append((all(not e[k]['disabled'] for k in libres), 'B3 retour default réactive'))
                # C/D. moteur sans clonage → voix clonées masquées, langues restreintes
                sans = [k for k in libres if 'bark' in k or 'kokoro' in k]
                if sans:
                    set_(M, sans[0])
                    page.wait_for_timeout(200)
                    voix = {o['v']: o for o in page.evaluate(_JS_OPTIONS, V)}
                    verdicts.append((all(voix[c]['hidden'] for c in clonees if c in voix),
                                     f'C {sans[0]} masque les voix clonées'))
                    masquees = [o['v'] for o in page.evaluate(_JS_OPTIONS, L) if o['hidden']]
                    verdicts.append((bool(masquees), f'D {sans[0]} masque {len(masquees)} langue(s)'))
                keep = [x for x in erreurs if not any(tok in x for tok in IGNORED_CONSOLE)]
                verdicts.append((not keep, f'console : {len(keep)} erreur(s) {keep[:1]}'))
            finally:
                browser.close()
    finally:
        _retirer(temoin)
        if element is not None:
            type(element).objects.filter(pk=element.pk).delete()
    return _bilan(verdicts)


def _avatarizer_pipeline_item(user):
    """Un job avatarizer PIPELINE en attente (texte à dire : les champs TTS de la modale ne
    s'affichent que pour lui, `show_if='text_content'`). Aucun fichier, rien ne démarre."""
    from wama.avatarizer.models import AvatarJob
    return AvatarJob.objects.create(user=user, mode='pipeline', status='PENDING',
                                    text_content='wama témoin appariement voix/langue')


def register_voice_language_scenarios():
    """Les deux apps TTS déclarent leurs ids ; le geste est commun."""
    from wama.common.services.nightly_tests import register
    for app, ids in (('synthesizer', {'model': 'tts_model', 'voice': 'voice_preset', 'language': 'language'}),
                     ('avatarizer', {'model': 'settingsTtsModel', 'voice': 'settingsVoicePreset',
                                     'language': 'settingsLanguage',
                                     # modale ⚙ GÉNÉRÉE à l'ouverture (cycle commun, 24/09)
                                     'open_item': _avatarizer_pipeline_item})):
        register(id=f'{app}.voice_language_matching', app=app, stage='ui',
                 description=f'{app} : voix ↔ langue ↔ moteur à DOUBLE SENS dans le navigateur '
                             '(grisé avec raison, jamais caché ; « auto » jamais grisé)',
                 run=lambda ctx, a=app, i=ids: check_voice_language_matching(a, f'/{a}/', i),
                 timeout_s=240)


# ═══════════════════════════════════════════════════════════════════════════════════════
# VOIX D'UN MORCEAU (composer) : « Chanson » grise les modèles qui ne CHANTENT pas
# ═══════════════════════════════════════════════════════════════════════════════════════

def check_vocals_matching():
    """La valeur « Chanson » du réglage Voix grise, au volet ET dans la modale ⚙, les modèles qui
    ne déclarent pas `supports_vocals` — avec la raison, jamais cachés, « auto » jamais grisé ;
    « Instrumental » ne grise rien (2026-10-05, `WamaInputMatch.capabilitySlot`). La modale porte
    aussi le prompt à deux faces avec son ✨ et le champ Paroles. (ok, detail).
    Un élément témoin du compte de test est créé hors du contexte Playwright, et retiré."""
    from playwright.sync_api import sync_playwright
    from wama.common.services.nightly_tests import SkipScenario, get_test_user
    from wama.composer.models import ComposerGeneration
    from wama.composer.utils.vocals import singing_models

    jeton = _test_session_key('composer')
    if not jeton:
        raise SkipScenario('aucun compte de test disponible')
    chanteurs = set(singing_models('text-to-music'))
    if not chanteurs:
        raise SkipScenario('aucun modèle ne déclare supports_vocals au catalogue')
    # Prompt VIDE : l'enrichissement à l'ingestion ne part pas (`prompt_ingest._on_created`) —
    # le témoin ne réveille aucun LLM, et sa modale montre le prompt de l'utilisateur (✨ offert).
    element = ComposerGeneration.objects.create(user=get_test_user(), prompt='',
                                                model='composer:musicgen-small')
    verdicts = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                ctx = browser.new_context(viewport={'width': 1500, 'height': 1100})
                ctx.add_cookies(_cookie(jeton))
                page = ctx.new_page()
                erreurs = []
                page.on('console', lambda m: erreurs.append(m.text) if m.type == 'error' else None)
                resp = page.goto(BASE_URL + '/composer/', wait_until='networkidle')
                v = _verdict_d_arrivee(page.url, _messages_a_l_ecran(page),
                                       resp.status if resp else None, '/composer/')
                if v is not None:
                    return v
                page.wait_for_timeout(1800)

                def mesurer(model_id, vocals_id, etape):
                    page.evaluate(_JS_SET, [vocals_id, 'song'])
                    page.wait_for_timeout(500)
                    e = {m['v']: m for m in page.evaluate(_JS_ETAT_MODELES, model_id)}
                    voix = [k for k, m in e.items() if m['disabled'] and 'Voix' in m['title']]
                    autos = [k for k in e if k.startswith('auto')]
                    verdicts.append((bool(voix) and not (set(voix) & chanteurs),
                                     f'{etape} « Chanson » grise {len(voix)} non-chanteur(s), '
                                     f'aucun chanteur'))
                    verdicts.append((not (set(voix) & set(autos)), f'{etape} « auto » jamais grisé'))
                    page.evaluate(_JS_SET, [vocals_id, 'instrumental'])
                    page.wait_for_timeout(400)
                    e = {m['v']: m for m in page.evaluate(_JS_ETAT_MODELES, model_id)}
                    verdicts.append((not [k for k, m in e.items() if 'Voix' in m['title']],
                                     f'{etape} « Instrumental » ne grise rien'))

                if not page.query_selector('#vocalsSelect'):
                    return False, 'réglage Voix (#vocalsSelect) absent du volet'
                mesurer('modelSelect', 'vocalsSelect', 'Volet :')
                gear = f'.settings-btn[data-id="{element.pk}"]'
                if not page.query_selector(gear):
                    return False, f'⚙ de l’élément témoin #{element.pk} absent de la file'
                for tour in (1, 2):          # la SECONDE modale (recréée) est celle qu'on mesure
                    page.locator(gear).first.click(timeout=15000)
                    page.wait_for_selector('.modal.show', timeout=8000)
                    page.wait_for_timeout(1800)
                    if tour == 1:
                        page.locator('.modal.show [data-bs-dismiss="modal"]').first.click()
                        page.wait_for_selector('.modal.show', state='detached', timeout=8000)
                        page.wait_for_timeout(500)
                verdicts.append((bool(page.query_selector('.modal.show #settingsLyrics')),
                                 'Modale : champ Paroles présent'))
                bar = page.evaluate("() => { const b = document.querySelector("
                                    "'.modal.show .wama-prompt-enrich'); return b ? b.textContent : ''; }")
                verdicts.append(('Traduire et enrichir' in bar, 'Modale : ✨ de la brique sous le prompt'))
                mesurer('settingsModel', 'settingsVocals', 'Modale :')
                keep = [x for x in erreurs if not any(tok in x for tok in IGNORED_CONSOLE)]
                verdicts.append((not keep, f'console : {len(keep)} erreur(s) {keep[:1]}'))
            finally:
                browser.close()
    finally:
        ComposerGeneration.objects.filter(pk=element.pk).delete()
    return _bilan(verdicts)


def check_imager_enrich_trigger():
    """Le ✨ « Traduire et enrichir » de l'imager est celui de la BRIQUE (2026-10-05) : présent
    sous le prompt des deux cards (image, vidéo), et plus aucun bouton écrit dans l'app. (ok, detail)."""
    from playwright.sync_api import sync_playwright
    from wama.common.services.nightly_tests import SkipScenario

    jeton = _test_session_key('imager')
    if not jeton:
        raise SkipScenario('aucun compte de test disponible')
    verdicts = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(viewport={'width': 1500, 'height': 1100})
            ctx.add_cookies(_cookie(jeton))
            page = ctx.new_page()
            erreurs = []
            page.on('console', lambda m: erreurs.append(m.text) if m.type == 'error' else None)
            resp = page.goto(BASE_URL + '/imager/', wait_until='networkidle')
            v = _verdict_d_arrivee(page.url, _messages_a_l_ecran(page),
                                   resp.status if resp else None, '/imager/')
            if v is not None:
                return v
            page.wait_for_timeout(1500)
            for prompt_id in ('imgPrompt', 'vidPrompt'):
                bar = page.evaluate(
                    "(id) => { const f = document.getElementById(id); if (!f) return null;"
                    " let n = f.nextElementSibling; while (n && !n.classList.contains('wama-prompt-enrich'))"
                    " n = n.nextElementSibling; return n ? n.textContent : ''; }", prompt_id)
                verdicts.append((bool(bar) and 'Traduire et enrichir' in bar,
                                 f'{prompt_id} : ✨ de la brique sous le prompt'))
            verdicts.append((not page.query_selector('.enhance-prompt-btn'),
                             'aucun bouton ✨ écrit dans l’app'))
            keep = [x for x in erreurs if not any(tok in x for tok in IGNORED_CONSOLE)]
            verdicts.append((not keep, f'console : {len(keep)} erreur(s) {keep[:1]}'))
        finally:
            browser.close()
    return _bilan(verdicts)


def register_vocals_scenarios():
    from wama.common.services.nightly_tests import register
    register(id='composer.vocals_matching', app='composer', stage='ui',
             description='composer : « Chanson » grise les non-chanteurs (volet + modale ⚙), '
                         '« auto » jamais ; Paroles et ✨ dans la modale',
             run=lambda ctx: check_vocals_matching(), timeout_s=240)
    register(id='imager.prompt_enrich_trigger', app='imager', stage='ui',
             description='imager : le ✨ du prompt est celui de la brique WamaPromptEnrich',
             run=lambda ctx: check_imager_enrich_trigger(), timeout_s=180)


def check_voice_library_pick(app: str, url_path: str, ids: dict):
    """Un champ de VOIX ouvre la fenêtre commune de la médiathèque : AJOUTER (fichier nommé, puis
    micro) et CHOISIR, sans quitter l'app (2026-09-30). (ok, detail).

    Né d'une sonde de session le jour même. Ce qu'il garde : le bouton est posé par `WamaParams`
    sur tout champ `options_source: 'voices'` (aucun code d'app) ; la fenêtre n'offre que la
    nature Voix ; la card d'ajout y est celle de la page médiathèque ; « Enregistrer » produit un
    webm que le serveur range en WAV (`Nature.to_pivot`) ; la voix ajoutée devient la valeur du
    champ (`ua_<id>`). Le micro est le périphérique SIMULÉ de Chromium. Tout ce qui est créé l'est
    sous le compte de test, et retiré.
    """
    import tempfile

    from playwright.sync_api import sync_playwright
    from wama.common.services.nightly_tests import SkipScenario, get_test_user
    from wama.media_library.models import UserAsset

    jeton = _test_session_key(app)
    if not jeton:
        raise SkipScenario('aucun compte de test disponible')
    user = get_test_user()
    before = set(UserAsset.objects.filter(user=user, asset_type='voice').values_list('pk', flat=True))
    element = ids['open_item'](user) if ids.get('open_item') else None
    voice = ids['voice']
    wav = os.path.join(tempfile.gettempdir(), 'wama_probe_voice.wav')
    with open(wav, 'wb') as fh:
        fh.write(_wav_silence(1.0, 16000))
    verdicts = []
    choose_ready = "() => !document.getElementById('mp-choose').disabled"

    def open_window(page):
        page.click(f'[data-library-pick="{voice}"]')
        page.wait_for_selector('#wama-mediapicker-modal.show', timeout=10000)
        page.wait_for_selector('#mp-tabs [data-mp-tab]', timeout=10000)
        page.click('#mp-add-toggle')
        page.wait_for_selector('#mp-add [data-library-add="mp"]', timeout=5000)

    def confirm_proposal(page):
        """La voix est d'abord ÉCOUTÉE (langue, genre proposés) : on attend la proposition, puis
        on valide « Ajouter » — le geste réel (2026-09-30)."""
        page.wait_for_selector('#mp-add [data-library-pending]:not([hidden])', timeout=15000)
        page.wait_for_function("() => { const b = document.querySelector('#mp-add [data-library-confirm]');"
                               " return b && !b.disabled; }", timeout=90000)
        said = page.inner_text('#mp-add [data-library-pending-text]')
        page.click('#mp-add [data-library-confirm]')
        return said

    def choose(page):
        page.click('#mp-choose')
        page.wait_for_selector('#wama-mediapicker-modal', state='hidden', timeout=5000)
        return page.eval_on_selector(f'#{voice}', 's => [s.value, s.options[s.selectedIndex].text]')

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=['--use-fake-ui-for-media-stream',
                                              '--use-fake-device-for-media-stream'])
            try:
                ctx = browser.new_context(viewport={'width': 1500, 'height': 1100},
                                          permissions=['microphone'])
                ctx.add_cookies(_cookie(jeton))
                page = ctx.new_page()
                errors = []
                page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
                resp = page.goto(BASE_URL + url_path, wait_until='networkidle')
                v = _verdict_d_arrivee(page.url, _messages_a_l_ecran(page),
                                       resp.status if resp else None, url_path)
                if v is not None:
                    return v
                if element is not None:
                    gear = f'.settings-btn[data-id="{element.pk}"]'
                    page.locator(gear).first.click(timeout=15000)
                    page.wait_for_selector('.modal.show', timeout=8000)
                    page.wait_for_timeout(1500)
                verdicts.append((page.locator(f'[data-library-pick="{voice}"]').count() == 1,
                                 'bouton médiathèque posé sur le champ voix'))
                if not verdicts[-1][0]:
                    return _bilan(verdicts)
                open_window(page)
                tabs = page.eval_on_selector_all('#mp-tabs [data-mp-tab]', 'els => els.map(e => e.dataset.mpTab)')
                verdicts.append((tabs == ['voice'], f'fenêtre limitée à la nature Voix ({tabs})'))
                verdicts.append((page.is_visible('#mp-add [data-library-record]'),
                                 '« Enregistrer » offert (voix déclarée recordable)'))
                # 1. un FICHIER nommé, dont on DIT la langue (`Attr.on_add`)
                page.fill('#mp-add [data-library-name]', 'wama_probe_named_voice')
                verdicts.append((page.locator('#mp-add [data-attr="language"]').count() == 1,
                                 'la langue de la voix est demandée à l’ajout'))
                page.select_option('#mp-add [data-attr="language"]', 'fr')
                page.set_input_files('#mpFileInput', wav)
                said = confirm_proposal(page)
                verdicts.append(('Écoute' not in said, f'proposition affichée : « {said[:80]} »'))
                page.wait_for_function(choose_ready, timeout=20000)
                value, label = choose(page)
                verdicts.append((value.startswith('ua_') and label.endswith('wama_probe_named_voice'),
                                 f'fichier ajouté puis choisi : {value} « {label} »'))
                # 2. le MICRO
                open_window(page)
                page.fill('#mp-add [data-library-name]', 'wama_probe_recorded_voice')
                page.click('#mp-add [data-library-record-btn]')
                page.wait_for_timeout(2500)
                page.click('#mp-add [data-library-record-btn]')
                confirm_proposal(page)
                page.wait_for_function(choose_ready, timeout=30000)
                value, label = choose(page)
                verdicts.append((value.startswith('ua_') and label.endswith('wama_probe_recorded_voice'),
                                 f'enregistrement ajouté puis choisi : {value}'))
                keep = [x for x in errors if not any(tok in x for tok in IGNORED_CONSOLE)]
                verdicts.append((not keep, f'console : {len(keep)} erreur(s) {keep[:1]}'))
            finally:
                browser.close()
        recorded = UserAsset.objects.filter(user=user, name='wama_probe_recorded_voice').first()
        verdicts.append((recorded is not None and recorded.file.name.endswith('.wav'),
                         f'enregistrement rangé en WAV ({recorded and recorded.file.name})'))
        named = UserAsset.objects.filter(user=user, name='wama_probe_named_voice').first()
        verdicts.append((named is not None and (named.attributes or {}).get('language') == 'fr',
                         f'langue dite à l’ajout enregistrée ({named and named.attributes})'))
    finally:
        for asset in UserAsset.objects.filter(user=user, asset_type='voice').exclude(pk__in=before):
            _retirer(asset)
        if element is not None:
            type(element).objects.filter(pk=element.pk).delete()
    return _bilan(verdicts)


def check_share_consent(nature: str = 'voice'):
    """Partager un asset qui porte une PERSONNE demande le consentement ; le retrait n'en demande
    pas ; les deux sont tracés (`common.ShareConsent`) — 2026-09-30, décision de Fabien. (ok, detail).

    Le geste RÉEL : la modale commune de partage (`WamaShare`) ouverte sur un asset témoin de la
    page médiathèque. Sans case cochée, rien ne doit changer ; cochée, le partage s'applique ;
    revenir au privé se fait sans condition.
    """
    from django.core.files.base import ContentFile
    from playwright.sync_api import sync_playwright
    from wama.common.models import ShareConsent
    from wama.common.services.nightly_tests import SkipScenario, get_test_user
    from wama.media_library.models import UserAsset

    jeton = _test_session_key('media_library')
    if not jeton:
        raise SkipScenario('aucun compte de test disponible')
    asset = UserAsset(user=get_test_user(), name='wama_probe_consent', asset_type=nature)
    asset.file.save('wama_probe_consent.wav', ContentFile(_wav_silence()), save=True)
    trace = ShareConsent.objects.filter(object_type='media_library.UserAsset', object_id=asset.pk)
    modal = '.wama-share-modal'
    verdicts = []

    # Lue DEPUIS LE NAVIGATEUR, par la route du partage (2026-10-07) : une lecture en base pendant
    # que Playwright tourne lève `SynchronousOnlyOperation` — ce geste était rouge chaque nuit
    # (rapports du 05 et du 06/10) pour cette seule raison. Les traces se comptent après.
    state_url = f'/common/api/partage/media_library/element/{asset.pk}/'

    def visibility(page):
        return page.evaluate(
            "(u) => fetch(u, {credentials: 'same-origin'}).then(r => r.json())"
            ".then(d => d.etat.visibility)", state_url)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                ctx = browser.new_context()
                ctx.add_cookies(_cookie(jeton))
                page = ctx.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(BASE_URL + f'/media-library/?tab={nature}', wait_until='networkidle')

                def open_share():
                    page.evaluate("([pk, n]) => WamaShare.ouvrir('media_library', pk, n, 'element')",
                                  [asset.pk, asset.name])
                    page.wait_for_selector(f'{modal}.show', timeout=8000)
                    page.wait_for_timeout(400)

                open_share()
                verdicts.append((page.locator(f'{modal} [data-consent]').is_hidden(),
                                 'consentement caché tant que la portée est « Privé »'))
                page.check(f'{modal} input[name="wama-share-portee"][value="public"]')
                verdicts.append((page.is_visible(f'{modal} [data-consent]'),
                                 'consentement montré pour « Public »'))
                page.click(f'{modal} .wama-share-ok')
                page.wait_for_timeout(800)
                verdicts.append((visibility(page) == 'private',
                                 'sans validation : rien n’est partagé'))
                page.check(f'{modal} [data-consent-check]')
                page.click(f'{modal} .wama-share-ok')
                page.wait_for_selector(modal, state='hidden', timeout=8000)
                verdicts.append((visibility(page) == 'public', 'validé : partagé'))
                page.wait_for_timeout(600)
                open_share()
                page.check(f'{modal} input[name="wama-share-portee"][value="private"]')
                page.click(f'{modal} .wama-share-ok')
                page.wait_for_selector(modal, state='hidden', timeout=8000)
                verdicts.append((visibility(page) == 'private', 'retrait sans condition'))
                verdicts.append((not errors, f'erreurs JS : {errors[:1]}'))
            finally:
                browser.close()
        kinds = ['retrait' if not t.statement else 'consentement'
                 for t in trace.order_by('created_at')]
        verdicts.append((kinds == ['consentement', 'retrait'],
                         f'tracés : le consentement validé puis le retrait ({kinds})'))
    finally:
        trace.delete()
        _retirer(asset)
    return _bilan(verdicts)


def check_library_filter_bar():
    """La BARRE COMMUNE de la médiathèque (2026-10-01, demande de Fabien) : recherche, origine,
    filtres d'attributs de l'onglet, tri — en mode `remote`, la page recharge sa grille. (ok, detail)

    Joué sur les voix SYSTÈME (présentes sur toute installation) : rien n'est créé.
    """
    from playwright.sync_api import sync_playwright
    from wama.common.services.nightly_tests import SkipScenario
    from wama.media_library.models import SystemAsset

    session_token = _test_session_key('media_library')
    if not session_token:
        raise SkipScenario('aucun compte de test disponible')
    if SystemAsset.objects.filter(is_active=True, asset_type='voice').count() < 2:
        raise SkipScenario('moins de deux voix système : rien à filtrer ni à trier')
    host = '#mlFilterBar'
    names_js = "els => els.map(e => e.textContent.trim())"
    verdicts = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(viewport={'width': 1500, 'height': 1000})
            ctx.add_cookies(_cookie(session_token))
            page = ctx.new_page()
            errors, asked = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: asked.append(r.url)
                    if '/media-library/api/' in r.url and r.method == 'GET' else None)
            page.goto(BASE_URL + '/media-library/?tab=voice', wait_until='networkidle')
            verdicts.append((page.locator(f'{host} [data-wama-filter-bar][data-mode="remote"]').count() == 1,
                             'barre commune montée (mode remote)'))
            verdicts.append((page.locator(f'{host} [data-f-nature="voice"]:visible').count() >= 1,
                             'filtres d’attributs de la voix montrés sur son onglet'))

            asked.clear()
            page.select_option(f'{host} select[data-f-facette="origin"]', 'system')
            page.wait_for_timeout(1500)
            total = page.locator('#assetGrid .asset-card').count()
            system = page.locator('#assetGrid .asset-card.system-asset').count()
            verdicts.append((any('origin=system' in u for u in asked) and total and total == system,
                             f'« Origine : Système » : {system}/{total} cards système'))

            asked.clear()
            page.select_option(f'{host} select[data-f-role="sort"]', 'name')
            page.wait_for_timeout(1500)
            names = page.eval_on_selector_all('#assetGrid .asset-card .asset-name', names_js)
            verdicts.append((any('sort=name' in u for u in asked) and len(names) >= 2
                             and names[0].casefold() <= names[-1].casefold(),
                             f'tri par nom transmis ({names[:1]} … {names[-1:]})'))
            verdicts.append((bool(page.inner_text(f'{host} .wama-filter-count').strip()),
                             'compteur rempli par la page'))

            wanted = names[0] if names else ''
            page.fill(f'{host} [data-f-role="recherche"]', wanted)
            page.wait_for_timeout(1800)
            found = page.eval_on_selector_all('#assetGrid .asset-card .asset-name', names_js)
            verdicts.append((bool(found) and wanted in found,
                             f'recherche « {wanted} » : {len(found)} résultat(s)'))

            page.click('#assetTypeTabs .nav-link[data-type="avatar"]')
            page.wait_for_timeout(1500)
            verdicts.append((page.locator(f'{host} [data-f-nature="voice"]:visible').count() == 0,
                             'onglet Avatars : les filtres de la voix disparaissent'))
            verdicts.append((not errors, f'erreurs JS : {errors[:1]}'))
        finally:
            browser.close()
    return _bilan(verdicts)


def register_voice_library_scenarios():
    """Les apps qui DÉCLARENT un champ de voix ; le geste est commun (le bouton aussi)."""
    from wama.common.services.nightly_tests import register
    for app, ids in (('synthesizer', {'voice': 'voice_preset'}),
                     ('avatarizer', {'voice': 'settingsVoicePreset',
                                     'open_item': _avatarizer_pipeline_item})):
        register(id=f'{app}.voice_library_pick', app=app, stage='ui',
                 description=f'{app} : le champ voix ouvre la médiathèque — ajouter (fichier, '
                             'micro) puis choisir, sans quitter l’app',
                 run=lambda ctx, a=app, i=ids: check_voice_library_pick(a, f'/{a}/', i),
                 timeout_s=240)
    register(id='media_library.share_consent', app='media_library', stage='ui',
             description='partager une voix demande le consentement ; le retrait non ; tout est tracé',
             run=lambda ctx: check_share_consent('voice'), timeout_s=180)
    register(id='media_library.filter_bar', app='media_library', stage='ui',
             description='la barre commune de la médiathèque : origine, filtres de l’onglet, tri, '
                         'recherche, compteur — la grille se recharge',
             run=lambda ctx: check_library_filter_bar(), timeout_s=180)


# ═══════════════════════════════════════════════════════════════════════════════════════
# MÉDIATHÈQUE : les natures DÉRIVENT (A′) et un objet 3D se REND (§17ter trou 2)
# ═══════════════════════════════════════════════════════════════════════════════════════

def _glb_temoin(animated: bool = True) -> bytes:
    """Un GLB minimal et VALIDE (cube unitaire, 8 sommets, 12 triangles) — fabriqué octet par
    octet, aucune dépendance. Sert au nocturne ET aux tests (`media_library/tests_object3d`)."""
    import json
    import struct
    verts = [(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
    idx = [0, 1, 3, 0, 3, 2, 4, 6, 7, 4, 7, 5, 0, 4, 5, 0, 5, 1,
           2, 3, 7, 2, 7, 6, 0, 2, 6, 0, 6, 4, 1, 5, 7, 1, 7, 3]
    vbuf = b''.join(struct.pack('<fff', *v) for v in verts)
    ibuf = b''.join(struct.pack('<H', i) for i in idx)
    ibuf += b'\0' * (-len(ibuf) % 4)
    bin_chunk = vbuf + ibuf
    doc = {
        'asset': {'version': '2.0', 'generator': 'wama-temoin'},
        'buffers': [{'byteLength': len(bin_chunk)}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(vbuf)},
                        {'buffer': 0, 'byteOffset': len(vbuf), 'byteLength': len(idx) * 2}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 8, 'type': 'VEC3',
                       'min': [0, 0, 0], 'max': [1, 1, 1]},
                      {'bufferView': 1, 'componentType': 5123, 'count': len(idx), 'type': 'SCALAR'}],
        'meshes': [{'name': 'cube', 'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
        'nodes': [{'mesh': 0, 'name': 'cube'}],
        'scenes': [{'nodes': [0]}], 'scene': 0,
    }
    if animated:
        doc['animations'] = [{'name': 'tourne', 'channels': [], 'samplers': []}]
        doc['skins'] = [{'joints': [0]}]
    jbytes = json.dumps(doc, separators=(',', ':')).encode('utf-8')
    jbytes += b' ' * (-len(jbytes) % 4)
    total = 12 + 8 + len(jbytes) + 8 + len(bin_chunk)
    return (struct.pack('<4sII', b'glTF', 2, total)
            + struct.pack('<I4s', len(jbytes), b'JSON') + jbytes
            + struct.pack('<I4s', len(bin_chunk), b'BIN\0') + bin_chunk)


def check_media_library_natures_3d(url_path: str = '/media-library/'):
    """La page médiathèque SERVIE dérive ses tables de `NATURES` (A′) et rend un GLB. (ok, detail).

    Un cube GLB est semé chez le compte de test (attributs LUS du fichier par la sonde), l'onglet
    « Objet 3D » le montre (icône dérivée), l'aperçu monte un <canvas> WebGL par la visionneuse
    commune, et le canvas est retiré à la fermeture. 0 erreur console — et un 404 se NOMME.
    """
    from playwright.sync_api import sync_playwright
    from django.core.files.base import ContentFile
    from wama.common.services.nightly_tests import SkipScenario, get_test_user
    from wama.media_library.models import UserAsset
    from wama.media_library.services import enrich_asset_from_file

    jeton = _test_session_key('media_library')
    if not jeton:
        raise SkipScenario('aucun compte de test disponible')
    user = get_test_user()
    for vieux in UserAsset.objects.filter(user=user, name='wama_temoin_cube_3d'):
        _retirer(vieux)
    a = UserAsset(user=user, name='wama_temoin_cube_3d', asset_type='object3d')
    a.file.save('wama_temoin_cube_3d.glb', ContentFile(_glb_temoin()), save=False)
    enrich_asset_from_file(a)
    a.save()
    verdicts = [(a.attributes.get('polygons') == 12 and a.attributes.get('rigged') is True,
                 f'sonde : attributs lus du fichier {a.attributes}')]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'])
            try:
                ctx = browser.new_context(viewport={'width': 1400, 'height': 1000})
                ctx.add_cookies(_cookie(jeton))
                page = ctx.new_page()
                erreurs = []
                page.on('console', lambda m: erreurs.append(m.text) if m.type == 'error' else None)
                page.on('response', lambda r: erreurs.append(f'404 {r.url}') if r.status == 404 else None)
                resp = page.goto(BASE_URL + url_path + '?tab=object3d', wait_until='networkidle')
                v = _verdict_d_arrivee(page.url, _messages_a_l_ecran(page),
                                       resp.status if resp else None, url_path)
                if v is not None:
                    return v
                page.wait_for_timeout(1500)
                natures = page.evaluate("() => (typeof NATURES === 'object') ? Object.keys(NATURES) : null")
                verdicts.append((bool(natures) and 'object3d' in natures and 'voice' in natures,
                                 f'NATURES servie : {natures}'))
                verdicts.append((page.evaluate("() => { const im = document.querySelector('script[type=\"importmap\"]');"
                                               " return !!im && im.textContent.includes('wama/3d-viewer'); }"),
                                 'importmap three déclarant la visionneuse'))
                card = page.query_selector(f'.asset-card[data-id="{a.pk}"]')
                verdicts.append((card is not None, 'card du cube dans l’onglet Objet 3D'))
                if card:
                    verdicts.append((card.query_selector('.fa-cube') is not None, 'icône dérivée de NATURES'))
                    card.hover()
                    card.query_selector('.preview-btn').click()
                    page.wait_for_selector('#wamaMediaPreviewModal.show', timeout=8000)
                    try:
                        page.wait_for_selector('#wamaMediaPreviewModal [data-wama-3d] canvas', timeout=15000)
                        monte = True
                    except Exception:
                        monte = False
                    statut = page.evaluate("() => { const s = document.querySelector('#wamaMediaPreviewModal [data-wama-3d]');"
                                           " return s ? s.textContent.trim().slice(0, 100) : ''; }")
                    verdicts.append((monte, f'canvas WebGL monté (statut « {statut} »)'))
                    page.click('#wamaMediaPreviewModal .btn-close')
                    page.wait_for_timeout(900)
                    verdicts.append((page.evaluate("() => !document.querySelector('#wamaMediaPreviewModal [data-wama-3d] canvas')"),
                                     'canvas retiré à la fermeture'))
                keep = [x for x in erreurs if not any(tok in x for tok in IGNORED_CONSOLE)]
                verdicts.append((not keep, f'console : {len(keep)} erreur(s) {keep[:1]}'))
            finally:
                browser.close()
    finally:
        _retirer(a)
    return _bilan(verdicts, 'constats')


def register_media_library_scenarios():
    from wama.common.services.nightly_tests import register
    register(id='media_library.natures_3d', app='media_library', stage='ui',
             description='Médiathèque : les natures DÉRIVENT (A′) et un objet 3D se rend '
                         '(sonde glTF, visionneuse three, canvas libéré)',
             run=lambda ctx: check_media_library_natures_3d(), timeout_s=180)

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
                clonees = [o['v'] for o in page.evaluate(_JS_OPTIONS, V) if o['v'].startswith(('ua_', 'cv_'))]
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
    return _bilan(verdicts)


def register_voice_language_scenarios():
    """Les deux apps TTS déclarent leurs ids ; le geste est commun."""
    from wama.common.services.nightly_tests import register
    for app, ids in (('synthesizer', {'model': 'tts_model', 'voice': 'voice_preset', 'language': 'language'}),
                     ('avatarizer', {'model': 'settingsTtsModel', 'voice': 'settingsVoicePreset',
                                     'language': 'settingsLanguage'})):
        register(id=f'{app}.voice_language_matching', app=app, stage='ui',
                 description=f'{app} : voix ↔ langue ↔ moteur à DOUBLE SENS dans le navigateur '
                             '(grisé avec raison, jamais caché ; « auto » jamais grisé)',
                 run=lambda ctx, a=app, i=ids: check_voice_language_matching(a, f'/{a}/', i),
                 timeout_s=240)


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

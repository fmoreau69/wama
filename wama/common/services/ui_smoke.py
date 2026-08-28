"""
Smoke UI nocturne : charge chaque page d'app dans un vrai navigateur et vérifie qu'elle vit.

POURQUOI. Une erreur JS casse SILENCIEUSEMENT une page entière : le navigateur arrête le script,
et il n'y a RIEN dans les logs serveur. `scripts/check_js.sh` (node --check) n'attrape que la
syntaxe — pas un `MediaPicker has already been declared` ni un `X is not defined` au chargement.
La première exécution manuelle de cette passe (2026-07-30) a trouvé une double inclusion de
brique globale sur deux apps, sur des pages utilisées quotidiennement sans que personne ne voie
rien. C'est le mode de panne le plus coûteux du projet.

TROIS COUCHES, ET UNE SEULE DÉCIDE.
1. **Barrière déterministe** (elle seule fait échouer) : HTTP 200, **zéro erreur console**,
   présence d'un sélecteur clé. Reproductible, échoue toujours pareil, coût nul.
2. **Diff de capture** contre une référence : dit OÙ ça a bougé. Ne fait PAS échouer — une file
   d'attente, une barre de ressources ou une date changent d'une nuit à l'autre, en faire un
   critère produirait du bruit qu'on apprendrait à ignorer.
3. **Triage par modèle vision local** : dit QUOI, en français, et UNIQUEMENT sur les captures qui
   ont bougé. Il n'est pas juge — un VLM affirme volontiers qu'une page cassée « semble
   correcte », et sa réponse varie d'une nuit à l'autre. Il te fait lire trois phrases au lieu
   d'ouvrir dix captures. Même précaution que le banc de modèles (`bench`) : le juge final reste humain.

Sous WSL2, où vivent le serveur ET les navigateurs Playwright (`~/.cache/ms-playwright`).

⚠ CRON : exporter `OLLAMA_HOST` (Ollama tourne sur l'hôte WINDOWS ; `127.0.0.1` depuis WSL2 ne
l'atteint pas). Sans lui, les couches 1 et 2 fonctionnent mais le triage échoue silencieusement
en « triage VLM indisponible » — piège rencontré deux fois pendant la mise au point.

CALIBRATION (2026-07-31) : deux passages consécutifs avec des références fraîches donnent
0 déclenchement sur 13 — le diff est stable, donc le VLM ne coûte rien les nuits sans
changement. Si un changement d'UI est VOULU, supprimer les références concernées : elles se
recréent au passage suivant (sinon le triage se déclenche chaque nuit et le signal se dilue).
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings

BASE_URL = os.environ.get('WAMA_UI_SMOKE_BASE', 'http://127.0.0.1:8000')
SHOTS_DIR = Path(settings.BASE_DIR) / 'logs' / 'ui_smoke'
REF_DIR = SHOTS_DIR / 'reference'
CUR_DIR = SHOTS_DIR / 'current'

# Au-delà de ce ratio de pixels changés, la capture part au triage VLM (elle ne casse rien).
DIFF_TRIAGE_RATIO = 0.02
# Modèle vision : env = épingle déclarée ; vide → résolu par la route commune DANS
# describe_image_ollama (tier default + vision, point unique — audit 19/08, plus de littéral
# qui pourrit). Résidence courte → les scénarios UI s'enchaînent sans repayer le chargement,
# et le modèle expire tout seul après la série.
VLM_MODEL = os.environ.get('WAMA_UI_SMOKE_VLM', '')
VLM_KEEP_ALIVE = '120s'

# Erreurs console à ignorer : bruit d'environnement, pas des régressions applicatives.
IGNORED_CONSOLE = (
    'favicon',                    # 404 d'icône, sans effet fonctionnel
    'ERR_INTERNET_DISCONNECTED',  # poste hors ligne (assets locaux, cf. règle « pas de CDN »)
)


def _session_keys():
    """Clés de session existantes — photo prise AVANT le passage."""
    try:
        from django.contrib.sessions.models import Session
        return set(Session.objects.values_list('session_key', flat=True))
    except Exception:
        return set()


def _drop_new_sessions(before: set):
    """
    Supprime les sessions créées PAR ce passage, sans jamais toucher celle d'un utilisateur.

    Une page en crée PLUSIEURS (chaque requête sans cookie en ouvre une) : viser la seule clé du
    cookie du navigateur ne nettoyait presque rien (mesuré : +8 lignes malgré la suppression).
    On supprime donc toutes les clés APPARUES pendant le passage — mais **uniquement les
    anonymes** : une session portant `_auth_user_id` appartient à quelqu'un de connecté, et la
    supprimer déconnecterait un utilisateur réel qui travaillerait pendant le passage. Un test ne
    doit jamais causer ça.
    """
    try:
        from django.contrib.sessions.models import Session
        new = Session.objects.exclude(session_key__in=before)
        doomed = [s.session_key for s in new if not s.get_decoded().get('_auth_user_id')]
        return Session.objects.filter(session_key__in=doomed).delete()[0] if doomed else 0
    except Exception:
        return 0


def _exercise_page(url, png_path, selector=None, timeout_ms=45000):
    """
    Charge `url`, PARCOURT LES ONGLETS, écrit la capture.

    Pourquoi interagir : charger une page ne teste que le rendu initial, or la majorité des
    erreurs JS vivent dans les GESTIONNAIRES d'événements — elles n'apparaissent qu'au clic.
    Les onglets sont le seul geste réellement commun (mesuré : présents sur 10 des 13 apps).

    Retourne (status, erreurs_js, sélecteur_trouvé, nb_onglets_parcourus, session_supprimée).
    """
    from playwright.sync_api import sync_playwright

    errors, status, found, tabs_done = [], None, None, 0
    png_path.parent.mkdir(parents=True, exist_ok=True)
    sessions_before = _session_keys()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1500, 'height': 1000})
            page.on('console', lambda m: errors.append(f"console.{m.type}: {m.text}")
                    if m.type == 'error' else None)
            page.on('pageerror', lambda e: errors.append(f"pageerror: {e}"))
            resp = page.goto(url, wait_until='networkidle', timeout=timeout_ms)
            status = resp.status if resp else None
            if selector:
                found = page.locator(selector).count() > 0

            # Onglets : le seul geste réellement commun aux apps. Deux précautions, toutes deux
            # apprises en mesurant (2026-07-31) :
            #  - beaucoup d'onglets sont MASQUÉS au repos (describer : 4 visibles sur 7) — cliquer
            #    un élément invisible n'est pas un geste utilisateur ;
            #  - nos propres clics MUTENT le DOM (changer de mode masque les onglets suivants :
            #    l'imager a 6 onglets visibles au chargement, plus autant après le 4e clic).
            # D'où : on revérifie la visibilité juste avant chaque clic, et un échec n'est une
            # ERREUR que si l'onglet est TOUJOURS visible après coup — sinon c'est notre propre
            # navigation qui l'a escamoté. Une barrière qui crie au loup ne serait pas relue.
            tabs = page.locator('[data-bs-toggle="tab"]')
            for i in range(min(tabs.count(), 8)):          # borne : pas de page à 30 onglets
                tab = tabs.nth(i)
                try:
                    if not tab.is_visible():
                        continue
                    tab.click(timeout=4000)
                    page.wait_for_timeout(250)             # laisse le gestionnaire s'exécuter
                    tabs_done += 1
                except Exception as e:
                    still_there = False
                    try:
                        still_there = tab.is_visible()
                    except Exception:
                        pass
                    if still_there:
                        errors.append(f"onglet {i} visible mais non cliquable: {type(e).__name__}")
            if tabs_done:
                page.wait_for_timeout(400)                 # laisse remonter une erreur tardive

            page.screenshot(path=str(png_path), full_page=False)
        finally:
            browser.close()
    dropped = _drop_new_sessions(sessions_before)
    keep = [e for e in errors if not any(tok in e for tok in IGNORED_CONSOLE)]
    return status, keep, found, tabs_done, dropped


def _diff_ratio(current: Path, reference: Path):
    """Part de pixels différents entre deux captures. None si pas comparable."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return None
    if not reference.exists():
        return None
    try:
        a = Image.open(current).convert('RGB')
        b = Image.open(reference).convert('RGB')
        if a.size != b.size:
            return 1.0                       # changement de gabarit = à regarder
        diff = ImageChops.difference(a, b).convert('L')
        changed = sum(1 for px in diff.getdata() if px > 24)
        return changed / float(a.size[0] * a.size[1])
    except Exception:
        return None


def _vlm_triage(png_path: Path, app: str):
    """Description en français de ce que MONTRE la capture. Jamais un verdict."""
    from wama.model_manager.services.vision_probe import describe_image_ollama

    res = describe_image_ollama(
        str(png_path), model=VLM_MODEL, timeout=180, keep_alive=VLM_KEEP_ALIVE,
        prompt=(f"Cette capture est la page de l'application « {app} » d'une plateforme web. "
                "Signale UNIQUEMENT ce qui semble cassé : zone vide qui devrait être remplie, "
                "texte qui déborde ou tronqué, éléments superposés, message d'erreur visible. "
                "Si rien ne cloche, réponds exactement « RAS ». Trois phrases maximum."))
    if not res.get('ok'):
        return f"triage VLM indisponible ({res.get('error')})"
    return (res.get('description') or '').strip()


def check_app_page(app: str, url_path: str, selector: str | None = None):
    """
    Scénario UI d'une app. Retourne (ok, detail) — contrat `Scenario.run`.

    Seule la couche 1 décide du succès. Les couches 2 et 3 enrichissent `detail`.
    """
    from wama.common.services.nightly_tests import SkipScenario

    url = f"{BASE_URL.rstrip('/')}{url_path}"
    try:
        status, errors, found, tabs, dropped = _exercise_page(
            url, CUR_DIR / f"{app}.png", selector)
    except Exception as e:
        # Serveur éteint ou navigateur absent = dépendance manquante, pas une régression.
        raise SkipScenario(f"page injoignable ({type(e).__name__}: {str(e)[:120]})")

    # ── Couche 1 : la barrière ────────────────────────────────────────────────
    problems = []
    if status != 200:
        problems.append(f"HTTP {status}")
    if errors:
        problems.append(f"{len(errors)} erreur(s) JS : " + " | ".join(errors[:3]))
    if selector and not found:
        problems.append(f"sélecteur absent : {selector}")

    # ── Couches 2 et 3 : où, puis quoi ────────────────────────────────────────
    extra = ""
    cur, ref = CUR_DIR / f"{app}.png", REF_DIR / f"{app}.png"
    ratio = _diff_ratio(cur, ref)
    if ratio is None and not ref.exists():
        REF_DIR.mkdir(parents=True, exist_ok=True)
        try:
            ref.write_bytes(cur.read_bytes())
            extra = " ; référence de capture créée"
        except OSError:
            pass
    elif ratio is not None and ratio > DIFF_TRIAGE_RATIO:
        extra = f" ; capture modifiée à {ratio:.1%} → {_vlm_triage(cur, app)}"

    gestes = f"{tabs} onglet(s) parcouru(s)" if tabs else "aucun onglet"
    trace = f" ; {dropped} session(s) nettoyée(s)" if dropped else ""
    if problems:
        return False, "; ".join(problems) + f" [{gestes}]" + extra + trace
    return True, f"page OK (HTTP 200, 0 erreur JS, {gestes}){extra}{trace}"


def discoverable_apps():
    """
    Apps exposant une page d'index, DÉDUITES des URLs — aucune liste en dur à maintenir.
    Retourne [(label, chemin)].
    """
    from django.apps import apps as django_apps
    from django.urls import NoReverseMatch, reverse

    out = []
    for cfg in django_apps.get_app_configs():
        if not (cfg.name or '').startswith('wama.'):
            continue
        try:
            out.append((cfg.label, reverse(f"{cfg.label}:index")))
        except NoReverseMatch:
            continue
    return sorted(out)


def register_ui_scenarios():
    """Enregistre un scénario `<app>.ui` par app disposant d'une page d'index."""
    from wama.common.services.nightly_tests import register

    for label, path in discoverable_apps():
        register(
            id=f"{label}.ui", app=label, stage="ui",
            description=f"Page {label} : HTTP 200, zéro erreur console JS",
            # Sélecteur MESURÉ sur les 13 pages (2026-07-31), pas supposé : `#appTabsContent`
            # vient du gabarit commun (10 apps) ; media_library, model_manager et studio ont
            # leur propre gabarit et n'ont que `.container-fluid`. La liste CSS couvre les deux
            # familles et atteste que la page a bien rendu sa coquille de contenu.
            run=(lambda p=path, a=label: (
                lambda ctx: check_app_page(a, p, selector='#appTabsContent, .container-fluid')
            ))(),
            timeout_s=120, vram_gb=0.0,
        )


# ── Scénario d'IMPORT : la page est saine, mais fait-elle quelque chose ? ───────────────
#
# POURQUOI IL A FALLU L'ÉCRIRE. `<app>.ui` mesure la SANTÉ de la page : HTTP 200, zéro
# erreur console. converter_01 satisfaisait les deux tout en étant totalement INERTE — son
# gabarit généré n'émettait aucun script, donc aucun écouteur n'était posé et aucune voie
# d'import n'émettait la moindre requête. Rien ne plante quand rien n'est chargé : le
# scénario passait au vert sur une app incapable de créer une seule card (mesuré 2026-08-22).
# La santé ne dit rien du COMPORTEMENT ; il fallait un scénario qui exerce un geste et
# vérifie qu'il PRODUIT quelque chose.

def _wav_silence(secondes: float = 0.2, taux: int = 8000) -> bytes:
    """Un WAV PCM VALIDE (mono 16 bits, silence), écrit sans aucune dépendance.

    ⚠ Pourquoi ça compte. Le témoin `.wav` était `b'temoin import WAMA\\n'` — 19 octets de
    TEXTE portant une extension audio. Les apps qui lisent l'en-tête (durée, canaux) le
    rejettent, donc le montage ne créait aucun élément et les scénarios de LOT concluaient
    « l'app ne groupe pas » sur des apps AUDIO qui groupent très bien. Un instrument qui
    dépose un faux fichier ne mesure pas l'app, il mesure son propre témoin.
    """
    import struct
    n = int(taux * secondes)
    donnees = b'\x00\x00' * n                       # silence 16 bits mono
    return (b'RIFF' + struct.pack('<I', 36 + len(donnees)) + b'WAVE'
            + b'fmt ' + struct.pack('<IHHIIHH', 16, 1, 1, taux, taux * 2, 2, 16)
            + b'data' + struct.pack('<I', len(donnees)) + donnees)


def _fichier_temoin(extensions: str) -> Path:
    """Un fichier minuscule d'une extension que l'app ACCEPTE (déduite de sa zone de dépôt)."""
    import tempfile
    bruts = [e.strip() for e in (extensions or '').split(',') if e.strip()]
    # Les familles MIME (`image/*`, `audio/*`) n'ont pas d'extension : les traduire, sinon on
    # retombait sur `.txt` — et un .txt déposé sur l'imager part vers l'APERÇU DE LOT (c'est un
    # fichier de prompts), donc aucun élément n'était créé et le test criait au loup.
    FAMILLES = {'image/*': '.png', 'audio/*': '.wav', 'video/*': '.mp4'}
    ext = next((FAMILLES[b] for b in bruts if b in FAMILLES),
               next((b.lstrip('*') for b in bruts if b.startswith('.')), '.txt'))
    # PNG 1×1 : la seule donnée binaire qu'on peut écrire sans dépendance.
    png = bytes.fromhex('89504e470d0a1a0a0000000d494844520000000100000001080600000'
                        '01f15c4890000000a49444154789c6360000002000100' '05fe02fea7'
                        'dc9a730000000049454e44ae426082'.replace(' ', ''))
    if ext in ('.png', '.jpg', '.jpeg', '.webp'):
        contenu = png
    elif ext in ('.wav',):
        contenu = _wav_silence()
    else:
        contenu = b'temoin import WAMA\n'
    f = tempfile.NamedTemporaryFile('wb', suffix=ext, delete=False)
    f.write(contenu); f.close()
    return Path(f.name)


def _deplier_autour(page, selecteur: str) -> bool:
    """Déplie le `.collapse` qui CONTIENT `selecteur`, par le vrai geste. Rend True si déplié.

    Un élément dans un repli a des dimensions NULLES : Playwright le voit invisible et attend
    30 s avant d'abandonner — abandon que le scénario lisait comme « navigateur indisponible »,
    un skip qui accusait l'environnement alors que la page allait très bien (2026-08-23).
    On passe par le TOGGLE de la card (contrat commun `[data-bs-toggle=collapse]
    [data-bs-target=#…]`), jamais par un `style.display` forcé : fabriquer un état que
    l'utilisateur ne peut pas atteindre lui-même ferait mesurer autre chose que son geste.

    Deux replis distincts au dépôt : le lot en file (`_batch_card.html`) et la CARD D'ENTRÉE
    elle-même (`_new_item_card.html collapsible=True` sans `deployed`) — 6 apps sur 9 la
    servent repliée, et sa barre de lot y est donc invisible tant qu'on ne l'ouvre pas.
    """
    replie = page.evaluate(
        "(sel) => {const e = document.querySelector(sel);"
        " const col = e && e.closest('.collapse');"
        " return col && !col.classList.contains('show') ? col.id : null;}", selecteur)
    if not replie:
        return False
    # DEUX bascules au dépôt, parce que les deux replis n'ont pas la même origine : le lot en
    # file est du Bootstrap (`data-bs-target`), la card d'entrée porte son propre JS depuis
    # 2026-08-03 (`data-nic-toggle`, `_new_item_card.html:70`) — describer et avatarizer
    # passaient `collapsible=True` sans que rien ne déplie. Chercher la seconde APRÈS la
    # première, et seulement dans la card qui contient le repli.
    bascule = (page.query_selector(f'[data-bs-toggle="collapse"][data-bs-target="#{replie}"]')
               or page.query_selector(f'[data-wama-nic]:has(#{replie}) [data-nic-toggle]'))
    if not bascule:
        return False
    bascule.click()
    try:
        page.wait_for_selector(f'#{replie}.show', timeout=5000)   # l'ouverture est ANIMÉE :
    except Exception:                                             # attendre l'ÉTAT, pas une durée
        pass
    page.wait_for_timeout(400)   # fin de transition Bootstrap
    return True


def _session_compte_de_test():
    """Clé de session d'un compte de TEST existant, ou None.

    On ne crée aucun compte : le dépôt en a déjà (`wama_nightly_test`, `ui_smoke_v3`), avec
    leurs rôles. En forger un ici inventerait des droits et masquerait justement ce que le
    scénario doit voir.
    """
    from importlib import import_module
    from django.contrib.auth import get_user_model
    for nom in ('wama_nightly_test', 'ui_smoke_v3', 'pw_smoke'):
        u = get_user_model().objects.filter(username=nom, is_active=True).first()
        if not u:
            continue
        SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
        s = SessionStore()
        s['_auth_user_id'] = str(u.pk)
        s['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
        s['_auth_user_hash'] = u.get_session_auth_hash()
        s.create()
        return s.session_key
    return None


def check_app_import(app: str, url_path: str):
    """L'app sait-elle CRÉER un élément depuis sa card d'entrée ? (ok, detail).

    Trois constats, du plus structurel au plus concret — le premier qui manque explique les
    suivants, d'où l'ordre :
      1. la voie d'import est-elle CÂBLÉE (WamaImport instancié) ?
      2. la zone de dépôt et le champ de fichier existent-ils ?
      3. déposer un fichier émet-il une requête, et un élément apparaît-il ?

    Ne démarre AUCUN traitement : on dépose, on observe, on nettoie.
    """
    from wama.common.services.nightly_tests import SkipScenario
    from playwright.sync_api import sync_playwright

    _nettoyes = []
    url = f"{BASE_URL.rstrip('/')}{url_path}"
    ETAT = """(() => {
        const dz = document.querySelector('[id$="DropZone"], [data-wama-nic] .dropzone, .dropzone');
        // Le champ d'IMPORT, pas le premier venu : une page porte souvent plusieurs
        // input[type=file] (image de référence, avatar, voix de clonage…). On vise d'abord
        // celui de la card d'entrée, puis la convention de nommage, puis le premier.
        // Le champ d'import est celui de la CARD D'ENTRÉE commune, identifié par le marqueur
        // de la brique (`data-wama-nic`) et par sa zone de dépôt. Hors de là, on ne devine pas :
        // une page porte jusqu'à 6 input[type=file] (image de référence, voix de clonage,
        // fichier de lot…), et en viser un au hasard produit un faux échec — mesuré le 22/08
        // sur composer (batchFileInput), imager (imgFileInput) et avatarizer (audio_input).
        // On s en tient au CONTRAT DE NOMMAGE de la brique commune (`_new_item_card.html`
        // reçoit `file_input_id` et la convention est `<app>FileInput`). Toute autre
        // heuristique vise à côté : ces pages portent jusqu'à 6 input[type=file], dont des
        // champs de RÉFÉRENCE (mélodie, avatar, image de style) qui ne créent aucun élément
        // — mesuré le 22/08 sur composer (melodyInput), imager (imgFileInput), avatarizer
        // (audio_input). Pas de champ au contrat = app sans import par fichier -> non applicable.
        // Ordre de visée, du plus sûr au plus large — chaque cran a été mesuré le 22/08 :
        //  1. DANS la zone de dépôt : c'est le champ de l'import, par construction ;
        //  2. le contrat de nommage de la brique (`<app>FileInput`) ;
        //  3. dans la card d'entrée, hors champs de LOT et de RÉFÉRENCE.
        // Sans le cran 1, on visait melodyInput (composer), imgFileInput (imager) ou
        // audio_input (avatarizer) — des champs de référence qui ne créent aucun élément,
        // d'où trois faux échecs. Avec le seul cran 2, on rejetait 5 apps qui importent très
        // bien mais nomment leur champ autrement (transcriber-file…).
        const carte = document.querySelector('[data-wama-nic]');
        const exclus = '[id*="atch"], [id*="elody"], [id*="eference"], [id*="voice"], [id*="avatar"]';
        const tous = [...document.querySelectorAll(`input[type=file]:not(${exclus})`)];
        const fi = (dz && dz.querySelector(`input[type=file]:not(${exclus})`))
                || document.querySelector(`[id$="FileInput"]:not(${exclus})`)
                || (carte && carte.querySelector(`input[type=file]:not(${exclus})`))
                // Dernier cran : UN SEUL champ candidat dans la page = aucune ambiguïté.
                // S'il y en a plusieurs et qu'aucun marqueur ne les départage, on ne devine
                // PAS — un test qui vise au hasard produit des faux échecs, et un faux échec
                // répété apprend à ignorer la barrière.
                || (tous.length === 1 ? tous[0] : null);
        // Ce que FAIT un dépôt sur cette card — DÉCLARÉ par l'app, pas deviné
        // (`common/_new_item_card.html`, data-wama-depot). 'attache' = le fichier se
        // joint au formulaire et c'est le bouton primaire qui crée l'élément.
        const carteDepot = (dz && dz.closest('[data-wama-depot]')) || carte
                || document.querySelector('[data-wama-depot]');
        return {cable: !!window._import || typeof window.WamaImport === 'function',
                instancie: !!window._import,
                depot: (carteDepot && carteDepot.getAttribute('data-wama-depot')) || 'cree',
                dropzone: !!dz, champ: !!fi,
                accept: fi ? (fi.getAttribute('accept') || '') : '',
                champ_id: fi ? (fi.id || '(sans id)') : '',
                champs_total: document.querySelectorAll('input[type=file]').length,
                cards: document.querySelectorAll('.wama-card').length};
    })()"""

    # NETTOYAGE : un test qui laisse des traces ne peut pas tourner toutes les nuits. Le modèle
    # d'item de l'app est déjà connu du PreviewRegistry — on n'invente pas de table de
    # correspondance, on lit celle qui existe. Sans lui, on ne supprime rien (et on le dit).
    modele = None
    try:
        from wama.common.utils.preview_registry import PreviewRegistry
        modele = PreviewRegistry.get_model(app)
    except Exception:
        modele = None
    ids_avant = set()
    if modele is not None:
        try:
            ids_avant = set(modele.objects.values_list('id', flat=True))
        except Exception:
            modele = None

    temoin = None
    sessions_before = _session_keys()
    # ⚠ Toute lecture ORM doit se faire AVANT `sync_playwright()` : à l'intérieur, Django
    # refuse l'accès synchrone (SynchronousOnlyOperation). Le jeton est donc préparé ici.
    jeton = _session_compte_de_test()
    if not jeton:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / ui_smoke_v3) "
                           "— les droits ne sont pas simulables, on ne mesure pas à l'aveugle")
    try:
        with sync_playwright() as p:
            navigateur = p.chromium.launch()
            try:
                contexte = navigateur.new_context(viewport={'width': 1500, 'height': 1000})
                # CONNECTÉ, et pas en visiteur : l'accès aux apps dépend des rôles (axe B) et
                # du tier (axe A). En anonyme, converter renvoie 302 sur son upload — un échec
                # de DROITS qu'on lirait à tort comme un défaut d'import. Le compte de test
                # nocturne porte les rôles usuels ; s'il manque, on SKIPPE plutôt que de
                # mesurer des droits en croyant mesurer un comportement.
                contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': jeton,
                                       'domain': '127.0.0.1', 'path': '/'}])
                page = contexte.new_page()
                posts = []
                # Le CORPS des réponses en échec est capturé (2026-08-22). Sans lui, le
                # scénario disait « 400 sur /anonymizer/upload/ » sans jamais dire POURQUOI :
                # on soupçonnait la route (« alias de l'IndexView »), alors qu'elle traite bien
                # les uploads en POST — c'est la VALIDATION du fichier témoin qui refusait.
                # Un échec qui n'explique pas coûte une enquête à chaque lecture.
                def _voir(r):
                    if r.request.method != 'POST':
                        return
                    corps = ''
                    if r.status >= 400:
                        try:
                            corps = (r.text() or '')[:200].replace('\\n', ' ')
                        except Exception:
                            corps = '(corps illisible)'
                    posts.append((r.status, r.url.split('?')[0], corps))
                page.on('response', _voir)
                resp = page.goto(url, wait_until='networkidle', timeout=45000)
                if not resp or resp.status != 200:
                    return False, f"page HTTP {resp.status if resp else '?'}"
                page.wait_for_timeout(1200)
                etat = page.evaluate(ETAT)

                # Le CÂBLAGE n'est pas le verdict — seulement une information. Première
                # version de ce test : « pas de WamaImport → échec ». Confronté aux 10 apps,
                # il déclarait le converter EN PLACE défaillant alors qu'il importe très
                # bien, avec son propre converter.js. C'était confondre l'ADOPTION de la
                # brique commune (affaire de la grille de conformité) avec la CAPACITÉ à
                # importer (objet de ce test). Seul le comportement tranche ici.
                voie = 'brique commune' if etat['cable'] else 'JS propre à l’app'
                if not (etat['dropzone'] or etat['champ']):
                    # Surface SANS card d'entrée (médiathèque, gestionnaire de modèles,
                    # studio) : le scénario ne s'y applique pas. SKIP, pas échec — une
                    # barrière qui crie au loup sur des cas hors périmètre ne serait pas relue.
                    raise SkipScenario("aucune card d'entrée sur cette surface — "
                                       "scénario d'import non applicable")
                if etat.get('depot') == 'attache':
                    # DÉCLARÉ : ici le dépôt joint le fichier au formulaire de la card, et
                    # c'est le bouton primaire qui crée l'élément (avatarizer : audio +
                    # avatar + réglages ; imager : prompt + image de référence). Exiger une
                    # création au dépôt y mesurerait une conception, pas un défaut — les deux
                    # apps échouaient pour cette seule raison (2026-08-22). Couvrir CE geste
                    # demande de remplir la card puis de cliquer : un autre scénario.
                    raise SkipScenario(
                        "la card DÉCLARE `data-wama-depot=attache` : le dépôt joint le "
                        "fichier, l'élément est créé par le bouton primaire — ce scénario "
                        "mesure le dépôt-qui-crée, il ne s'applique pas")
                if not etat['champ']:
                    # PAS un échec : une app PROMPT-PRIMAIRE (composer, imager, avatarizer en
                    # mode pipeline) n'importe pas de fichier de travail — on y saisit un texte.
                    # Le geste équivalent existe, il n'est simplement pas celui-ci.
                    raise SkipScenario(
                        f"pas de champ de fichier dans la card d'entrée "
                        f"({etat['champs_total']} ailleurs dans la page) : app sans import "
                        f"par fichier — scénario non applicable")

                temoin = _fichier_temoin(etat['accept'])
                avant = etat['cards']
                cible = etat['champ_id']
                sel = f"#{cible}" if cible and cible != '(sans id)' else 'input[type=file]'
                page.set_input_files(sel, str(temoin))
                page.wait_for_timeout(4500)
                apres = page.evaluate("document.querySelectorAll('.wama-card').length")
                envoyes = [f"{s} {u.rsplit('/', 2)[-2]}/" for s, u, _c in posts]
            finally:
                navigateur.close()
    except SkipScenario:
        # Un SKIP DÉLIBÉRÉ traverse tel quel. Sans cette clause il retombait dans le `except
        # Exception` ci-dessous et ressortait préfixé « navigateur/serveur indisponible » —
        # un motif FAUX collé sur des raisons parfaitement établies (« aucune card d'entrée »,
        # « data-wama-depot=attache »). Un rapport qui invente la cause d'un skip apprend à
        # se méfier de tous les skips (mesuré le 2026-08-22 sur les 5 skips de la passe).
        raise
    except Exception as e:
        raise SkipScenario(f"navigateur/serveur indisponible ({type(e).__name__}: {str(e)[:100]})")
    finally:
        if temoin:
            try:
                temoin.unlink()
            except OSError:
                pass
        _drop_new_sessions(sessions_before)
        if modele is not None:
            try:
                crees = set(modele.objects.values_list('id', flat=True)) - ids_avant
                if crees:
                    modele.objects.filter(id__in=crees).delete()
                    _nettoyes.append(len(crees))
            except Exception:
                pass

    if not posts:
        return False, (f"dépôt sur {etat['champ_id']} ({etat['champs_total']} champ(s) fichier "
                       f"dans la page) : AUCUNE requête émise — la zone de dépôt existe "
                       "mais RIEN NE L'ÉCOUTE. Défaut silencieux : ni erreur console, ni "
                       "message ; c'est l'état exact d'une app générée sans couche JS.")
    echecs = [f"{s} {u}" + (f" → {c}" if c else '') for s, u, c in posts if s >= 400]
    if echecs:
        return False, f"requêtes en échec : {' | '.join(echecs[:2])}"
    trace = f" ; {sum(_nettoyes)} élément(s) de test supprimé(s)" if _nettoyes else \
            ("" if modele is not None else " ; ⚠ modèle inconnu du PreviewRegistry : rien nettoyé")
    if apres <= avant:
        return False, (f"requête(s) acceptée(s) ({', '.join(envoyes[:3])}) mais aucun élément "
                       f"n'apparaît ({avant} → {apres}) — contrat de réponse ou rafraîchissement"
                       + trace)
    return True, (f"élément créé ({avant} → {apres} cards ; {', '.join(envoyes[:3])} ; "
                  f"voie : {voie}){trace}")


def register_import_scenarios():
    """Enregistre un scénario `<app>.import` par app disposant d'une page d'index.

    Déduit des URL comme `register_ui_scenarios` — aucune liste à tenir, donc toute app
    NOUVELLE (générée comprise) est couverte le jour où elle expose son index.
    """
    from wama.common.services.nightly_tests import register

    for label, path in discoverable_apps():
        register(
            id=f"{label}.import", app=label, stage="ui",
            description=f"Card d'entrée {label} : un dépôt crée un élément",
            run=(lambda p=path, a=label: (lambda ctx: check_app_import(a, p)))(),
            timeout_s=180, vram_gb=0.0,
        )


# ── Geste 14, part « ENVOYER VERS » : importer depuis le gestionnaire de fichiers ───────
#
# Le seul chemin d'import qui ne PART PAS de l'app : on est dans le gestionnaire de fichiers,
# on fait un clic droit sur un fichier, et le sous-menu « Envoyer vers… » propose les apps
# capables de le recevoir. Deux moitiés que rien n'oblige à coïncider, et c'est tout l'objet
# du scénario :
#   • le MENU est bâti côté client depuis `WAMA_APP_CATALOG.input_extensions` — la déclaration
#     de l'app, injectée pour TOUTES les entrées du catalogue ;
#   • la RÉCEPTION est côté serveur (`filemanager.views.api_import_to_app`), qui dispatche vers
#     un `import_to_<app>` écrit à la main.
# Une app peut donc être OFFERTE sans être RECEVABLE. Un test qui posterait sur l'endpoint ne
# le verrait jamais : il faut passer par le menu, c'est-à-dire par le geste.
def check_app_send_to(app: str, url_path: str):
    """« Envoyer vers <app> » depuis le gestionnaire de fichiers crée-t-il un élément ? (ok, detail)."""
    from wama.common.services.nightly_tests import SkipScenario
    from playwright.sync_api import sync_playwright

    from wama.common.app_registry import APP_CATALOG
    spec = APP_CATALOG.get(app) or {}
    exts = list(spec.get('input_extensions') or ())
    libelle = spec.get('label') or app
    if not exts:
        raise SkipScenario("l'app ne déclare aucune extension d'entrée : elle ne peut pas "
                           "apparaître au menu « Envoyer vers… » — geste non applicable")

    # Deux conditions, pas une : accepter des extensions ne suffit pas, encore faut-il que le
    # gestionnaire de fichiers sache REMPLIR l'app (`filemanager.views.IMPORTERS`). Depuis le
    # 2026-08-28 le menu est bâti sur les DEUX. On lit ici la seconde — mais on ne SORT PAS
    # tout de suite : une app sans importeur doit être ABSENTE du menu, et c'est justement ce
    # qu'il faut aller vérifier à l'écran. Sortir avant le clic droit rendrait le scénario
    # aveugle à la réapparition du défaut qu'il vient de faire fermer.
    try:
        from wama.filemanager.views import receivable_apps
        recevable = app in receivable_apps()
    except Exception:
        recevable = True   # registre illisible : on mesure comme avant, sans rien présumer
    DETTE = (f"aucun importeur `import_to_{app}` au registre du gestionnaire de fichiers : "
             f"l'app ACCEPTE {', '.join(exts[:4])} mais rien ne sait la remplir depuis "
             "l'explorateur, et le menu ne la propose donc pas (VÉRIFIÉ à l'écran) — "
             "geste non câblé, dette ouverte")

    jeton = _session_compte_de_test()
    if not jeton:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / ui_smoke_v3) "
                           "— les droits ne sont pas simulables, on ne mesure pas à l'aveugle")
    uid = _id_du_compte_de_test()
    if not uid:
        raise SkipScenario("id du compte de test illisible — sans lui, aucun dossier à peupler")

    # Le témoin est déposé dans le dossier TEMPORAIRE du compte de test — le seul emplacement
    # que `is_path_allowed` ouvre hors dossiers d'app, donc celui d'un vrai fichier utilisateur.
    modele = None
    ids_avant = set()
    try:
        from wama.common.utils.preview_registry import PreviewRegistry
        modele = PreviewRegistry.get_model(app)
        ids_avant = set(modele.objects.values_list('id', flat=True))
    except Exception:
        modele = None

    source = _fichier_temoin(','.join(e if e.startswith('.') else f'.{e}' for e in exts))
    dossier = Path(settings.MEDIA_ROOT) / f'users/{uid}/temp'
    dossier.mkdir(parents=True, exist_ok=True)
    temoin = dossier / f'envoyer_vers_{app}{source.suffix}'
    temoin.write_bytes(source.read_bytes())
    source.unlink(missing_ok=True)

    ARBRE = "#filemanager-tree"
    detail_menu, poste, cree_ailleurs = '', [], []
    sessions_before = _session_keys()
    try:
        with sync_playwright() as p:
            navigateur = p.chromium.launch()
            try:
                contexte = navigateur.new_context(viewport={'width': 1500, 'height': 1000})
                contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': jeton,
                                       'domain': '127.0.0.1', 'path': '/'}])
                page = contexte.new_page()

                def _voir(r):
                    if r.request.method == 'POST' and '/filemanager/api/import' in r.url:
                        corps = ''
                        try:
                            corps = (r.text() or '')[:200]
                        except Exception:
                            corps = '(corps illisible)'
                        poste.append((r.status, corps))
                page.on('response', _voir)

                # Le gestionnaire de fichiers N'A PAS de page à lui : c'est un volet gauche
                # inclus par `base.html` sur TOUTES les pages (`filemanager/sidebar.html`).
                # On l'atteint donc depuis la page de l'app elle-même — ce qui est aussi le
                # geste réel : on est dans l'app, on va chercher un fichier dans l'explorateur.
                resp = page.goto(f"{BASE_URL.rstrip('/')}{url_path}",
                                 wait_until='networkidle', timeout=45000)
                if not resp or resp.status != 200:
                    return False, f"page {url_path} HTTP {resp.status if resp else '?'}"
                page.wait_for_selector(f'{ARBRE} .jstree-anchor', timeout=20000)

                # DÉPLIER le dossier « Temporaires » par l'API de l'arbre. C'est de
                # l'ÉCHAFAUDAGE, pas le geste : le geste mesuré est le clic droit et le
                # sous-menu. Ouvrir un dossier par l'API évite de dépendre du rang du nœud
                # dans un arbre dont le contenu varie d'une nuit à l'autre.
                page.evaluate("() => { const t = window.jQuery && jQuery('#filemanager-tree');"
                              " if (t && t.jstree) t.jstree(true).open_node('temp'); }")
                cible = f'{ARBRE} .jstree-anchor:text-is("{temoin.name}")'
                try:
                    page.wait_for_selector(cible, timeout=15000)
                except Exception:
                    return False, (f"le témoin déposé dans users/{uid}/temp n'apparaît pas dans "
                                   f"l'arbre ({temoin.name}) — l'arbre ne montre pas les fichiers "
                                   "du dossier temporaire, ou ne s'est pas rafraîchi")

                page.click(cible, button='right')
                try:
                    page.wait_for_selector('.vakata-context:visible', timeout=8000)
                except Exception:
                    return False, "le clic droit sur un fichier n'ouvre aucun menu contextuel"

                entree = page.query_selector('.vakata-context a:has-text("Envoyer vers")')
                if not entree:
                    if not recevable:
                        raise SkipScenario(DETTE)
                    libelles = page.evaluate(
                        "() => [...document.querySelectorAll('.vakata-context a')]"
                        ".map(a => a.textContent.trim()).filter(Boolean).slice(0, 12)")
                    return False, ("le menu contextuel n'offre pas « Envoyer vers… » sur un "
                                   f"fichier {temoin.suffix} que l'app DÉCLARE accepter "
                                   f"({', '.join(exts[:4])}…) — entrées vues : {libelles}")
                entree.hover()
                page.wait_for_timeout(600)

                # Le sous-menu porte le LIBELLÉ de l'app (APP_CATALOG.label), pas son id.
                choix = page.query_selector(f'.vakata-context a:text-is("{libelle}")')
                if not recevable:
                    # Le contrôle INVERSE, et c'est lui qui garde la porte fermée : une app que
                    # le serveur ne sait pas remplir ne doit PAS être proposée. Le mesurer ici
                    # coûte le même clic droit ; ne pas le mesurer laisserait le défaut revenir
                    # au premier ajout d'app sans que rien ne le dise.
                    if choix:
                        return False, (f"« Envoyer vers… » propose {libelle}, mais AUCUN "
                                       f"`import_to_{app}` n'existe côté serveur : l'envoi sera "
                                       "refusé (400) après avoir été offert — les deux moitiés "
                                       "du geste ont recommencé à diverger")
                    raise SkipScenario(DETTE)
                if not choix:
                    offerts = page.evaluate(
                        "() => [...document.querySelectorAll('.vakata-context ul a')]"
                        ".map(a => a.textContent.trim()).filter(Boolean)")
                    return False, (f"« Envoyer vers… » n'offre pas {libelle} alors que l'app "
                                   f"DÉCLARE accepter {temoin.suffix} — offert : {offerts}")
                choix.click()
                page.wait_for_timeout(3500)
                detail_menu = f"menu → {libelle}"
            finally:
                navigateur.close()
    except SkipScenario:
        raise
    except Exception as e:
        raise SkipScenario(f"navigateur/serveur indisponible ({type(e).__name__}: {str(e)[:100]})")
    finally:
        _drop_new_sessions(sessions_before)
        temoin.unlink(missing_ok=True)
        if modele is not None:
            try:
                crees = set(modele.objects.values_list('id', flat=True)) - ids_avant
                if crees:
                    # L'import COPIE le fichier dans le dossier d'entrée de l'app : supprimer
                    # la ligne ne suffit pas, la copie resterait sur disque nuit après nuit.
                    # On relève les chemins AVANT la suppression, tant que les objets existent.
                    copies = []
                    for objet in modele.objects.filter(id__in=crees):
                        for champ in objet._meta.get_fields():
                            if not getattr(champ, 'attname', None) or not hasattr(champ, 'storage'):
                                continue
                            valeur = getattr(objet, champ.attname, None)
                            if valeur:
                                copies.append(Path(settings.MEDIA_ROOT) / str(valeur))
                    modele.objects.filter(id__in=crees).delete()
                    cree_ailleurs.append(len(crees))
                    for chemin in copies:
                        try:
                            if chemin.is_file():
                                chemin.unlink()
                        except OSError:
                            pass
            except Exception:
                pass

    if not poste:
        return False, (f"{detail_menu} : AUCUNE requête d'import émise — le menu propose "
                       "l'envoi, mais le clic ne poste rien")
    refus = [f"HTTP {s} → {c}" for s, c in poste if s >= 400]
    if refus:
        return False, (f"le menu OFFRE « Envoyer vers {libelle} », le serveur REFUSE : "
                       f"{' | '.join(refus[:2])} — les deux moitiés du geste ne sont pas "
                       "bâties sur la même source (menu : catalogue d'apps ; serveur : liste "
                       "écrite à la main dans `api_import_to_app`)")
    if modele is None:
        return True, (f"{detail_menu} : requête acceptée ({poste[0][0]}) ; ⚠ modèle inconnu du "
                      "PreviewRegistry — création non vérifiée, rien nettoyé")
    if not cree_ailleurs:
        return False, (f"{detail_menu} : requête acceptée ({poste[0][0]}) mais AUCUN élément "
                       f"n'apparaît dans {app} — l'import répond bien et ne crée rien")
    return True, (f"{detail_menu} : {sum(cree_ailleurs)} élément(s) créé(s) depuis le "
                  f"gestionnaire de fichiers, puis nettoyé(s)")


def register_send_to_scenarios():
    """Enregistre un scénario `<app>.send_to` par app d'index — geste 14, part « Envoyer vers »."""
    from wama.common.services.nightly_tests import register

    for label, path in discoverable_apps():
        register(
            id=f"{label}.send_to", app=label, stage="ui",
            description=f"« Envoyer vers {label} » depuis le gestionnaire de fichiers",
            run=(lambda p=path, a=label: (lambda ctx: check_app_send_to(a, p)))(),
            timeout_s=180, vram_gb=0.0,
        )


# ── Gestes 3 et 4 : DUPLIQUER puis SUPPRIMER un élément ────────────────────────────────
#
# POURQUOI CE SCÉNARIO EXISTE (WAMA_VERIFICATION.md §3, phase 1). Sur les ~16 gestes que la
# convention rend obligatoires, UN SEUL était prouvé par un clic (le dépôt). Tous les autres
# n'étaient attestés que par la grille — c'est-à-dire par l'ADOPTION de la brique, jamais par
# son fonctionnement. La journée du 2026-08-22 a montré deux fois ce que vaut cette différence :
# l'anonymizer rendait un 400 à TOUS ses utilisateurs avec une grille verte.
#
# CE QU'IL MESURE EN PLUS DU GESTE. Les boutons `.duplicate-btn` / `.delete-btn` ne viennent
# PAS d'un partial commun : chaque app les réécrit dans son propre gabarit de card. Leur
# uniformité est donc une CONVENTION tenue par discipline (contrat documenté en tête de
# `_media_card.html` & co.), et une convention non mesurée dérive. Ce scénario est le seul
# endroit où elle est vérifiée sur pièces.
#
# ⚠ IL NE SUPPRIME QUE CE QU'IL A CRÉÉ. La suppression vise l'identifiant APPARU entre les deux
# relevés — jamais « la première card », qui appartiendrait à un vrai travail de l'utilisateur
# (règle : pas de test destructif ; le compte id=1 est le compte réel de Fabien).
def check_app_duplicate_delete(app: str, url_path: str):
    """Dupliquer un élément puis supprimer le doublon remet-il la file dans son état ? (ok, detail).

    Auto-nettoyant par construction : le doublon créé par le geste EST celui que le geste
    suivant supprime. Un aller-retour réussi ne laisse aucun résidu — et s'il en laisse, le
    filet ORM du `finally` s'en charge et le DIT.
    """
    from wama.common.services.nightly_tests import SkipScenario
    from playwright.sync_api import sync_playwright

    _nettoyes = []
    url = f"{BASE_URL.rstrip('/')}{url_path}"
    # Identifiants des cards présentes — la seule source qui permette de distinguer le doublon
    # d'un élément préexistant SANS lire l'ORM (interdit pendant `sync_playwright`).
    IDS = "[...document.querySelectorAll('.wama-card[data-id]')].map(c => c.dataset.id)"

    try:
        from wama.common.utils.preview_registry import PreviewRegistry
        modele = PreviewRegistry.get_model(app)
    except Exception:
        modele = None
    ids_avant_orm = set()
    if modele is not None:
        try:
            ids_avant_orm = set(modele.objects.values_list('id', flat=True))
        except Exception:
            modele = None

    sessions_before = _session_keys()
    jeton = _session_compte_de_test()
    if not jeton:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / ui_smoke_v3) "
                           "— les droits ne sont pas simulables, on ne mesure pas à l'aveugle")
    detail = ''
    try:
        with sync_playwright() as p:
            navigateur = p.chromium.launch()
            try:
                contexte = navigateur.new_context(viewport={'width': 1500, 'height': 1000})
                contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': jeton,
                                       'domain': '127.0.0.1', 'path': '/'}])
                page = contexte.new_page()
                # La suppression demande confirmation sur plusieurs apps (`confirm()` natif).
                # Sans ce gestionnaire, Playwright la refuse par défaut et le geste échouerait
                # pour une raison qui n'a rien à voir avec ce qu'on mesure.
                page.on('dialog', lambda d: d.accept())
                echecs = []
                page.on('response', lambda r: (
                    echecs.append(f"{r.status} {r.url.split('?')[0]}")
                    if r.request.method == 'POST' and r.status >= 400 else None))

                resp = page.goto(url, wait_until='networkidle', timeout=45000)
                if not resp or resp.status != 200:
                    return False, f"page HTTP {resp.status if resp else '?'}"
                page.wait_for_timeout(1200)

                ids0 = page.evaluate(IDS)
                if not ids0:
                    # MONTAGE, pas geste mesuré. Première version : on SKIPPAIT ici. Résultat
                    # mesuré le 2026-08-22 — **14 apps sur 14 en skip**, parce que `<app>.import`
                    # nettoie derrière lui et laisse donc les files vides. Un scénario qui ne
                    # peut jamais tourner est pire qu'absent : il occupe la ligne du rapport en
                    # promettant une couverture qu'il n'apporte pas.
                    #
                    # On monte donc la fixture ici. On ne recopie PAS l'heuristique à trois crans
                    # de `check_app_import` : on s'en tient au CONTRAT de la brique commune —
                    # le champ de fichier de la card d'entrée (`[data-wama-nic]`), hors champs
                    # de lot et de référence. Si ce contrat ne suffit pas, on SKIPPE : l'import
                    # a son propre scénario, ce n'est pas ici qu'on doit le diagnostiquer.
                    exclus = '[id*="atch"], [id*="elody"], [id*="eference"], [id*="voice"], [id*="avatar"]'
                    champ = page.query_selector(
                        f'[data-wama-nic] input[type=file]:not({exclus})')
                    if not champ:
                        raise SkipScenario(
                            "file vide et aucun champ d'import au contrat de la card commune "
                            "— impossible de monter un élément à dupliquer (l'import lui-même "
                            "est mesuré par `<app>.import`)")
                    # Le témoin est fabriqué d'après l'`accept` DÉCLARÉ par le champ : une app
                    # qui n'accepte que du .wav rejetterait un .txt, et on lirait un échec de
                    # validation comme un défaut de duplication.
                    temoin_fixture = _fichier_temoin(champ.get_attribute('accept') or '')
                    try:
                        champ.set_input_files(str(temoin_fixture))
                        page.wait_for_timeout(4500)
                        ids0 = page.evaluate(IDS)
                    finally:
                        try:
                            temoin_fixture.unlink()
                        except OSError:
                            pass
                    if not ids0:
                        raise SkipScenario(
                            "file vide et le dépôt de montage n'a créé aucun élément — le geste "
                            "n'a pas d'objet ici (cause à chercher dans `<app>.import`)")
                # ⚠ Les apps NE PARTAGENT PAS un nom de classe unique : anonymizer écrit
                # `.delete-btn`, converter `.job-delete-btn`, et un grep sur « delete-btn »
                # matche les DEUX (la sous-chaîne), ce qui avait fait conclure à tort que la
                # convention était tenue (erreur du 2026-08-22). On vise donc le SUFFIXE, et on
                # RAPPORTE la graphie trouvée : le geste est mesuré, la divergence est dite —
                # jamais masquée par un sélecteur tolérant et muet.
                DUP = '[class$="duplicate-btn"], [class*="duplicate-btn "]'
                DEL = '[class$="delete-btn"], [class*="delete-btn "]'
                # Un utilisateur ne clique que ce qu'il VOIT. Sans ce filtre, `.first` peut
                # résoudre sur la card d'un lot replié (dimensions nulles) et le clic expire —
                # en accusant l'environnement au lieu de dire « le bouton est masqué ».
                visible = lambda sel: ', '.join(s.strip() + ':visible' for s in sel.split(','))
                bouton_dup = page.query_selector(DUP)
                if not bouton_dup:
                    return False, (f"{len(ids0)} élément(s) en file mais AUCUN bouton de "
                                   "duplication (ni `.duplicate-btn`, ni suffixe équivalent) — "
                                   "la convention de card n'est pas tenue par cette app")
                graphies = page.evaluate(
                    "(() => {const n = c => [...document.querySelectorAll(c)]"
                    ".flatMap(e => [...e.classList]).filter(x => x.endsWith('delete-btn') "
                    "|| x.endsWith('duplicate-btn')); return [...new Set(n('*'))].join(', ');})()")

                # ⚠ CLIQUER PAR LOCATOR, JAMAIS PAR ElementHandle (corrigé le 2026-08-23).
                # `query_selector` rend un HANDLE sur un nœud PRÉCIS. Or les files se
                # rafraîchissent : sur transition de statut, l'app REMPLACE le nœud de la card
                # (`refreshCard`, partial serveur). Le handle capturé pointe alors sur un nœud
                # détaché, et Playwright réessaie l'actionnabilité jusqu'au timeout.
                # C'est exactement ce qui faisait skipper describer et synthesizer en
                # « ElementHandle.click: Timeout 30000ms » : deux apps qui DÉMARRENT le
                # traitement au dépôt, donc dont la card change d'état pendant le scénario.
                # Diagnostiqué au navigateur — le bouton était visible, actif, `pointer-events:
                # auto`, et `elementFromPoint` renvoyait bien son icône : rien n'était masqué.
                # Un locator RE-RÉSOUT le sélecteur à chaque tentative : il suit le re-rendu.
                page.locator(visible(DUP)).first.click(timeout=15000)
                page.wait_for_timeout(3000)
                ids1 = page.evaluate(IDS)
                nouveaux = [i for i in ids1 if i not in ids0]
                if len(ids1) <= len(ids0) or not nouveaux:
                    return False, (f"clic sur `.duplicate-btn` : la file ne bouge pas "
                                   f"({len(ids0)} → {len(ids1)} cards)"
                                   + (f" ; requêtes en échec : {echecs[0]}" if echecs else
                                      " ; AUCUNE requête en échec — le bouton n'est pas écouté"))

                doublon = nouveaux[0]

                # ── DÉPLIER LE LOT SI LE DOUBLON Y ATTERRIT ────────────────────────────────
                # Mesuré au navigateur le 2026-08-23 : sur describer et synthesizer, dupliquer
                # CONSOLIDE l'élément et son doublon dans un LOT, dont le conteneur `.collapse`
                # est replié par défaut. La card du doublon a donc des dimensions NULLES
                # (`getBoundingClientRect` → 0×0, `offsetParent` null) et son bouton Supprimer
                # n'est jamais actionnable : `click()` attendait 30 s puis abandonnait.
                # Le scénario lisait cet abandon comme « navigateur indisponible » — un skip qui
                # accusait l'environnement alors que la page allait parfaitement bien.
                # On déplie par le VRAI geste — mécanique commune `_deplier_autour()`.
                _deplier_autour(page, f'.wama-card[data-id="{doublon}"]')

                sel_del = f'.wama-card[data-id="{doublon}"] :is({DEL})'
                if not page.query_selector(sel_del):
                    sel_del = f':is({DEL})[data-id="{doublon}"]'
                if not page.query_selector(sel_del):
                    return False, (f"doublon #{doublon} créé, mais aucun bouton de suppression "
                                   f"ne le porte (graphies vues dans la page : {graphies or '—'}) "
                                   "— il RESTE en file (nettoyé par le filet ORM)")
                # Locator ici aussi : la card du doublon vient d'apparaître et peut être
                # re-rendue par le premier tour de polling (même cause que ci-dessus).
                page.locator(f'{sel_del}:visible').first.click(timeout=15000)
                page.wait_for_timeout(3000)
                ids2 = page.evaluate(IDS)
                if doublon in ids2:
                    return False, (f"doublon #{doublon} toujours présent après clic sur "
                                   f"`.delete-btn` ({len(ids1)} → {len(ids2)} cards)"
                                   + (f" ; {echecs[0]}" if echecs else ""))
                detail = (f"aller-retour complet : {len(ids0)} → {len(ids1)} (doublon #{doublon}) "
                          f"→ {len(ids2)} cards ; graphies : {graphies or '—'}")
            finally:
                navigateur.close()
    except SkipScenario:
        raise
    except Exception as e:
        raise SkipScenario(f"navigateur/serveur indisponible ({type(e).__name__}: {str(e)[:100]})")
    finally:
        _drop_new_sessions(sessions_before)
        if modele is not None:
            try:
                restes = set(modele.objects.values_list('id', flat=True)) - ids_avant_orm
                if restes:
                    modele.objects.filter(id__in=restes).delete()
                    _nettoyes.append(len(restes))
            except Exception:
                pass

    # Un résidu n'invalide pas le geste, mais il se DIT : il signifie que la suppression a
    # retiré la card de l'écran sans supprimer l'objet — exactement le genre d'écart qu'un
    # « vert » muet laisserait s'installer.
    if _nettoyes:
        return True, (f"{detail} ⚠ mais {sum(_nettoyes)} objet(s) subsistai(en)t en base après "
                      "le geste — la card disparaît de l'écran sans que l'objet soit supprimé")
    return True, detail


def register_duplicate_delete_scenarios():
    """Enregistre un scénario `<app>.duplicate_delete` par app disposant d'une page d'index."""
    from wama.common.services.nightly_tests import register

    for label, path in discoverable_apps():
        register(
            id=f"{label}.duplicate_delete", app=label, stage="ui",
            description=f"File {label} : dupliquer un élément puis supprimer le doublon",
            run=(lambda p=path, a=label: (lambda ctx: check_app_duplicate_delete(a, p)))(),
            timeout_s=180, vram_gb=0.0,
        )


# ── Geste 2 : OUVRIR LES PARAMÈTRES d'un élément ───────────────────────────────────────
#
# POURQUOI CE SCÉNARIO, ET POURQUOI MAINTENANT (2026-08-23). Le ⚙ vient d'obtenir sa brique
# (`queue-actions.js`) et son critère de grille (`settings_wiring`, vert sur 10/10). Or ce
# critère atteste précisément DEUX PRÉSENCES — le bouton au contrat dans le gabarit, l'ouvreur
# déclaré dans le JS — et rien de plus : il ne peut pas voir qu'un ouvreur lève avant d'afficher,
# qu'une modale s'ouvre VIDE faute de schéma, ni qu'un second handler la referme aussitôt.
# « Un critère de grille atteste une ADOPTION, jamais un FONCTIONNEMENT » (WAMA_VERIFICATION §1) :
# le vert de `settings_wiring` est donc exactement ce qui APPELLE ce clic, pas ce qui le remplace.
#
# CE QU'IL EXIGE, ET POURQUOI CHAQUE EXIGENCE EST LÀ :
#   1. le bouton existe au contrat commun → sinon la brique ne le voit pas ;
#   2. le clic OUVRE une modale visible → c'est le geste, et c'est ce qu'aucune analyse ne prouve ;
#   3. la modale contient au moins UN champ de saisie → une modale ouverte mais vide est le
#      défaut réel qu'on a déjà vu ailleurs (volet rendu, `<select>` VIDE, imager 06/08) : « ça
#      s'ouvre » n'est pas « ça sert ». C'est la marche qui sépare l'écran mort de l'écran utile.
#
# IL NE MODIFIE RIEN. Le geste catalogué complet est « ouvrir, modifier, enregistrer, relire » ;
# on n'en prouve ici que la première moitié, et on le DIT dans le détail plutôt que de laisser
# croire que le tour est joué. Enregistrer déclenche selon les apps une relance de traitement
# (donc du GPU) : la seconde moitié se traitera avec les gestes 8-13, sur le converter en CPU
# (WAMA_VERIFICATION §4). Un scénario qui promet plus qu'il ne mesure est pire qu'absent.
def check_app_settings(app: str, url_path: str):
    """Le ⚙ d'un élément ouvre-t-il une modale de paramètres utilisable ? (ok, detail)."""
    from wama.common.services.nightly_tests import SkipScenario
    from playwright.sync_api import sync_playwright

    _nettoyes = []
    url = f"{BASE_URL.rstrip('/')}{url_path}"
    IDS = "[...document.querySelectorAll('.wama-card[data-id]')].map(c => c.dataset.id)"

    try:
        from wama.common.utils.preview_registry import PreviewRegistry
        modele = PreviewRegistry.get_model(app)
    except Exception:
        modele = None
    ids_avant_orm = set()
    if modele is not None:
        try:
            ids_avant_orm = set(modele.objects.values_list('id', flat=True))
        except Exception:
            modele = None

    sessions_before = _session_keys()
    jeton = _session_compte_de_test()
    if not jeton:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / ui_smoke_v3) "
                           "— les droits ne sont pas simulables, on ne mesure pas à l'aveugle")
    detail = ''
    try:
        with sync_playwright() as p:
            navigateur = p.chromium.launch()
            try:
                contexte = navigateur.new_context(viewport={'width': 1500, 'height': 1000})
                contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': jeton,
                                       'domain': '127.0.0.1', 'path': '/'}])
                page = contexte.new_page()
                page.on('dialog', lambda d: d.accept())
                erreurs = []
                page.on('pageerror', lambda e: erreurs.append(str(e)[:120]))
                echecs = []
                page.on('response', lambda r: (
                    echecs.append(f"{r.status} {r.url.split('?')[0]}")
                    if r.status >= 400 and r.request.resource_type in ('xhr', 'fetch') else None))

                resp = page.goto(url, wait_until='networkidle', timeout=45000)
                if not resp or resp.status != 200:
                    return False, f"page HTTP {resp.status if resp else '?'}"
                page.wait_for_timeout(1200)

                ids0 = page.evaluate(IDS)
                if not ids0:
                    # Même montage de fixture que `duplicate_delete`, et pour la même raison :
                    # `<app>.import` nettoie derrière lui, donc la file est vide la plupart du
                    # temps et un scénario qui skippe toujours ne couvre rien.
                    exclus = '[id*="atch"], [id*="elody"], [id*="eference"], [id*="voice"], [id*="avatar"]'
                    champ = page.query_selector(f'[data-wama-nic] input[type=file]:not({exclus})')
                    if not champ:
                        raise SkipScenario(
                            "file vide et aucun champ d'import au contrat de la card commune "
                            "— aucun élément dont ouvrir les paramètres")
                    temoin = _fichier_temoin(champ.get_attribute('accept') or '')
                    try:
                        champ.set_input_files(str(temoin))
                        page.wait_for_timeout(4500)
                        ids0 = page.evaluate(IDS)
                    finally:
                        try:
                            temoin.unlink()
                        except OSError:
                            pass
                    if not ids0:
                        raise SkipScenario(
                            "file vide et le dépôt de montage n'a créé aucun élément "
                            "(cause à chercher dans `<app>.import`)")

                # Graphies RÉELLEMENT présentes — rapportées qu'on réussisse ou non. C'est ce
                # relevé qui a montré, le 2026-08-23, que la matrice des actions de card
                # sous-estimait la divergence du ⚙ (avatarizer et enhancer manquaient).
                graphies = page.evaluate(
                    "(() => {const n = [...document.querySelectorAll('button')]"
                    ".flatMap(e => [...e.classList])"
                    ".filter(x => x.endsWith('settings-btn') || x.startsWith('btn-settings')"
                    " || x.includes('-settings')); return [...new Set(n)].join(', ');})()")

                SEL_GEAR = '.wama-card[data-id] .settings-btn[data-id]'
                if not page.query_selector(SEL_GEAR):
                    return False, (f"{len(ids0)} élément(s) en file mais aucun bouton au contrat "
                                   f"commun `.settings-btn[data-id]` dans une card "
                                   f"(graphies vues : {graphies or '—'})")
                # Le bouton existe — mais est-il ATTEIGNABLE ? Un ⚙ dans un lot replié a des
                # dimensions nulles. La distinction compte : « absent » et « masqué » sont deux
                # défauts différents, et un scénario qui les confond fait perdre le diagnostic.
                #
                # Si tout est replié, on DÉPLIE par le vrai geste (toggle de la card mère,
                # contrat commun `_batch_card.html`) : une file dont tous les éléments sont dans
                # un lot est un état parfaitement normal — mesuré sur describer, dont les
                # éléments se consolident. Refuser de déplier reviendrait à déclarer le geste
                # impossible alors que l'utilisateur l'atteint en un clic.
                if not page.query_selector(f'{SEL_GEAR}:visible'):
                    _deplier_autour(page, SEL_GEAR)
                if not page.query_selector(f'{SEL_GEAR}:visible'):
                    return False, (f"{len(ids0)} élément(s) en file : le ⚙ existe au contrat "
                                   "commun mais AUCUN n'est visible (card dans un lot replié, "
                                   "ou masquée) — le geste est hors de portée de l'utilisateur")

                avant = page.evaluate("document.querySelectorAll('.modal.show').length")
                # Locator VISIBLE et non ElementHandle — deux corrections du 2026-08-23, chacune
                # après diagnostic au navigateur : un handle pointe sur un nœud PRÉCIS, or les
                # cards sont remplacées au changement de statut (nœud détaché → clic qui expire) ;
                # et `.first` sans filtre peut désigner une card repliée, invisible donc
                # inactionnable. Un locator re-résout, `:visible` garantit qu'on clique ce que
                # l'utilisateur voit.
                page.locator(f'{SEL_GEAR}:visible').first.click(timeout=15000)
                # Bootstrap anime l'ouverture : attendre l'ÉTAT, pas un délai au hasard.
                try:
                    page.wait_for_selector('.modal.show', timeout=6000)
                except Exception:
                    return False, (
                        "clic sur `.settings-btn` : AUCUNE modale ne s'ouvre"
                        + (f" ; erreur JS : {erreurs[0]}" if erreurs else
                           (f" ; requête en échec : {echecs[0]}" if echecs else
                            " ; aucune erreur JS, aucune requête en échec — le clic n'aboutit à "
                            "rien de visible (ouvreur non déclaré, ou modale absente du gabarit)"))
                        + f" ; graphies : {graphies or '—'}")

                apres = page.evaluate("document.querySelectorAll('.modal.show').length")
                if apres <= avant:
                    return False, f"aucune modale supplémentaire ouverte ({avant} → {apres})"

                # Une modale ouverte mais VIDE ne rend aucun service : on exige au moins un
                # contrôle de saisie. `:visible` écarte les champs cachés (ids techniques).
                champs = page.evaluate(
                    "(() => {const m = [...document.querySelectorAll('.modal.show')].pop();"
                    " if (!m) return 0;"
                    " return m.querySelectorAll('input:not([type=hidden]), select, textarea').length;})()")
                titre = (page.evaluate(
                    "(() => {const m = [...document.querySelectorAll('.modal.show')].pop();"
                    " const t = m && m.querySelector('.modal-title');"
                    " return t ? t.textContent.trim().slice(0, 60) : '';})()") or '—')
                if not champs:
                    return False, (f"modale « {titre} » ouverte mais SANS aucun champ de saisie "
                                   "— l'ouverture réussit, le service rendu est nul")

                detail = (f"⚙ cliqué → modale « {titre} » ouverte avec {champs} champ(s) ; "
                          f"graphies : {graphies or '—'} ; "
                          "⚠ MOITIÉ DU GESTE — modifier/enregistrer/relire n'est PAS mesuré ici")
            finally:
                navigateur.close()
    except SkipScenario:
        raise
    except Exception as e:
        raise SkipScenario(f"navigateur/serveur indisponible ({type(e).__name__}: {str(e)[:100]})")
    finally:
        _drop_new_sessions(sessions_before)
        if modele is not None:
            try:
                restes = set(modele.objects.values_list('id', flat=True)) - ids_avant_orm
                if restes:
                    modele.objects.filter(id__in=restes).delete()
                    _nettoyes.append(len(restes))
            except Exception:
                pass

    if _nettoyes:
        detail += f" ; {sum(_nettoyes)} élément(s) de montage nettoyé(s)"
    return True, detail


# ── Montage d'un LOT : brique commune aux scénarios qui portent sur la card MÈRE ────────
# Extrait de `check_app_batch_actions` le 2026-08-27, quand `inspector_actions` en a eu besoin
# à son tour. Le recopier aurait dupliqué QUATRE avertissements chèrement acquis (deux fichiers
# et non un, l'id sur les boutons et non sur la mère, l'ORM hors `sync_playwright`, le nettoyage
# qui ne doit rien avaler) — exactement ce que la règle « zéro duplication » protège.

# Ids des cards MÈRES de lot (contrat `_batch_card.html` : `.wama-card.is-batch`).
# ⚠ La card MÈRE ne porte PAS `data-batch-id` — seuls ses BOUTONS le portent (la mère a
# `data-batch-total`, les boutons `data-batch-id`). Première version de `batch_actions` :
# 14 skips sur 14, l'id étant cherché sur la mère. Défaut d'INSTRUMENT, corrigé avant
# d'accuser une seule app.
_LOTS_EN_FILE = """(() => Array.from(document.querySelectorAll('.wama-card.is-batch'))
    .map(e => { const b = e.querySelector('[data-batch-id]');
                return b ? b.getAttribute('data-batch-id') : ''; })
    .filter(Boolean))()"""


# ── La voie de LOT : la seule création qui ne DÉMARRE rien ─────────────────────────────────
#
# POURQUOI ELLE EXISTE À CÔTÉ DU DÉPÔT ORDINAIRE. `_monter_un_lot` dépose deux fichiers de
# travail : cela ne marche QUE là où le dépôt CRÉE (`data-wama-depot=cree`). Sur avatarizer,
# composer et imager le dépôt ATTACHE — c'est le bouton primaire qui crée, et il DÉMARRE dans
# la foulée : composer expédie la tâche DANS sa vue de création (`composer/views.py:235`,
# `compose_task.apply_async`) et avatarizer enchaîne côté client (`avatarizer/js/index.js:253`,
# `createJob()` puis `startJob()`). Le geste n°7 de la grille est donc un geste GPU — et une
# session n'en lance jamais (crashs hôte).
#
# Le fichier de LOT est la seule voie de création dont le CONTRAT garantit qu'elle ne démarre
# rien : la barre commune sépare « Ajouter » (`#batchCreateOnlyBtn`) de « Démarrer »
# (`#batchCreateAndStartBtn`), et aucune des trois vues de création de lot ne porte de
# `.delay`/`apply_async` (relevé le 2026-08-27 : premier envoi à `imager/views.py:887`,
# `avatarizer/views.py:932`, `composer` dans `batch_start`). C'est donc elle qui ouvre la file
# de ces trois apps — et avec elle `batch_actions` ET `inspector_actions`.

# Les champs de RÉFÉRENCE ne créent rien (mélodie, avatar, voix de clonage, image de style).
# ⚠ Le champ de LOT, lui, n'est PAS exclu ici — contrairement à `_monter_un_lot` : c'est
# précisément celui qu'on vise.
_CHAMPS_DE_REFERENCE = '[id*="elody"], [id*="eference"], [id*="voice"], [id*="avatar"]'


class _LotRefuse(Exception):
    """Le geste du fichier de lot a été exercé, mais l'app n'a rien créé.

    Distinct d'un `SkipScenario` (surface absente : il n'y a rien à mesurer). Pour le scénario
    DÉDIÉ c'est un ÉCHEC — l'app publie un gabarit que sa propre chaîne refuse ; pour les
    scénarios qui ne font qu'EMPRUNTER cette voie afin de remplir une file, c'est une
    impossibilité de montage, donc un skip. Une seule mécanique, deux lectures.
    """


_GABARIT_DE_LOT = """(async () => {
    // Le gabarit est DÉCLARÉ par l'app (`batch_template_url` de la card commune) et rendu en
    // lien de téléchargement. On n'en fabrique donc aucun ici : un fichier de lot inventé
    // mesurerait NOTRE idée du format, pas celui que l'app publie à ses utilisateurs.
    const carte = document.querySelector('[data-wama-nic]');
    const lien = document.getElementById('batchTemplateLink')
              || (carte && carte.querySelector('a[download][href]'))
              || document.querySelector('a[download][href*="template"]');
    if (!lien) return null;
    try {
        const r = await fetch(lien.getAttribute('href'), {credentials: 'same-origin'});
        return r.ok ? await r.text() : null;
    } catch (e) { return null; }
})()"""


def _id_du_compte_de_test():
    """L'id du compte de test, lu DEPUIS UN THREAD ORDINAIRE.

    ⚠ `sync_playwright` installe une boucle d'événements dans le thread courant : tout accès
    ORM y lève `SynchronousOnlyOperation`. Mesuré le 2026-08-27 — le montage retombait alors
    sur le placeholder du gabarit, et l'app se voyait accusée de refuser son propre lot.
    Django ne l'interdit que dans le thread PORTEUR de la boucle : un thread nu suffit.
    """
    from concurrent.futures import ThreadPoolExecutor

    def _lire():
        from django.db import connections
        try:
            from wama.common.services.nightly_tests import get_test_user
            return getattr(get_test_user(), 'id', None)
        finally:
            connections.close_all()   # connexion propre au thread : à refermer avec lui

    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_lire).result(timeout=20)


def _source_resolvable(app: str, combien: int = 2):
    """`combien` médias RÉELS du compte de test ; (chemins relatifs à MEDIA_ROOT, Paths).

    POURQUOI. La source d'exemple d'un gabarit est un PLACEHOLDER (`https://example.com/…`).
    Les apps qui se contentent de STOCKER la source créent quand même l'élément ; celles qui la
    RÉSOLVENT à la création n'en créent aucun — le converter télécharge via
    `upload_media_from_url` et récolte un 404. Le maillon « un lot apparaît en file » n'y était
    donc pas mesuré, et un placeholder ne mesure de toute façon la chaîne qu'à moitié PARTOUT.
    On dépose un vrai fichier dans le domicile DÉCLARÉ des entrées d'app (`get_app_media_path`,
    le même helper que les vues) et on donne son chemin relatif, que les deux familles savent
    résoudre. L'appelant le supprime : voir `_monter_un_lot_par_gabarit`.

    `.wav` de silence : la seule extension acceptée à la fois par les apps média généralistes
    (converter : audio) et par les apps de parole (transcriber), sans dépendance d'encodage.

    ⚠ DES SOURCES DISTINCTES, jamais la même deux fois. Mesuré le 2026-08-27 sur l'avatarizer :
    deux lignes portant le MÊME chemin ne rendent qu'un élément à l'aperçu — l'app déduplique.
    Un élément = lot unitaire = pas de card mère (`_queue_entry.html`), donc « aucun lot créé »
    alors que la chaîne fonctionne. Doubler une URL d'exemple ne posait pas le problème ; un
    chemin réel, si. Un vrai lot porte de toute façon des sources différentes.
    """
    try:
        from wama.common.utils.media_paths import get_app_media_path
        uid = _id_du_compte_de_test()
        if not uid:
            return [], []
        dossier = get_app_media_path(app, uid, 'input')
        dossier.mkdir(parents=True, exist_ok=True)
        racine = Path(settings.MEDIA_ROOT).resolve()
        rels, cibles = [], []
        for i in range(1, combien + 1):
            cible = dossier / f'temoin_lot_nocturne_{i}.wav'
            cible.write_bytes(_wav_silence())
            cibles.append(cible)
            rels.append(str(cible.resolve().relative_to(racine)).replace('\\', '/'))
        return rels, cibles
    except Exception as exc:
        # ⚠ Best-effort, mais JAMAIS muet : sans média réel le témoin retombe sur le
        # placeholder du gabarit, et le scénario conclurait « l'app refuse son propre lot »
        # alors que c'est NOTRE montage qui a manqué. Le motif remonte dans le verdict.
        _source_resolvable.dernier_echec = f'{type(exc).__name__}: {exc}'
        return [], []


_source_resolvable.dernier_echec = ''


def _temoin_de_lot(texte: str, sources=()) -> Path:
    """Le gabarit de l'app, sa dernière ligne utile DOUBLÉE → au moins deux éléments.

    ⚠ DOUBLER, jamais inventer. Trois syntaxes de lot coexistent (`batch_parsers` : balises
    CLI, tableur à en-têtes, positionnel hérité) et l'app choisit la sienne : fabriquer une
    ligne ici mesurerait notre lecture du formalisme au lieu du gabarit réellement publié.
    Doubler la ligne d'exemple reste dans sa syntaxe, quelle qu'elle soit.

    ⚠ DEUX éléments au moins : un lot unitaire ne rend pas de card mère (`_queue_entry.html`
    ne pose `.batch-group` que si le lot n'est pas unitaire — leçon de `_monter_un_lot`).

    `sources` — remplace la VALEUR de l'exemple par des médias réels (un par ligne produite),
    et SEULEMENT si la ligne porte un champ unique (aucun délimiteur de colonnes). Substituer
    une valeur n'est pas inventer une ligne : la syntaxe reste celle du gabarit. On s'interdit
    en revanche de toucher aux lignes multi-colonnes, où l'on devrait deviner LAQUELLE est la
    source — c'est précisément la devinette que « doubler, jamais inventer » proscrit.
    """
    import tempfile
    lignes = (texte or '').splitlines()
    utiles = [l for l in lignes if l.strip() and not l.lstrip().startswith('#')]
    if not utiles:
        raise _LotRefuse("le gabarit publié par l'app ne contient que des commentaires — "
                         "aucune ligne d'exemple à déposer")
    exemple = utiles[-1]
    # « Source nue » = ni colonnes, ni BALISES. Le test des seuls délimiteurs ne suffit pas :
    # la ligne à balises de l'avatarizer (`-p "…" -r avatar1.png --language fr`) n'en contient
    # aucun, et la substituer par un chemin a détruit sa syntaxe — l'aperçu ne rendait plus
    # qu'un élément, donc plus de lot mère, donc « l'app refuse son lot » (mesuré 2026-08-27).
    # Un chemin ou une URL ne porte jamais de jeton commençant par « - ».
    nue = (not any(d in exemple for d in ('|', ',', ';', '\t'))
           and not any(t.startswith('-') for t in exemple.split()))
    if sources and nue:
        # L'exemple disparaît au profit des sources réelles, UNE PAR LIGNE (elles sont
        # distinctes : voir `_source_resolvable`, l'aperçu déduplique les identiques).
        avant = lignes[:lignes.index(exemple)]
        lignes = avant + list(sources)
        finales = lignes
    else:
        finales = lignes + [exemple]
    f = tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8')
    f.write('\n'.join(finales) + '\n')
    f.close()
    return Path(f.name)


def _monter_un_lot_par_gabarit(page, app: str = ''):
    """Dépose le FICHIER DE LOT publié par l'app, clique « Ajouter » ; rend (ids neufs, détail).

    NE DÉMARRE RIEN, par contrat de la barre commune : « Ajouter » (`#batchCreateOnlyBtn`)
    crée des éléments PENDING ; « Démarrer » (`#batchCreateAndStartBtn`) est l'AUTRE bouton,
    jamais cliqué ici. C'est ce qui rend ce geste exécutable de jour sur un GPU partagé.
    """
    from wama.common.services.nightly_tests import SkipScenario

    if not page.query_selector('#batchDetectBar'):
        raise SkipScenario("aucune barre de détection de lot dans la page (`show_batch_bar` "
                           "non déclaré) — le fichier de lot n'a pas de surface ici")
    # La card d'entrée est servie REPLIÉE par 6 apps sur 9 (mesuré le 2026-08-27) : sa barre de
    # lot existe alors au DOM avec des dimensions nulles, et « Ajouter » n'est jamais
    # actionnable. L'utilisateur l'ouvre d'un clic avant de déposer quoi que ce soit ; on fait
    # le même geste, sinon on mesurerait un repli et on l'écrirait « l'app refuse le lot ».
    _deplier_autour(page, '#batchDetectBar')
    texte = page.evaluate(_GABARIT_DE_LOT)
    if not texte:
        raise SkipScenario("l'app ne publie aucun gabarit de lot téléchargeable "
                           "(`batch_template_url` absent de sa card d'entrée)")
    # Deux formes coexistent, toutes deux DÉCLARÉES : un champ DÉDIÉ (`fileInputId` passé à
    # WamaBatchImport — composer : #batchFileInput), ou le champ ORDINAIRE de la card, l'app
    # routant elle-même les .txt/.csv vers la brique (imager : `routeFile` → `detectAndHandle` ;
    # avatarizer : même geste sur la zone audio). Au-delà, on ne devine pas.
    champ = (page.query_selector('input[type=file][id*="atch"]')
             or page.query_selector(
                 f'[data-wama-nic] input[type=file]:not({_CHAMPS_DE_REFERENCE})'))
    if not champ:
        raise SkipScenario("ni champ de lot dédié ni champ de fichier dans la card d'entrée — "
                           "nulle part où déposer le fichier de lot")

    lots0 = page.evaluate(_LOTS_EN_FILE) or []
    sources, medias = (_source_resolvable(app) if app else ([], []))
    if app and not sources:
        raise _LotRefuse("montage impossible : aucun média réel n'a pu être déposé pour le "
                         f"compte de test ({_source_resolvable.dernier_echec or 'raison inconnue'})")
    temoin = _temoin_de_lot(texte, sources)
    try:
        champ.set_input_files(str(temoin))
        # La barre ne s'ouvre qu'APRÈS l'aperçu SERVEUR : c'est lui qui compte les éléments, et
        # un fichier dont il tire 0 élément laisse la barre fermée SANS message
        # (`batch-import.js:140` — repli silencieux vers l'upload direct).
        try:
            page.wait_for_selector('#batchCreateOnlyBtn', state='visible', timeout=25000)
        except Exception:
            raise _LotRefuse(
                "le gabarit publié par l'app a bien été déposé, mais son propre aperçu de lot "
                "n'en tire aucun élément : la barre reste fermée, sans erreur ni message")
        compte = page.evaluate(
            "(document.getElementById('batchCreateCount') || {}).textContent || '?'")
        try:
            with page.expect_navigation(wait_until='load', timeout=30000):
                page.click('#batchCreateOnlyBtn', timeout=15000)
        except Exception:
            # Pas de navigation (une app peut rafraîchir sa file sans recharger) : le clic a
            # eu lieu, on ne le REJOUE PAS — un second « Ajouter » créerait un second lot.
            pass
        try:
            page.wait_for_load_state('networkidle', timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
    finally:
        for _f in [temoin, *medias]:
            try:
                if _f:
                    _f.unlink()
            except OSError:
                pass

    lots = page.evaluate(_LOTS_EN_FILE) or []
    nouveaux = [i for i in lots if i not in lots0]
    if not nouveaux:
        raise _LotRefuse(
            f"« Ajouter » cliqué sur un aperçu de {compte} élément(s), mais AUCUN lot nouveau "
            f"en file ({len(lots0)} → {len(lots)}) — création refusée, ou file non rafraîchie")
    return nouveaux, (f"fichier de lot déposé : {compte} élément(s) annoncés, "
                      f"{len(nouveaux)} lot(s) créé(s) sans démarrage")


def _monter_par_la_voie_de_lot(page, pourquoi: str, app: str = ''):
    """Emprunte la voie de lot pour REMPLIR une file ; tout refus y devient un SKIP.

    Ici on ne MESURE pas le geste — on s'en sert. Un refus ne dit donc rien de l'app qu'on
    voulait mesurer : le scénario dédié `<app>.batch_import`, lui, le compte comme un échec.
    """
    from wama.common.services.nightly_tests import SkipScenario
    try:
        return _monter_un_lot_par_gabarit(page, app)[0]
    except (_LotRefuse, SkipScenario) as exc:
        raise SkipScenario(f"{pourquoi} ; repli par le FICHIER DE LOT : {exc}")


def _monter_un_lot(page, app: str = ''):
    """Dépose deux fichiers témoins pour obtenir un LOT en file ; renvoie ses ids.

    ⚠ DEUX fichiers, pas un. Mesuré le 2026-08-24 sur converter : un dépôt simple crée une
    card ORDINAIRE, sans card mère (`is-batch` absent du DOM) — `_queue_entry.html` ne pose
    `.batch-group` que si le lot n'est PAS unitaire. Le lot n'apparaît qu'à partir de
    plusieurs fichiers de même nature. Première version de `batch_actions` : 14 skips sur 14
    pour cette seule raison.

    Lève `SkipScenario` si l'app n'offre pas de quoi monter — jamais un échec : ne pas
    pouvoir mesurer n'est pas la même chose que mesurer un défaut.

    DEUX VOIES, dans cet ordre : le dépôt ordinaire quand la card déclare qu'il CRÉE, sinon —
    et en repli quand il ne groupe pas — le FICHIER DE LOT publié par l'app.
    """
    exclus = '[id*="atch"], [id*="elody"], [id*="eference"], [id*="voice"], [id*="avatar"]'
    champ = page.query_selector(f'[data-wama-nic] input[type=file]:not({exclus})')
    # Ce que FAIT un dépôt ici est DÉCLARÉ, pas deviné (`_new_item_card.html`). `attache` =
    # le fichier se joint au formulaire et rien n'est créé : déposer y perdrait 8 s pour
    # conclure « l'app ne groupe pas », ce qui serait FAUX. On passe donc directement par la
    # voie de lot, qui est la voie de création de ces apps-là.
    depot = page.evaluate("""(() => {
        const c = document.querySelector('[data-wama-depot]');
        return c ? c.getAttribute('data-wama-depot') : 'cree'; })()""")
    if not champ or depot == 'attache':
        raison = ("la card DÉCLARE `data-wama-depot=attache` (le dépôt n'y crée rien)"
                  if depot == 'attache' else
                  "aucun champ d'import au contrat de la card commune")
        return _monter_par_la_voie_de_lot(page, raison, app)
    accept = champ.get_attribute('accept') or ''
    t1, t2 = _fichier_temoin(accept), _fichier_temoin(accept)
    try:
        if champ.get_attribute('multiple') is not None:
            champ.set_input_files([str(t1), str(t2)])
            page.wait_for_timeout(6000)
        else:
            champ.set_input_files(str(t1))
            page.wait_for_timeout(4000)
            champ = page.query_selector(
                f'[data-wama-nic] input[type=file]:not({exclus})') or champ
            champ.set_input_files(str(t2))
            page.wait_for_timeout(4000)
        lots = page.evaluate(_LOTS_EN_FILE)
    finally:
        for _t in (t1, t2):
            try:
                _t.unlink()
            except OSError:
                pass
    if not lots:
        return _monter_par_la_voie_de_lot(
            page, "deux dépôts de montage n'ont créé aucun LOT (card mère `is-batch` absente) "
                  "— l'app ne groupe pas, ou l'import échoue (cf. `<app>.import`)", app)
    return lots


def _total_nettoye(bilan) -> int:
    """Somme d'un bilan de `_garde_de_montage`, dont les entrées sont des (compte, modèle)."""
    return sum(n for n, _ in bilan)


@contextmanager
def _garde_de_montage(app: str, etiquette: str):
    """Recense les objets de l'app AVANT, puis supprime EN SORTIE ceux que le passage a créés.

    ⚠ DOIT ENVELOPPER le bloc `sync_playwright()`, jamais vivre dedans : l'ORM y lève
    `SynchronousOnlyOperation`, et un `except Exception: pass` AVALE cette erreur — le
    nettoyage semblait donc tourner alors qu'il ne faisait rien (mesuré : 39 objets accumulés
    en une session). D'où aussi le `print` explicite en cas d'échec : un nettoyage muet est
    pire qu'un nettoyage absent, puisqu'on croit l'avoir.

    ÉLÉMENTS d'abord, LOTS ensuite : dans la forme à FK directe (converter), supprimer le lot
    CASCADE sur ses éléments — l'inverse les ferait disparaître avant d'être comptés.
    On ne touche QUE ce que ce passage a créé (différence d'ids).
    """
    from wama.common.utils.batch_common import batch_model_for
    try:
        from wama.common.utils.preview_registry import PreviewRegistry
        modele = PreviewRegistry.get_model(app)
    except Exception:
        modele = None
    ids_avant = set()
    if modele is not None:
        try:
            ids_avant = set(modele.objects.values_list('id', flat=True))
        except Exception:
            modele = None
    # Le montage cree aussi des LOTS : `PreviewRegistry` ne connait que le modele d'ELEMENT,
    # d'ou l'accesseur DERIVE. Sans lui, des lots vides survivaient a chaque passage (9 chez
    # converter).
    modele_lot = batch_model_for(modele) if modele is not None else None
    lots_avant = set()
    if modele_lot is not None:
        try:
            lots_avant = set(modele_lot.objects.values_list('id', flat=True))
        except Exception:
            modele_lot = None

    bilan = []
    try:
        yield bilan
    finally:
        for _modele, _avant in ((modele, ids_avant), (modele_lot, lots_avant)):
            if _modele is None:
                continue
            try:
                restes = set(_modele.objects.values_list('id', flat=True)) - _avant
                if restes:
                    # Les FICHIERS avant les lignes. `QuerySet.delete()` ne touche AUCUN
                    # FileField : l'app copie la source dans son dossier d'entrée
                    # (`copy_into_app_input`) et cette copie survivait à l'objet — 6 `.wav`
                    # retrouvés dans `media/converter/…` le 2026-08-27. Un harnais ne laisse
                    # rien dans `media/`, qui est le domicile des entrées/sorties RÉELLES.
                    _racine = str(Path(settings.MEDIA_ROOT).resolve())
                    _champs = [f.name for f in _modele._meta.get_fields()
                               if getattr(f, 'get_internal_type', lambda: '')() in
                               ('FileField', 'ImageField')]
                    if _champs:
                        for _obj in _modele.objects.filter(id__in=restes).only(*_champs):
                            for _nom in _champs:
                                _fic = getattr(_obj, _nom, None)
                                try:
                                    _chemin = Path(_fic.path).resolve() if _fic else None
                                except Exception:
                                    _chemin = None
                                if _chemin and str(_chemin).startswith(_racine):
                                    _chemin.unlink(missing_ok=True)
                    _modele.objects.filter(id__in=restes).delete()
                    # (compte, modèle) et non un entier nu : un survivant ne veut pas dire la
                    # même chose selon qu'il s'agit d'un ÉLÉMENT ou d'un LOT — le second ne
                    # rend aucune card, donc aucun écran ne le trahit (cf. `check_app_clear_all`).
                    bilan.append((len(restes), _modele._meta.model_name))
            except Exception as _exc:            # ne JAMAIS avaler en silence
                bilan.append((0, getattr(getattr(_modele, '_meta', None), 'model_name', '?')))
                print(f"[{etiquette}] nettoyage {app} impossible : {type(_exc).__name__}")


def check_app_batch_actions(app: str, url_path: str):
    """Les actions de LOT (⧉ puis 🗑) agissent-elles vraiment ? (ok, detail).

    Geste 4 de la grille FONCTIONNELLE, et le premier qui porte sur le LOT et non sur
    l'élément. Il manquait : `<app>.duplicate_delete` mesure `.wama-card[data-id]`, donc la
    card FILLE — les boutons de la card MÈRE n'étaient couverts par aucun clic, alors même
    qu'ils venaient d'être portés à la brique commune (`queue-actions.js`, 2026-08-23/24).
    Un portage non exercé est un portage supposé.

    Ce qui est mesuré, dans cet ordre — le premier manquant explique les suivants :
      1. le partial ÉMET-il les URLs de lot (`actions_communes`) ? sinon l'app n'est pas portée
         et le scénario le DIT, sans prétendre mesurer un geste qui n'existe pas encore ;
      2. ⧉ ajoute-t-il un lot ?
      3. 🗑 retire-t-il celui qu'on vient d'ajouter ?

    Non destructif par construction : on ne supprime QUE le lot que l'on vient de créer,
    identifié par différence d'ids — jamais un lot préexistant de l'utilisateur.
    """
    from wama.common.services.nightly_tests import SkipScenario
    from playwright.sync_api import sync_playwright

    url = f"{BASE_URL.rstrip('/')}{url_path}"
    LOTS = _LOTS_EN_FILE
    # ⚠ Les URLs sont sur les BOUTONS, pas sur la card mère — c'est ce que lit la brique
    # (`actionDeLot` fait `closest('.batch-delete-btn[data-batch-delete-url]')`), et c'est là
    # que le partial les pose (`_batch_card.html:141/147`). Les chercher sur la mère faisait
    # conclure « app non portée » sur deux apps qui l'étaient — 3ᵉ défaut d'instrument de ce
    # scénario, tous trouvés avant d'avoir accusé une seule app.
    URLS = """(() => {
        const q = (c, a) => { const b = document.querySelector('.' + c + '[' + a + ']');
                              return b ? b.getAttribute(a) : null; };
        return {del:   q('batch-delete-btn',    'data-batch-delete-url'),
                dup:   q('batch-duplicate-btn', 'data-batch-duplicate-url'),
                start: q('batch-start-btn',     'data-batch-start-url')};
    })()"""

    jeton = _session_compte_de_test()
    if not jeton:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / ui_smoke_v3)")

    # Le montage crée deux éléments pour obtenir un lot ; la garde les retire en sortie.
    with _garde_de_montage(app, 'batch_actions') as _nettoyes:
      with sync_playwright() as p:
        navigateur = p.chromium.launch()
        try:
            contexte = navigateur.new_context(viewport={'width': 1500, 'height': 1000})
            contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': jeton,
                                   'domain': '127.0.0.1', 'path': '/'}])
            page = contexte.new_page()
            page.on('dialog', lambda d: d.accept())   # 🗑 confirme (confirm() natif)
            echecs = []
            page.on('response', lambda r: (
                echecs.append(f"{r.status} {r.url.split('?')[0]}")
                if r.request.method == 'POST' and r.status >= 400 else None))

            resp = page.goto(url, wait_until='networkidle', timeout=45000)
            if not resp or resp.status != 200:
                return False, f"page HTTP {resp.status if resp else '?'}"
            page.wait_for_timeout(1200)

            lots0 = page.evaluate(LOTS) or _monter_un_lot(page, app)

            # 1. L'app est-elle PORTEE ? (l'opt-in `actions_communes` emet les URLs)
            urls = page.evaluate(URLS) or {}
            manquantes = [k for k in ('del', 'dup', 'start') if not urls.get(k)]
            if manquantes:
                return False, (f"{len(lots0)} lot(s) en file mais la card mere n'emet pas "
                               f"{manquantes} — l'app n'a pas encore `actions_communes=True` "
                               f"(portage a la brique commune non fait)")

            # ⧉ et 🗑 de lot RECHARGENT la page (la brique ne leur déclare aucune suite) : il
            # FAUT attendre la navigation, sinon l'évaluation qui suit tombe dans un contexte
            # détruit — « Execution context was destroyed » (vu sur anonymizer, pas sur
            # converter : une race ne se manifeste pas partout, ce qui la rend trompeuse).
            def _clic_puis_rechargement(loc):
                try:
                    with page.expect_navigation(wait_until='load', timeout=30000):
                        loc.click(timeout=15000)
                except Exception:
                    loc.click(timeout=15000)          # pas de navigation : on retombe ici
                page.wait_for_load_state('networkidle', timeout=30000)
                page.wait_for_timeout(1200)

            # 2. ⧉ de LOT
            bouton_dup = page.locator('.wama-card.is-batch .batch-duplicate-btn:visible').first
            if not bouton_dup.count():
                return False, f"URLs emises mais aucun ⧉ de lot VISIBLE ({len(lots0)} lot(s))"
            _clic_puis_rechargement(bouton_dup)
            lots1 = page.evaluate(LOTS)
            if len(lots1) <= len(lots0):
                return False, (f"⧉ de lot cliquee mais la file n'a pas grandi "
                               f"({len(lots0)} → {len(lots1)})"
                               + (f" — POST en echec : {echecs}" if echecs else ""))
            nouveaux = [i for i in lots1 if i not in lots0]
            if not nouveaux:
                return False, "la file a grandi mais aucun id NOUVEAU — doublon non identifiable"

            # 3. 🗑 de LOT, sur le doublon SEULEMENT
            cible = nouveaux[0]
            # Le 🗑 porte lui-même l'id : on vise le BOUTON, pas la mère (qui ne l'a pas).
            btn_del = page.locator(f'.batch-delete-btn[data-batch-id="{cible}"]:visible').first
            if not btn_del.count():
                return False, (f"doublon #{cible} cree mais aucun 🗑 de lot dessus "
                               f"— NETTOYAGE IMPOSSIBLE, lot laisse en file")
            _clic_puis_rechargement(btn_del)
            lots2 = page.evaluate(LOTS)
            if cible in lots2:
                return False, (f"🗑 de lot cliquee mais le doublon #{cible} est TOUJOURS la "
                               + (f" — POST en echec : {echecs}" if echecs else ""))

            detail = (f"⧉ puis 🗑 de LOT exercés : {len(lots0)} → {len(lots1)} → "
                      f"{len(lots2)} lot(s) ; doublon #{cible} créé puis retiré")
        finally:
            navigateur.close()
    if _nettoyes:
        detail += f" ; {_total_nettoye(_nettoyes)} objet(s) de montage nettoyé(s)"
    return True, detail


def check_app_batch_import(app: str, url_path: str):
    """Un FICHIER DE LOT crée-t-il N éléments SANS en démarrer aucun ? (ok, detail).

    Geste 14 de la grille FONCTIONNELLE, moitié « fichier de lot » — les autres moitiés
    (import récursif de dossier, URL, « Envoyer vers ») restent à couvrir.

    POURQUOI CELUI-CI D'ABORD, ALORS QUE LE PLAN ANNONÇAIT LE GESTE N°7. Le geste n°7
    (« créer par le bouton primaire ») devait débloquer d'un coup `inspector_actions` et
    `batch_actions` sur avatarizer, composer et imager — les trois apps dont la file reste
    vide. Mesuré le 2026-08-27, il s'est révélé être un geste **GPU** : composer expédie la
    tâche DANS sa vue de création (`composer/views.py:235`) et avatarizer enchaîne
    `createJob()` puis `startJob()` côté client (`avatarizer/js/index.js:253-254`). Seul
    l'imager crée sans lancer. Une session ne déclenche jamais de traitement (crashs hôte) :
    le geste n°7 rejoint donc la famille 8-13, et c'est le fichier de lot qui atteint le même
    but par la seule voie dont le contrat garantit qu'elle ne démarre rien.

    Trois constats, du plus structurel au plus concret — le premier qui manque explique les
    suivants :
      1. l'app PUBLIE-t-elle un gabarit de lot et une barre de détection ?
      2. déposer CE gabarit ouvre-t-il un aperçu, et « Ajouter » crée-t-il un LOT ?
      3. le contrat « créer ≠ démarrer » est-il TENU — aucun appel de démarrage émis ?

    ⚠ Le point 3 n'est pas décoratif : c'est lui qui autorise ce scénario à tourner de jour
    sur un GPU partagé. S'il tombe, ce n'est pas seulement l'app qui est en défaut — c'est ce
    scénario qui doit CESSER d'être exécuté tant que ce n'est pas corrigé.
    """
    from wama.common.services.nightly_tests import SkipScenario
    from playwright.sync_api import sync_playwright

    url = f"{BASE_URL.rstrip('/')}{url_path}"
    jeton = _session_compte_de_test()
    if not jeton:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / ui_smoke_v3)")

    # Le geste CRÉE des éléments et un lot : la garde retire en sortie ceux de ce passage,
    # et rien d'autre (différence d'ids) — jamais un objet du travail réel de l'utilisateur.
    with _garde_de_montage(app, 'batch_import') as _nettoyes:
      with sync_playwright() as p:
        navigateur = p.chromium.launch()
        try:
            contexte = navigateur.new_context(viewport={'width': 1500, 'height': 1000})
            contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': jeton,
                                   'domain': '127.0.0.1', 'path': '/'}])
            page = contexte.new_page()
            posts = []
            page.on('response', lambda r: (posts.append((r.status, r.url.split('?')[0]))
                                           if r.request.method == 'POST' else None))
            # Un refus LIGNE À LIGNE ne passe par aucun code HTTP : la vue répond 200 avec
            # `count: 0` et ses `warnings`, et la brique les affiche (toast, ou `alert` si
            # `WamaApp` manque). On collecte les DEUX surfaces — sans elles, un refus expliqué
            # et une chaîne cassée rendent le même verdict aveugle « aucun lot nouveau ».
            dialogues = []
            page.on('dialog', lambda d: (dialogues.append(d.message), d.dismiss()))
            resp = page.goto(url, wait_until='networkidle', timeout=45000)
            if not resp or resp.status != 200:
                return False, f"page HTTP {resp.status if resp else '?'}"
            page.wait_for_timeout(1200)
            # Le toast s'efface seul au bout de 3,5 s (`wama-app-base.js:128`) : le lire APRÈS
            # le geste serait une course. On l'observe donc à la volée.
            page.evaluate("""() => {
                window.__wamaToasts = [];
                new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => {
                    if (n.nodeType === 1 && n.classList && n.classList.contains('wama-toast'))
                        window.__wamaToasts.push(n.textContent);
                }))).observe(document.body, {childList: true});
            }""")

            try:
                _nouveaux, detail = _monter_un_lot_par_gabarit(page, app)
            except _LotRefuse as exc:
                rates = [f"{s} {u}" for s, u in posts if s >= 400]
                try:
                    dits = list(dialogues) + (page.evaluate("window.__wamaToasts || []") or [])
                except Exception:
                    dits = list(dialogues)
                # L'app a-t-elle DIT pourquoi ? Si oui, la chaîne n'est pas muette : elle a
                # tourné jusqu'au bout et a rendu son motif à l'utilisateur. Le cas connu est
                # la SOURCE D'EXEMPLE : le converter résout la source à la création
                # (`upload_media_from_url`) et l'URL du gabarit est un placeholder injoignable,
                # là où les apps qui stockent la source sans la résoudre créent l'élément.
                # ⚠ Le maillon « un lot apparaît en file » reste alors NON MESURÉ pour cette
                # app — trou NOMMÉ, à fermer avec un média réel, pas un skip qui l'enterre.
                if dits:
                    raise SkipScenario(
                        f"{exc} — mais l'app a rendu son motif : « {dits[0][:220]} ». Chaîne "
                        f"exercée jusqu'au refus ; le maillon « lot créé » reste non mesuré "
                        f"tant que le gabarit porte une source d'exemple non résolvable.")
                return False, (f"{exc}"
                               + (f" — POST en échec : {' | '.join(rates[:2])}" if rates else ""))
            rates = [f"{s} {u}" for s, u in posts if s >= 400]
            if rates:
                return False, f"{detail}, MAIS requête(s) en échec : {' | '.join(rates[:2])}"

            # Contrat « créer ≠ démarrer ». Relevé PAR MOTIF sur l'URL : il ORIENTE, il ne
            # prouverait pas l'absence de démarrage par une autre voie. Il suffit ici, où les
            # trois routes de démarrage de lot finissent toutes par `/start/` — et l'absence
            # de tout `.delay` dans les vues de création a été vérifiée à la lecture.
            demarrages = [u for s, u in posts if u.rstrip('/').endswith('/start')]
            if demarrages:
                return False, (f"{detail} — MAIS le contrat « créer ≠ démarrer » est ROMPU : "
                               f"{demarrages[0]} appelé. Un traitement a été lancé : ce "
                               f"scénario ne peut plus tourner de jour en l'état.")
            detail += f" ; aucun appel de démarrage ({len(posts)} POST observé(s))"
        finally:
            navigateur.close()
    if _nettoyes:
        detail += f" ; {_total_nettoye(_nettoyes)} objet(s) de test nettoyé(s)"
    return True, detail


def register_batch_import_scenarios():
    """Enregistre un scénario `<app>.batch_import` par app disposant d'une page d'index."""
    from wama.common.services.nightly_tests import register

    for label, path in discoverable_apps():
        register(
            id=f"{label}.batch_import", app=label, stage="ui",
            description=f"Card d'entrée {label} : un FICHIER DE LOT crée N éléments sans "
                        f"rien démarrer",
            run=(lambda p=path, a=label: (lambda ctx: check_app_batch_import(a, p)))(),
            timeout_s=240, vram_gb=0.0,
        )


def register_batch_actions_scenarios():
    """Enregistre un scénario `<app>.batch_actions` par app disposant d'une page d'index."""
    from wama.common.services.nightly_tests import register

    for label, path in discoverable_apps():
        register(
            id=f"{label}.batch_actions", app=label, stage="ui",
            description=f"File {label} : ⧉ puis 🗑 sur la card MÈRE d'un lot (brique commune)",
            run=(lambda p=path, a=label: (lambda ctx: check_app_batch_actions(a, p)))(),
            timeout_s=240, vram_gb=0.0,
        )


# ── Geste 5 : TOUT EFFACER ─────────────────────────────────────────────────────────────
#
# Le seul geste du catalogue dont l'effet VOULU est destructeur : il n'y a pas de version
# « qui ne touche que ce que le passage a créé ». On ne peut donc pas l'exercer comme les
# autres, et ce n'est pas une raison de ne pas le mesurer — c'est une raison de BORNER :
#   • il ne s'exerce que sous le COMPTE DE TEST (`_session_compte_de_test`, qui ne forge
#     jamais de compte) — sans lui, skip, jamais de repli sur un compte réel ;
#   • les dix vues `clear_all` filtrent toutes sur `user=` (relevé le 2026-08-28, 10/10) :
#     la portée du geste est donc close par le code, pas par la prudence de l'instrument.
# La garde de montage reste posée : après l'effacement, la différence d'ids est vide, elle
# n'a plus rien à retirer — ce qui est exactement l'aveu que le geste a fait son travail.
_FILE_EN_ETAT = """(() => {
    const cartes = Array.from(document.querySelectorAll('[data-id]'))
        .filter(e => /card/.test(String(e.className || '')) && e.dataset.id)
        .map(e => e.dataset.id);
    const lots = Array.from(document.querySelectorAll('.wama-card.is-batch'))
        .map(e => { const b = e.querySelector('[data-batch-id]');
                    return b ? b.getAttribute('data-batch-id') : ''; })
        .filter(Boolean);
    const enCours = document.querySelectorAll('[data-status="RUNNING"]').length;
    return {cartes: Array.from(new Set(cartes)), lots: Array.from(new Set(lots)),
            en_cours: enCours};
})()"""


def check_app_clear_all(app: str, url_path: str):
    """« Tout effacer » vide-t-il la file — TOUT DE SUITE et POUR DE BON ? (ok, detail).

    Geste 5 de la grille FONCTIONNELLE. Deux vérités sont mesurées, et elles ne sont pas la
    même : ce que l'utilisateur VOIT juste après son clic, et ce que le serveur a réellement
    supprimé. Les séparer n'est pas du zèle — les gestionnaires d'app retirent les cards à la
    main après le POST (`queryContainer.querySelectorAll('.synthesis-card').forEach(remove)`,
    transcriber), donc tout ce qui n'est pas visé par ce sélecteur SURVIT à l'écran jusqu'au
    rechargement. Une file qui garde une card mère de lot après « Tout effacer » tient une
    promesse à moitié, et aucune erreur console ne le dit.

    Ce qui est mesuré, dans cet ordre — le premier manquant explique les suivants :
      1. le bouton commun existe-t-il (`_queue_actions.html` → `.btn-outline-danger`) ?
      2. le POST d'effacement répond-il sans erreur ?
      3. la file est-elle vide À L'ÉCRAN, sans rechargement ?
      4. l'est-elle encore APRÈS rechargement — c'est-à-dire côté serveur ?

    ⚠ Un élément RUNNING fait SKIPPER, jamais échouer : deux apps refusent alors le geste par
    contrat (avatarizer répond 400 « stoppez-le avant de tout effacer », composer et le codegen
    font `.exclude(status='RUNNING')`). Un reste zombie du compte de test — ils existent, cf.
    `reference_orphan_task_reconcile` — accuserait donc une app pour l'état d'une fixture.
    """
    from wama.common.services.nightly_tests import SkipScenario
    from playwright.sync_api import sync_playwright

    url = f"{BASE_URL.rstrip('/')}{url_path}"
    jeton = _session_compte_de_test()
    if not jeton:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / ui_smoke_v3)")

    with _garde_de_montage(app, 'clear_all') as _nettoyes:
      with sync_playwright() as p:
        navigateur = p.chromium.launch()
        try:
            contexte = navigateur.new_context(viewport={'width': 1500, 'height': 1000})
            contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': jeton,
                                   'domain': '127.0.0.1', 'path': '/'}])
            page = contexte.new_page()
            page.on('dialog', lambda d: d.accept())   # `confirm('Supprimer tout ?')`
            posts = []
            page.on('response', lambda r: (
                posts.append((r.status, r.url.split('?')[0]))
                if r.request.method == 'POST' and 'clear' in r.url else None))

            resp = page.goto(url, wait_until='networkidle', timeout=45000)
            if not resp or resp.status != 200:
                return False, f"page HTTP {resp.status if resp else '?'}"
            page.wait_for_timeout(1200)

            etat0 = page.evaluate(_FILE_EN_ETAT)
            if not etat0['cartes'] and not etat0['lots']:
                _monter_un_lot(page, app)             # lève SkipScenario si l'app n'offre rien
                page.goto(url, wait_until='networkidle', timeout=45000)
                page.wait_for_timeout(1500)
                etat0 = page.evaluate(_FILE_EN_ETAT)
            if not etat0['cartes'] and not etat0['lots']:
                raise SkipScenario("file vide après montage — il n'y a rien à effacer")
            if etat0['en_cours']:
                raise SkipScenario(
                    f"{etat0['en_cours']} élément(s) RUNNING en file : deux apps refusent alors "
                    f"le geste par contrat (400 avatarizer, exclusion composer) — mesurer ici "
                    f"accuserait l'app pour l'état de la fixture")

            # 1. Le bouton COMMUN. Les dix index passent par `_queue_toolbar.html`, qui inclut
            #    `_queue_actions.html` : le « Tout effacer » y est le seul `.btn-outline-danger`
            #    de `.wama-queue-actions`. On ne cherche donc AUCUN id d'app — ils diffèrent tous
            #    (`clearAllBtn`, `transcriber-clear-btn`, `anon-clear-all-btn`…) et les lister
            #    referait par recopie ce que le partial commun a justement centralisé.
            bouton = page.locator('.wama-queue-actions button.btn-outline-danger:visible').first
            if not bouton.count():
                return False, ("aucun « Tout effacer » au contrat commun "
                               "(`.wama-queue-actions .btn-outline-danger`) — l'index de l'app "
                               "n'inclut pas `_queue_actions.html`")

            # 2. Le POST. Certaines apps rechargent dans la foulée : on tolère la navigation.
            try:
                with page.expect_response(
                        lambda r: r.request.method == 'POST' and 'clear' in r.url,
                        timeout=30000) as attendu:
                    bouton.click(timeout=15000)
                reponse = attendu.value
                statut = reponse.status
            except Exception:
                statut = None
            page.wait_for_timeout(1500)
            if statut is not None and statut >= 400:
                if statut == 400:
                    raise SkipScenario(f"l'app REFUSE l'effacement (HTTP 400) — {posts}")
                return False, f"le POST d'effacement répond HTTP {statut} ({posts})"
            if statut is None and not posts:
                return False, ("« Tout effacer » cliqué mais AUCUN POST d'effacement émis — "
                               "le bouton commun est rendu, son handler ne l'est pas")

            # 3. Ce que l'utilisateur VOIT, sans rechargement.
            try:
                etat1 = page.evaluate(_FILE_EN_ETAT)
            except Exception:
                etat1 = None                          # l'app a rechargé : rien à reprocher

            # 4. Ce que le SERVEUR a vraiment supprimé.
            page.goto(url, wait_until='networkidle', timeout=45000)
            page.wait_for_timeout(1200)
            etat2 = page.evaluate(_FILE_EN_ETAT)
            if etat2['cartes'] or etat2['lots']:
                return False, (f"effacement demandé (POST {statut or 'ok'}) mais après "
                               f"rechargement il reste {len(etat2['cartes'])} card(s) et "
                               f"{len(etat2['lots'])} lot(s) — la file n'est PAS vidée")
            if etat1 is not None and (etat1['cartes'] or etat1['lots']):
                return False, (f"la file n'est vidée qu'au RECHARGEMENT : juste après le clic il "
                               f"reste à l'écran {len(etat1['cartes'])} card(s) et "
                               f"{len(etat1['lots'])} lot(s) — le retrait client ne vise pas "
                               f"tout ce que le serveur a supprimé")

            detail = (f"« Tout effacer » exercé : {len(etat0['cartes'])} card(s) + "
                      f"{len(etat0['lots'])} lot(s) → 0/0 à l'écran ET après rechargement "
                      f"(POST {statut or 'ok'})")
        finally:
            navigateur.close()
    # 5. Ce qu'aucun écran ne montre. La garde retire en sortie ce que le passage a créé et qui
    #    existe ENCORE : après « Tout effacer », ce compte doit être NUL. Il ne l'est pas
    #    partout — un LOT vidé de ses éléments ne rend aucune card, donc il survit en base sans
    #    que rien ne le signale (mesuré le 2026-08-28 sur converter : `jobs.delete()` ne touche
    #    pas `ConversionBatch`, là où reader et composer purgent explicitement leurs lots et où
    #    transcriber s'en remet au signal `post_delete`). C'est le même défaut que les 9 lots
    #    vides que cette garde a dû balayer le 2026-08-24 — sauf qu'ici il est DEMANDÉ à l'app.
    if _nettoyes:
        _restes = ", ".join(f"{n} {nom}" for n, nom in _nettoyes if n)
        return False, (f"{detail} — mais {_total_nettoye(_nettoyes)} objet(s) du montage "
                       f"SURVIVENT en base ({_restes}) : « Tout effacer » laisse derrière lui "
                       f"ce qui ne rend aucune card")
    return True, detail


def register_clear_all_scenarios():
    """Enregistre un scénario `<app>.clear_all` par app disposant d'une page d'index."""
    from wama.common.services.nightly_tests import register

    for label, path in discoverable_apps():
        register(
            id=f"{label}.clear_all", app=label, stage="ui",
            description=f"File {label} : « Tout effacer » vide la file à l'écran ET au serveur",
            run=(lambda p=path, a=label: (lambda ctx: check_app_clear_all(a, p)))(),
            timeout_s=240, vram_gb=0.0,
        )


_CLIC_DOM = """(a) => {
    const sel = a.portee === 'item' ? '[data-id="' + a.id + '"]'
                                    : '.batch-group[data-batch-id="' + a.id + '"]';
    const hote = document.querySelector(sel);
    if (!hote) return {ok: false, raison: 'hôte introuvable après re-rendu (' + sel + ')'};
    hote.dispatchEvent(new MouseEvent('click',
                                      {bubbles: true, cancelable: true, view: window}));
    return {ok: true};
}"""


def _clic_de_selection(page, portee: str, ident: str) -> str:
    """Sélectionne la cible marquée ; renvoie le MODE de clic réellement employé.

    ⚠ 5ᵉ défaut d'instrument de cette famille, mesuré le 2026-08-27 sur `reader` (échec
    reproductible 2 passages sur 2, `TimeoutError: Locator.click`). Deux causes se
    cumulent, et AUCUNE n'est un défaut de l'app :

      1. la file se RE-REND toute seule. Le reader sonde `/<app>/<id>/html/` environ une
         fois par seconde tant qu'un élément est PENDING — 19 requêtes en 4 s au relevé.
         Chaque re-rendu remplace le nœud, donc EFFACE l'attribut `data-wama-nightly-cible`
         posé par `CIBLE` : la cible mesurée à t=0,9 s avait disparu à t=1,2 s ;
      2. le nœud reparaît en pleine animation `wama-fan-in` (`wama-inspector.css:116`,
         .42 s) : boîte qui glisse de 547 à 558 px, opacité 0,11 → 1. Playwright exige
         qu'un élément soit « stable » (boîte inchangée sur deux trames) avant de cliquer.

    Le locator re-résout donc en boucle sur un nœud neuf, toujours en mouvement, jusqu'à
    expiration. Un humain, lui, clique sans difficulté : c'est la STRICTESSE de l'outil de
    mesure qui bute, pas la card.

    D'où deux étages, dans cet ordre et jamais l'inverse :
      * clic RÉEL d'abord (preuve la plus forte : l'élément est visible, stable, et reçoit
        bien les événements) ;
      * à défaut, clic DOM `dispatchEvent` sur l'hôte, retrouvé par son `data-id` /
        `data-batch-id` — qui, eux, survivent au re-rendu. Il remonte par bouillonnement
        jusqu'à la délégation de `wama-inspector.js`, donc il mesure exactement le contrat
        visé (délégation → `selectItem`/`selectBatch` → remplissage du volet). Il ne prouve
        PAS l'atteignabilité au pointeur — le détail le DIT (`[clic DOM …]`), on ne fait pas
        passer la mesure faible pour la forte.
    """
    try:
        page.locator('[data-wama-nightly-cible]').first.click(timeout=6000)
        return 'clic réel'
    except Exception as exc:
        secours = page.evaluate(_CLIC_DOM, {'portee': portee, 'id': str(ident)})
        if not secours.get('ok'):
            raise RuntimeError(
                f"ni clic réel ni clic DOM : {type(exc).__name__} puis "
                f"{secours.get('raison')}") from exc
        return 'clic DOM — file en re-rendu continu, élément jamais « stable »'


# ── Désélection : la MOITIÉ due du geste 6 ─────────────────────────────────────────────
#
# `common.volet.deselection` mesure déjà la désélection, mais sur une file SYNTHÉTIQUE et sur
# UNE page (transcriber) : c'est une non-régression de BRIQUE pour le défaut du 2026-08-22.
# Elle ne dit rien de ce que fait chaque app avec ses propres cards — or c'est exactement ce
# que `WAMA_VERIFICATION` compte comme la moitié due du geste 6.
#
# On la greffe donc ici plutôt que dans un scénario à part : le coût de ces scénarios est le
# MONTAGE DE FIXTURE (un lot multi-éléments, 10 à 25 s par app), pas les clics. Un scénario
# jumeau paierait ce montage une deuxième fois pour trois clics de plus.

_MARQUE_CROIX = """() => {
    const visible = (e) => { const r = e.getBoundingClientRect();
                             return r.width > 2 && r.height > 2; };
    document.querySelectorAll('[data-wama-nightly-croix]')
            .forEach(e => e.removeAttribute('data-wama-nightly-croix'));
    // On ne présume PAS de l'hôte (#inspectorInfo vs bandeau) : la brique rend le ✕ sur deux
    // chemins distincts (`fillDetail` pour l'item, l'en-tête de lot pour la mère). On cherche
    // le CONTRAT — la classe — où qu'il soit rendu.
    const croix = Array.from(document.querySelectorAll('.wama-info-deselect')).filter(visible);
    if (!croix.length) return {ok: false, raison: "aucun ✕ `.wama-info-deselect` visible dans "
                                                  + "le volet après sélection"};
    croix[0].setAttribute('data-wama-nightly-croix', '1');
    return {ok: true};
}"""

_CLIC_DOM_CROIX = """() => {
    const c = document.querySelector('[data-wama-nightly-croix]');
    if (!c) return {ok: false, raison: 'le ✕ a disparu avant le clic DOM'};
    c.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
    return {ok: true};
}"""

# Ce qui doit AVOIR DISPARU. Deux surfaces, car un seul des deux nettoyages suffit à laisser
# l'UI dans un état faux : un volet vidé mais une card encore surlignée, c'est la sélection
# fantôme du 2026-08-22 ; une card dé-surlignée mais un volet encore peuplé, ce sont des
# actions qui s'appliqueraient à un élément que l'utilisateur ne voit plus désigné.
_RESTE_SELECTION = """() => {
    const h = document.getElementById('inspectorActions');
    return {boutons: h ? h.querySelectorAll('button, a.btn').length : 0,
            surlignees: document.querySelectorAll('.inspector-selected').length};
}"""


def _clic_de_deselection(page):
    """Ferme la sélection par le ✕ ; renvoie (mode employé, raison de non-mesure).

    Même doctrine à deux étages que `_clic_de_selection`, et pour la même raison mesurée :
    clic RÉEL d'abord (preuve forte), clic DOM en secours quand la file se re-rend sous
    l'outil. Le mode est REMONTÉ dans le détail — on ne fait pas passer la mesure faible
    pour la forte.
    """
    # Le ✕ de l'item n'est PAS rendu par le clic : il l'est par `fillDetail`, à l'arrivée
    # de `/common/detail/<app>/<pk>/`. Le chercher juste après le clic mesure donc la
    # LATENCE de cette requête, pas la présence du ✕ — et transcriber, dont l'adaptateur
    # de détail est le plus lourd, a été le seul déclaré « désélection NON MESURÉE » le
    # 2026-08-28 alors que son ✕ arrive bien (mesuré à 1,8 s). 7ᵉ défaut d'instrument de
    # cette famille. On ATTEND l'apparition, bornée ; l'absence reste un vrai constat.
    try:
        page.wait_for_selector('.wama-info-deselect', state='visible', timeout=4000)
    except Exception:
        pass
    marque = page.evaluate(_MARQUE_CROIX)
    if not marque.get('ok'):
        return None, marque.get('raison')
    try:
        page.locator('[data-wama-nightly-croix]').first.click(timeout=4000)
        return 'clic réel', None
    except Exception as exc:
        secours = page.evaluate(_CLIC_DOM_CROIX)
        if not secours.get('ok'):
            return None, (f"ni clic réel ni clic DOM sur le ✕ : {type(exc).__name__} "
                          f"puis {secours.get('raison')}")
        return 'clic DOM — ✕ jamais « stable »', None


def check_app_inspector_actions(app: str, url_path: str):
    """SÉLECTIONNER une card (puis un lot) remplit-il le volet ACTIONS — et le ✕ le vide-t-il ?

    ANGLE MORT DU NOCTURNE JUSQU'AU 2026-08-27, et il a coûté deux défauts MUETS.
    `<app>.batch_actions` clique les boutons DE LA CARD — il n'emprunte jamais la
    SÉLECTION, or c'est elle seule qui appelle `renderItemActions`/`renderBatchActions`
    (`wama-inspector.js`, `selectItem`/`selectBatch` → `fillActions`). Sont donc passés
    sous les radars :
      * le contrat INVERSÉ de `renderBatchActions` — TypeError au clic sur une card
        mère, dans 4 apps, atteint sur le compte de Fabien (2026-08-26) ;
      * l'imager qui ne déclarait AUCUN des deux rappels : `fillActions` fait
        `if (renderFn)`, donc le volet restait VIDE — sans erreur, sans journal.
    Un volet vide NE PLANTE PAS. Seule une assertion sur son CONTENU le voit :
    c'est tout l'objet de ce scénario. Cf. « ce qui ne plante pas ne se signale pas ».

    PORTÉE DES ÉCRITURES. La mesure elle-même n'est QUE des clics de sélection —
    aucun POST, rien de modifié. Mais le chemin « card MÈRE » n'existe pas sans un
    lot multi-éléments (cf. plus bas), que le compte de test n'a presque jamais :
    ce scénario en monte donc un quand il manque, sous `_garde_de_montage` qui
    retire en sortie CE QU'IL A CRÉÉ et rien d'autre (différence d'ids). Il ne
    touche jamais un objet préexistant, ni le moindre compte réel.

    ⚠ INSTRUMENT — on ne code EN DUR aucun sélecteur de card. Ils diffèrent par app
    (`.anon-card`, `.job-card`, `.imager-card[data-id]`, `.synthesis-card`,
    `.generation-card`, `.wama-card`…) et une union figée dériverait au premier
    portage. On s'appuie sur ce que fait la délégation elle-même : elle remonte par
    `e.target.closest(CARD_SEL)`. Il suffit donc de cliquer N'IMPORTE OÙ dans la
    card, sur un descendant qui n'est ni bouton, ni lien, ni champ, ni aperçu, ni
    zone d'actions — la liste EXACTE que la délégation ignore (`wama-inspector.js`).
    C'est la leçon des 3 défauts d'instrument de `batch_actions` : mesurer le
    contrat, jamais une recopie du contrat.
    """
    from wama.common.services.nightly_tests import SkipScenario
    from playwright.sync_api import sync_playwright

    url = f"{BASE_URL.rstrip('/')}{url_path}"

    # Marque une cible cliquable et la renvoie. `portee` vaut 'item' ou 'lot'.
    #   item : un descendant sûr d'un élément portant `data-id` (une card) ;
    #   lot  : un descendant sûr d'un `.batch-group[data-batch-id]` qui n'est DANS
    #          aucune card — sinon la délégation sélectionne l'item et jamais le lot
    #          (elle teste la card AVANT le lot : `wama-inspector.js`).
    CIBLE = """(portee) => {
        const IGNORE = 'button, a, input, select, textarea, .wama-card-preview, .btn-group-actions';
        const visible = (e) => { const r = e.getBoundingClientRect();
                                 return r.width > 4 && r.height > 4; };
        document.querySelectorAll('[data-wama-nightly-cible]')
                .forEach(e => e.removeAttribute('data-wama-nightly-cible'));
        // Les cards FILLES d'un lot vivent dans un `.collapse` REPLIÉ (`_queue_entry.html`) :
        // taille nulle, donc injouables, et l'instrument concluait « aucune card en file »
        // sur des apps qui en avaient — 4ᵉ défaut d'instrument de cette famille (mesuré le
        // 2026-08-27 sur converter et describer, juste après le montage du lot). On déplie,
        // ce que fait le chevron de la card mère : on rend la cible atteignable, on ne
        // truque pas ce qui est mesuré (le remplissage du volet reste intact).
        if (portee === 'item') {
            document.querySelectorAll('.batch-group .collapse')
                    .forEach(c => c.classList.add('show'));
        }
        let hotes;
        if (portee === 'item') {
            hotes = Array.from(document.querySelectorAll('[data-id]'))
                .filter(e => e.dataset.id && !e.closest(IGNORE) && !e.matches(IGNORE));
        } else {
            hotes = Array.from(document.querySelectorAll('.batch-group[data-batch-id]'))
                .filter(e => e.dataset.batchId);
        }
        // Un clic RÉEL atterrit au CENTRE de l'élément marqué — pas sur l'élément
        // marqué. Un conteneur peut donc être « cliquable » et voir son centre occupé
        // par un enfant que la délégation IGNORE : le clic part, rien ne se passe, et
        // l'instrument accuse l'app. C'est ce qui est arrivé au converter, seule app à
        // écrire son propre emballage `.batch-group` autour de l'en-tête ET du repli
        // des filles (les autres : `.batch-group` EST la card mère) — 6ᵉ défaut
        // d'instrument de cette famille, mesuré le 2026-08-28. On vérifie donc ce que
        // la délégation verra VRAIMENT : `elementFromPoint` au point de clic.
        const atterrit_bien = (c, hote) => {
            const r = c.getBoundingClientRect();
            const x = r.left + r.width / 2, y = r.top + r.height / 2;
            if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return null;  // hors écran
            const dessus = document.elementFromPoint(x, y);
            if (!dessus || dessus.closest(IGNORE)) return false;
            if (portee === 'lot') return !dessus.closest('[data-id]')
                                          && dessus.closest('.batch-group[data-batch-id]') === hote;
            const carte = dessus.closest('[data-id]');
            return !!carte && carte.dataset.id === hote.dataset.id;
        };
        for (const hote of hotes) {
            if (!visible(hote)) continue;
            const candidats = [hote, ...hote.querySelectorAll('*')];
            for (const c of candidats) {
                if (c.closest(IGNORE) || c.matches(IGNORE)) continue;
                if (portee === 'lot' && c.closest('[data-id]')) continue;
                if (!visible(c)) continue;
                if (c.children.length && c !== hote) continue;   // feuille de préférence
                if (atterrit_bien(c, hote) === false) continue;  // null = hors écran, on tente
                c.setAttribute('data-wama-nightly-cible', '1');
                return {ok: true, id: hote.dataset.id || hote.dataset.batchId,
                        tag: c.tagName.toLowerCase()};
            }
        }
        return {ok: false, hotes: hotes.length};
    }"""

    # Ce que le volet contient APRÈS sélection. On compte des boutons, pas des octets :
    # un volet peut porter un titre sans une seule action, et c'est un échec.
    CONTENU = """() => {
        const h = document.getElementById('inspectorActions');
        if (!h) return {absent: true};
        return {absent: false,
                boutons: h.querySelectorAll('button, a.btn').length,
                texte: (h.innerText || '').trim().slice(0, 120)};
    }"""

    jeton = _session_compte_de_test()
    if not jeton:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / ui_smoke_v3)")

    # ⚠ Le chemin « card MÈRE » EXIGE un lot multi-éléments : `_queue_entry.html` ne pose
    # `.batch-group` QUE si le lot n'est pas unitaire. Or le compte de test n'en possède
    # quasiment aucun (mesuré le 2026-08-27 : 4 lots multi sur les 10 apps, tous comptes
    # confondus). Premier passage sans montage : 3 OK / 7 « file vide » — le chemin qui
    # portait le contrat inversé de `renderBatchActions` restait DONC non mesuré, dans un
    # scénario écrit pour lui. On monte le lot, comme `batch_actions`, et la garde le retire.
    with _garde_de_montage(app, 'inspector_actions') as _nettoyes:
      with sync_playwright() as p:
        navigateur = p.chromium.launch()
        try:
            contexte = navigateur.new_context(viewport={'width': 1500, 'height': 1000})
            contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': jeton,
                                   'domain': '127.0.0.1', 'path': '/'}])
            page = contexte.new_page()
            erreurs_js = []
            page.on('pageerror', lambda e: erreurs_js.append(str(e)[:160]))

            resp = page.goto(url, wait_until='networkidle', timeout=45000)
            if not resp or resp.status != 200:
                return False, f"page HTTP {resp.status if resp else '?'}"
            page.wait_for_timeout(1200)

            if page.evaluate(CONTENU).get('absent'):
                raise SkipScenario("pas de volet #inspectorActions sur cette page "
                                   "(app non portée à `_inspector_actions.html`)")

            # ⚠ Un montage qui échoue ne doit PAS emporter la mesure de l'autre chemin :
            # 4 apps ne savent pas grouper (avatarizer, enhancer, imager, transcriber —
            # cf. leurs skips de `batch_actions`), or leur chemin « item » est mesurable et
            # transcriber l'avait déjà validé (card #237 → 4 boutons). On note donc la raison
            # et on continue : deux chemins, deux verdicts.
            monte, raison_lot = False, None
            if not page.evaluate(CIBLE, 'lot').get('ok'):
                try:
                    _monter_un_lot(page, app)
                    # Rechargement : on mesure la file telle que le SERVEUR la rend, pas
                    # l'état laissé par le script d'import.
                    page.goto(url, wait_until='networkidle', timeout=45000)
                    page.wait_for_timeout(1500)
                    monte = True
                except SkipScenario as _exc:
                    raison_lot = str(_exc)

            constats, mesures, deselections = [], 0, 0
            for portee, libelle in (('item', 'card'), ('lot', 'card MÈRE de lot')):
                cible = page.evaluate(CIBLE, portee)
                if not cible.get('ok'):
                    constats.append(
                        f"{libelle} : NON MESURÉ — "
                        + (raison_lot if portee == 'lot' and raison_lot
                           else "aucune en file (rien à sélectionner)"))
                    continue
                mode = _clic_de_selection(page, portee, cible['id'])
                page.wait_for_timeout(700)
                etat = page.evaluate(CONTENU)
                if etat.get('boutons', 0) < 1:
                    # ⚠ Le détail d'échec REMONTE ce qui a déjà été mesuré. Sans ça, un échec sur
                    # le 2ᵉ chemin efface le verdict du 1ᵉʳ et impose une re-mesure de 20 s pour
                    # savoir ce qui marchait — défaut d'instrument constaté le 2026-08-28.
                    return False, (
                        f"sélection d'une {libelle} (#{cible['id']}) : le volet Actions reste "
                        f"VIDE — {'callback absent' if not erreurs_js else 'JS en erreur'} "
                        f"(rappel : `fillActions` fait `if (renderFn)`, un rappel manquant ne "
                        f"lève RIEN ; mode de clic : {mode})"
                        + (f" ; déjà mesuré : {' ; '.join(constats)}" if constats else "")
                        + (f" ; {' | '.join(erreurs_js)}" if erreurs_js else ""))
                trace = (f"{libelle} #{cible['id']} → {etat['boutons']} bouton(s)"
                         + ('' if mode == 'clic réel' else f" [{mode}]"))
                mesures += 1

                # ── seconde moitié du geste 6 : le ✕ referme-t-il la sélection ? ──
                mode_des, pourquoi = _clic_de_deselection(page)
                if mode_des is None:
                    trace += f", désélection NON MESURÉE ({pourquoi})"
                else:
                    page.wait_for_timeout(500)
                    reste = page.evaluate(_RESTE_SELECTION)
                    if reste.get('boutons', 0) or reste.get('surlignees', 0):
                        return False, (
                            f"sélection d'une {libelle} (#{cible['id']}) : le ✕ ne referme pas "
                            f"— {reste.get('boutons')} bouton(s) encore dans le volet Actions et "
                            f"{reste.get('surlignees')} card(s) encore surlignée(s). Une "
                            f"sélection FANTÔME : les actions du volet désignent un élément que "
                            f"l'utilisateur ne voit plus sélectionné (défaut du 2026-08-22)"
                            + (f" ; {' | '.join(erreurs_js)}" if erreurs_js else ""))
                    trace += (", ✕ → volet vidé et surbrillance retirée"
                              + ('' if mode_des == 'clic réel' else f" [{mode_des}]"))
                    deselections += 1
                constats.append(trace)

            if erreurs_js:
                return False, f"volet rempli mais JS en erreur : {' | '.join(erreurs_js)}"
            if not mesures:
                raise SkipScenario("aucun chemin mesurable — " + " ; ".join(constats))
            detail = ("sélection → volet Actions" + (" → ✕" if deselections else "") + " : "
                      + " ; ".join(constats)
                      + (" (lot monté pour l'occasion)" if monte else ""))
            if not deselections:
                # ⚠ Le geste 6 ne vaut PAS couvert si seule sa première moitié a été exercée.
                # Le dire dans le détail, sinon un vert se lira comme le geste entier — c'est
                # exactement le faux vert que `WAMA_VERIFICATION` traque.
                detail += " ⚠ MOITIÉ — désélection non mesurée sur cette app"
        finally:
            navigateur.close()
    if _nettoyes:
        detail += f" ; {_total_nettoye(_nettoyes)} objet(s) de montage nettoyé(s)"
    return True, detail


def register_inspector_actions_scenarios():
    """Enregistre un scénario `<app>.inspector_actions` par app disposant d'un index."""
    from wama.common.services.nightly_tests import register

    for label, path in discoverable_apps():
        register(
            id=f"{label}.inspector_actions", app=label, stage="ui",
            description=(f"File {label} : SÉLECTIONNER une card puis un lot remplit le volet "
                         f"Actions, et le ✕ le referme (geste 6 entier ; chemin que "
                         f"`batch_actions` n'emprunte pas)"),
            run=(lambda p=path, a=label: (lambda ctx: check_app_inspector_actions(a, p)))(),
            timeout_s=180, vram_gb=0.0,
        )


def register_settings_scenarios():
    """Enregistre un scénario `<app>.settings` par app disposant d'une page d'index."""
    from wama.common.services.nightly_tests import register

    for label, path in discoverable_apps():
        register(
            id=f"{label}.settings", app=label, stage="ui",
            description=f"File {label} : le ⚙ d'un élément ouvre une modale de paramètres",
            run=(lambda p=path, a=label: (lambda ctx: check_app_settings(a, p)))(),
            timeout_s=180, vram_gb=0.0,
        )


# ── Volet droit : la DÉSÉLECTION d'un batch ────────────────────────────────────────────
#
# POURQUOI CE SCÉNARIO EXISTE. Le ✕ d'un batch ne désélectionnait RIEN sur 7 pages
# (anonymizer, composer, converter, describer, enhancer, reader, transcriber) : `showBatchInfo`
# proxifiait le clic par le bouton du bandeau (`$(ids.deselect).click()`), or ce bandeau a été
# retiré de ces pages le 2026-07-08 (PROJECT_STATUS §21.3.6). `od` valait null, le clic tombait
# dans le vide, et seule la touche Échap désélectionnait. AUCUNE erreur console : le défaut est
# invisible aux scénarios `<app>.ui`, qui ne mesurent que la santé de la page.
#
# CE QU'IL MESURE, ET SUR QUOI. La BRIQUE, pas les données : le scénario injecte une file
# SYNTHÉTIQUE (un batch, deux cards) dans la page, y câble un `WamaInspector` à lui, exerce le
# geste et retire tout. Il ne dépend donc d'aucun élément en base — il tourne sur une file vide,
# toutes les nuits, sans rien créer ni supprimer. Une variante « cliquer un vrai batch » aurait
# exigé des données de test, donc un scénario qui SKIPPE la plupart des nuits.
#
# La page hôte est celle d'une app RÉELLEMENT touchée, et le scénario VÉRIFIE qu'elle n'a pas
# de bandeau : c'est la condition exacte du défaut. Si un bandeau y réapparaissait, le proxy
# masquerait la régression — le scénario le dit au lieu de passer au vert par accident.

VOLET_GESTE = """(() => {
    const R = {banniere: !!document.getElementById('inspectorBanner')};
    if (!window.WamaInspector || typeof window.WamaInspector.init !== 'function') {
        R.erreur = 'WamaInspector absent de la page'; return R;
    }
    const box = document.createElement('div');
    box.id = 'voletTestQueue';
    box.style.display = 'none';
    box.innerHTML = '<div class="batch-group" data-batch-id="999999">'
        + '<div data-batch-total="2" data-batch-success="1" data-batch-running="0" data-batch-failure="0"></div>'
        + '<div class="synthesis-card" data-id="999001"></div>'
        + '<div class="synthesis-card" data-id="999002"></div>'
        + '</div>';
    document.body.appendChild(box);
    try {
        // keyboardNav:false — l'instance de test ne doit pas laisser d'écouteur clavier
        // au niveau `document` derrière elle (le conteneur, lui, part avec `box.remove()`).
        const insp = window.WamaInspector.init({
            queueContainer: box, cardSelector: '.synthesis-card',
            batchSelector: '.batch-group', keyboardNav: false,
        });
        if (!insp) { R.erreur = 'init() a rendu null'; return R; }
        insp.selectBatch('999999');
        const grp = box.querySelector('.batch-group');
        R.selectionne = grp.classList.contains('inspector-selected');
        R.batch_avant = (insp.state() || {}).batchId;
        const croix = document.querySelector('#inspectorInfo .wama-info-deselect');
        R.croix = !!croix;
        if (croix) croix.click();
        R.batch_apres = (insp.state() || {}).batchId;
        R.encore_selectionne = grp.classList.contains('inspector-selected');
    } catch (e) {
        R.erreur = String(e && e.message || e);
    } finally {
        box.remove();
    }
    return R;
})()"""


def check_volet_deselection(app: str, url_path: str):
    """Le ✕ d'un batch désélectionne-t-il vraiment ? (ok, detail)."""
    from wama.common.services.nightly_tests import SkipScenario
    from playwright.sync_api import sync_playwright

    url = f"{BASE_URL.rstrip('/')}{url_path}"
    sessions_before = _session_keys()
    # ⚠ Lecture ORM AVANT sync_playwright (SynchronousOnlyOperation) — même contrainte
    # que le scénario d'import.
    jeton = _session_compte_de_test()
    if not jeton:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / ui_smoke_v3) "
                           "— la page d'app exige une session")
    try:
        with sync_playwright() as p:
            navigateur = p.chromium.launch()
            try:
                contexte = navigateur.new_context(viewport={'width': 1500, 'height': 1000})
                contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': jeton,
                                       'domain': '127.0.0.1', 'path': '/'}])
                page = contexte.new_page()
                resp = page.goto(url, wait_until='networkidle', timeout=45000)
                if not resp or resp.status != 200:
                    return False, f"page HTTP {resp.status if resp else '?'}"
                page.wait_for_timeout(800)
                r = page.evaluate(VOLET_GESTE)
            finally:
                navigateur.close()
    except Exception as e:
        raise SkipScenario(f"navigateur/serveur indisponible ({type(e).__name__}: {str(e)[:100]})")
    finally:
        _drop_new_sessions(sessions_before)

    if r.get('erreur'):
        return False, f"brique inutilisable : {r['erreur']}"
    if not r.get('selectionne'):
        return False, ("`selectBatch` n'a pas surligné le batch synthétique — le contrat de "
                       "sélection a changé (classe `inspector-selected` / `.batch-group`)")
    if not r.get('croix'):
        return False, ("aucun ✕ (`.wama-info-deselect`) dans #inspectorInfo après sélection d'un "
                       "batch : `showBatchInfo` ne rend plus son bouton de fermeture")
    if r.get('encore_selectionne') or r.get('batch_apres') is not None:
        return False, (f"RÉGRESSION : le ✕ du batch ne désélectionne pas (batch "
                       f"{r.get('batch_avant')} → {r.get('batch_apres')}, surbrillance "
                       f"{'toujours là' if r.get('encore_selectionne') else 'retirée'}). "
                       "C'est le défaut du 2026-08-22 : le ✕ proxifiait par le bouton du "
                       "bandeau, absent de cette page.")
    banniere = "⚠ un bandeau est réapparu sur cette page — la condition du défaut n'est plus " \
               "reproduite ici" if r.get('banniere') else "sans bandeau (condition du défaut)"
    return True, (f"✕ du batch : sélection {r.get('batch_avant')} → désélection effective, "
                  f"surbrillance retirée ; {banniere}")


# ── Volet droit : DEUX inspecteurs sur la même page ────────────────────────────────────
#
# POURQUOI. `enhancer` (image + audio) et `imager` (image + vidéo) câblent DEUX instances sur
# une seule page, une par domaine. Or les hôtes du volet sont uniques par page (#inspectorInfo,
# #inspectorActions, #media-section… lus par id fixe) : les deux instances écrivaient dans les
# mêmes éléments sans se connaître. Sélectionner dans un domaine puis basculer sur l'autre
# laissait DEUX sélections vivantes — volet peuplé par la première, sa card toujours surlignée
# dans une file devenue invisible (mesuré 2026-08-22, WAMA_VOLETS §4②).
#
# Le scénario reproduit la situation avec deux files SYNTHÉTIQUES : il vaut donc pour toute
# page à instances multiples, présente ou future, sans dépendre des données d'enhancer.

VOLET_DEUX_INSTANCES = """(() => {
    const R = {};
    if (!window.WamaInspector || typeof window.WamaInspector.init !== 'function') {
        R.erreur = 'WamaInspector absent de la page'; return R;
    }
    const boites = ['A', 'B'].map((n, i) => {
        const b = document.createElement('div');
        b.id = 'voletTest' + n;
        b.style.display = 'none';
        b.innerHTML = '<div class="synthesis-card" data-id="99900' + (i + 1) + '"></div>';
        document.body.appendChild(b);
        return b;
    });
    try {
        const insp = boites.map(b => window.WamaInspector.init({
            queueContainer: b, cardSelector: '.synthesis-card', keyboardNav: false,
        }));
        if (!insp[0] || !insp[1]) { R.erreur = 'init() a rendu null'; return R; }
        insp[0].selectItem('999001');
        R.a_seule = insp[0].state().itemId;
        insp[1].selectItem('999002');
        R.a_apres_b = insp[0].state().itemId;
        R.b_apres_b = insp[1].state().itemId;
        R.surbrillances = document.querySelectorAll(
            '#voletTestA .inspector-selected, #voletTestB .inspector-selected').length;
    } catch (e) {
        R.erreur = String(e && e.message || e);
    } finally {
        boites.forEach(b => b.remove());
    }
    return R;
})()"""


def check_volet_instances(app: str, url_path: str):
    """Deux inspecteurs coexistant : le second chasse-t-il la sélection du premier ? (ok, detail)."""
    from wama.common.services.nightly_tests import SkipScenario
    from playwright.sync_api import sync_playwright

    url = f"{BASE_URL.rstrip('/')}{url_path}"
    sessions_before = _session_keys()
    jeton = _session_compte_de_test()
    if not jeton:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / ui_smoke_v3)")
    try:
        with sync_playwright() as p:
            navigateur = p.chromium.launch()
            try:
                contexte = navigateur.new_context(viewport={'width': 1500, 'height': 1000})
                contexte.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': jeton,
                                       'domain': '127.0.0.1', 'path': '/'}])
                page = contexte.new_page()
                resp = page.goto(url, wait_until='networkidle', timeout=45000)
                if not resp or resp.status != 200:
                    return False, f"page HTTP {resp.status if resp else '?'}"
                page.wait_for_timeout(800)
                r = page.evaluate(VOLET_DEUX_INSTANCES)
            finally:
                navigateur.close()
    except Exception as e:
        raise SkipScenario(f"navigateur/serveur indisponible ({type(e).__name__}: {str(e)[:100]})")
    finally:
        _drop_new_sessions(sessions_before)

    if r.get('erreur'):
        return False, f"brique inutilisable : {r['erreur']}"
    if r.get('a_seule') != '999001':
        return False, ("la 1re instance n'a pas sélectionné son élément "
                       f"(itemId={r.get('a_seule')!r}) — contrat de sélection changé")
    if r.get('b_apres_b') != '999002':
        return False, ("la 2e instance n'a pas pris la sélection "
                       f"(itemId={r.get('b_apres_b')!r})")
    if r.get('a_apres_b') is not None or r.get('surbrillances') != 1:
        return False, (f"RÉGRESSION : deux sélections vivantes à la fois — 1re instance "
                       f"itemId={r.get('a_apres_b')!r} après sélection dans la 2e, "
                       f"{r.get('surbrillances')} card(s) surlignée(s) au lieu d'une. "
                       "C'est le défaut du 2026-08-22 sur enhancer/imager : les instances "
                       "partagent les hôtes du volet sans se connaître.")
    return True, ("2 inspecteurs coexistants : la sélection de la 2e chasse celle de la 1re "
                  f"(1 seule card surlignée, itemId {r.get('a_seule')} → None)")


def register_volet_scenarios():
    """Enregistre les scénarios de volet droit (WAMA_VOLETS §4) — ✕ de batch, instances."""
    from wama.common.services.nightly_tests import register

    # Page hôte FIXE et VÉRIFIÉE : le transcriber est l'une des 7 pages mesurées sans bandeau
    # (2026-08-22). La déduire dynamiquement ferait porter le test par une page qui pourrait,
    # elle, avoir un bandeau — donc masquer la régression. Chemin par `reverse` et non écrit
    # en dur : une URL supposée est une source d'aller-retours.
    from django.urls import NoReverseMatch, reverse
    try:
        chemin = reverse('transcriber:index')
    except NoReverseMatch:                                    # pragma: no cover
        return
    register(
        id="common.volet.deselection", app="common", stage="ui",
        description="Volet droit : le ✕ d'un batch désélectionne (brique, file synthétique)",
        run=(lambda p=chemin: (lambda ctx: check_volet_deselection('transcriber', p)))(),
        timeout_s=120, vram_gb=0.0,
    )
    register(
        id="common.volet.instances", app="common", stage="ui",
        description="Volet droit : deux inspecteurs coexistants ne gardent qu'une sélection",
        run=(lambda p=chemin: (lambda ctx: check_volet_instances('transcriber', p)))(),
        timeout_s=120, vram_gb=0.0,
    )

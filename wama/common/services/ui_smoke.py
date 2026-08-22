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
    contenu = png if ext in ('.png', '.jpg', '.jpeg', '.webp') else b'temoin import WAMA\n'
    f = tempfile.NamedTemporaryFile('wb', suffix=ext, delete=False)
    f.write(contenu); f.close()
    return Path(f.name)


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
                bouton_dup = page.query_selector(DUP)
                if not bouton_dup:
                    return False, (f"{len(ids0)} élément(s) en file mais AUCUN bouton de "
                                   "duplication (ni `.duplicate-btn`, ni suffixe équivalent) — "
                                   "la convention de card n'est pas tenue par cette app")
                graphies = page.evaluate(
                    "(() => {const n = c => [...document.querySelectorAll(c)]"
                    ".flatMap(e => [...e.classList]).filter(x => x.endsWith('delete-btn') "
                    "|| x.endsWith('duplicate-btn')); return [...new Set(n('*'))].join(', ');})()")

                bouton_dup.click()
                page.wait_for_timeout(3000)
                ids1 = page.evaluate(IDS)
                nouveaux = [i for i in ids1 if i not in ids0]
                if len(ids1) <= len(ids0) or not nouveaux:
                    return False, (f"clic sur `.duplicate-btn` : la file ne bouge pas "
                                   f"({len(ids0)} → {len(ids1)} cards)"
                                   + (f" ; requêtes en échec : {echecs[0]}" if echecs else
                                      " ; AUCUNE requête en échec — le bouton n'est pas écouté"))

                doublon = nouveaux[0]
                cible = page.query_selector(f'.wama-card[data-id="{doublon}"] :is({DEL})') \
                    or page.query_selector(f':is({DEL})[data-id="{doublon}"]')
                if not cible:
                    return False, (f"doublon #{doublon} créé, mais aucun bouton de suppression "
                                   f"ne le porte (graphies vues dans la page : {graphies or '—'}) "
                                   "— il RESTE en file (nettoyé par le filet ORM)")
                cible.click()
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

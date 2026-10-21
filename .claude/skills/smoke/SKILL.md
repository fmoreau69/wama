---
name: smoke
description: Validation visuelle et fonctionnelle réelle de WAMA dans le navigateur (script Playwright → PNG → Read ; le MCP navigateur peut être là ou non — vérifier, jamais supposer). Utiliser pour les « validations navigateur en attente », après un port d'app, ou quand l'utilisateur demande de vérifier visuellement une page.
---

# /smoke — Validation navigateur réelle

Objectif : fermer l'angle mort récurrent « ⚠ RESTE À VALIDER NAVIGATEUR » des handoffs. On vérifie
le RENDU RÉEL, pas la structure du code.

## 0. Préconditions
- Le serveur doit tourner (WSL2) : vérifier `http://localhost:8000` répond (curl -s -o /dev/null
  -w '%{http_code}'). S'il ne répond pas, DEMANDER à l'utilisateur de le lancer — ne pas le
  démarrer soi-même sans demande.
  ⚠ **Et il doit servir le code qu'on mesure** (2026-09-18) : un gunicorn non rechargé sert
  l'ancien Python — une route neuve y rend 404, et le scénario accuserait le code. Le live ne se
  recharge jamais soi-même ; la mesure se fait alors sur un **serveur de dev jetable, sur un autre
  port** (recette en fin de skill), qu'on arrête après. C'est la seule exception à « ne pas
  démarrer soi-même », et elle ne touche pas au live.
- **Le MCP Playwright existe, mais sa disponibilité VARIE — la vérifier, jamais la supposer.**
  Corrigé le 2026-08-22 : ce skill affirmait « aucun MCP Playwright n'est configuré » (constat du
  31/07). C'est faux — ses outils sont déclarés dans les allowlists (`.claude/settings.json` et
  `settings.local.json`) et étaient disponibles en début de session. Ce qui reste vrai du constat
  d'origine : il n'y a **pas de `.mcp.json` dans le dépôt** (le serveur est déclaré au niveau du
  CLI, pas du projet) — d'où la confusion.
  ⚠ Mesuré le 22/08 : la connexion MCP **est tombée en cours de session** et les outils ont
  DISPARU du registre. Un skill qui promet une passe MCP fait donc perdre du temps une fois sur
  deux. **Vérifier au moment** (`ToolSearch` sur `mcp__playwright__…`), et retomber sans état
  d'âme sur la route qui, elle, ne dépend de rien :
- **Route FIABLE, indépendante du MCP : script Playwright (python) → PNG → `Read`.** L'outil de
  lecture rend l'image, la vérification visuelle marche sans MCP. Le dépôt a déjà ses sondes
  (`logs/ui_smoke/*.py`) et surtout ses scénarios enregistrés — cf. la charpente ci-dessous.
  - ⚠ **LE `/tmp` DE WINDOWS N'EST PAS CELUI DE WSL2** (ajouté le 2026-09-12, un aller-retour
    perdu). Le script s'écrit dans le scratchpad de session, qui est côté Windows ; le lancer
    sous WSL2 exige donc le chemin `/mnt/c/...` équivalent — pas une copie vers `/tmp`, qui
    atterrit dans le `/tmp` de l'hôte et laisse WSL dire `No such file or directory`.
    ✅ `wsl.exe -e bash -lc 'cd /mnt/d/WAMA/... && venv_linux/bin/python "/mnt/c/Users/<…>/scratchpad/<sonde>.py"'`
    — et ne PAS déposer la sonde dans le dépôt pour contourner (elle y resterait).
- Navigateurs installés **côté WSL2** (`~/.cache/ms-playwright`, chromium-1228), `playwright`
  importable dans `venv_linux` **et** `venv_win` → lancer le script sous WSL2, là où tourne aussi
  le serveur.
- **AVANT d'écrire un script : réutiliser la brique.** `wama/common/services/ui_smoke.py` fait
  déjà chargement + erreurs console + parcours des onglets + capture + diff + triage VLM, et
  `python manage.py run_nightly_tests --stage ui` l'exécute sur toutes les apps. 🔴 **Le nombre
  de scénarios ne se recopie PAS** — ce skill a annoncé « 13 apps, 2 familles » jusqu'au
  2026-08-26 alors qu'il y en avait **72 scénarios sur 14 apps, en 7 familles**. Toujours
  commencer par `--list`.
- **PLUSIEURS familles de scénarios, et elles ne disent pas la même chose.** Au 2026-08-26 :
  `.ui` (SANTÉ : HTTP 200, zéro erreur console) · `.settings` (le ⚙ ouvre une modale) ·
  `.import` (un dépôt crée-t-il un élément ?) · `.duplicate_delete` · `.batch_actions` (⧉ puis 🗑
  sur la card MÈRE) · plus les scénarios transverses `common.volet.*`.
  ⚠ **La SANTÉ ne prouve aucun COMPORTEMENT** : `converter_01` satisfaisait `.ui` en étant
  totalement INERTE — aucun script chargé, donc rien à planter. C'est la raison d'être des
  familles qui CLIQUENT ; une app verte sur `.ui` seule n'est pas une app vérifiée.
  Sélection : `--id <id>`, préfixe `--id converter_01.`, suffixe `--id .import`, ou `--list`.
  **Une sonde ad hoc de plus dans `logs/ui_smoke/` (17 au 26/08) est presque toujours la mauvaise
  réponse : la faire entrer ici la rend rejouable et nocturne.**
- ⚠ **Aucune lecture ORM À L'INTÉRIEUR de `sync_playwright()`** — Django lève
  `SynchronousOnlyOperation`. Préparer sessions, ids et comptes AVANT d'ouvrir le contexte, et
  faire les comptages/nettoyages APRÈS l'avoir refermé. Piège rencontré deux fois le 22/08.
- ⚠ **Se connecter avec un compte de TEST existant** (`wama_nightly_test`, `wama_ui_smoke_v3`,
  `wama_pw_smoke` — préfixe `wama_` depuis le 2026-10-01), jamais en anonyme : depuis la fermeture du 22/08, le compte anonyme n'a plus aucun
  rôle ni tier utilisateur — une passe anonyme mesure des DROITS en croyant mesurer un
  comportement. Ne pas forger un compte : en inventer un inventerait ses droits.
- ⚠ JAMAIS d'action destructive : pas de suppression d'items, pas de « Tout effacer », pas de
  lancement de génération lourde GPU sans accord. Le user id=1 est le compte réel de Fabien.

## 1. Sources des points à valider
- `docs/construction/suivi/PROJECT_STATUS.md` : chercher « valider navigateur » / « validation navigateur » (sections
  20bis, 21, 23…) — c'est la liste de dette visuelle accumulée.
- Le chantier du jour : chaque élément UI touché.

## 2. Procédure par page
1. Naviguer vers la page (`/transcriber/`, `/composer/`…), attendre le chargement réseau.
2. Screenshot pleine page + screenshots ciblés (card d'entrée, file, card mère batch, inspecteur).
3. LIRE le screenshot et confronter aux attendus déclarés (CARD_DESIGN, conventions §9.8, ordre
   des boutons ⚙▶⬇⧉🗑, barre de progression, chips, toolbar).
4. Interactions non destructives seulement : déplier/replier un batch, sélectionner une card
   (inspecteur), ouvrir/fermer une modale ⚙, trier/filtrer.
5. Console navigateur : relever les erreurs JS.

## 3. Rapport
- Par page : ✅ conforme / ❌ écart (avec screenshot à l'appui + description précise de l'écart).
- Mettre à jour les mentions « validation navigateur en attente » de PROJECT_STATUS pour ce qui
  est validé (via /palier).
- Ne JAMAIS marquer validé ce qui n'a pas été vu à l'écran.

## 4. Pièges vécus (2026-07-31) — tous ont coûté un aller-retour

- **NE PAS DEVINER les sélecteurs ni les URLs.** `main` n'existe nulle part (13/13 en faux échec) ;
  les URLs se prennent par `reverse("<app>:<nom>")`. Mesurer d'abord, coder ensuite :
  `#appTabsContent` existe sur les 10 apps du gabarit commun, `.container-fluid` sur les 13.
- **Une file VIDE ne mesure rien.** En anonyme il n'y a aucune card dans le DOM : en conclure
  qu'« aucun sélecteur de card commun n'existe » est faux (`WamaInspector.initFromSchema` déclare
  un `cardSelector` par app). Pour tester une card, il faut du contenu — compte de test + partage.
- **Un compte neuf est redirigé (302)** par la couche d'accès aux apps (`@app_access`) AVANT la vue :
  ce n'est pas la fonctionnalité testée qui échoue. Lui donner les Groups `role:*`.
- **Nos propres clics mutent le DOM** : revérifier la visibilité juste avant chaque clic, et ne
  compter comme erreur que ce qui reste visible après l'échec.
- **`OLLAMA_HOST` doit être exporté** (Ollama tourne sur l'hôte Windows) sinon le triage VLM
  échoue en silence — les couches déterministes, elles, continuent de fonctionner.
- **`innerText` subit `text-transform: uppercase`** (19/08) : chercher « Réglages » dans le texte
  rendu échoue sur les libellés stylés en capitales — comparer en minuscules, ou viser les nœuds
  (`.wama-insp-sec-lbl`) plutôt que le texte.
- **Le gear ⚙ n'a PAS de sélecteur uniforme** (mesuré 19/08) : `[data-action="settings"]`
  (enhancer, contrat cardSettings), `.settings-btn` (transcriber/imager…), `.job-settings-btn`
  (converter), `.btn-settings-job` (avatarizer). Les viser TOUS ; et `closest()` sur la card doit
  inclure `[class*="-card"]`.
- **Le cookie de session s'appelle `settings.SESSION_COOKIE_NAME`** (`wama_sessionid`) —
  jamais `sessionid` en dur : une sonde ad hoc qui le code en dur navigue en ANONYME et
  mesure des droits en croyant mesurer la page (vécu 30/08 ; la brique `ui_smoke` le lit
  déjà de settings, s'en inspirer).
  ⚠ **Par le MCP navigateur, `document.cookie` NE PEUT PAS le poser** (2026-09-06) : le
  serveur en a déjà déposé un, `HttpOnly`, que JS n'a pas le droit d'écraser — l'écriture
  échoue en SILENCE et on reste anonyme. Passer par le contexte Playwright :
  `browser_run_code_unsafe` → `page.context().addCookies([{name, value, domain:'localhost',
  path:'/', httpOnly:true}])`, puis naviguer. La clé se forge hors navigateur, exactement
  comme `ui_smoke._test_session_key` : `get_test_user()` (déclaratif, rôles
  `communication` + `recherche`) puis `SessionStore` avec `_auth_user_id` /
  `_auth_user_backend` / `_auth_user_hash`.
  *Vécu le 2026-09-06 : faute de cette voie, j'ai conclu « /studio/ inatteignable, smoke
  impossible » — alors que le compte, ses rôles ET le mécanisme existaient déjà, et que ce
  paragraphe nommait déjà le compte et le cookie. Un blocage d'outillage se vérifie contre
  le dépôt AVANT d'être annoncé comme une limite.* Et un marqueur DOM peut être ABSENT à l'état vide
  légitime (`#ragListe` sans document) ou injecté par JS conditionnel — vérifier la
  CONDITION du gabarit avant de conclure, la capture lue tranche.
- **Le compte smoke doit porter les Groups `user` + `role:*`** sinon @app_access répond 302 vers
  l'accueil — et une page « chargée » peut être L'ACCUEIL après redirect : vérifier un marqueur de
  la page visée, pas le seul code 200 (piège vécu sur `/converter_01/`).
- **Le contrôle « zéro erreur console » est le plus rentable** : il a trouvé une double inclusion
  de brique globale (`MediaPicker`) sur 2 apps dès la 1re exécution (relevé du 19/08), sur des
  pages utilisées tous
  les jours. `node --check` ne voit que la syntaxe, jamais une erreur au chargement.
- ⚠ **Une capture d'ÉLÉMENT hors de la zone visible d'un conteneur qui DÉFILE sort déformée**
  (2026-10-10) : `locator('#llmKeysList').screenshot()` dans le volet droit, liste à y=941 dans une
  fenêtre de 1000, rendait des lignes superposées et une police à empattements — on aurait conclu
  au portage cassé. Les styles calculés étaient justes (`input-group` en flex, police système).
  ✅ `scrollIntoView` de l'élément, puis capture de la PAGE ; et vérifier `getComputedStyle`
  avant de déclarer un rendu cassé sur la foi d'une capture d'élément.
- ⚠ **Une page réservée aux ADMINS se mesure sans forger de compte** (2026-10-10) : aucun compte
  de test n'est admin. Donner le groupe `admin` à `wama_pw_smoke` le temps de la sonde, le retirer
  dans le `finally` (avec ce que la sonde a écrit), et vérifier en sortie qu'il ne l'a plus —
  jamais une session forgée sur un compte réel.
- ⚠⚠ **Mesurer l'ÉLÉMENT que l'utilisateur regarde, pas son CONTENEUR** (2026-10-06). Smoke de
  Comparer dans la modale : il mesurait le calque `.wama-compare-top` (bonne boîte, rognage
  juste) et concluait « superposition OK » — pendant que l'`<img>` DANS ce calque était bornée par
  une règle CSS de l'hôte et s'étirait. Fabien l'a vu à l'œil le jour même. ✅ Mesurer
  `getBoundingClientRect()` du média lui-même contre celui de la référence, à DEUX positions du
  curseur (20 % et 80 %) : un média qui suit le curseur au lieu de rester fixe est le défaut.
  Et lire la capture : un chiffre juste sur le mauvais nœud est une preuve fausse.


## Fixtures de sonde — le NOM est le filet (leçon du 2026-09-02)

- 🔴 **Toute fixture déposée par une sonde passe par `_fichier_temoin()`** (ui_smoke — le
  préfixe `wama_temoin_` est ce qui rend le fichier balayable par `sweep_test_witnesses`).
  Un nom écrit à la main y ÉCHAPPE : mesuré en clôture du 02/09, une douzaine de fixtures
  nommées à la main s'étaient accumulées dans le média du compte de test — invisibles du
  balayeur, nettoyées à la main. *Un `delete()` ORM sur le job de sonde ne supprime pas
  ses fichiers : seul le nom-témoin garantit le rattrapage.*
- ⚠ Trou PRÉEXISTANT constaté au même endroit : des fichiers `temoin_*` (sans le préfixe
  `wama_temoin_`) d'anciens harnais échappent aussi au motif — déclaré, pas nettoyé (pas
  les miens) ; le jour où on élargit le motif, vérifier sur échantillon qu'aucun fichier
  utilisateur ne matche (même prudence que la note du §3quater de WAMA_VERIFICATION).
- 🔴 **Le MÉNAGE d'un geste vit dans son `finally`, jamais après** (leçon du 2026-10-07).
  `card_transfer` et `batch_transfer` supprimaient leur card témoin APRÈS leur bloc `try` : un
  geste interrompu par une exception (ou sorti par un `return` de page refusée) la laissait en
  base. Quatre restes se sont accumulés en une après-midi, et comme ils DÉSIGNAIENT encore le
  fichier témoin, le passage suivant le COPIAIT au lieu de le déplacer — un faux rouge sur du
  code sain, fabriqué par les passages d'avant. ✅ Dans le `finally` : relire en base où sont
  les fichiers À CET INSTANT (ils ont pu bouger), les supprimer, puis les lignes. Et, avant de
  lire un rouge sur un geste qui a déjà échoué dans la journée, compter les témoins restés
  (`wama_temoin_*` en base ET sur disque, comptes de test seulement).

## Jouer un scénario sur du code Python NEUF sans toucher au gunicorn (recette du 2026-09-18)

- Le serveur live (`127.0.0.1:8000`) sert l'ANCIEN Python tant que le gunicorn WSL2 n'est pas
  rechargé — et `/palier` interdit de le recharger soi-même. Symptôme : une route neuve rend
  **404** pendant que sa voisine rend 302 ; le scénario conclurait à un code cassé.
- ✅ **Le geste** : `venv_win/Scripts/python.exe manage.py runserver 127.0.0.1:8011 --noreload`
  en tâche de fond (même Postgres WSL2, même `media/`, `DEBUG=True` donc les statics viennent des
  sources), puis un script qui pose `os.environ['WAMA_UI_SMOKE_BASE'] = 'http://127.0.0.1:8011'`
  **avant** `django.setup()` — l'adresse `wama_self` d'`external_sources` est lue à l'import
  d'`ui_smoke` — et appelle les `check_…()` d'`ui_smoke_menus` (ou d'`ui_smoke`). Playwright et
  Chromium sont dans venv_win. Attendre que la route neuve réponde 302 avant de jouer.
- ⚠ Arrêter le serveur 8011 en fin de mesure ; ne JAMAIS déclencher de tâche Celery depuis
  venv_win (deux Redis). Les scénarios sèment sous le compte de test nocturne et nettoient.
- Mesuré : C 6/6, E 7/7, F 6/6 sur le chantier médiathèque du 18/09, contre un live en 404.
- 🔴 **Une sonde qui ÉCRIT dans le cache (aperçu « pendant », progression) exige un serveur jetable
  CÔTÉ WSL** (vécu le 2026-10-04) : un processus Windows hors tests a son cache EN MÉMOIRE
  (`settings.py`, règle `runtime_side`) — le `runserver` venv_win et le script de sonde ont alors
  chacun le leur, et la face lue reste vide sans erreur (`has_during: False`). Côté WSL, serveur
  et sonde partagent le Redis : `venv_linux/bin/python manage.py runserver 127.0.0.1:8011` dans
  le même script WSL que la sonde Playwright (Chromium est installé côté WSL), arrêté à la fin.
- 🔴 **Dès que la mesure touche à un MOTEUR, le serveur jetable se lance CÔTÉ WSL** (vécu le
  2026-10-03) : sous venv_win, l'exécutabilité est jugée sur l'hôte Windows — MusicGen, AudioGen
  et YuE2 sortaient « moteur sans backend installé », donc **grisés** dans le select, et la borne
  de durée par capacité était inobservable. ✅ `wsl.exe -e bash -lc 'cd /mnt/d/WAMA/… && exec
  venv_linux/bin/python manage.py runserver 127.0.0.1:8011 --noreload'` en tâche de fond, et le
  script d'observation lancé AUSSI sous WSL (Playwright et Chromium y sont ; `127.0.0.1:8011` y
  désigne bien ce serveur). La recette venv_win ci-dessus reste valable pour une page sans moteur.
  ⚠ Pour l'arrêter, `pkill -f "[r]unserver 127.0.0.1:8011"` — le crochet évite que `pkill -f` ne
  tue le `bash -lc` qui le porte (son motif figure dans sa propre ligne de commande ; vécu deux
  fois le même soir, exit 15 avant la commande suivante).
  🔴 **Le crochet ne suffit pas si la MÊME commande lance aussi le serveur** (vécu le 2026-10-21) :
  la ligne du `bash -lc` contient alors `runserver 127.0.0.1:8011 --noreload` en clair, `pgrep -f`
  la trouve, et la session se tue elle-même (exit 15). ✅ Viser la fin exacte de la ligne du
  serveur : `pgrep -f "manage.py runserver 127.0.0.1:8011 --noreload --insecure$" | xargs -r kill`.
  ⚠ **Et un serveur jetable peut SURVIVRE à sa session** : lancé par `nohup … &`, il est resté
  vivant et a servi les passes suivantes (avec le Python de SON démarrage) ; lancé par `( … &)`, il
  meurt avec la session `wsl.exe`. Avant d'en lancer un : `pgrep -af "python manage.py runserver"`,
  et après : le même, qui doit être vide — sinon la passe suivante mesure un AUTRE code.
- ⚠ **Une scène 3D (three.js) se mesure aussi sans GPU** (2026-10-21, constellation des
  utilisateurs) : `chromium.launch(args=['--use-gl=swiftshader', '--enable-webgl',
  '--ignore-gpu-blocklist'])` — sans quoi la page affiche son repli « WebGL indisponible ». Les
  avertissements `GPU stall due to ReadPixels` pendant les captures sont du pilote logiciel, pas
  de la page : ne compter que les `console.error` et `pageerror`. Une étiquette qui suit une
  rotation n'est jamais « stable » pour Playwright : `click(force=True)` — l'utilisateur clique
  bien une cible en mouvement. Une page intégrée en iframe se lit par `page.frame_locator(…)`.
- ⚠ **Le compte de test nocturne n'a pas forcément de card dans l'app visée** : mesuré, seul
  `wama_ui_smoke_v3` portait une card dans CHACUNE des apps ; une observation du volet se fait sous
  ce compte (session forgée comme `_test_session_key`, retirée ensuite).

## Prouver « aucune régression VISUELLE » d'une extraction : le banc de parité au pixel (2026-10-21)

> Demande de Fabien en portant la constellation des utilisateurs sur la brique commune : *« je ne
> veux aucune régression sur les visuels 3D existants »*. Un smoke qui dit « la scène se forme »
> ne le prouve pas ; seule une comparaison ANCIEN code / NOUVEAU code, mêmes entrées, le prouve.

- **Les deux codes servis en même temps** : l'ancien depuis un worktree de HEAD (recette d'AGENTS.md :
  y copier `.env` et les migrations — et, pour une scène 3D, `wama/static/vendors/three-*/build/`,
  avalé par `.gitignore`), sur un port ; le nouveau depuis l'arbre, sur un autre. Les deux
  côté WSL, `runserver --noreload --insecure` (les statics viennent des SOURCES).
- **Les mêmes entrées** : les faits servis d'un fichier par `context.route(...)` (un jeu réel + un
  jeu synthétique qui exerce ce que le réel n'a pas : projets, apports, partages à une portée,
  comptes inactifs et de test) ; les replis aussi (`getContext` → `null` pour « sans WebGL », la
  route en 500).
- **Le même temps** : `add_init_script` qui remplace `requestAnimationFrame` et `performance.now`
  par une horloge avancée à la main (`window.__tick(ms)`, pas de 16 ms) ; capture
  `animations='disabled'`. Sans cela, deux passages du MÊME code diffèrent.
- **Les mêmes gestes**, une capture + un relevé du DOM (volet, étiquettes, infobulle, mesures) à
  chacun. ⚠ **Sortir la souris de la scène après un survol** : une étiquette qui bouge sous une
  souris immobile fait apparaître l'infobulle au hasard (mesuré : elle variait entre deux passages
  du même code, ~20 000 px).
- **Comparer** au pixel (PIL `ImageChops.difference`) en écartant ce qui n'est pas la page mesurée
  (l'explorateur de fichiers, x < 280 : il lit `media/`, différent d'un worktree), et le DOM une fois
  le seul renommage VOULU retiré. Bruit mesuré entre deux passages du même code : ≤ 40 px, sous le
  champ de recherche focalisé ou le verre d'un volet — à étalonner par deux passages de l'ancien
  code AVANT de juger le nouveau.
- Toute retouche ultérieure de la brique se reprouve contre la dernière passe du nouveau code
  (transitivité), sans refaire le worktree.

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
- ⚠ **Se connecter avec un compte de TEST existant** (`wama_nightly_test`, `ui_smoke_v3`,
  `pw_smoke`), jamais en anonyme : depuis la fermeture du 22/08, le compte anonyme n'a plus aucun
  rôle ni tier utilisateur — une passe anonyme mesure des DROITS en croyant mesurer un
  comportement. Ne pas forger un compte : en inventer un inventerait ses droits.
- ⚠ JAMAIS d'action destructive : pas de suppression d'items, pas de « Tout effacer », pas de
  lancement de génération lourde GPU sans accord. Le user id=1 est le compte réel de Fabien.

## 1. Sources des points à valider
- `PROJECT_STATUS.md` : chercher « valider navigateur » / « validation navigateur » (sections
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
  déjà de settings, s'en inspirer). Et un marqueur DOM peut être ABSENT à l'état vide
  légitime (`#ragListe` sans document) ou injecté par JS conditionnel — vérifier la
  CONDITION du gabarit avant de conclure, la capture lue tranche.
- **Le compte smoke doit porter les Groups `user` + `role:*`** sinon @app_access répond 302 vers
  l'accueil — et une page « chargée » peut être L'ACCUEIL après redirect : vérifier un marqueur de
  la page visée, pas le seul code 200 (piège vécu sur `/converter_01/`).
- **Le contrôle « zéro erreur console » est le plus rentable** : il a trouvé une double inclusion
  de brique globale (`MediaPicker`) sur 2 apps dès la 1re exécution (relevé du 19/08), sur des
  pages utilisées tous
  les jours. `node --check` ne voit que la syntaxe, jamais une erreur au chargement.

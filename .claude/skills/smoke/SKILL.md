---
name: smoke
description: Validation visuelle et fonctionnelle réelle de WAMA dans le navigateur (Playwright MCP - screenshots lus par Claude). Utiliser pour les « validations navigateur en attente », après un port d'app, ou quand l'utilisateur demande de vérifier visuellement une page.
---

# /smoke — Validation navigateur réelle

Objectif : fermer l'angle mort récurrent « ⚠ RESTE À VALIDER NAVIGATEUR » des handoffs. On vérifie
le RENDU RÉEL, pas la structure du code.

## 0. Préconditions
- Le serveur doit tourner (WSL2) : vérifier `http://localhost:8000` répond (curl -s -o /dev/null
  -w '%{http_code}'). S'il ne répond pas, DEMANDER à l'utilisateur de le lancer — ne pas le
  démarrer soi-même sans demande.
- **Aucun MCP Playwright n'est configuré dans ce dépôt** (vérifié 2026-07-31 : pas de `.mcp.json`,
  aucun outil navigateur exposé). La route NORMALE est donc : **script Playwright → PNG → `Read`**
  (l'outil de lecture rend l'image, la vérification visuelle marche sans MCP). Ne pas annoncer une
  passe MCP avant d'avoir vérifié sa disponibilité.
- Navigateurs installés **côté WSL2** (`~/.cache/ms-playwright`, chromium-1228), `playwright`
  importable dans `venv_linux` **et** `venv_win` → lancer le script sous WSL2, là où tourne aussi
  le serveur.
- **AVANT d'écrire un script : réutiliser la brique.** `common/services/ui_smoke.py` fait déjà
  chargement + erreurs console + parcours des onglets + capture + diff + triage VLM, et
  `python manage.py run_nightly_tests --stage ui` l'exécute sur les 13 apps en ~45 s. Commencer
  par là ; n'écrire un script ad hoc que pour ce qu'elle ne couvre pas.
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
- **Le compte smoke doit porter les Groups `user` + `role:*`** sinon @app_access répond 302 vers
  l'accueil — et une page « chargée » peut être L'ACCUEIL après redirect : vérifier un marqueur de
  la page visée, pas le seul code 200 (piège vécu sur `/converter_01/`).
- **Le contrôle « zéro erreur console » est le plus rentable** : il a trouvé une double inclusion
  de brique globale (`MediaPicker`) sur 2 apps dès la 1re exécution, sur des pages utilisées tous
  les jours. `node --check` ne voit que la syntaxe, jamais une erreur au chargement.

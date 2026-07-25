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
- Outils Playwright MCP disponibles (sinon fallback : script Playwright → PNG → Read).
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

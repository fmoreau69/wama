---
name: brique
description: Extraire une logique dupliquée vers wama/common/ (brique commune) puis la faire adopter — le geste central de la règle « zéro duplication ». Utiliser quand du code se répète entre 2+ apps, quand l'utilisateur dit « centralise », « extrais en brique », « factorise », ou avant de copier-coller quoi que ce soit entre apps.
---

# /brique — Extraction vers common/ + adoption

Règle CLAUDE.md : tout code utilisé par plus d'une app va dans `wama/common/`. Si tu t'apprêtes
à copier-coller entre apps, c'est LE signal d'extraire d'abord.

## 1. Avant d'écrire — la brique existe-t-elle déjà ?
- Grep `wama/common/utils/`, `templates/common/`, `static/common/js/` + l'index
  `WAMA_APP_CONVENTIONS §12.2` + `WAMA_APP_GENERATION_ROUTE.md` (facette concernée).
- Grep `app_registry.py` avant toute nouvelle taxonomie (piège récidivé 3× : MEDIA_CATEGORIES,
  normalize_types existaient déjà).
- Ne pas réveiller le code DORMANT (`AI-models/manager.py`, registry.json).

## 2. Extraire (construction propre, pas de surcharge)
- Partir de la MEILLEURE implémentation existante (souvent transcriber/reader), pas d'une moyenne.
- La brique est déclarative/paramétrable (kwargs, hooks `reset=`/`derive=`/`extra=`) — jamais de
  `if app == 'x'` dedans.
- Python → `common/utils/` ou `common/services/` ; template → `templates/common/_*.html` ;
  JS → s'ajoute à `wama-app-base.js` ou fichier dédié `static/common/js/`.
- Spécificités légitimes d'app : elles se DÉCLARENT (capacité, schéma, adapter), elles ne se
  codent pas en dur dans la brique.

## 3. Adopter immédiatement (une brique sans consommateur = dette)
- Recâbler l'app source + au moins un 2e consommateur dans la même passe si possible.
- Supprimer le code local remplacé (pas de double chemin) ; si la suppression doit attendre une
  validation navigateur → l'inscrire dans `REMOVAL_LEDGER.md` (R*).
- JS/CSS modifiés → copier vers `staticfiles/<app>/` ; Python → restart WSL2 à signaler.

## 4. Tracer
- La brique + son taux d'adoption → `WAMA_APP_GENERATION_ROUTE.md` (facette F1-F8 concernée).
- Si mesurable → ajouter/ajuster le critère dans `conformity_checker.py` (cf. /conformite §3).
- Palier → `/palier` (PROJECT_STATUS + commit par chemins explicites).

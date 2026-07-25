---
name: reprise
description: Rituel de début de session WAMA — recharger le contexte réel (docs de statut, handoff, commits récents, migrations) avant de toucher au code. Utiliser en début de session, ou quand l'utilisateur dit « reprise », « où en est-on », « continue le chantier ».
---

# /reprise — Rituel de début de session WAMA

Objectif : repartir de l'état RÉEL du projet, pas d'un souvenir. À dérouler dans l'ordre, sans rien modifier.

## 1. État git
- `git log --oneline -15` + `git status` — identifier ce qui a bougé depuis la dernière session.
- Si la branche n'est pas `dev`, le signaler avant toute chose.

## 2. Handoff & statut
- Chercher un `REPRISE_*.md` à la racine plus récent que le dernier connu (Glob `REPRISE_*.md`). Le lire s'il existe.
- Lire l'en-tête + les sections pertinentes de `PROJECT_STATUS.md` (ne pas tout relire : cibler le chantier demandé + « Ordre de reprise recommandé »).
- Pour un chantier UI/apps : relire la section correspondante de `WAMA_APP_GENERATION_ROUTE.md` (facettes F1–F8) avant de coder.

## 3. Confrontation au réel (obligatoire)
- Les statuts des `.md` SURESTIMENT souvent l'avancement : vérifier par Grep/Read les 2-3 affirmations dont dépend le travail du jour.
- Vérifier les migrations : `wsl.exe -e bash -lc 'cd /mnt/d/WAMA/web-app-for-media-automation && venv_linux/bin/python manage.py migrate --check'` (base WSL2 = la vraie ; la base Windows est une copie dev — si on touche aux modèles, appliquer DES DEUX côtés).

## 4. Périmètre de session
- Énoncer en 2-3 phrases le périmètre retenu (fichiers/apps touchés) et le point de sortie visé (= le palier où l'on committera).
- Si une autre instance Claude travaille en parallèle (voir REPRISE/handoff), respecter la partition des fichiers déclarée ; ne JAMAIS toucher un périmètre réservé à l'autre instance.

## Rappels permanents
- Jamais de `cd` en préfixe de commande shell.
- Commits par chemins explicites (jamais `git add -A`), au palier ; push = demander.
- Pas de tests destructifs (`delete()` en masse) ; user id=1 = compte réel.

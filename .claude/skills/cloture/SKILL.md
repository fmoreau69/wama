---
name: cloture
description: Rituel de FIN de session WAMA — miroir de /reprise. Balayage « rien laissé de côté », contrôles mécaniques si les registres ont bougé, handoff §REPRISE avec point d'entrée 🔚, mémoire persistante, liste explicite des pendings. Utiliser quand l'utilisateur dit « on clôt la session », « consigne tout », « fermeture », ou avant de repartir à neuf.
---

# /cloture — Rituel de fin de session WAMA

Objectif : qu'une session se ferme comme /reprise l'ouvre — depuis l'état RÉEL, sans rien
perdre. La question à laquelle tout répond : *« si la prochaine session démarre à froid,
retrouve-t-elle TOUT ? »*

## 0. Périmètre multi-instances (avant tout)
- `git status` : identifier ce qui est à TOI vs à l'autre instance (voir partition du handoff).
  Ne JAMAIS commiter les fichiers de l'autre ; si un commit de l'autre a absorbé ta
  consignation partagée (PROJECT_STATUS), vérifier qu'elle est dans HEAD (`git show HEAD:…`).

## 1. Palier final
- Dérouler `/palier` sur le travail restant : validations empiriques, consignation dans les
  docs de référence, commits par chemins explicites. Rien ne doit rester en working tree
  DANS TON périmètre.

## 2. Contrôles mécaniques — seulement ceux que la session a rendus nécessaires
- Un REGISTRE a bougé (APP_CATALOG, params, capacités, tool_api, mecanismes.py…) →
  `manifest_export --check` (⚠ depuis WSL2 — venv_win = faux périmés sur les libraries) ;
  régénérer si périmé. `doc_facts --check` si un fait généré a pu bouger.
- Des RÉFÉRENCES doc ont bougé → `check_docs` (depuis Windows). Si une cible attendue a été
  créée/abandonnée, **réajuster le seuil « N CASSÉ attendus » dans /reprise** (un seuil
  périmé fait passer une vraie dérive pour du normal — vécu 10/08).
- La grille a pu bouger → `check_app_conformity` (rapport global, pas `--app`).

## 3. Balayage « rien laissé de côté » — chercher, pas se souvenir
- Grep la conversation/le PROJECT_STATUS du jour pour les `⚠` posés en cours de route :
  chacun est soit RÉGLÉ, soit dans la liste des pendings du handoff. Aucun troisième état.
- Données/artefacts de session à tracer : comptes et items de test semés (compte smoke,
  jobs), scripts utilitaires laissés hors git (scratchpad, logs/), sorties
  PENDING_HUMAN_VALIDATION (wama-dev-ai/outputs). Les CONSIGNER (où, pourquoi, jetable ?).
- `git stash list` vide, pas de worktree oublié (`git worktree list`).

## 4. Handoff
- Compléter le §REPRISE du jour dans PROJECT_STATUS avec un bloc final :
  **🔚 POINT D'ENTRÉE SESSION SUIVANTE** (une ligne actionnable) + **file des chantiers
  ouverts** (ordre, bloquants marqués) + **pendings système** (restart workers/gunicorn,
  push N commits, validations navigateur en attente).
- **Multi-sessions (plusieurs clôtures le même jour) : APPEND-only.** Chaque session ajoute
  SON bloc « SUITE … » (ou son §REPRISE) avec son périmètre — on n'édite JAMAIS le bloc
  d'une autre session, on ne « fusionne » pas les 🔚 : /reprise lit TOUS les 🔚 du jour.
  Mécanique éprouvée (13/08, 2 instances) : petits blocs + relire avant chaque édition
  (le fichier bouge sous tes pieds) + si le commit de l'autre instance a absorbé ton bloc,
  vérifier `git show HEAD:PROJECT_STATUS.md | grep <ton ancre>` — contenu > attribution.
- `REPRISE_<date>.md` séparé UNIQUEMENT si le volume le justifie (sinon §REPRISE suffit).
- « Contrôles attendus au prochain /reprise » : donner les CHIFFRES (corpus N, check_docs
  N CASSÉ, roundtrip, scores de grille) — c'est ce bloc que /reprise confronte.

## 5. Mémoire persistante
- Mettre à jour les fichiers mémoire des chantiers touchés (pas de nouveau fichier si un
  existant couvre le sujet) ; n'y mettre que le NON-DÉRIVABLE du code/des docs : décisions,
  pourquoi, pièges vécus, récidives. Dates ABSOLUES.
- Mettre à jour la ligne de handoff de `MEMORY.md` (pointer le §REPRISE du jour).
- Une leçon de MÉTHODE (récidive, correction de Fabien) → l'ajouter au fichier feedback_*
  concerné, pas à un fichier projet.

## 6. Sortie
- Message final : ce qui ATTEND l'utilisateur (restart ? push ? décision ?), le point
  d'entrée de la prochaine session, et la liste des pendings — RIEN d'autre à retenir de
  tête. Ne JAMAIS écrire « tout est consigné » sans avoir déroulé le §3.

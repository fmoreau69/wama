---
name: palier
description: Clôturer proprement un palier de chantier WAMA — validations empiriques, consignation dans les docs de référence, commit local par chemins explicites. Utiliser en fin d'étape de travail, ou quand l'utilisateur dit « palier », « consigne », « clôture la session ».
---

# /palier — Clôture d'un palier de chantier

Objectif : ne jamais laisser un palier non consigné ni non validé. À dérouler dans l'ordre.

## 1. Validation empirique (avant toute consignation)
- `wsl.exe -e bash -lc 'cd /mnt/d/WAMA/web-app-for-media-automation && venv_linux/bin/python manage.py check'`
- Si des modèles ont changé : `manage.py makemigrations --check --dry-run` puis `migrate` DES DEUX côtés (WSL2 = live, Windows = copie dev).
- Si du JS/CSS d'app a changé : copier `wama/<app>/static/` → `staticfiles/<app>/`.
- Si du Python runtime a changé : noter que le restart du process WSL2 est requis (le signaler à l'utilisateur, ne pas restarter soi-même sans demande).
- Smoke test réel quand c'est transverse (charger la page, appeler l'endpoint) — pas seulement `check`.

## 2. Consignation (exhaustive, pas lossy)
- `PROJECT_STATUS.md` : mettre à jour la/les sections du chantier (✅/🔄/⏳, date, ce qui RESTE — y compris « validation navigateur en attente » si on n'a pas pu cliquer).
- Le doc de référence du domaine (cf. table CLAUDE.md) : consigner décision + pourquoi + implications + ce que ça remplace.
- Cam Analyzer : entrée `CAM_ANALYZER_CHANGELOG.md` obligatoire si le comportement a changé.
- Mémoire persistante : seulement le non-dérivable du code (décisions, pièges, feedback).

## 3. Commit local (autonome), push (demander)
- `git add <chemins explicites>` — JAMAIS `git add -A` ni `git add .`.
- Un commit par palier logique, message conventionnel français (`feat(app): …`, `fix: …`, `docs: …`).
- Ne JAMAIS pousser sans demande explicite de l'utilisateur.

## 4. Handoff si la session s'arrête là
- Si des validations restent en attente (navigateur, restart WSL2), les lister dans la section REPRISE de `PROJECT_STATUS.md` ou un `REPRISE_<date>.md` si le volume le justifie (exception à la règle « pas de nouveau .md » : les REPRISE_* sont des artefacts datés de handoff).

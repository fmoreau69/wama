---
name: palier
description: Clôturer proprement UN PALIER de chantier WAMA — tests du périmètre, consignation dans les docs de référence, commit local par chemins explicites. Utiliser en fin d'étape de travail, ou quand l'utilisateur dit « palier », « consigne ». Pour la fin de SESSION entière, c'est /cloture (plus large : registres, promesses à moitié tenues, handoff).
---

# /palier — Clôture d'un palier de chantier

Objectif : ne jamais laisser un palier non consigné ni non validé. À dérouler dans l'ordre.

## 1. Validation empirique (avant toute consignation)
- 🔴 **LES TESTS DU PÉRIMÈTRE TOUCHÉ, SANS CONDITION.** `manage.py check` ne prouve que
  l'import ; il passe sur du code faux. Lancer les tests des modules touchés (`manage.py test
  <module>`), et **un rouge ne se clôt PAS en silence** : il est *corrigé*, ou *DÉCLARÉ dans le
  handoff par son NOM*. Un palier qui reporte « N tests OK » en ayant écarté les rouges du
  décompte produit une preuve fausse — pire que pas de tests du tout. (Même trou que `/cloture`
  a bouché le 2026-08-26 ; il était ici aussi.)
- `wsl.exe -e bash -lc 'cd /mnt/d/WAMA/web-app-for-media-automation && venv_linux/bin/python manage.py check'`
- Si des modèles ont changé : `manage.py makemigrations --check --dry-run` puis `migrate` DES DEUX côtés (WSL2 = live, Windows = copie dev).
- Si du JS/CSS d'app a changé : copier `wama/<app>/static/` → `staticfiles/<app>/`.
- Si du Python runtime a changé : noter que le restart du process WSL2 est requis (le signaler à l'utilisateur, ne pas restarter soi-même sans demande).
- Smoke test réel quand c'est transverse (charger la page, appeler l'endpoint) — pas seulement `check`.

## 2. Consignation (exhaustive, pas lossy)
- `PROJECT_STATUS.md` : mettre à jour la/les sections du chantier (✅/🔄/⏳, date, ce qui RESTE — y compris « validation navigateur en attente » si on n'a pas pu cliquer).
- Le doc de référence du domaine (cf. table CLAUDE.md) : consigner décision + pourquoi + implications + ce que ça remplace.
- Mécanisme transversal créé/déplacé/supprimé → entrée du registre `wama/common/mecanismes.py` puis `python manage.py doc_facts` (la table de `WAMA_MECANISMES.md` est GÉNÉRÉE, ne jamais l'éditer à la main).
- Un registre déclaratif a bougé (params, capacités, tool_api, modèles…) → `python manage.py manifest_export` puis `manifest_export --check` **depuis WSL2** (la vue venv_win donne de faux « périmés » sur les libraries — dépendances de wheel différentes).
- Cam Analyzer : entrée `CAM_ANALYZER_CHANGELOG.md` obligatoire si le comportement a changé.
- Mémoire persistante : seulement le non-dérivable du code (décisions, pièges, feedback).

## 3. Commit local (autonome), push (demander)
- 🔴 **`git commit <chemins explicites> -m "…"` — en UN geste.** JAMAIS `git add -A`, jamais
  `git add .`, et **jamais un `git commit` sans pathspec**, même après un `add` ciblé. ⚠ Ce
  skill a prescrit `git add <explicites>` puis commit jusqu'au 2026-08-26 : c'est **exactement**
  le geste que CLAUDE.md interdit depuis le 22/08, et il rate dans les deux sens — il emporte
  tout l'index d'une autre instance, ET il laisse derrière ce qui est modifié sans être stagé
  (HEAD cassé le 22/08 alors que l'arbre de travail passait 245 tests).
- 🔴 **Relire `git diff <fichier>` AVANT de commiter un fichier co-édité** (`PROJECT_STATUS.md`,
  `mecanismes.py`, `manifests/**`). Si le diff contient des lignes que tu n'as pas écrites,
  **soit tu l'annonces dans ton message, soit tu attends — jamais en silence.** Vécu deux fois :
  12 fichiers balayés, puis 14 lignes de `mecanismes.py` le 2026-08-26.
- Un commit par palier logique, message conventionnel français (`feat(app): …`, `fix: …`, `docs: …`).
- ⚠ **Message long → `-F <fichier>`, jamais `-m`** : les backticks d'un `-m` sont interprétés par
  le shell et des fragments s'évaporent en silence (récidivé 23/08 puis 26/08).
- Ne JAMAIS pousser sans demande explicite de l'utilisateur.

## 4. Handoff si la session s'arrête là
- Validations en attente (navigateur, restart WSL2) → section **`§REPRISE <date>` de
  `PROJECT_STATUS.md`**, qui est LE domicile des handoffs.
  ⚠ **Ne plus créer de `REPRISE_<date>.md`** : un seul subsiste (`REPRISE_2026-08-06.md`,
  historique), et les suivants ont tous été absorbés dans `PROJECT_STATUS`. En créer un nouveau
  rouvre la règle « un domaine = un fichier » qu'ils avaient justement fini par enfreindre.
- Session entière qui se termine → skill `/cloture` (plus complet : tests, registres, balayage
  des promesses à moitié tenues, ce qu'on a laissé de côté).

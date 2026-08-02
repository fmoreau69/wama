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

### 3a. Contrôles MÉCANIQUES — lancer les 4, ne pas les paraphraser
> Un statut lu dans un `.md` est une intention ; seules ces commandes disent le réel. Elles sont
> rapides et ne modifient rien. **Reporter leurs chiffres tels quels, ne jamais les déduire.**

```bash
python manage.py check_docs                 # références doc→code
python manage.py manifest_export --check    # corpus de manifestes périmé ?
python manage.py manifest_roundtrip --all   # régénération : facettes projetables, fidélité
python manage.py check_app_conformity       # grille 74 critères par app
```
- ⚠ `check_docs` : lancer depuis **Windows** (`./venv_win/Scripts/python.exe`) — il parcourt
  l'arborescence, et `/mnt/d` depuis WSL2 met plusieurs minutes.
- **État attendu au 2026-08-02** : `check_docs` = **3 CASSÉ** (cibles à créer : `_result_tabs.html`,
  `wama/common/middleware.py`, `_settings_modal.html`). **Une 4ᵉ = vraie dérive, à traiter.**
- `manifest_export --check` doit dire « corpus à jour ». Sinon un registre a bougé sans que le
  corpus soit régénéré (`python manage.py manifest_export`).

### 3b. Confrontation ciblée
- Les statuts des `.md` SURESTIMENT souvent l'avancement : vérifier par Grep/Read les 2-3 affirmations dont dépend le travail du jour.
- Vérifier les migrations : `wsl.exe -e bash -lc 'cd /mnt/d/WAMA/web-app-for-media-automation && venv_linux/bin/python manage.py migrate --check'` (base WSL2 = la vraie ; la base Windows est une copie dev — si on touche aux modèles, appliquer DES DEUX côtés).

## 4. Périmètre de session
- Énoncer en 2-3 phrases le périmètre retenu (fichiers/apps touchés) et le point de sortie visé (= le palier où l'on committera).
- Si une autre instance Claude travaille en parallèle (voir REPRISE/handoff), respecter la partition des fichiers déclarée ; ne JAMAIS toucher un périmètre réservé à l'autre instance.

## Rappels permanents
- Jamais de `cd` en préfixe de commande shell.
- Commits par chemins explicites (jamais `git add -A`), au palier ; push = demander.
- Pas de tests destructifs (`delete()` en masse) ; user id=1 = compte réel.
- **Avant toute nouvelle brique** : lire la facette F concernée dans `WAMA_APP_GENERATION_ROUTE.md`
  puis `ls wama/common/{utils,services}` et les JS communs (cf. `/brique §1`). Sauté le 31/07 →
  briques de batch ratées et câblage à refaire.
- **Une seule base de données depuis le 2026-07-31** : `settings._resolve_db_host()` fait pointer
  le Django lancé depuis Windows sur le Postgres de WSL2. UN seul `migrate` suffit désormais (la
  base Postgres de Windows est orpheline). Les migrations sont **gitignorées** (`.gitignore:8`) :
  ne pas tenter de les commiter.
- **Vérifier empiriquement, ne jamais deviner** un sélecteur, une URL (`reverse()`), un nom de
  champ de modèle ou une commande : chaque supposition de la session du 31/07 a coûté un
  aller-retour (`main`, `Project(slug=…)`, URLs enhancer, `BatchEnhancement(name=…)`).
- **Lire la FORME d'un retour, ne jamais la deviner** (02/08, deux fois) : `facet_report` expose
  déjà `runtime_projectable`/`codegen_required` ; `studio_redundancy` rend `diffs` en LISTE — un
  `isinstance(dict)` masquait le verdict d'un round-trip existant depuis 2026-07-21.
- **Chercher l'accesseur AVANT de déduire une règle** (02/08) : un motif dans les données est la
  TRACE d'un mécanisme, pas une règle. Le lien app↔modèles est `AIModel.source` ; ma déduction
  donnait « 31/42 + 11 trous », le réel est **91/91**.
- **`manage.py check` ne voit PAS les imports paresseux** : il est passé au vert sur un
  `ImportError` introduit dans un import local. Relancer la suite complète après tout déplacement
  de symbole.

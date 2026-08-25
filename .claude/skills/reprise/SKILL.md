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

### 3a. Contrôles MÉCANIQUES — lancer les 6, ne pas les paraphraser
> Un statut lu dans un `.md` est une intention ; seules ces commandes disent le réel. Elles sont
> rapides et ne modifient rien. **Reporter leurs chiffres tels quels, ne jamais les déduire.**

```bash
python manage.py check_docs                 # références doc→code
python manage.py manifest_export --check    # corpus de manifestes périmé ? (⚠ depuis WSL2)
python manage.py manifest_roundtrip --all   # régénération : facettes projetables, fidélité
python manage.py check_app_conformity       # grille 77 critères par app (mesuré 22/08)
python manage.py doc_facts --check          # blocs GÉNÉRÉS des .md (dont la carte WAMA_MECANISMES)
python manage.py test                       # SUITE COMPLÈTE (~4 min) — ajoutée le 2026-08-25
```

#### ⚠ Pourquoi la suite de tests est entrée dans ce rituel (2026-08-25)

> Les 5 contrôles ci-dessus ne lancent **aucun test Django**. Résultat mesuré ce jour :
> `test_conventions_completes_et_typees` était **rouge depuis le 23/08 14:03** — deux jours —
> et aucun `/reprise` ne pouvait le voir. Il n'a été découvert que parce qu'un portage d'app
> a fait lancer la suite pour d'autres raisons.
>
> 🔴 **ET NE PAS LIRE LE SEUL NOMBRE D'ÉCHECS — LIRE LES MESSAGES, TOUS.** Le même jour, en
> ne lisant que le DERNIER message imprimé, j'ai rapporté « un défaut dans les 11 apps »
> là où il y avait **un seul défaut, dans le test** : il exemptait `export_binding` en dur
> et ignorait `export_formats`, sa clé jumelle ajoutée après lui. Les apps étaient justes.
> Un compte d'échecs ne dit pas COMBIEN de causes il y a — les relever toutes :
> `manage.py test 2>&1 | grep -E "^(FAIL|ERROR):|AssertionError"`.

**État attendu au 2026-08-25** : **852 tests, ~214 s**, `FAILED (failures=8, errors=2)` —
**STABLE** (vérifié sur 3 exécutions, mêmes noms). Ces 10 ont **DEUX causes connues** ;
toute autre est une dérive :

| # | ce que c'est | cause |
|---|---|---|
| **8** | `wama.synthesizer.tests.ViewsTest` + `IntegrationTest` — tous `302 != 200` | les tests créent un user **sans droit sur l'app** ; `AppAccessMiddleware` redirige vers `/`. Les tests précèdent le gating d'apps. Correctif : `is_superuser=True` (tier `admin` ∈ `BYPASS_TIERS`) ou accorder le rôle |
| **2** | `ERROR: wama-dev-ai.core` / `wama-dev-ai.ui` (`ModuleNotFoundError`) | la découverte de tests entre dans `wama-dev-ai/`, dossier **tiret-case volontairement non importable** (règle de nommage, CLAUDE.md). Rien à « corriger » côté nommage |

⚠ **Comparer les NOMS des tests en échec, jamais leur nombre** — un compte identique peut
recouvrir un échec qui remplace un autre :
`manage.py test wama.synthesizer 2>&1 | grep '^FAIL:' | sed 's/^FAIL: //;s/ (.*//' | sort`.

> **Une 3ᵉ cause a existé jusqu'au 2026-08-25 et a été SUPPRIMÉE** — la garder en tête, car
> elle explique les références plus anciennes qui annoncent « 9 échecs ».
> `test_filename_property` était **INSTABLE** : la suite écrivait dans le `MEDIA_ROOT` RÉEL
> (**1069 fichiers** relevés, jusque dans les dossiers d'utilisateurs réels — les ids d'une
> base de test entrent en collision avec les vrais), et Django renommait `test.txt` en
> `test_c5e24b5d.txt` sur collision, faisant tomber `assertIn('test.txt', …)`. Le compte
> oscillait **8↔9 sans qu'une ligne de code ne change**. Réglé par
> `wama/common/runners.py` (`TEST_RUNNER`) : chaque exécution reçoit son propre dossier
> jetable sous `media_tests/`. **Ne jamais rétablir de test qui écrit dans `media/`.**
- ⚠ `check_docs` : lancer depuis **Windows** (`./venv_win/Scripts/python.exe`) — il parcourt
  l'arborescence, et `/mnt/d` depuis WSL2 met plusieurs minutes.
- ⚠ `manifest_export --check` : lancer depuis **WSL2** (`venv_linux`) — les manifestes `library`
  sont extraits par `importlib.metadata`, donc VENV-DÉPENDANTS ; depuis venv_win le contrôle
  déclare de faux « périmés » (mesuré 13/08 : torch/transformers/vibevoice, les wheels Windows
  ne déclarent pas les dépendances nvidia-*/triton du wheel Linux). Le corpus reflète
  venv_linux = le runtime réel.
- Comparer les chiffres au bloc « Contrôles attendus au prochain /reprise » du **dernier
  §REPRISE** de `PROJECT_STATUS.md` (corpus N manifestes, roundtrip, scores de grille) — c'est
  lui qui porte les valeurs à jour, pas ce skill.
- **État attendu au 2026-08-23** : `check_docs` = **4 CASSÉ / 0 périmée** (~489 réfs — ce TOTAL
  grossit à chaque doc écrite, ne pas en faire un critère). Les 4 sont **UNE SEULE cible**,
  `common/_result_tabs.html`, citée **quatre fois** par `PROJECT_STATUS.md` — pas des liens morts :
  cible de `REMOVAL_LEDGER` R18, duplication vérifiée présente (`transcriber/index.html:307` et
  `describer/index.html:109` portent le même `#resultTabs`).
  - ⚠ `wama/common/middleware.py` a QUITTÉ cette liste le 20/08 : le fichier EXISTE désormais
    (`RunOutcomeCaptureMiddleware`, chantier mémoire) — mais `UserLanguageMiddleware` (tableau
    i18n du `ROADMAP`) n'y est toujours PAS écrit : la référence résout, l'intention i18n reste due.

  🔴 **NE PAS LIRE CE NOMBRE COMME UN SEUIL — c'est le défaut de conception du contrat**
  (relevé le 23/08, pending ouvert). `check_docs` et `nightly_scenarios.CASSE_ASSUMES` comptent
  des **RÉFÉRENCES**, pas des **cibles manquantes**. Le compte monte donc **tout seul** dès qu'un
  §REPRISE recite la même cible — c'est exactement ce qui l'a fait passer de 2 à 4 en une journée,
  **sans aucune dérive réelle**. Un seuil qui bouge sans raison finit par être relevé
  machinalement, donc à ne plus protéger.
  **Le critère à appliquer : compter les CIBLES DISTINCTES — attendu = 1** (`_result_tabs.html`).
  Une **2ᵉ cible distincte** = vraie dérive. Comparer les fichiers cités, jamais le seul nombre.

  > ⚠ Ce seuil était à « 3 attendus / une 4ᵉ = dérive » jusqu'au 10/08 et **il était devenu faux** :
  > `_settings_modal.html` a été **livré autrement** le 06/08 (la modale est GÉNÉRÉE par
  > `WamaParams.settingsModal()`, le partial n'a donc jamais été créé) et sa référence a été retirée
  > des docs. Un seuil périmé est pire qu'absent : il fait passer une vraie dérive pour du normal.
  > **Réajuster ce compte à chaque fois qu'une cible est créée ou abandonnée.**
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

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
python manage.py check_app_conformity       # grille 82 critères déclarés (mesuré 26/08)
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

**État attendu au 2026-08-29** (mesuré ce jour ; c'était **852** le 25/08, **911** le 26/08 et
**1145** le 28/08 — le total grossit à chaque test ajouté, **ne pas en faire un critère** : les
**+9** du 29/08 sont les invariants de langue TTS de `dacf8f7d`) : **1154 tests**, **`OK`**,
plus la ligne `Découverte : 2 module(s) ignoré(s) hors périmètre (wama-dev-ai.core, wama-dev-ai.ui)`.
**Le SEUL attendu est `OK`.** La suite est verte : tout échec est désormais une dérive, il n'y a
plus de cause « connue » à excuser.

> ⚠ **Cet attendu a été FAUX du 27/08 au 28/08** et c'est la leçon à retenir de lui : il annonçait
> `FAILED (failures=8, errors=2)` « STABLE, deux causes connues » alors que les deux étaient
> **soldées**. Un attendu rouge qui décrit du vert est aussi nocif qu'un seuil périmé (cf. le 🔴
> plus haut) : il fait accueillir une vraie régression comme « la normale ». **Réécrire ce bloc
> dans le commit qui change l'état de la suite**, jamais plus tard.
>
> ⚠⚠ **Et le total lui-même a été faux le jour même où je l'ai réécrit** : j'ai inscrit « 1147 »
> le matin du 28/08, puis **deux exécutions du même arbre** (venv_win 127 s, venv_linux 506 s —
> aucun fichier de test modifié entretemps, vérifié au `git show --name-only`) ont rendu **1145**
> l'une comme l'autre. La découverte de tests n'a rien de dynamique (aucun `load_tests`, aucun
> `setattr(… test_…)` dans le dépôt) : c'était une **erreur de recopie**, pas une dérive.
> *Recopier un nombre d'une sortie longue est un geste faillible — c'est exactement pourquoi ce
> total n'est pas un critère.* Ne jamais s'alarmer d'un écart de ±quelques unités ; ne jamais
> tolérer autre chose que `OK`.

Les deux ex-causes, pour lire les références antérieures qui annoncent « 10 échecs » :

| # | ce que c'était | comment c'est SOLDÉ |
|---|---|---|
| **8** | `wama.synthesizer.tests.ViewsTest` + `IntegrationTest` — tous `302 != 200` : user créé **sans droit sur l'app**, `AppAccessMiddleware` redirigeait vers `/` | une fabrique locale (`wama/synthesizer/tests.py:43-48`) **accorde le rôle `communication`**, comme `nightly_tests.get_test_user()`. ⚠ La voie `is_superuser=True` a été **explicitement écartée** : neutraliser le portier rend les tests aveugles à une régression du gating. Un test de vues doit **franchir** le portier, pas le contourner |
| **2** | `ERROR: wama-dev-ai.core` / `.ui` (`ModuleNotFoundError`) : la découverte entrait dans un dossier **tiret-case volontairement non importable** | `wama/common/runners.py:81` — `RACINES_HORS_DECOUVERTE = ('wama-dev-ai',)`, élagage annoncé à l'écran (donc jamais silencieux) |

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
  Depuis le **2026-08-27** il couvre AUSSI **les skills** (`.claude/skills/*/SKILL.md`) et les
  renvois `.md` entre docs — d'où un corpus qui a bondi (540 → 741 → **1103** au 28/08, 34 docs
  et 13 skills). `--skills` les isole. ⚠ **Ce total n'est PAS un critère** : il monte avec chaque
  doc et chaque skill ajouté. Le seul critère est le nombre de CIBLES distinctes (🔴 ci-dessous).
  ⚠ **Il vérifie que les RÉFÉRENCES existent, pas que les CHIFFRES disent vrai** : le pire défaut
  de l'audit du 26/08 (`/port-app` annonçant « F6/F7/F8 : ZÉRO critère ») serait passé au travers.
- ⚠ `manifest_export --check` : lancer depuis **WSL2** (`venv_linux`) — les manifestes `library`
  sont extraits par `importlib.metadata`, donc VENV-DÉPENDANTS ; depuis venv_win le contrôle
  déclare de faux « périmés » (mesuré 13/08 : torch/transformers/vibevoice, les wheels Windows
  ne déclarent pas les dépendances nvidia-*/triton du wheel Linux). Le corpus reflète
  venv_linux = le runtime réel.
- Comparer les chiffres au bloc « Contrôles attendus au prochain /reprise » du **dernier
  §REPRISE** de `PROJECT_STATUS.md` (corpus N manifestes, roundtrip, scores de grille) — c'est
  lui qui porte les valeurs à jour, pas ce skill.
- 🔴 **LE CRITÈRE EST LE NOMBRE DE CIBLES DISTINCTES — attendu = 1.** (Détail et raison plus bas.)
  Comparer les **fichiers cités**, jamais le nombre de références.

- **État MESURÉ au 2026-08-31** : `check_docs` = **8 références cassées / 0 périmée sur ~1274**,
  pour **1 SEULE cible distincte** — le **partial d'onglets de résultat jamais créé** (cible de
  `REMOVAL_LEDGER` R18 ; duplication vérifiée présente, `transcriber/index.html:307` et
  `describer/index.html:109` portent le même `#resultTabs`).
  ⚠ **Le chemin n'est volontairement pas réécrit ici** — l'écrire ferait de cette ligne une
  référence cassée de plus. C'est exactement ainsi que le compte est passé de 4 à 5 le 24/08 :
  le bloc « Contrôles attendus » l'a recité pour en rendre compte.
  ⚠ Le total de RÉFÉRENCES enfle mécaniquement (518 → 1103 le 28/08 → **~1274** le 31/08) sans
  qu'aucune dérive n'existe : chaque §REPRISE ajoute des citations. **Seul le nombre de cibles
  distinctes est le critère** ; ce total n'est là que pour dater la mesure.
  ⚠⚠ **Ne pas lire « 4 », « 5 » ni « 8 » comme un seuil** — voir le 🔴 ci-dessus. Le 26/08, j'ai lu la
  ligne d'état périmée (« 4 / 518 ») et conclu à tort que le seuil du skill avait dérivé, alors
  que le critère juste était deux lignes plus bas et **tenait**. *Un chiffre périmé posé à côté
  de la bonne règle se fait lire à sa place.*
  - ⚠ `wama/common/middleware.py` a QUITTÉ cette liste le 20/08 : le fichier EXISTE désormais
    (`RunOutcomeCaptureMiddleware`, chantier mémoire) — mais `UserLanguageMiddleware` (tableau
    i18n du `ROADMAP`) n'y est toujours PAS écrit : la référence résout, l'intention i18n reste due.

  🔴 **NE PAS LIRE CE NOMBRE COMME UN SEUIL.** Le contrat automatique, lui, compte désormais juste :
  `nightly_scenarios.CIBLES_ASSUMEES = 1` compare des **CIBLES DISTINCTES** (✅ **corrigé le
  2026-08-27** ; le pending du 23/08 est SOLDÉ — il s'appelait `CASSE_ASSUMES` et comparait des
  **RÉFÉRENCES**, un nombre qui monte **tout seul** dès qu'un §REPRISE recite la même cible :
  c'est ce qui l'avait fait passer de 2 à 4 en une journée **sans aucune dérive réelle**, et le
  scénario nocturne `common.consistency.docs` était **rouge pour cette seule raison**, vérifié en
  le lançant). Un seuil qui bouge sans raison finit par être relevé machinalement, donc à ne plus
  protéger.
  **Le critère à appliquer reste le même à la main : compter les CIBLES DISTINCTES — attendu = 1**
  (`_result_tabs.html`). Une **2ᵉ cible distincte** = vraie dérive. Comparer les fichiers cités,
  jamais le seul nombre. Le gate ajoute une **tolérance zéro aux défauts francs** (frontmatter de
  skill), qui ne sont jamais « assumés ».

  > ⚠ Ce seuil était à « 3 attendus / une 4ᵉ = dérive » jusqu'au 10/08 et **il était devenu faux** :
  > `_settings_modal.html` a été **livré autrement** le 06/08 (la modale est GÉNÉRÉE par
  > `WamaParams.settingsModal()`, le partial n'a donc jamais été créé) et sa référence a été retirée
  > des docs. Un seuil périmé est pire qu'absent : il fait passer une vraie dérive pour du normal.
  > **Réajuster ce compte à chaque fois qu'une cible est créée ou abandonnée.**
- `manifest_export --check` doit dire « corpus à jour ». Sinon un registre a bougé sans que le
  corpus soit régénéré (`python manage.py manifest_export`).

### 3a bis. 🔴 LE DOCUMENT DE DOMAINE DU CHANTIER — avant de toucher au code

> **Ajouté le 2026-09-03 après un cas vécu coûteux.** Une session a passé une journée sur le
> cache HuggingFace en *proposant* un mécanisme, puis en découvrant qu'il existait, puis en
> corrigeant trois de ses propres affirmations — sans jamais ouvrir `ROADMAP §5b`, qui portait
> le **design validé depuis le 2026-06-17**, l'état MESURÉ, le garde et le détecteur. Elle
> avait pourtant fait ce rituel correctement : **le rituel ne le demandait pas.**
>
> Les 6 contrôles ci-dessus disent l'état de la PLATEFORME ; ils ne disent rien de ce qui est
> **déjà décidé** sur le sujet du jour. Une décision écrite qu'on ne lit pas se re-prend — plus
> mal, et en tournant en rond.

1. **Nommer le domaine du chantier**, puis ouvrir SON document de référence — la table
   « Fichiers de référence par domaine » de `CLAUDE.md` est l'index (`/port-app` porte la même
   discipline pour les facettes d'app). Exemples de correspondance :

   | chantier | à lire AVANT |
   |---|---|
   | cache HF, emplacement/catégories des modèles | **`ROADMAP §5b`** (+ la règle « nouveau modèle » de `CLAUDE.md`) |
   | modèles, capacités, tirage, entrées acceptées | `INPUT_MODEL_MATCHING.md` + `WAMA_APP_GENERATION_ROUTE §F4b` |
   | génération d'app, jumelle, gabarits | `WAMA_APP_GENERATION_ROUTE.md` (dont **§S 🔒**) |
   | manifestes | `WAMA_MANIFEST_SPEC.md` + `..._ARCHITECTURE.md` |
   | prompts, assistant, RAG | `WAMA_LLM.md` · mémoire : `WAMA_MEMORY.md` |
   | registres/catalogues | `common/registries.py` + `PROJECT_STATUS §registres` |

2. **Chercher la décision AVANT la solution** : `grep -n "décid\|acté\|validé" <doc>` — si le
   design est déjà tranché, le travail est de l'EXÉCUTER, pas de le reconcevoir.
3. **Chercher la brique avant d'en proposer une** (`ls wama/common/utils`, `grep` du verbe) :
   proposer puis découvrir qu'elle existe coûte un tour complet à chaque fois.

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
- ⚠⚠ **`rtk` compresse une SORTIE, il ne MESURE pas.** Mesuré le 26/08 : `rtk grep "attributes"`
  a rendu **1 correspondance sur 4** réelles (vérifié à l'outil natif) — et j'avais commencé à
  conclure sur ce relevé. Il reste bon pour ce qu'il vise (`git status`, `git diff`, logs,
  builds). **Dès qu'une recherche sert à AFFIRMER** (« il n'y a qu'un consommateur », « ce nom
  n'est pris nulle part », « N occurrences ») → **outil natif `Grep`**, qui ne filtre rien.
  Même famille que le biais de `consommateurs()` dans `WAMA_MECANISMES` : un instrument qui rate
  des correspondances est **pire qu'aucun instrument**, parce qu'il rend un chiffre.
- ⚠ **Un diagnostic reçu d'une autre instance se vérifie comme n'importe quelle affirmation**
  (26/08 : « les 91 manifestes périmés viennent du monde Data » — c'étaient des manifestes
  `model` issus d'un autre chantier). Un pending mal attribué est un pending que personne ne prend.

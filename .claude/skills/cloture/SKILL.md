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
- ⚠⚠ **LA RÈGLE DES CHEMINS EXPLICITES NE PROTÈGE PAS D'UN FICHIER CO-ÉDITÉ.**
  `git commit <chemin>` prend l'état **COMPLET** du fichier dans l'arbre, pas seulement tes
  modifications — `PROJECT_STATUS.md`, `WAMA_DATA_WORLD.md`, `MEMORY.md` sont co-écrits en
  permanence. **Seule discipline qui tienne : relire `git diff <fichier>` JUSTE AVANT de
  commiter, et vérifier que tout ce qu'on y voit est de soi.** Un `git status` dit que le
  fichier est modifié, **pas PAR QUI**.
  Si le diff contient du travail d'autrui : soit on l'annonce **dans le message**, soit on
  attend — jamais en silence. (Vécu 23/08 : 2 lignes emportées. Vécu 26/08 : 14 lignes
  emportées dans `mecanismes.py`, découvertes APRÈS le commit.)

## 1. Palier final
- Dérouler `/palier` sur le travail restant : validations empiriques, consignation dans les
  docs de référence, commits par chemins explicites. Rien ne doit rester en working tree
  DANS TON périmètre.

## 2. Contrôles mécaniques

### 2a. 🔴 LES TESTS DE TON PÉRIMÈTRE — inconditionnel, jamais « si la session l'a rendu nécessaire »

```bash
python manage.py test <tes modules>      # ciblé, quelques secondes
```

> **Pourquoi c'est en tête et non dans la liste conditionnelle** : `/reprise` a dû ajouter la
> suite complète le 2026-08-25 après qu'un test soit resté **rouge deux jours** sans qu'aucun
> rituel ne puisse le voir. Une clôture qui ne lance rien referme exactement le même trou, par
> l'autre bout — on peut fermer une session sur du rouge et le léguer.
>
> Ciblé suffit ici (`/reprise` lance la suite complète à l'ouverture) ; ce qui compte est que
> **le chiffre reporté au §4 soit MESURÉ dans cette session**, pas recopié du handoff précédent.
> ⚠ Et lire les **NOMS** des rouges, jamais le seul compte — un total identique peut recouvrir
> un échec qui en remplace un autre.

### 2b. Les autres — seulement ceux que la session a rendus nécessaires
- Un REGISTRE a bougé (APP_CATALOG, params, capacités, tool_api, mecanismes.py…) →
  `manifest_export --check` (⚠ depuis WSL2 — venv_win = faux périmés sur les libraries) ;
  régénérer si périmé. `doc_facts --check` si un fait généré a pu bouger.
  ⚠ **Un corpus périmé n'appartient pas forcément à ta session** : vérifier QUOI est périmé
  (le kind, les clés) avant de régénérer — régénérer figerait le WIP non commité d'une autre
  instance. Vécu 26/08 : 91 manifestes `model` périmés attribués au monde Data, alors qu'ils
  venaient du chantier « contrat de prompt » d'une autre instance.
- La grille a pu bouger → `check_app_conformity` (rapport global, pas `--app`).
- Un REGISTRE NUMÉROTÉ partagé a reçu des entrées (décisions `D<n>` de `WAMA_DATA_WORLD`,
  trous, `R<n>` de `REMOVAL_LEDGER`) → **vérifier l'unicité des numéros** :
  `grep -o "^| ~*D[0-9]*~*" <fichier> | sort | uniq -d` doit être vide.
  ⚠ Vécu 26/08 : deux instances ont ouvert **D27 et D28 le même jour sur quatre sujets
  différents** — chaque numéro désignait deux décisions et **rien n'a sonné**. Résolution :
  renuméroter les SIENNES (les autres sont citées par du WIP) + **table de renvoi**, car les
  messages de commit gardent l'ancienne numérotation. Garde mécanique ouvert en **D34**.

### 2c. `check_docs` — et le piège qui a récidivé QUATRE fois
- Des RÉFÉRENCES doc ont bougé → `check_docs` (Windows OU WSL2, rendu identique).
- 🔴 **Le nombre de CASSÉ n'est PAS un seuil** — `check_docs` compte des **références**, pas des
  **cibles manquantes** : le compte monte tout seul dès qu'un `.md` recite la même cible.
  **Le critère est le nombre de CIBLES DISTINCTES** (voir `/reprise §3a`, qui porte la valeur
  attendue). Une cible distincte de plus = vraie dérive ; une référence de plus vers la même
  cible = du bruit.
- ⚠⚠ **NE JAMAIS RÉÉCRIRE UN CHEMIN CASSÉ POUR LE DÉCRIRE** — pas même dans le bloc
  « Contrôles attendus » qui rend compte du contrôle. `check_docs` le compte comme une
  référence de plus. **Rencontré les 14/08, 22/08, puis le 24/08 — où c'est le bloc de
  contrôle lui-même qui a fait passer le compte de 4 à 5 — et évité de justesse le 26/08.**
  ✅ **Le geste** : nommer la cible en clair (« le partial d'onglets de résultat jamais créé »)
  **sans écrire de chemin résolvable**, et dire POURQUOI, sinon le suivant le rétablira par
  souci de précision.

## 3. Balayage « rien laissé de côté » — chercher, pas se souvenir

> ⚠ **« Se rappeler des ⚠ posés » n'est PAS chercher.** Le balayage doit avoir une source
> MÉCANIQUE, sinon il contredit son propre titre et ne retrouve que ce qu'on avait déjà en tête.

- **Les `⚠` de la session** — les relire là où ils sont ÉCRITS, pas là où on croit s'en souvenir :
  ```bash
  git log --format='%H' --author="$(git config user.name)" -20   # les commits de la session
  git show <sha> | grep -n "⚠\|TODO\|à trancher\|reste à\|non fait"
  git diff HEAD~<n> -- '*.md' | grep "^+" | grep "⚠\|⇒ \*\*D[0-9]"
  ```
  Chacun est soit **RÉGLÉ**, soit dans la liste des pendings du handoff. **Aucun troisième état.**
- **Les promesses tenues à moitié** — chercher ce qu'on a annoncé « à faire maintenant » puis
  laissé : `grep -n "gratuit maintenant\|à faire maintenant\|quick win\|⏳" <docs touchées>`.
  ⚠ Vécu 26/08 : `A2`/`A3`/`A4` annoncés « gratuits maintenant, irrattrapables ensuite » dans un
  document écrit LE JOUR MÊME, et non faits — invisible sans cette passe.
- **Les décisions ouvertes** du périmètre : les compter et les lister dans le handoff, une par
  ligne. Une décision ouverte qui n'apparaît pas dans le handoff est une décision perdue.
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
  — **cibles distinctes** et références —, tests de ton périmètre, roundtrip, scores de grille).
  C'est ce bloc que /reprise confronte.
  - 🔴 **Chaque chiffre doit avoir été MESURÉ dans cette session.** Recopier celui du handoff
    précédent produit un contrôle qui ne contrôle plus rien, et il survit des semaines.
  - 🔴 **Si une CIBLE DISTINCTE a été créée ou abandonnée, mettre à jour `/reprise` DANS LE MÊME
    COMMIT** — même règle que « créer un `.md` de référence = ajouter sa ligne à la table de
    CLAUDE.md dans le même commit ». Un critère périmé fait passer une vraie dérive pour du
    normal (vécu 10/08), et le rattrapage différé n'arrive jamais.

## 5. Mémoire persistante
- Mettre à jour les fichiers mémoire des chantiers touchés (pas de nouveau fichier si un
  existant couvre le sujet) ; n'y mettre que le NON-DÉRIVABLE du code/des docs : décisions,
  pourquoi, pièges vécus, récidives. Dates ABSOLUES.
- Mettre à jour la ligne de handoff de `MEMORY.md` (pointer le §REPRISE du jour).
- Une leçon de MÉTHODE (récidive, correction de Fabien) → l'ajouter au fichier feedback_*
  concerné, pas à un fichier projet.
- ⚠ **`MEMORY.md` a une taille utile bornée** (le harnais alerte vers 20 Ko, plafond de lecture
  ~24 Ko). Une ligne de handoff par session le fait grossir mécaniquement. **Compacter en même
  temps qu'on ajoute** : une session CLOSE se réduit à *pointeur + leçon seule*, son détail
  vivant dans son §REPRISE et sa fiche mémoire. ⚠ Réduire = **raccourcir les lignes**, jamais
  supprimer une entrée d'index sans le dire — c'est un index partagé entre instances.

## 6. Sortie
- Message final : ce qui ATTEND l'utilisateur (restart ? push ? décision ?), le point
  d'entrée de la prochaine session, et la liste des pendings — RIEN d'autre à retenir de
  tête. Ne JAMAIS écrire « tout est consigné » sans avoir déroulé le §3.
- **Dire aussi ce qu'on a laissé de côté, nommément.** Une clôture qui n'énonce que le livré
  laisse croire que le reste est fait. Ce qui a été *annoncé puis non fait* passe en tête de
  cette liste, avant les décisions ouvertes.
- ⚠ **Un arbitrage BLOQUANT se signale comme tel, séparément des autres décisions** : la
  prochaine session doit savoir en une ligne ce qu'elle ne peut pas commencer sans réponse.

---
name: commit-partiel
description: Commiter SES seuls hunks d'un fichier co-édité par une autre instance (PROJECT_STATUS, ROADMAP, AGENTS.md, mecanismes.py, docs générées) — l'index se construit hunk par hunk, se VÉRIFIE, puis se commite. Utiliser quand `git status` montre un fichier partagé porteur de lignes qui ne sont pas à soi, quand l'utilisateur dit « une autre instance travaille dessus », « ne commite que tes lignes », « attention au WIP de l'autre », ou avant tout commit d'un handoff.
---

# /commit-partiel — ne commiter que ses hunks d'un fichier co-édité

> PROMU (n=2 : 2026-09-19, distillé de cinq résolutions en une session ; **2026-09-26, il a guidé
> QUATRE commits de bout en bout** sur un dépôt à instances concurrentes — chat de l'assistant,
> brique du texte à dire, docs, handoff).
> ⭐ **Et il a rapporté plus qu'il n'a coûté** : les §3 ci-dessous ont gagné quatre pièges de cette
> exécution, dont deux qui avaient **cassé l'index** ou **fait citer un objet mort**. La condition
> de promotion posée le 19/09 était « une exécution guidée de bout en bout, pas la 6ᵉ occurrence du
> geste » — c'est celle-là qui est remplie.

Doctrine d'origine : `AGENTS.md §DISCIPLINE GIT MULTI-INSTANCES` — *aucun commit ne se fait
depuis l'index partagé*, et **`git commit <chemin>` prend l'état COMPLET du fichier**, pas
seulement ses lignes (`/cloture §0`, `/palier §3`). Sur un fichier que deux instances écrivent en
même temps, les deux formes sûres d'AGENTS.md se contredisent : le pathspec emporte le WIP
d'autrui, l'index partagé aussi. Ce skill est la troisième voie : **un index CONSTRUIT puis
VÉRIFIÉ**, et c'est la vérification qui rend le commit sans pathspec légitime.

## 0. Quand — et quand pas

- OUI : un fichier de suivi ou de doctrine (`docs/construction/suivi/PROJECT_STATUS.md`,
  `docs/construction/suivi/ROADMAP.md`, `AGENTS.md`), un registre (`wama/common/mecanismes.py`)
  ou une doc GÉNÉRÉE (`docs/construction/architecture/WAMA_MECANISMES.md`, le bloc du README)
  porte mes lignes ET des lignes non commitées d'une autre instance. Le repère : `git diff
  <fichier>` montre des hunks que je n'ai pas écrits.
- NON : mes fichiers PROPRES (personne d'autre ne les touche) — `git commit <chemins> -F msg`,
  la forme d'AGENTS.md. Ne pas mélanger les deux dans la tête : les propres entrent par `git add`,
  les co-édités par le patch.
- JAMAIS : `git add -A` / `git add .`, `git commit <fichier co-édité>`, `git stash` (il emporte
  aussi les modifications d'autrui), `git add -p` (interactif, non supporté ici).
- 🔴 **RELIRE CE FICHIER AU MOMENT DU GESTE — jamais d'après une copie chargée plus tôt dans la
  session** (vécu le 2026-10-04). Une session longue a suivi le §1 tel qu'il était quand elle
  l'avait lu — `git commit` sur index temporaire —, alors que le fichier portait depuis six jours
  la forme `commit-tree -p $BASE` : son commit a ANNULÉ deux commits d'autres sessions
  (`90ef25c3`, `6d01d528`), rétablis ensuite. Ce skill grandit à chaque piège vécu par une
  instance ; *la version que l'on a en tête est celle d'avant le dernier piège*.

## 1. Le geste, dans l'ordre

```bash
# a. l'index doit être VIDE avant de commencer — sinon il porte du WIP d'autrui
git diff --cached --stat            # attendu : rien
# b. un patch -U0 des seuls hunks dont une ligne +/- porte MON mot-clé
python .claude/skills/commit-partiel/stage_my_hunks.py <scratchpad>/mine.patch \
    "docs/construction/suivi/PROJECT_STATUS.md=<mot-clé>" "docs/construction/suivi/ROADMAP.md=<mot-clé>"
# c. dans l'index, sans toucher l'arbre
git apply --cached --unidiff-zero --whitespace=nowarn <scratchpad>/mine.patch
# d. mes fichiers PROPRES, entiers — APRÈS avoir mesuré leur différence À CET INSTANT
#    (« propre » est une supposition : vécu le 2026-10-13, `a10d9651` a emporté deux hunks d'une
#    autre instance dans un fichier « à moi »). Dans le script, avant le `git add` :
#    expect() { [ "$(git diff --numstat HEAD -- "$1" | cut -f1,2 | tr '\t' /)" = "$2/$3" ] || exit 5; }
#    expect <fichier> <mes ajouts> <mes suppressions>      # relevés en relisant MON diff
git add <fichier propre> ...
# e. VÉRIFIER — tout ce qui s'affiche doit être à moi (fichiers ET hunks)
git diff --cached --stat
git diff --cached -U0 | grep '^@@'
# f. commiter DEPUIS l'index vérifié — sans pathspec, c'est voulu ; le message le DIT.
#    ⚠ Avec un INDEX TEMPORAIRE, jamais `git commit` : il prendrait pour parent un HEAD qui a pu
#    bouger depuis le read-tree, et ANNULERAIT les commits intermédiaires (vécu 2026-09-28, §3).
#    BASE = le HEAD lu au read-tree ; l'update-ref échoue si la branche a bougé.
NEW=$(git commit-tree "$(git write-tree)" -p "$BASE" -F <scratchpad>/msg.txt)
git update-ref "refs/heads/$(git branch --show-current)" "$NEW" "$BASE"
# g. l'index est redevenu vide, HEAD ne porte que mes fichiers
#    ⚠ Avec un INDEX TEMPORAIRE, l'index PARTAGÉ garde les blobs d'AVANT pour mes chemins : un
#    retour arrière stagé que le prochain commit d'autrui emporterait (oublié dans un script le
#    2026-10-13, vu ici). Réaligner CES SEULS chemins, jamais un reset global :
git reset -q HEAD -- <mes chemins>
git diff --cached --stat | wc -l    # 0
git show --stat --format='%h %s' HEAD
```

Le **mot-clé** est un mot que SEULES mes lignes changées portent dans ce fichier : le nom du
chantier, une clé de champ (`vram_measured`), un nom de doc neuf. Un mot présent dans le contexte
seulement ne sélectionne rien (le patch est sans contexte).

⚠ **Quand mes hunks n'ont AUCUN mot commun** — cas vécu deux fois le 2026-09-26 sur une doc, où
l'un de mes trois hunks était une ligne de prose modifiée ne partageant aucun terme avec les
deux autres (mot-clé `levier` : 2 hunks sur 3 ; `evier` : les mêmes 2). Élargir le mot-clé
jusqu'à l'attraper aurait pris des hunks d'autrui. ✅ Sélectionner par **NUMÉRO de hunk**, après
les avoir LUS un par un : `pick_hunks.py <fichier> <patch> <n1> <n2> …` (les numéros sont ceux de
la ligne ANCIENNE, tels que `git diff -U0 | grep '^@@'` les affiche). Le script échoue si le
compte retenu ne correspond pas aux numéros demandés — on ne peut pas en rater un en silence.
⚠ **`<patch>` est le fichier de SORTIE** (vécu le 2026-10-07) : le script fait lui-même le
`git diff -U0` du fichier — lui donner un diff pré-calculé en entrée et rediriger sa sortie
écrase ce diff par les lignes « RETENU/laisse » qu'il imprime. Le patch se pose ensuite par
`stage_by_oldlines.py <fichier> <patch>`, jamais par `git apply` (piège du 2026-09-26 ci-dessous).
⭐ *Le mot-clé est une heuristique ; la lecture des hunks est la mesure. Quand les deux
divergent, c'est la lecture qui décide.*

Le **message** dit que l'index a été construit hunk par hunk sur des fichiers co-édités : celui
qui lira `git log` doit comprendre pourquoi ce commit n'a pas de pathspec.

🔴 **AJOUTER À LA FIN D'UN FICHIER CO-ÉDITÉ N'EST PAS SÛR — et le patch est ce qui le dit.**
Vécu DEUX fois le 2026-09-27 sur `PROJECT_STATUS`, en ajoutant un bloc de palier : lire le fichier,
composer le bloc, puis l'écrire. Entre la lecture et l'écriture, **une autre instance avait commité
5 lignes à la même fin de fichier** — mon écriture les a effacées sans qu'aucun `git status` ne le
montre (le fichier était « modifié », comme toujours). *Un append n'est pas une insertion : c'est
une réécriture complète du fichier à partir d'un état déjà périmé.*
✅ **Le geste, en deux temps** : (1) relire le fichier **dans la même commande** que l'écriture
(un script qui fait `read_bytes()` puis `write_bytes()` d'affilée, jamais une lecture d'il y a
trois tours) ; (2) **exiger que le patch ne contienne AUCUNE suppression** —
`grep -c '^-' <patch>` doit rendre **1** (la seule ligne `--- a/<fichier>` de l'en-tête). Une
suppression dans un patch qui prétend AJOUTER un bloc est le signe qu'on emporte le travail d'un
autre ; le hunk affiché comme `@@ -N,5 +N,20 @@` au lieu de `@@ -N,0 +N,20 @@` le dit aussi.
⭐ *La règle « aucun commit depuis l'index partagé » a une sœur : aucune écriture depuis une
lecture périmée.*

## 2. Si l'index n'est PAS vide au départ

C'est le WIP stagé d'une autre instance. Deux issues, jamais une troisième : **attendre** son
commit (elle a stagé, elle va commiter), ou commiter mes seuls fichiers PROPRES par pathspec et
laisser le co-édité pour plus tard. Ne pas `git reset` l'index d'autrui : ce n'est pas destructif,
mais c'est défaire son geste dans son dos.

## 3. Pièges VÉCUS

- **2026-09-14 — le contexte mêle les auteurs.** Avec le contexte par défaut, un hunk de
  `WAMA_MECANISMES.md` contenait ma ligne ET celle de l'autre instance (deux lignes voisines de
  la même table). D'où `-U0` : une plage changée = un hunk.
- **2026-09-14 — l'autre instance a commité pendant que je préparais.** Son commit a emporté le
  fichier entier, ma ligne comprise. Vérifier `git show HEAD:<fichier> | grep <ancre>` avant de
  refaire quoi que ce soit : *contenu > attribution*, une ligne dans HEAD sous son nom vaut mieux
  qu'un second commit.
- **2026-09-15 — les fins de ligne.** Le script lisait le diff en texte : Python traduit `\r\n` en
  `\n`, le patch ne correspondait plus à l'index. Pire : un `apply --cached` antérieur avait fait
  entrer des lignes CRLF dans un blob (avertissements « trailing whitespace » au moment d'appliquer),
  et le diff suivant montrait mes 13 lignes comme « modifiées ». Le script travaille en octets ;
  la normalisation se fait au commit suivant, c'est attendu.
- **2026-09-16 — mot-clé dans le contexte.** `Banc de comparaison` était la ligne AU-DESSUS de
  mes lignes changées dans `mecanismes.py` : 0 hunk sélectionné. Le mot-clé doit être sur une
  ligne `+` ou `-`.
- **2026-09-16 — la console Windows.** Un `↔` dans un titre de hunk a fait planter l'affichage
  (cp1252). Le script remplace ce qu'il ne sait pas encoder ; le patch, lui, est en UTF-8.
- **2026-09-24 — une INSERTION PURE se pose par NUMÉRO DE LIGNE, pas par contenu.** Sans
  contexte (`-U0`), un hunk qui remplace est vérifié par ses lignes `-` ; un hunk qui ne fait
  qu'AJOUTER (`@@ -N,0 +M @@`) n'a rien à vérifier : `git apply` le pose à la ligne N. Si des
  hunks laissés de côté le précèdent dans le fichier, N ne désigne plus le même endroit. Vécu
  sur `manifests/apps/reader.json` : `"update_settings",` inséré DANS une entrée de route →
  JSON invalide sur HEAD, `doc_facts` en panne (signalé par une autre instance). Avant de
  commiter : **valider le fichier indexé** (`git show :<fichier>` → parseur JSON/`py_compile`),
  et relire chaque insertion pure dans `git diff --cached`.
- **2026-09-19 — un reste déclaré sur un fichier co-édité peut être déjà soldé trois blocs plus
  bas.** Avant de commiter un handoff dans `PROJECT_STATUS`, relire les blocs du même jour :
  un autre s'y est peut-être déjà chargé du point.

- 🔴🔴 **2026-09-26 — `git apply --cached --unidiff-zero` POSE MAL UNE INSERTION PURE quand des
  hunks laissés la PRÉCÈDENT.** C'est la récidive du piège du 24/09, par l'autre bout : là il
  s'agissait d'un hunk posé au bon endroit d'un fichier devenu faux ; ici le hunk lui-même
  atterrit ailleurs. Mesuré sur `assistant_engine.py` (12 hunks miens, 10 laissés) : un hunk
  `@@ -328,0 +364,5 @@` de docstring s'est posé **d'après le numéro NOUVEAU 364**, et comme les
  35 lignes d'autrui qui le précèdent n'étaient pas appliquées, 364 désignait le milieu du corps
  de la fonction — **le fichier indexé ne compilait plus**.
  ✅ **La voie sûre** : ne pas laisser `git apply` choisir. Recomposer le blob **par les numéros
  de lignes ANCIENS** (ils référencent tous le même fichier, HEAD, donc ils ne se décalent
  jamais), puis le poser avec `git hash-object -w --stdin` + `git update-index --cacheinfo`.
  Script : `stage_by_oldlines.py` à côté de ce skill. Il **vérifie chaque hunk de remplacement
  contre HEAD avant de poser** (`present == removed`) — un hunk qui ne correspond pas arrête tout.
  ✅ **Et le contrôle qui l'aurait attrapé de toute façon** : après avoir construit l'index,
  `git show :<fichier>` puis `py_compile` (ou le parseur du format) **sur le blob INDEXÉ**, plus
  un `grep` à zéro sur les symboles des hunks laissés. L'arbre de travail, lui, compile toujours :
  il porte les deux chantiers. ⚠ Extraire ce blob par une redirection shell le TRANSCODE sous
  Windows (un em-dash devenu `?` → faux `SyntaxError`) : lire en OCTETS, sinon on diagnostique
  son propre instrument.
  🔴 **Récidive le 2026-09-30 — SANS avoir ouvert ce skill** (script maison `apply --unidiff-zero`
  sur le gabarit du transcriber, 5 hunks d'autrui avant le mien) : le bloc `{% comment %}` s'est
  posé DANS le script du lot (numéro nouveau 203 au lieu de l'ancien 222), commité tel quel
  (`3883098d`), rattrapé par `91d65890` (blob recomposé depuis HEAD + `update-index --cacheinfo`).
  Le contrôle qui l'a vu : `git diff -U0 --ignore-cr-at-eol` APRÈS le commit, qui montrait encore
  mes lignes — côté retiré ET côté ajouté. *Charger ce skill avant tout commit partiel, même
  « simple » : le piège est dans l'outil, pas dans la complexité du cas.*
  🔴 **3ᵉ récidive le 2026-10-12, encore SANS avoir ouvert ce skill** — et `/palier §3` en était
  la cause : il prescrivait lui-même « patch `-U0` + `git apply --cached` » (corrigé le jour même).
  Hunks filtrés d'un `-U0` sur une doc dérivée (`docs/dev/briques.md`, un bloc de six lignes
  d'autrui retiré du patch) : quatre entrées posées six lignes trop haut (`ac46fb72`), rattrapé par
  `91513a99` (contenu cible = fichier de l'arbre MOINS la part d'autrui, vérifié par deux `diff`
  — contre l'arbre, contre HEAD —, puis `hash-object` + `update-index --cacheinfo`). Même contrôle
  qui l'a vu : le diff de l'arbre contre le nouveau HEAD, relu après le commit.
- 🔴 **2026-09-26 — vérifier l'index PUIS commiter laisse une FENÊTRE DE COURSE.** Mesuré le
  jour même : `git diff --cached --stat` montrait 15 fichiers, le `git commit` qui a suivi en a
  porté **16**. Une autre instance avait stagé un `git mv` entre les deux (le temps de rédiger le
  message). Rien n'a été perdu — son contenu de travail est resté non stagé —, mais le renommage
  est enregistré sous mon message.
  ✅ **La forme sans fenêtre est l'INDEX TEMPORAIRE ci-dessous, et elle vaut pour TOUS les cas,
  pas seulement « index non vide » : un index vide ne le reste pas.** Le faire par défaut.
  ⭐ *Une vérification et le geste qu'elle autorise doivent être ATOMIQUES, ou la vérification ne
  vaut que pour l'instant où elle a eu lieu.*
- 🔴 **2026-09-26 — un `--amend` RECRÉE le commit : LE SHA AFFICHÉ PAR LE PREMIER `git commit`
  EST MORT.** Vécu le jour même : le handoff citait le sha d'avant l'amendement du message, donc
  un objet **introuvable, `git log --all` compris**. Une consignation qui cite un sha mort envoie
  la session suivante nulle part, **et rien ne le signale** — `check_docs` ne vérifie pas les shas.
  ✅ Relire `git log -1 --format=%h` **après le dernier amendement**, et pour retrouver un commit
  amendé, le chercher par son MESSAGE (`git log --format='%h %s' | grep <ancre>`), jamais par le
  sha noté plus tôt.
- 🔴🔴 **2026-09-28 — L'INDEX TEMPORAIRE A SA PROPRE FENÊTRE : il ANNULE les commits qui
  arrivent entre `read-tree HEAD` et `git commit`.** L'index est construit depuis le HEAD de
  l'instant T ; `git commit` prend pour PARENT le HEAD de l'instant T+n. Vécu : deux commits
  d'autres instances (calendrier, import — 15:52) entre mon `read-tree` et mon `commit` (16:03) →
  mon commit avait leur commit pour parent et l'ANCIEN arbre pour contenu : il **défaisait tout
  leur travail dans HEAD** (`fullcalendar` supprimé, planification nocturne revenue en arrière,
  vues de 4 apps rétablies). Rien ne l'a signalé : le `--stat` vérifié AVANT le commit était juste,
  c'est le parent qui avait bougé. Vu en relisant `git show HEAD -- wama/settings.py`.
  ✅ **La forme ATOMIQUE** : noter le HEAD lu (`BASE=$(git rev-parse HEAD)` au moment du
  `read-tree`), puis `TREE=$(git write-tree)`, `NEW=$(git commit-tree $TREE -p $BASE -F msg)`,
  `git update-ref refs/heads/<branche> $NEW $BASE` — l'`update-ref` à valeur attendue **échoue**
  si la branche a bougé : on reconstruit sur le nouveau HEAD, on ne défait rien.
  ✅ **Le contrôle qui l'attrape après coup** : `git show --stat HEAD` doit lister MES seuls
  fichiers ; une suppression ou un fichier inconnu = parent déplacé. Réparation : reconstruire
  l'arbre sur `HEAD~1` (leur commit) + mes fichiers, puis remplacer par `commit-tree` +
  `update-ref <nouveau> <commit fautif>` — jamais `--amend`, qui remplacerait HEAD quel qu'il soit.
- **2026-09-26 — l'index partagé n'est PAS vide (WIP stagé d'autrui) mais on doit commiter
  quand même.** Voie sûre : un INDEX TEMPORAIRE — `GIT_INDEX_FILE=<scratchpad>/tmp.index`,
  `BASE=$(git rev-parse HEAD)` puis `git read-tree $BASE`, `git apply --cached` du patch,
  `git add` de ses fichiers propres, **`commit-tree -p $BASE` + `update-ref … $BASE`** (jamais
  `git commit` : voir le piège du 2026-09-28 ci-dessus), puis `unset GIT_INDEX_FILE`. ⚠⚠ **ET ENSUITE** : l'index partagé garde, pour
  les chemins commités, les blobs de l'ANCIEN HEAD — `git status` les montre alors en `M`/`D`
  en 1ʳᵉ colonne, c'est-à-dire comme un RETOUR ARRIÈRE STAGÉ que le prochain `git commit` de
  l'autre instance emporterait. Réaligner **ces seuls chemins** : `git reset -q HEAD -- <mes
  chemins>` (jamais un `git reset` global), puis vérifier que `git diff --cached --stat` est
  revenu à l'état d'autrui d'avant.

- 🔴🔴 **2026-09-28 — l'INDEX TEMPORAIRE a sa propre fenêtre de course : HEAD qui BOUGE.** Construit
  par `git read-tree HEAD`, il photographie le HEAD de CET instant. Une autre instance a commité
  `48a198bc` quarante secondes avant mon `git commit` : le commit, posé sur le NOUVEAU HEAD avec
  l'arbre construit sur l'ANCIEN, a **défait ses deux fichiers** (`838184e7`, 33 fichiers annoncés
  pour 31 construits — le seul signe). Rattrapé par un commit correctif à pathspec (`7aa1e258`),
  contenu vérifié identique à `48a198bc`.
  ✅ **Le contrôle** : noter `BASE=$(git rev-parse HEAD)` au `read-tree`, et juste avant le commit
  exiger `[ "$(git rev-parse HEAD)" = "$BASE" ]` — sinon RECONSTRUIRE l'index (relancer le script),
  jamais commiter. Et après : `git show --stat HEAD` doit compter EXACTEMENT les fichiers de l'index
  temporaire ; un fichier de plus est un changement d'autrui défait.
  ⭐ *Un index isolé protège de l'index des autres, pas de leurs commits.*

- ⚠ **2026-10-01 — « hunks=0, patch VIDE » alors que le fichier porte bien mes lignes : le
  répertoire COURANT n'était pas la racine du dépôt.** Les scripts de ce skill appellent `git`
  dans le cwd (le terminal de la session était dans un sous-dossier, `manifests/apps`) : le diff
  rendait vide, et un script qui ne trouve rien ne lève pas. ✅ Lancer le geste depuis un script
  qui fait lui-même `cd <racine>` en tête (le `cd` est alors DANS le script, pas en préfixe de
  commande — règle de `CLAUDE.md`), et lire le compte « hunks=… miens=… » avant d'appliquer :
  zéro sur un fichier qu'on sait avoir touché = mauvais répertoire, pas « rien à moi ».

- ⚠ **2026-10-06 — une vérification d'index s'écrit contre la DIFFÉRENCE, jamais contre une
  supposition sur HEAD.** Vécu : pour prouver que le WIP d'autrui restait hors de l'index sur
  `imager/apps.py`, j'ai exigé dans le blob indexé une ligne que je CROYAIS dans HEAD
  (`register_app_detail_spec('imager'`) — elle était justement dans le WIP de l'autre instance.
  `set -e` a arrêté le script AVANT le commit (rien de cassé), mais la garde était fausse.
  ✅ Ce qui se vérifie sans rien supposer : `git diff --cached -U0 -- <f>` ne porte QUE mes
  lignes (ex. `grep -c '^-<ma ligne>'` = 1 et `--numstat` = mes compteurs), et une ligne d'autrui
  compte autant dans `:<f>` que dans `HEAD:<f>`.
  ⭐ *Une garde qui affirme le contenu d'un fichier suppose sa version ; une garde qui affirme
  une différence n'en suppose aucune.*
- 🔴 **2026-10-05 — une GARDE qui s'arrête ne protège que ce qui lui est enchaîné par `&&`.**
  Vécu : `python garde.py && git diff … ; git commit … -- <chemins>` — la garde a bien refusé
  (« fichier déjà modifié par autrui », le point d'étape venait d'être touché à l'instant), mais le
  `git commit` qui suivait un POINT-VIRGULE est parti quand même, par chemin, et a emporté 29
  lignes d'une autre session sous mon message. Rattrapé par remplacement du commit (`commit-tree`
  sur le parent + `update-ref <nouveau> <fautif>`, puis `git reset -q HEAD -- <fichier>`) : les
  lignes sont revenues non commitées dans l'arbre.
  ✅ La garde et le commit vivent dans le MÊME script, ou sont liés par `&&` de bout en bout ;
  jamais un `;` entre une vérification et le geste qu'elle autorise. Et un fichier « propre il y a
  une minute » ne l'est plus : c'est l'état AU MOMENT du commit qui compte.
- 🔴🔴 **2026-10-11 — RÉCIDIVE du piège du 28/09 (HEAD qui bouge), cette fois sur TROIS commits.**
  `c44f0432` a pour parent `d237fd8e`, mais son arbre avait été lu sur `025e7209` : il a DÉFAIT
  dans HEAD trois commits d'autres sessions (29 fichiers, dont 6 supprimés). Rien ne l'a signalé à
  son auteur ; vu par une autre session parce que `git diff --cached` montrait comme « à ajouter »
  des fichiers qu'elle savait commités. ⇒ le `[ HEAD = BASE ]` + `update-ref … $BASE` du §1 n'est
  pas facultatif, c'est lui qui manquait.
  ✅ **Réparation sans réécrire l'histoire, et sans rien recopier à la main** — la fusion à trois
  voies sur la base PÉRIMÉE : `TREE=$(git merge-tree --write-tree --merge-base=<base périmée>
  <parent réel> <commit fautif> | head -1)` (une seule ligne = sans conflit). Trouver la base :
  `git diff --stat <candidat> <fautif>` ne doit montrer QUE le travail propre du fautif. Vérifier
  avant de poser : `git diff --stat <parent réel> $TREE` = ce travail exactement ; puis
  `commit-tree $TREE -p <fautif>` + `update-ref … <fautif>` (`f531436f`). Ici l'arbre fusionné
  était IDENTIQUE à l'index partagé, qui portait encore le bon contenu — l'index réaligné sur HEAD
  est revenu vide de lui-même.
- ⚠ **2026-10-12 — le classifieur du mode auto peut REFUSER `commit-tree` + `update-ref`** (lu
  comme une falsification d'historique). Ne pas insister ni contourner : repli sur la voie du §1
  par l'index PARTAGÉ, **seulement s'il est vide au départ** — `stage_my_hunks.py` puis
  `stage_by_oldlines.py` (il pose le blob par `update-index`, sans `commit-tree`), vérification
  et `git commit -F` sans pathspec **enchaînés par `&&` dans une seule commande** (la fenêtre de
  course se réduit à cette commande). Vécu sur un bloc de clôture ajouté en fin de
  `PROJECT_STATUS`, à côté d'un palier non commité d'une autre instance : `45a0a8ac`, 19 lignes
  miennes seules.
  ⚠ Et dans le script de garde, sous `set -o pipefail`, **`grep -c … | grep -qx 0` échoue
  justement quand le compte vaut zéro** (`grep -c` sort en 1 sans correspondance) : la garde a
  arrêté un index CORRECT. Tester une absence par `! grep -q <motif>`.
  ⚠ **Et pas `git show :<f> | grep -q <motif>` non plus** (vécu le même jour, autre session) :
  `grep -q` ferme le tube à la PREMIÈRE correspondance, `git show` meurt en SIGPIPE, `pipefail`
  rend l'échec et `set -e` arrête un index CORRECT juste avant le commit. Écrire le blob indexé
  dans un fichier (`git show :<f> > <scratchpad>/x`), puis `grep -q` sur ce fichier.
- 🔴 **2026-10-18 — un relevé TRONQUÉ ne mesure pas, et un DÉPLACEMENT ne porte aucun mot
  d'autrui.** `git diff -U0 <f> | grep '^[-+]' | head -30` n'a montré que mes lignes de
  `mecanismes.py` ; une autre instance y avait déplacé 232 lignes à l'identique, plus bas que la
  coupure — commitées sous mon message (`42157a42`, 245/240 pour ~8 lignes miennes), vu au
  `--numstat` du commit. Un `grep` des mots-clés de son chantier ne le voit pas non plus : un bloc
  déplacé n'en contient aucun. ✅ Comparer le `--numstat` à ce qu'on attend (la garde `expect` du §1
  d) ; après coup, `git show --numstat HEAD` puis un relevé « lignes retirées ET réajoutées à
  l'identique » par fichier. Réparé par le blob recomposé (parent + mes seules éditions) et
  `commit-tree` + `update-ref <nouveau> <fautif>` (`5ffd611e`) ; le déplacement est resté intact
  dans l'arbre.
- 🔴 **2026-10-18 — un compteur `expect` RECOPIÉ du `numstat` de l'arbre ne garde rien.** Le
  commit `188f732b` a emporté deux tests d'une autre instance dans `synthesizer/tests.py` : la garde
  `expect … 79 1` avait été remplie en lisant `git diff --numstat` à l'instant même — elle comparait
  l'arbre à lui-même. ✅ Le compte attendu se fait sur CE QU'ON A ÉCRIT (lignes de son bloc, ou les
  `def test_` de sa classe), puis se confronte au `numstat` ; un fichier de tests partagé se relit
  par ses `def test_` ajoutés (`git diff -U0 <f> | grep '^+    def test_'`) avant le commit.

## 4. Docs générées

Un bloc régénéré (`doc_facts`) projette le REGISTRE tel qu'il est dans l'arbre, WIP d'autrui
compris. Deux gestes sûrs : filtrer les hunks comme pour tout fichier co-édité, ou laisser la
régénération à qui commitera le registre (cf. `/cloture §2b` : régénérer figerait le WIP non
commité d'une autre instance).

✅ **Troisième geste, quand c'est TON registre qui a bougé** (2026-09-30) : régénérer dans un
**worktree de HEAD** (après le commit du registre) — il ne projette que du code COMMITÉ — puis
poser ces fichiers dans un index temporaire (`git hash-object -w --path=<f> <worktree>/<f>` +
`update-index --cacheinfo`) et commiter.
⚠⚠ **Mais un worktree n'a pas ce qui est NON VERSIONNÉ, et deux docs générées le lisent**
(vécu le 2026-10-14, deux fois de suite) : la table de `WAMA_MECANISMES.md` y sortait des
DÉCOMPTES de consommateurs différents sur toute la table (22 au lieu de 33, 362 au lieu de 419 —
le décompte balaie aussi des fichiers ignorés), et le bloc généré du skill `conformite` y
annonçait « aucun rapport mesuré », faute de `logs/`. Commiter ces versions aurait été un
artefact du worktree présenté comme une régénération.
✅ **Le geste qui a tenu** : comparer chaque doc régénérée entre le worktree et l'arbre principal
(`diff --strip-trailing-cr`). Identique → la version du worktree est sûre (`docs/dev/briques.md`
l'était). Différente → n'en prendre que SES lignes, recomposées sur le blob de HEAD (pour la
table des mécanismes : le texte régénéré de ses lignes, la cellule de décompte de HEAD), avec
une garde qui exige le nombre exact de lignes changées ; et laisser de côté un bloc qui dépend
de `logs/`.
🔴 **Et NE PAS « nettoyer » l'arbre ensuite par `git checkout -- <doc générée>`** : vécu le jour
même, une autre instance avait régénéré ces fichiers entre la vérification et le geste, et le
checkout a effacé sa régénération (projection pure, donc rattrapable par `doc_facts`, mais c'est
une chance, pas une règle). Après le commit, `git reset -q HEAD -- <f>` réaligne l'INDEX et suffit ;
l'arbre ne se touche pas — ce qui y reste modifié est à quelqu'un d'autre.

🔴 **Des MANIFESTES régénérés dans un worktree de HEAD se jouent depuis WSL (`venv_linux`)**
(2026-10-04). Le worktree règle « ne projeter que du commité » ; il ne règle pas « avec quel
venv ». Vécu : `manifest_export --kind app` joué par venv_win dans le worktree a SORTI trois
librairies des manifestes d'app (audiocraft, resemble-enhance — absentes du venv Windows), commité
tel quel, rattrapé au commit suivant par un ré-export WSL. Le signe : des lignes `"kind":
"library"` SUPPRIMÉES dans `git show --stat` d'un commit de régénération. Les docs (`doc_facts`)
ne sont pas concernées ; tout ce qui lit `importlib.metadata` l'est.

## 5. Avant de livrer le commit

- `git diff --cached --stat` relu **à voix haute** : chaque fichier, chaque nombre de lignes, est
  à moi. Une ligne inattendue = `git reset -q -- <fichier>` de cette seule entrée, et on cherche.
- Le commit fait, `git status --porcelain` doit toujours montrer les fichiers co-édités en ` M`
  (première colonne à espace) : le WIP d'autrui est resté dans l'arbre, intact.

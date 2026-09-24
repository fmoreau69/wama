---
name: commit-partiel
description: Commiter SES seuls hunks d'un fichier co-édité par une autre instance (PROJECT_STATUS, ROADMAP, AGENTS.md, mecanismes.py, docs générées) — l'index se construit hunk par hunk, se VÉRIFIE, puis se commite. Utiliser quand `git status` montre un fichier partagé porteur de lignes qui ne sont pas à soi, quand l'utilisateur dit « une autre instance travaille dessus », « ne commite que tes lignes », « attention au WIP de l'autre », ou avant tout commit d'un handoff.
---

# /commit-partiel — ne commiter que ses hunks d'un fichier co-édité

> ⚠ CANDIDAT (n=1, 2026-09-19) — une seule session l'a produit, donc `check_skills` suit son âge.
> ⚠ Mais **le GESTE, lui, a été vécu CINQ fois** dans cette session (14→19/09) : ce qui n'a jamais
> été éprouvé, c'est le skill. Il sera promu à sa première exécution qu'il aura guidée de bout en
> bout — pas à la 6ᵉ occurrence du geste.

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

## 1. Le geste, dans l'ordre

```bash
# a. l'index doit être VIDE avant de commencer — sinon il porte du WIP d'autrui
git diff --cached --stat            # attendu : rien
# b. un patch -U0 des seuls hunks dont une ligne +/- porte MON mot-clé
python .claude/skills/commit-partiel/stage_my_hunks.py <scratchpad>/mine.patch \
    "docs/construction/suivi/PROJECT_STATUS.md=<mot-clé>" "docs/construction/suivi/ROADMAP.md=<mot-clé>"
# c. dans l'index, sans toucher l'arbre
git apply --cached --unidiff-zero --whitespace=nowarn <scratchpad>/mine.patch
# d. mes fichiers PROPRES, entiers
git add <fichier propre> ...
# e. VÉRIFIER — tout ce qui s'affiche doit être à moi (fichiers ET hunks)
git diff --cached --stat
git diff --cached -U0 | grep '^@@'
# f. commiter DEPUIS l'index vérifié — sans pathspec, c'est voulu ; le message le DIT
git commit -F <scratchpad>/msg.txt
# g. l'index est redevenu vide, HEAD ne porte que mes fichiers
git diff --cached --stat | wc -l    # 0
git show --stat --format='%h %s' HEAD
```

Le **mot-clé** est un mot que SEULES mes lignes changées portent dans ce fichier : le nom du
chantier, une clé de champ (`vram_measured`), un nom de doc neuf. Un mot présent dans le contexte
seulement ne sélectionne rien (le patch est sans contexte).

Le **message** dit que l'index a été construit hunk par hunk sur des fichiers co-édités : celui
qui lira `git log` doit comprendre pourquoi ce commit n'a pas de pathspec.

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

## 4. Docs générées

Un bloc régénéré (`doc_facts`) projette le REGISTRE tel qu'il est dans l'arbre, WIP d'autrui
compris. Deux gestes sûrs : filtrer les hunks comme pour tout fichier co-édité, ou laisser la
régénération à qui commitera le registre (cf. `/cloture §2b` : régénérer figerait le WIP non
commité d'une autre instance).

## 5. Avant de livrer le commit

- `git diff --cached --stat` relu **à voix haute** : chaque fichier, chaque nombre de lignes, est
  à moi. Une ligne inattendue = `git reset -q -- <fichier>` de cette seule entrée, et on cherche.
- Le commit fait, `git status --porcelain` doit toujours montrer les fichiers co-édités en ` M`
  (première colonne à espace) : le WIP d'autrui est resté dans l'arbre, intact.

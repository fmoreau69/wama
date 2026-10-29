# Brief commun — audit « doc de construction ↔ code » de WAMA

## Cadre
- Dépôt à auditer, EN LECTURE SEULE : `/tmp/claude-0/-home-user-wama/2d5c9bd3-5251-5273-ad46-62da8e49809a/scratchpad/dev`
  (copie de travail détachée de `origin/dev`, commit `3b497863`, 2026-10-29). C'est la vérité du code.
- **Ne modifie AUCUN fichier de ce dossier**, ne lance aucune commande git qui change son état
  (pas de checkout, reset, commit, stash). `git log`, `git show`, `git log -S` sont permis
  (préfixe `git -C <dossier>`). Ne lance pas `manage.py` (Django n'est pas installé ici).
- Le seul fichier que tu écris est ton rapport : `/tmp/claude-0/-home-user-wama/2d5c9bd3-5251-5273-ad46-62da8e49809a/scratchpad/out/findings/<LOT>.md`.
- But : un rapport que des sessions Claude Code locales du mainteneur (Fabien) appliqueront
  ensuite pour mettre la doc à jour. Il doit donc être ACTIONNABLE sans relire ton raisonnement.
- Langue du rapport : français.

## Doctrine du projet à appliquer (extraits d'AGENTS.md — à respecter strictement)
1. **Une affirmation sur le code nomme la LIGNE qui la fonde** (fichier:ligne, ou sortie de
   commande). Pas de conclusion tirée d'un compteur, d'une ressemblance de noms ou d'un grep
   étroit : ouvre le code désigné. Si tu concluais une ABSENCE, dis quel motif tu as cherché et
   pourquoi il couvre le cas (symbole ET ses accesseurs / autres graphies).
2. **Un CONSTAT** (affirmation sur l'état présent : « X n'existe pas », « N apps adoptent »,
   « ⏳ non implémenté », « le fichier fait ceci ») **qui contredit le code a tort par défaut**.
3. **Une INTENTION** (objectif, cible, vision, plan ⏳) **ne contredit pas le code** : elle ne se
   signale que si elle est désormais RÉALISÉE (statut à passer ✅/🔄) ou explicitement abandonnée
   par le code. Ne propose JAMAIS de retirer une intention parce qu'elle n'est pas construite.
4. Un statut DATÉ (« mesuré le 2026-09-18 : 863/906 ») est une trace historique, pas un constat
   faux : ne le signale que s'il est présenté comme l'état ACTUEL sans date, ou si une phrase plus
   récente du même doc dit le contraire sans que la plus ancienne soit marquée périmée.
5. Les passages barrés `~~…~~`, explicitement archivés, « ex-`…` », « renommé » sont voulus.
6. Les docs `PROJECT_STATUS.md` et `CAM_ANALYZER_CHANGELOG.md` sont des JOURNAUX : leurs blocs
   datés sont vrais à leur date. On n'y signale que (a) les en-têtes / tableaux d'état / listes de
   PENDING ou de reprise présentés comme l'état courant, (b) les ⏳ ouverts qui sont faits.
7. Ne signale pas le style, la langue, la longueur ou la mise en forme. Seulement le VRAI/FAUX
   par rapport au code, et les contradictions entre documents de référence.

## Méthode attendue
1. Lis ton/tes document(s) EN ENTIER, par tranches (outil Read avec offset/limit).
2. Relève chaque constat vérifiable : statuts ✅/🔄/⏳, « n'existe pas / non implémenté / reste à
   faire / aucun consommateur », chiffres d'état (N apps, N critères, N tests, budgets), chemins
   et symboles cités, descriptions de comportement d'une brique.
3. Confronte chacun au code (Grep/Glob/Read sur le dépôt ci-dessus ; `git log` pour dater un
   changement). Priorise ce qui ORIENTERAIT MAL une session future (un ⏳ qui est fait, une
   brique dite absente qui existe, un chemin mort, un comportement décrit à tort).
4. Trie les **candidats mécaniques** fournis pour ton lot (fichier
   `/tmp/claude-0/-home-user-wama/2d5c9bd3-5251-5273-ad46-62da8e49809a/scratchpad/out/mech/<chemin_du_doc avec / remplacés par __>.txt`,
   s'il existe) : confirme ou écarte chacun. `LIGNE_DECALEE` donne la ligne actuelle probable du
   symbole — vérifie-la. `SYMBOLE_INCONNU` est un candidat FAIBLE (souvent du code tiers, une
   intention, une clé de donnée) : ne le rapporte que si tu as établi un renommage / un retrait.
5. Contradictions entre docs : si ton doc affirme une chose qu'un autre doc de référence
   contredit (et que le code tranche), signale-le en nommant les deux emplacements.

## Format OBLIGATOIRE du rapport `<LOT>.md`
```
# Lot <LOT> — <documents couverts>

## Synthèse
- 3 à 8 puces : les écarts les plus importants du lot, et l'état général (doc globalement à jour
  ou non, sections les plus périmées).

## <chemin/du/doc.md>
| # | Ligne(s) | Type | Ce que dit la doc | Ce que dit le code (preuve) | Correction proposée | Confiance |
|---|---|---|---|---|---|---|
| 1 | 1234 | STATUT_PERIME | « ⏳ nœud pipeline non implémenté » | `wama/…/x.py:40-42` … | passer ✅ + date + renvoi | certaine |
```
Types autorisés (un seul par ligne) :
`STATUT_PERIME` (⏳/🔄 alors que c'est fait, ou ✅ alors que c'est défait) ·
`CONSTAT_FAUX` (affirmation sur l'état présent contredite par le code) ·
`CHIFFRE_PERIME` (compte présenté comme actuel, non daté, faux) ·
`REFERENCE_CASSEE` (fichier/symbole/doc cité qui n'existe plus ; donner le nouveau s'il existe) ·
`LIGNE_DECALEE` (fichier:ligne qui ne pointe plus sur ce qui est décrit ; donner la bonne ligne) ·
`CONTRADICTION_DOCS` (deux docs se contredisent ; dire lequel le code confirme) ·
`MANQUE` (le code a une brique/décision majeure que ce doc, qui en est le domicile, ignore).

Règles de remplissage :
- « Ce que dit la doc » : citation COURTE et exacte (pour qu'une session la retrouve par recherche).
- « Preuve » : `chemin:ligne` dans le dépôt, ou commit `sha` + date, ou commande + sortie.
- « Correction proposée » : formulée pour être appliquée telle quelle (quoi écrire, où).
- Confiance : `certaine` (preuve lue) ou `probable` (preuve indirecte — dire laquelle).
- Regroupe les `LIGNE_DECALEE` d'un même doc dans une seule sous-table en fin de section.
- Termine par `## Non vérifié` : ce que tu n'as pas pu trancher, et pourquoi.

Sois exhaustif sur ton lot, mais ne remplis pas de lignes douteuses : mieux vaut 40 écarts
prouvés que 150 soupçons. Ta réponse finale (message de retour) : 5 lignes maximum — le chemin
du rapport, le nombre d'écarts par type, et les 3 plus graves.

---
name: doc-sync
description: Tenir les .md de référence WAMA à jour du code — PASSE COURTE après chaque livrable (doc du domaine, statut de la section de ROADMAP qui le planifiait, marque de la section de vision qui porte l'intention) et PASSE LONGUE de resynchronisation (références cassées, chemins périmés, statuts contredits, ROADMAP et vision confrontées au code). Utiliser après un livrable (appelée par /palier, /reverif, /port-app, /brique…), en fin de gros chantier, ou quand l'utilisateur dit « mets à jour les docs », « la doc est en retard ».
---

# /doc-sync — la doc suit le code, en cours de route et pas seulement à la clôture

Objectif : que les docs de référence (un domaine = un fichier, table d'`AGENTS.md`) disent le réel.
Deux passes : la COURTE, à chaque livrable, quelques minutes ; la LONGUE, quand la doc a décroché.

> **Pourquoi la passe courte existe (2026-10-26, Fabien : « la doc semble très en retard par rapport
> à l'existant du code, notamment roadmap et vision […] généraliser l'ajout dans les skills qui le
> nécessitent, pas seulement à la clôture »).** Mesuré ce jour-là : la ROADMAP (6 756 lignes) portait
> en tête « Dernière mise à jour : 2026-07-20 » et la vision une confrontation au code du 2026-08-27,
> pour ~3 000 commits depuis. `/palier` consignait dans `PROJECT_STATUS` et dans le doc du domaine ;
> RIEN ne faisait suivre le statut de la section de ROADMAP qui PLANIFIAIT le livrable, ni la marque
> de la section de vision qui en porte l'INTENTION. Elles restaient ⏳ pendant que le code avançait.

## 0. La règle qui tranche tout : CONSTAT ≠ INTENTION (`AGENTS.md`, § VÉRIFIER LA ROUTE)

- Un **constat** dit l'état présent (« X est livré », « N outils », « pas câblé », une marque
  ✅/🔄/⏳/💡) : s'il contredit le code, il a TORT — on le corrige, daté, preuve à l'appui.
- Une **intention** (but, plan, vision) ne se retire JAMAIS par une passe : sa marque change
  (✅ fait · 🔄 en partie · ⏳ pas encore), datée. Seule une DÉCISION la retire.
- Une **trace datée** (un relevé « mesuré le … », un palier de `PROJECT_STATUS`) ne se réécrit pas :
  on y AJOUTE un relevé daté.
- Toute correction nomme sa preuve : `fichier:ligne`, sha de commit, sortie de commande. Jamais une
  conclusion d'un `grep` seul (ouvrir ce qu'il désigne) ; une ABSENCE se prouve en grepant le symbole
  ET ses accesseurs.

## 1. PASSE COURTE — après CHAQUE livrable (appelée par les skills de travail)

Trois questions, chacune tranchée par une lecture :
1. **Le doc du domaine** (table d'`AGENTS.md`) a-t-il la ligne du livrable — décision, pourquoi,
   ce qu'il remplace, ce qui reste ? Un mécanisme transversal neuf : son entrée au registre
   `wama/common/mecanismes.py`, jamais une ligne à la main dans la table générée.
2. **La section de la ROADMAP qui le PLANIFIAIT** porte-t-elle son statut à jour ? La trouver :
   `grep -n -i "<nom du chantier>\|<symbole livré>" docs/construction/suivi/ROADMAP.md`. Passer
   ⏳ → 🔄/✅ **daté, sha cité**, et nommer ce qui reste. Un grand chantier livré entre aussi à la
   **Frise** (en tête de la ROADMAP).
3. **La section de la VISION qui en porte l'intention** (`docs/construction/mondes/WAMA_VISION_COMPLET.md`)
   change-t-elle de marque, ou son texte d'un constat (un compte, « pas encore ») ? La corriger,
   datée ; une capacité neuve d'envergure y gagne une phrase, dans la section de son monde.
Puis `python manage.py check_docs` (aucune référence neuve cassée) et, si un registre a bougé,
`python manage.py doc_facts` puis `doc_facts --check` (blocs GÉNÉRÉS). Une doc générée régénérée
porte aussi le travail d'autrui : n'en commiter que sa part (`/commit-partiel`).

## 2. PASSE LONGUE — resynchroniser une doc qui a décroché

### 2.1 Vérité terrain d'abord
- `git log --since=<date de la dernière mise à jour du doc> --name-only --format='=== %h %ad %s'
  --date=short -- . ':(exclude)venv_win' ':(exclude)venv_linux' ':(exclude)staticfiles'` → dumper
  dans le scratchpad (fichier consultable par les agents).
- Lister les `.md` racine et `docs/construction/archive/` : un lien vers un fichier archivé est cassé.

### 2.2 Fan-out d'agents (docs volumineux)
Agents Explore en parallèle, un par TRANCHE de doc (la ROADMAP se découpe par plages de lignes de
~1 000 à 1 600 lignes, la vision en entier), chacun avec :
- la tranche à lire EN ENTIER + le dump de commits ;
- la règle du §0 (constat / intention / trace datée) écrite dans la consigne ;
- vérifier CHAQUE lien `.md` et chemin de code, CHAQUE statut et CHAQUE chiffre contre le code ;
- sortie normalisée : LIGNE / ACTUEL / PROBLÈME [STATUT PÉRIMÉ] [FAIT PÉRIMÉ] [CASSÉ] [MANQUANT] /
  PREUVE / CORRECTION PROPOSÉE ; INCERTAIN sans preuve.

Groupes : la table des domaines d'`AGENTS.md` fait foi (~30 domaines) — la relire pour composer les
groupes ; toute énumération écrite ici dériverait.

### 2.3 Contre-vérification (obligatoire avant édition)
Les agents se trompent, surtout sur les ABSENCES et les « c'est fait » : re-vérifier soi-même
(`Grep`, `git log -S`, lecture du code) chaque [STATUT PÉRIMÉ], [CASSÉ] et [FAIT PÉRIMÉ] AVANT de
l'appliquer. Ignorer les INCERTAIN non confirmés. ⚠ Un sha cité doit exister (`git cat-file -t`).

### 2.4 Appliquer
- **Blocs GÉNÉRÉS = hors périmètre manuel** : la table de `docs/construction/architecture/WAMA_MECANISMES.md`
  et les blocs `WAMA:FAITS` se régénèrent par `python manage.py doc_facts` (source = registres) —
  un écart s'y corrige à la source puis se régénère.
- Éditions MINIMALES (statut, date, référence, chiffre) ; jamais de réécriture d'une section saine.
- Mettre à jour la date d'en-tête (« Dernière mise à jour », « dernière confrontation au code ») des
  docs touchés.
- Respecter « un domaine = un fichier » : aucun doc « bis » ; un contenu au mauvais endroit se
  fusionne vers le fichier de référence.

## 3. Commit
Commit local par chemins explicites (les seuls `.md` touchés ; `/commit-partiel` dès qu'un fichier
est co-édité), message `docs(<domaine>) : …` qui dit ce qui a été confronté et à quelle date.
Push = demander.

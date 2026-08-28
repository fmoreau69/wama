---
name: skill-forge
description: Distiller un geste RÉSOLU en skill versionné (.claude/skills/) ou compléter le skill existant qui couvre déjà le domaine — l'écrivain de la mémoire procédurale (la moitié d'Hermes retenue le 2026-07-29). Utiliser en fin de résolution d'une tâche répétable non couverte, quand une demande ressemble à une résolution passée (2ᵉ occurrence = promotion), ou quand l'utilisateur dit « fais-en un skill », « distille », « skill-forge ».
---

# /skill-forge — Distiller une résolution en skill

> ⚠ CANDIDAT (n=1, 2026-08-28) — écrit depuis la doctrine et UNE naissance vécue (`/crash-residus`) ;
> sera promu à la première distillation qu'il aura lui-même guidée de bout en bout.

Doctrine d'origine : décision Hermes (`ROADMAP.md` §16.7) — le runtime est écarté, la
**mémoire procédurale** est retenue : « ce qui manque n'est pas le dossier mais l'écrivain ».
Ce skill EST cet écrivain, pour la partie dev (`.claude/skills/`) uniquement — voir §6.

## 0. La règle d'or — distiller, jamais inventer

Un skill naît d'une tâche **RÉSOLUE** : il fige ce qui vient d'être vécu et mesuré, à la
**clôture** de la résolution — jamais à l'ouverture d'une requête, où il n'y a rien à
distiller (un gabarit vide au mieux, de la doctrine inventée au pire).

> ⚠⚠ **Un skill est de la doctrine exécutable, pas une note** : ce qu'il affirme est appliqué
> sans être revérifié. Un chiffre faux dans un `.md` se discute ; dans un skill, **il se fait
> obéir** (audit 2026-08-26 : 8 skills sur 11, écrits avec soin, portaient des chiffres ou
> chemins faux). N'y écrire que du vécu dans la session, du mesuré, ou du renvoi.

## 1. Chercher l'existant AVANT de créer — même règle que les `.md`

- Lire les descriptions de `.claude/skills/*/SKILL.md`. Si un skill couvre le domaine →
  le **COMPLÉTER**. **Un domaine = un skill** ; jamais de skill « bis » (c'est la maladie
  des `.md` concurrents, version skills — et un skill-écrivain automatique est précisément
  le mécanisme qui peut la réintroduire en masse).
- Vérifier si la demande ressemble à une résolution passée : handoffs `PROJECT_STATUS.md`
  §REPRISE + index `MEMORY.md` (c'est la trace cross-sessions — pas besoin d'un journal de
  requêtes). Si oui et qu'un skill **candidat** existe déjà → §4, c'est une promotion.

## 2. Règles de naissance (checklist, toutes bloquantes)

- [ ] dossier kebab-case, frontmatter `name:` **== nom du dossier** (invariant `check_docs`)
- [ ] `description` = le QUOI + le **QUAND déclencher**, avec les phrases que l'utilisateur
      dira réellement (« les disques se remplissent », « on clôt la session »…)
- [ ] **la COMMANDE, pas la valeur** : tout chiffre mesurable est remplacé par la commande
      qui le mesure ; une valeur ne subsiste que **datée**, pour l'ordre de grandeur
- [ ] **les chiffres vivent dans leur doc-domicile** (table des domaines de CLAUDE.md) —
      le skill RENVOIE, il ne recopie pas
- [ ] scripts rejouables **DANS le dossier du skill**, jamais au scratchpad — un scratchpad
      meurt avec sa session (vécu : les scripts de nettoyage du 25/08, réécrits le 28/08
      dans `/crash-residus`)
- [ ] références code/doc par **chemins exacts vérifiés** (`check_docs` lit les skills)
- [ ] pièges **VÉCUS et datés** seulement — un piège imaginé est de la doctrine inventée
- [ ] gestes destructifs ou irréversibles → marqués « validation utilisateur » / « arbitrage
      Fabien », jamais auto-exécutables
- [ ] si le skill s'appuie sur une brique du repo → la citer par son domicile
      (`WAMA_MECANISMES.md` pour la trouver), ne jamais paraphraser son comportement

## 3. Naissance à n=1 : le statut CANDIDAT

Distillé d'UNE seule résolution, le skill porte en tête de corps :

```
> ⚠ CANDIDAT (n=1, <date>) — distillé d'une résolution unique, non confronté à une 2ᵉ occurrence.
```

Il est utilisable immédiatement (c'est le but : spécialiser dès la 1ʳᵉ requête suivante),
mais son lecteur sait qu'il n'a encore rien prouvé.

## 4. Promotion à n=2 — la 2ᵉ occurrence est la VALIDATION

Quand une demande retombe sur un skill candidat : le **dérouler tel quel**, noter ce qui
n'a pas tenu (chemin qui a bougé, étape manquante, ordre faux), **corriger dans la foulée**,
puis retirer la marque CANDIDAT. C'est le signal de retour minimal côté dev — l'équivalent
`RunOutcome` du runtime n'existe pas encore (§6).

Un candidat qui dort sans 2ᵉ occurrence pendant des mois est un candidat à la **fusion ou au
retrait** — le signaler à l'utilisateur, ne jamais le supprimer seul (`REMOVAL_LEDGER.md` si
retrait acté).

## 5. Avant de livrer

1. `python manage.py check_docs` — zéro NOUVELLE référence cassée, zéro « chiffre sans
   source » côté skills.
2. Relire la `description` depuis la position du DÉCLENCHEUR : la phrase que dira
   l'utilisateur la matche-t-elle ? Un skill que rien ne déclenche n'existe pas.
3. **Jamais d'auto-commit** : le skill naît en working tree, l'humain valide
   (`git add .claude/skills/<nom>` + commit par chemins explicites).

## 6. Hors périmètre — ne pas improviser ici

Les phases suivantes ont un autre écrivain et d'autres préalables :
- **skills compilés depuis le déclaratif** (manifestes, `function_catalog`, monde Data) :
  là, générer dès l'ouverture de la 1ʳᵉ requête est légitime — la matière précède la
  requête. Chantier lié à la couche manifestes, pas à ce skill.
- **skills runtime WAMA** (`wama/common/prompt_skills/`) : l'écrivain sera un rôle LLM —
  donc une passe LLM automatique → **GOUVERNÉE obligatoirement** (leçon prospection +
  crashs d'août : c'est ce type de passe qui tombait l'hôte), et préalable `RunOutcome`
  (`ROADMAP.md` §16.7). Rien de tout cela ne se lance depuis ici.

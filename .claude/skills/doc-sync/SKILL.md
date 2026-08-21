---
name: doc-sync
description: Synchroniser les .md de référence WAMA (PROJECT_STATUS, WAMA_APP_GENERATION_ROUTE, conventions, manifestes…) avec l'état réel du code et des commits — liens cassés, chemins périmés, statuts contredits. Utiliser après un refactoring, en fin de gros chantier, ou quand l'utilisateur demande de « mettre à jour les docs ».
---

# /doc-sync — Audit et mise à jour des docs de référence

Objectif : que les docs de référence (un domaine = un fichier, cf. CLAUDE.md) reflètent le réel. On corrige les références et l'état ; on ne réécrit PAS les docs.

## 1. Vérité terrain d'abord
- `git log --since=<date dernière MAJ du doc> --name-status --format='=== %h %ad %s' --date=short -- . ':(exclude)venv_win' ':(exclude)venv_linux'` → dumper dans le scratchpad (fichier consultable par les agents).
- Lister les `.md` racine (`ls *.md`) et `docs/archive/` : tout lien racine vers un fichier archivé est cassé.

## 2. Fan-out d'agents (docs volumineux)
Lancer des agents Explore en parallèle (1 par groupe de docs) avec pour chacun :
- lire le(s) doc(s) EN ENTIER + le dump de commits ;
- vérifier CHAQUE lien .md (existence au chemin cité), CHAQUE chemin de code/symbole (Glob/Grep) ;
- confronter les affirmations d'état aux commits récents, preuve obligatoire ;
- sortie normalisée : LIGNE / ACTUEL / PROBLÈME / PREUVE / CORRECTION PROPOSÉE, classée [CASSÉ]/[PÉRIMÉ]/[MINEUR], INCERTAIN si pas de preuve.

Groupes habituels : ① PROJECT_STATUS.md ② WAMA_APP_GENERATION_ROUTE.md + WAMA_APP_CONVENTIONS.md ③ WAMA_MANIFEST_SPEC/ARCHITECTURE + WAMA_DATA_FUNCTION_CARDS + WAMA_IA_TRANSVERSE ④ ROADMAP + REPRISE_* + CLAUDE.md.

## 3. Contre-vérification (obligatoire avant édition)
- Les agents hallucinent parfois, surtout les affirmations d'ABSENCE : re-vérifier soi-même (Grep/test -f) chaque finding [CASSÉ] et [PÉRIMÉ] AVANT de l'appliquer. Ignorer les INCERTAIN non confirmés.

## 4. Application
- **Blocs GÉNÉRÉS = hors périmètre manuel** : la table de `WAMA_MECANISMES.md` et les blocs
  `WAMA:FAITS` se régénèrent par `python manage.py doc_facts` (source = registres, ex.
  `wama/common/mecanismes.py`) — ne JAMAIS les éditer à la main ; un écart s'y corrige à la
  source puis se régénère (`doc_facts --check` pour vérifier).
- Éditions MINIMALES (référence, date, statut ✅/🔄/⏳) ; jamais de réécriture de section saine.
- Mettre à jour la date d'en-tête « Mise à jour : » des docs touchés.
- Respecter « un domaine = un fichier » : ne pas créer de doc « bis » ; si un contenu est au mauvais endroit, le fusionner vers le fichier de référence du domaine.

## 5. Commit
- Commit local par chemins explicites (uniquement les .md touchés), message `docs: synchronise <fichiers> avec l'état réel (<date>)`. Push = demander.

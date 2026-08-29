---
name: renommage-api
description: Renommer une API française (ou tout renommage d'identifiants multi-fichiers) sans rien rendre FAUX — inventaire mesuré, moteur tokenisé, grep des jumeaux par chaîne, revérification jusqu'à HEAD. Utiliser quand on solde une couche de la dette de nommage (CLAUDE.md §nommage), ou pour tout renommage traversant plusieurs consommateurs. CANDIDAT (n=1, session 2026-08-29 : registries.py + ~45 noms model_manager, zéro casse).
---

# /renommage-api — renommer sans rendre FAUX

> ⚠⚠ **Un renommage ne casse rien, il rend FAUX** : un appel raté ne se signale pas
> toujours. Chaque étape ci-dessous existe parce qu'un trou précis a été rencontré le
> 2026-08-29 (session « DETTE DE NOMMAGE », bilan = `PROJECT_STATUS §PENDING 2026-08-29`).

## 1. Inventaire MESURÉ (jamais de liste de tête)
- Extraire les `def`/`class` du périmètre +, pour CHAQUE nom, le relevé repo-wide des
  consommateurs (`grep -rnw`, py+html+js+json, staticfiles INCLUS, venvs/logs exclus).
- ⚠ Un grep par radicaux attrape des FAUX POSITIFS anglais (`get_memory_cleaner` via
  « cle », `_discover_composer_models` via « poser ») — trier à l'œil avant de mapper.
- ⚠ Pour les mots NUS (`lancer`, `etat`, `cle`), le compte mélange appels et PROSE
  française — il oriente, il ne conclut pas.

## 2. Moteur TOKENISÉ, jamais un sed aveugle
- Un script par LOT : mapping {ancien: nouveau}, remplacement à frontières de mot
  (`\b`), liste de fichiers EXPLICITE (le scoping par fichier protège des homonymes
  d'autres modules — `_referentiel` existait aussi dans wama_data).
- **Sûrs en aveugle** : noms composés (`poser_identite`) et préfixés `_` — la prose
  française ne les contient jamais. **Les accents protègent** (« clé » ≠ `cle`,
  « rafraîchisseur » ≠ `rafraichir`).
- **JAMAIS en aveugle** : verbes/mots nus (`rechercher`, `lancer`) → éditions ciblées
  site par site, et les chaînes AFFICHÉES (le mot « Registre » dans un `source="…"`
  français a été renommé « Registry » — vu à l'ÉCRAN par le smoke, par aucun test).

## 3. Les jumeaux qu'aucun test ne voit — grep OBLIGATOIRE après application
- **Le DOMICILE lui-même** : renommer les consommateurs et oublier la définition —
  `py_compile` passe sur un import cassé ; seul le grep du nom l'a vu (`_cle_de_rang`).
- **Les jumeaux PAR CHAÎNE** : routes Celery (`CELERY_TASK_ROUTES` de settings.py),
  noms de tâches (`name='common.…'`), gabarits (`{% tag %}`), JS lisant des clés de
  payload, copies `staticfiles/`.
- **Frontière des données** : ce qui est STOCKÉ/déclaré reste (clés `extra_info`,
  vocabulaire de valeurs), ce qui est CALCULÉ se renomme (payloads éphémères).
  Drapeaux CLI = surface opérateur → français toléré (arbitrage 29/08).

## 4. RELIRE le diff intégral avant de committer
- 1 prose abîmée et 1 FAUX POSITIF de fichier entier (`tests_skills_catalog` — clés de
  DONNÉES homonymes d'identifiants) n'ont été vus qu'à la relecture. Restaurer par
  `git checkout <fichier>` puis ne rejouer que le légitime.

## 5. Revérifier jusqu'à HEAD, pas jusqu'au disque
1. tests ciblés du périmètre → 2. suite COMPLÈTE (exit 0 fait foi) → 3. `manage.py
   check` + `check_templates` → 4. **tests SUR HEAD en worktree** (rituel
   `reference_verif_sur_head_worktree` : .env + migrations à recopier) → 5. smoke
   NAVIGATEUR après restart du parc (⚠ gunicorn sert l'ancien code ; ⚠ sonde WSL :
   `no_proxy=localhost` sinon le proxy UGE avale localhost) → 6. re-consignation
   (CLAUDE.md, §PENDING, mémoire) avec les RESTES ASSUMÉS nommés.

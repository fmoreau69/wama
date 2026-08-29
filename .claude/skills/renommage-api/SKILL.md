---
name: renommage-api
description: Renommer une API française (ou tout renommage d'identifiants multi-fichiers) sans rien rendre FAUX — inventaire mesuré, moteur tokenisé, grep des jumeaux par chaîne, revérification jusqu'à HEAD. Utiliser quand on solde une couche de la dette de nommage (CLAUDE.md §nommage), ou pour tout renommage traversant plusieurs consommateurs. PROMU (n=2 : 2026-08-29 registries.py + ~45 noms model_manager ; 2026-08-30 les 2 briques JS communes, 119 identifiants + 1 nom de fichier — zéro casse les deux fois).
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

## 4bis. Si le périmètre est du JS — trois choses changent (ajouté n=2, 2026-08-30)

> Le reste du skill tient tel quel. Ce qui change est l'ATTESTATION : un `.py` mal renommé
> casse à l'import, un `.js` mal renommé **casse dans le navigateur, en silence**.

- **Aucun vérificateur de syntaxe JS n'est installé ici** (ni `node` sous Windows, ni sous
  WSL) → la seule preuve qu'un fichier renommé est encore VALIDE est un smoke qui récupère
  le fichier **SERVI** et le parse (`new Function(texte)`), puis vérifie que le nouveau
  global existe, que l'ancien a disparu, et que l'ancien chemin sort en **404**.
- **`staticfiles/` se resynchronise dans le MÊME geste**, suppression de l'ancien nom
  comprise — c'est ce dossier qui est servi. Contrôle : les deux copies doivent partager le
  même blob (`git hash-object`).
- **Un nom de FICHIER `.js` est une surface** (il se lit dans un `<script src>`) : le
  renommer oblige à grepper le CHEMIN, pas seulement les identifiants — gabarits,
  `mecanismes.py` (annexes), docs de référence, et les tests qui cherchent des **chaînes**
  dans le fichier (ici `tests_codegen_templates.py`, seul garde-fou automatique du lot — et
  il ne couvrait que 5 des 99 noms).
- **La frontière des DONNÉES vaut aussi pour le DOM** : attributs `data-*` et clés de
  payload NE se renomment PAS avec les identifiants. S'ils forment un vocabulaire partagé
  (`data-abo-*` et `data-f-<facette>`), c'est **ensemble ou pas du tout** — un
  demi-vocabulaire est pire que l'ancien. L'écrire comme RESTE ASSUMÉ dans le fichier.
- **Les gabarits Django sont relus à chaque requête** ici (`APP_DIRS`, pas de cached
  loader) : renommer un `<script src>` prend effet sans redémarrer gunicorn — donc pas de
  fenêtre de casse pour les autres instances. À revérifier si un cached loader apparaît.

## 5. Revérifier jusqu'à HEAD, pas jusqu'au disque
1. tests ciblés du périmètre → 2. suite COMPLÈTE (exit 0 fait foi) → 3. `manage.py
   check` + `check_templates` → 4. **tests SUR HEAD en worktree** (rituel
   `reference_verif_sur_head_worktree` : .env + migrations à recopier) → 5. smoke
   NAVIGATEUR après restart du parc (⚠ gunicorn sert l'ancien code ; ⚠ sonde WSL :
   `no_proxy=localhost` sinon le proxy UGE avale localhost) → 6. re-consignation
   (CLAUDE.md, §PENDING, mémoire) avec les RESTES ASSUMÉS nommés.

---
name: manifeste
description: Travailler sur la couche manifestes WAMA (7 kinds — app, library, model, function, pipeline, project, dataset) — extraire, composer via `requires`, contrôler, ingérer. Utiliser dès qu'une demande touche `wama/common/manifests/**` ou le corpus `manifests/**`, quand on relie une app à ses modèles/librairies, quand on parle d'auto-génération d'app, de projection vers les registres, ou d'un rôle LLM producteur de manifestes (librarian…).
---

# /manifeste — Couche manifestes : extraire, composer, contrôler, projeter

Le manifeste est **le formalisme** de WAMA : il décrit ce qu'une chose EST, de façon portable et
déclarative. Il ne décrit JAMAIS l'état runtime de cette installation.

> **Docs de référence — un domaine, un fichier (ne pas en créer un « bis »)**
> `WAMA_MANIFEST_SPEC.md` (formalisme, §7 composition) · `WAMA_MANIFEST_ARCHITECTURE.md`
> (flux/schéma, §5 auto-génération, §7 projection) · `ROADMAP.md` §16.7 (décision Hermes) ·
> `wama/model_manager/PROSPECTION_PIPELINE.md` (chaîne prospect→install→app).

## 1. Où est quoi

| Quoi | Où |
|---|---|
| Registre des kinds, dataclass `ManifestKind` | `wama/common/manifests/kinds.py` (`MANIFEST_KINDS`) |
| Un fichier par kind (`validate`/`extract`/`project`) | `wama/common/manifests/builtin/<kind>.py` |
| Enveloppe + `requires` + résolution | `wama/common/manifests/envelope.py` |
| Ingest (machine à états, idempotent/réversible) | `wama/common/manifests/ingest.py` |
| Projection vers les registres | `wama/common/manifests/projection.py` |
| Corpus d'exemples (à la RACINE, pas dans wama/) | `manifests/apps/*.json`, `manifests/libraries/*.json`, `manifests/models/*.json` |
| Gabarits code-gen (urls/tasks/apps/models, marche A) | `wama/common/manifests/codegen/` (`*_gen.py`, rendus marqués `[manifest-gen]`) |
| Le JUGE profond (strip → régénère → 3 axes) | `manage.py app_regen_check <app>` — worktree UNIQUEMENT |
| Rôle LLM « projet → manifeste library » | `wama-dev-ai/run_librarian.py` + `prompts/librarian.txt` |
| Rôle LLM « glu de tâche » (marche B) | `wama-dev-ai/run_codegen.py` + `prompts/codegen.txt` — sortie `PENDING_HUMAN_VALIDATION`, n'écrit jamais dans `wama/` |

## 2. Mesurer avant d'affirmer

Ne JAMAIS recopier un tableau d'état depuis un `.md` : ils dérivent. Mesurer :

```bash
# quels kinds ont réellement extract / project ? (source = les hooks passés à register_kind)
PYTHONPATH=. python -c "import django,os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','wama.settings');django.setup();import wama.common.manifests.builtin;from wama.common.manifests.kinds import MANIFEST_KINDS as M;[print(n, bool(k.extract), bool(k.project)) for n,k in sorted(M.items())]"
```

```powershell
# quels liens app -> model / library existent dans le corpus ?
Get-ChildItem .\manifests\apps\*.json | ForEach-Object { $j = Get-Content $_ -Raw | ConvertFrom-Json;
  "{0,-14} {1}" -f $_.BaseName, (($j.requires | Group-Object kind | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ' ') }
```

Photo au 2026-08-12 soir, MARCHE A CLOSE (à re-mesurer, pas à croire) : **4 kinds écrivent**
(`app`, `library`, `model`, `function`) ; le kind `app` projette **10 facettes**
(`PROJECTED_FACETS` — access DB + identity/ports/capabilities/studio/modes/prompts/params/
inspector/**tool_api** (A4 : entrée-valeur `TRIAD_SPECS`, triades construites à l'import))
**+ `processing` PARTIEL ASSUMÉ** (urls.py régénérable ; tasks.py mince et models.py A5 en
CREATE-ONLY — un models.py existant porte des MIGRATIONS, jamais touché) via les **gabarits
`wama/common/manifests/codegen/`** (urls_gen/tasks_gen/apps_gen/models_gen — fichiers marqués
`[manifest-gen]`, jamais de rendu partiel, un fichier main n'est jamais réécrit). Reste
code-gen : `models` (model_config) ; corps de backends et champs de résultat = **marche B**
(rôle codegen wama-dev-ai + banc de modèles — GPU : avec Fabien seulement). `dataset` n'a
pas d'`extract` : pour lui le manifeste EST l'origine.
Composition mesurée : **91 liens `app → model`** + jambes `app → library` SEMÉES (corpus
**110 manifestes** — 10 apps + 9 libraries + 91 models dérivés des requires ; transcriber =
4 modèles + 9 libraries, 13/13 résolus) ; strates actées (SPEC §7.4-5) : socle plateforme
(`library_index.SOCLE_PLATEFORME`, jamais cité) / libraries métier / outils système (trou #15).

## 3. Contrôles à relancer après toute modification

```bash
python manage.py manifest_export --check          # corpus à jour ? ⚠ depuis WSL2 (libraries
                                                  # venv-dépendantes : venv_win = faux périmés)
python manage.py manifest_roundtrip --all         # extract -> ingest -> extract est-il fidèle ?
python manage.py doc_facts --check                # les blocs WAMA:FAITS des .md sont-ils à jour ?
python manage.py check_docs                       # liens/chemins des docs (2 CASSÉ connus au 10/08)
python manage.py app_regen_check <app>            # le JUGE profond (strip→apply→3 axes) —
                                                  # WORKTREE UNIQUEMENT (refuse dev/main),
                                                  # après tout palier de write-back/gabarit
```

Un round-trip qui diverge sur un champ **déclaratif** est un bug ; sur un champ **runtime**
(`is_loaded`, `local_path`, timestamps) c'est normal — ces champs sont volontairement exclus.

## 4. Garde-fous (non devinables — c'est pour eux que ce skill existe)

- **Frontière de responsabilité (§7.1)** : `library` possède dépôt, licence, version, install,
  points d'entrée, contraintes techniques. **JAMAIS** l'usage qu'une app en fait — ça, c'est le
  `requires` de l'app. Ne pas remonter d'usage applicatif dans un manifeste de librairie.
- **`library` ≠ `model`.** `faster-whisper` (paquet PyPI) est une `library` ; `Systran/faster-whisper-large-v3`
  (poids HF) est un `model`. `install.pip` n'a de sens que pour une `library` : un modèle se
  télécharge (ollama pull / HF snapshot / release Ultralytics), il ne s'installe pas par pip.
- **Semis EXPLICITE au corpus** : `manifest_export --kind library <clé>`. Aucun critère automatique
  ne décide qu'une lib mérite d'entrer — c'est une décision humaine.
- **Null plutôt que plausible** : ce qui n'est pas extractible reste ABSENT. Ne jamais inventer une
  contrainte GPU, une licence ou une version pour « compléter » un manifeste.
- **Un rôle LLM n'ingère JAMAIS.** Il écrit dans `wama-dev-ai/outputs/` avec
  `status: PENDING_HUMAN_VALIDATION`, ses erreurs de validation et ses `divergences_vs_mecanique`.
  Le LLM propose, la chaîne mécanique juge, l'humain valide. Patron de référence : `run_librarian.py`.
- **Le manifeste DÉCRIT, l'endpoint EXÉCUTE.** Un kind sans `project` ne peut rien écrire en base ;
  l'installation passe par `install_from_spec()` (`model_installer.py`), pas par la couche manifeste.
- **Un modèle se DÉCOUVRE, il ne se déclare pas** (ajouté 2026-08-05, avec `project_model`). C'est la
  frontière propre au kind `model`, à ne surtout pas calquer sur `library` :
  - `project_model` ne **crée jamais** de ligne — un `AIModel` né d'un manifeste serait un modèle
    fantôme, sans poids sur le disque, que la sélection pourrait pourtant retenir. Cible absente →
    on le dit, on ne fait rien (« lancer `sync_models` d'abord »).
  - Le manifeste n'a autorité que sur les champs **déclaratifs** : `license`, `platform_ref`. Rien
    d'autre. `is_downloaded`, `is_loaded`, `local_path`, `vram_gb`, `capabilities` appartiennent à
    la découverte.
  - ⚠ **La découverte réécrit `capabilities` EN ENTIER à chaque `sync_models`.** Toute valeur posée
    en dehors d'elle est effacée au passage suivant. Vécu deux fois le 2026-08-05 : `audio_enhance`
    corrigé en base puis réécrit par le beat une heure plus tard, et 11 `abilities` renseignées par
    une commande de rattrapage puis ramenées à 0 par un sync. **Corriger dans `model_registry`,
    jamais seulement en base.**
- **Un contrôle vert juste après un correctif de catalogue ne prouve rien** : le beat
  `model-manager-reconcile` tourne toutes les 2 h avec le code chargé en mémoire. Redémarrer les
  workers, puis re-mesurer. Vérifier l'âge des process : `ps -eo pid,etimes,cmd | grep celery`.
- **`platform_ref` porte le FAIT, pas l'URL** (`huggingface:org/repo`, `ollama:gemma4`,
  `roboflow:projet/3`). L'URL se dérive dans `AIModel.platform_url`, table plateforme → gabarit à un
  seul endroit — ajouter une plateforme s'y fait en une ligne. Ne pas stocker d'URL.
- **La taxonomie a son propre contrôle** : `python manage.py check_model_taxonomy` (types, sources,
  tâches, et projection vers huggingface/ultralytics/roboflow/ollama). Sort en 1 sur une valeur non
  déclarée. Si un nouveau modèle apporte une tâche inconnue, **la déclarer dans `ModelTask`** — ne
  jamais contourner le garde-fou. Les quatre référentiels ne décrivent pas la même chose (HF : une
  tâche ; Ollama : un ensemble de capacités ; Roboflow : plus fin sur la segmentation), donc on
  **projette** vers eux, on ne s'y **réduit** pas — plusieurs de nos tâches sont volontairement plus
  fines (`text-to-music` ≠ `text-to-audio` : composition vs ambiance/bruitage).
- **Verrous d'installation (ROADMAP §16.7, transposés d'Hermes)** : allowlist en dur dans l'arbre
  (la config utilisateur ne l'élargit pas), PyPI par nom seul (pas de `git+https`/`--index-url`/`file:`),
  pin PEP 440, kill switch. WAMA transpose les **verrous**, pas le **cycle de vie** : on installe à
  l'ingestion du manifeste (une fois, validée), pas à la première utilisation — motif :
  reproductibilité scientifique.

## 5. Écrire un nouveau kind

1. `builtin/<kind>.py` : `validate_<kind>_body()` + `extract_<kind>()` (+ `project_` seulement si un
   registre existe pour l'accueillir) puis `register_kind(ManifestKind(...))`.
2. L'importer dans `builtin/__init__.py` (sinon il n'est jamais enregistré).
3. Semer 1-2 exemples au corpus et lancer `manifest_roundtrip --all`.
4. Mettre à jour `WAMA_MANIFEST_SPEC.md` (formalisme) **et** `WAMA_MANIFEST_ARCHITECTURE.md`
   (tableau des kinds) — les deux dérivent vite.

## 6. Coordination

`wama/common/manifests/**` est un chemin **partagé entre instances Claude** : vérifier le handoff
(`PROJECT_STATUS.md` §REPRISE) avant d'y toucher, et commiter par chemins explicites.
Clôture du chantier : skill `/palier`.

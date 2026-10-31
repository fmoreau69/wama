# AI-models — le dossier des poids de WAMA

> Réécrit le 2026-10-31 (audit doc ↔ code). L'ancienne version prescrivait des modèles
> « téléchargés au premier usage », listait des dossiers disparus (`vision-language/`, `wan/`,
> `registry.json`, `external/`) et contredisait la règle d'installation d'`AGENTS.md`. Ce
> fichier ne recopie plus aucune règle : il dit **où** vivent les poids et **renvoie** aux
> sources qui font foi.

## Ce que contient ce dossier

```
AI-models/
├── README.md                  # ce fichier
├── .gitignore                 # exclut les poids de Git
├── models/                    # les poids, un dossier par catégorie (voir models/README.md)
├── cache/huggingface/         # cache HF PARTAGÉ : les sous-dépendances (t5, tokenizers, backbones…)
├── manager.py                 # ⚠ code DORMANT, importé nulle part (WAMAModelManager)
├── weekly_model_discovery.py  # ⚠ stub jamais exécutable (cf. PROSPECTION_PIPELINE.md)
└── sources/ollama.py          # connecteur lu seulement par manager.py
```

Le nom du dossier est en tiret parce qu'il n'est jamais importé (`AGENTS.md`, « Nommage des
dossiers »). La racine est déclarée une fois : `AI_MODELS_DIR` dans `wama/settings.py`.

## Ce qui fait foi (ne pas le recopier ici)

| question | source |
|---|---|
| quels dossiers, pour quelles familles ? | `wama/settings.py::MODEL_PATHS` (catégories = `ModelType`, `wama/model_manager/models.py`) |
| quels modèles existent, installés ou non, leur taille ? | le catalogue `AIModel` — page **Model Manager** (`/model-manager/`) |
| comment un modèle s'installe | `AGENTS.md`, « Librairies et modèles s'installent par la route — aucune dérive » |
| comment un backend range un modèle (`cache_dir=`, leviers A–D) | `AGENTS.md`, « Ajout d'un nouveau modèle AI » ; `wama/common/utils/hf_weights.py` |
| le registre de prospection et de veille | `wama/model_manager/PROSPECTION_PIPELINE.md` |

## Installer un modèle — en bref

Par la route, jamais à la main ni « au premier usage » :

- bouton **Installer** du Model Manager, ou `python manage.py pull_model <clé>` (même demande) ;
- `python manage.py install_requires <app> --apply` pour tout ce qu'une app déclare ;
- une tâche qui a besoin d'un modèle absent déclenche cette même route et attend
  (`wama/common/utils/model_readiness.py::ensure_installed`).

Moteur commun : `wama/model_manager/services/model_installer.py::install_from_spec` (pilotes
`hf` / `github` / `files` / `yolo` / `ollama`). Un fichier hors du Hub se DÉCLARE sur sa ligne de
catalogue (`{path, size, sha256, origin}`), il ne se télécharge pas dans un backend.

## Contrôles

- `python manage.py check_model_layout` — aucun snapshot étranger dans un dossier de famille ;
- `wama/common/tests/tests_install_route.py` — aucun téléchargement de poids ni `pip` hors de la route ;
- `wama/common/tests/tests_hf_cache_routing.py` — aucune mutation de `HF_HUB_CACHE` / `HF_HOME`.

## Git

Les poids sont exclus de Git (`AI-models/.gitignore`) : le dépôt reste léger, les poids se
reconstruisent par la route d'installation.

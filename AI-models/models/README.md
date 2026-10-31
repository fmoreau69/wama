# AI-models/models — l'arborescence des poids, par catégorie

> Réécrit le 2026-10-31 (audit doc ↔ code). L'ancienne version recopiait un `MODEL_PATHS`
> d'avant septembre (`vision-language/`, `diffusion/wan/`, Hunyuan Video, le Whisper du
> describer), des tables de modèles par app et un guide d'installation « au premier usage »
> avec des `os.environ` dans le code et un script absent (`download_onnx_models.py`) — tout cela
> contraire à `AGENTS.md`. Rien n'est plus recopié ici : les sources qui font foi sont nommées.

## Le principe : `models/<catégorie>/<famille>/`

- **La catégorie** est une valeur de `ModelType` (`wama/model_manager/models.py:16-34`) : `vision`,
  `diffusion`, `speech`, `vlm`, `llm`, `embedding`, `upscaling`, `lipsync`, `music`, `ocr`, `nlp`.
- **La famille** est soit DÉCLARÉE dans `wama/settings.py::MODEL_PATHS` (un chemin par famille que
  WAMA connaît par son nom — ex. `MODEL_PATHS['speech']['whisper']`), soit posée par l'installeur
  sous la racine de sa catégorie (balayage générique du catalogue). Déclarer une famille la sort
  du balayage générique : c'est un choix, pas un oubli.
- Les **sous-dépendances** partagées (t5, tokenizers, backbones timm…) ne vont pas ici mais au
  cache partagé `AI-models/cache/huggingface/`.
- Alias historiques : `MODEL_PATHS['vision_language']` → `vlm`, `MODEL_PATHS['reader']` → `ocr`
  (`wama/settings.py:216-217`).

## Où lire la vérité

| question | source |
|---|---|
| les dossiers déclarés | `wama/settings.py::MODEL_PATHS` (créés au démarrage) |
| les modèles de chaque app | `wama/<app>/utils/model_config.py` + le catalogue `AIModel` (page Model Manager) |
| taille, VRAM, état installé | le catalogue (`disk_gb`, `vram_gb`, statut) — jamais une table recopiée |
| ajouter un modèle | `AGENTS.md`, « Ajout d'un nouveau modèle AI » (checklist `settings.py` → `model_config.py` → `cache_dir=` → registre) |
| installer un modèle | `AGENTS.md`, « Librairies et modèles s'installent par la route » ; résumé dans `AI-models/README.md` |
| une librairie qui pose ses poids hors de HF | sa variable d'aiguillage posée UNE FOIS dans `wama/settings.py` (ex. `DEEPFACE_HOME`) |

## Contrôle

`python manage.py check_model_layout` signale tout snapshot ÉTRANGER rangé dans un dossier de
famille (le défaut que produisait une mutation de `HF_HUB_CACHE` dans un backend).

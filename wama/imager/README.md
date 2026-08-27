# WAMA Imager — génération d'images ET de vidéos

Application de génération visuelle de WAMA (monde Médias) : images et vidéos à partir de prompts,
avec fichiers de référence, mots-clés imposés, enrichissement de prompt ✨ et médiathèque.

> ⚠ Réécrit le 2026-08-27 — l'ancien README décrivait l'ère imaginAIry (2025) : « Imager utilise
> imaginAIry », modèles OpenJourney/Dreamlike/SD 1.5-2.1, cache `~/.cache/imaginairy/`. Tout cela
> est périmé : imaginAIry n'est plus qu'un backend parmi d'autres, ces modèles ont été retirés, et
> les poids vivent sous `AI-models/` (`MODEL_PATHS` de `settings.py`).

## Architecture réelle : des backends interchangeables

La génération passe par `wama/imager/backends/` — **une dizaine de moteurs** derrière un manager
commun (`backends/manager.py`), **`diffusers` étant le défaut** :

| Backend | Domaine |
|---|---|
| `diffusers_backend` | images (SDXL, Qwen-Image, Hunyuan…) — **défaut** |
| `qwen_image_backend`, `flux2_klein_backend` | images spécialisées (édition, logos) |
| `wan_video_backend`, `ltx_video_backend`, `cogvideox_backend`, `mochi_backend`, `hunyuan_video_backend` | **vidéo** (t2v, i2v) |
| `imaginairy_backend` | historique, conservé comme moteur optionnel |

**Sources vivantes — ne pas recopier de listes de modèles ici** (elles dérivent, c'est ce qui a
tué l'ancien README) :

- `wama/imager/utils/model_config.py` — les modèles déclarés, VRAM, répertoires ;
- le catalogue `AIModel` (model_manager) — l'état installé/actif réel ;
- la table de `CLAUDE.md §Modèles imager actifs` — indicative, marquée comme telle.

## Sélection automatique de modèle

`utils/auto_model.py::resolve_auto_model` délègue à la brique centrale
`model_manager/services/model_selector.py::select_model_id()` (VRAM-aware), appelée **au
lancement** de la tâche (`tasks.py`) — l'utilisateur peut laisser « auto ».

## Fonctionnalités

- domaines **image** et **vidéo** (déclarés dans `wama/common/utils/app_modes.py`) ;
- fichiers de **référence** (img2img / i2v), **mots-clés imposés** (chips), enrichissement de
  prompt ✨ via la pipeline commune (`PROMPT_TARGETS`) ;
- file d'attente commune WAMA : batch, progression + ETA apprise, inspecteur, sortie
  **multi-images** (grille de vignettes, mécanisme préview n°30) ;
- médiathèque : références et sorties partageables.

## Utilisation

1. `/imager/` → prompt (+ négatif), domaine image/vidéo, modèle (ou auto), paramètres ;
2. la card entre en file ; démarrage individuel ou « Démarrer tout » ;
3. téléchargement/duplication/suppression par les boutons canoniques de card.

Celery requis (`celery -A wama worker`). Endpoints principaux : `create/`, `start/<id>/`,
`progress/<id>/`, `download/<id>/`, `delete/<id>/` — la liste complète vit dans
`wama/imager/urls.py`.

## Licences

Chaque modèle porte sa licence dans le catalogue (`AIModel.license`) ; la vue mesurée est
`/common/licences/`, la politique dans `LICENSING.md`. Ne pas supposer « commercial OK » par
défaut (plusieurs modèles vidéo sont NC ou communautaires).

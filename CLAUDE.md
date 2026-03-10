# CLAUDE.md — Instructions pour Claude Code (WAMA)

## ⚠️ RÈGLE OBLIGATOIRE : AJOUT D'UN NOUVEAU MODÈLE AI

**Cette règle s'applique à TOUS les modèles téléchargés via HuggingFace Hub,
transformers, diffusers, ou tout autre système de modèles.**

### Checklist obligatoire (dans cet ordre) :

#### 1. `wama/settings.py` — Ajouter le path dédié
```python
MODEL_PATHS = {
    'diffusion': {
        ...
        'mon_modele': AI_MODELS_DIR / "models" / "diffusion" / "mon-modele",
    },
    # ou 'speech', 'vision', etc. selon le domaine
}
```

#### 2. `wama/<app>/utils/model_config.py` — Déclarer la constante DIR
```python
MON_MODELE_DIR = MODEL_PATHS.get('<domaine>', {}).get('mon_modele',
    settings.AI_MODELS_DIR / "models" / "<domaine>" / "mon-modele")
Path(MON_MODELE_DIR).mkdir(parents=True, exist_ok=True)
```

#### 3. Backend `wama/<app>/backends/<nom>_backend.py` — Pattern obligatoire
```python
def load(self, ...):
    import os
    cache_dir = str(MON_MODELE_DIR)  # récupérer depuis model_config

    # ── CRITIQUE : TOUJOURS avant tout import HF ──────────────────────
    os.environ['HF_HUB_CACHE'] = cache_dir
    os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir
    # ──────────────────────────────────────────────────────────────────

    from transformers import AutoModel  # ou diffusers, etc.

    model = AutoModel.from_pretrained(
        model_id,
        cache_dir=cache_dir,   # TOUJOURS passer cache_dir
        ...
    )
```

#### 4. `wama/<app>/utils/model_config.py` — Ajouter le modèle
```python
MON_APP_MODELS = {
    'mon-modele': {
        'model_id': 'mon-modele',
        'hf_id': 'org/model-name',
        'type': 'image|video|speech|...',
        'vram_gb': X,
        'description': '...',
    }
}
```

#### 5. `wama/model_manager/services/model_registry.py` — Mettre à jour la découverte
Ajouter le nouveau modèle dans la fonction `_discover_*_models()` correspondante.

---

### ❌ Ce qui est INTERDIT :
- Laisser un modèle se télécharger dans `AI-models/cache/huggingface/` par défaut
- Importer `transformers`/`diffusers`/`huggingface_hub` AVANT de setter `HF_HUB_CACHE`
- Oublier de passer `cache_dir` à `from_pretrained()`
- Ne pas ajouter le path dans `settings.py MODEL_PATHS`
- Créer un modèle sans l'enregistrer dans `model_registry.py`

### ✅ Règle mnémotechnique :
> **"Path d'abord, env vars ensuite, import après"**
> settings.py → model_config.py → `os.environ['HF_HUB_CACHE']` → `from transformers import ...`

---

## Architecture WAMA — Points clés

- **Django** + **Celery** (Redis) pour les tâches async
- **Modèles AI** : `AI-models/` à la racine du projet, organisé par `models/<domaine>/<famille>/`
- **Cache HuggingFace global** : `AI-models/cache/huggingface/` (fallback uniquement)
- **Static files** : dupliquer `wama/<app>/static/` → `staticfiles/<app>/` pour les fichiers JS/CSS modifiés
- **Gestion centralisée** : `wama/model_manager/` + `model_registry.py` pour la découverte

## Modèles imager actifs (RTX 4090 24GB)

### Images
| Modèle | VRAM | Dir |
|--------|------|-----|
| hunyuan-image-2.1 | 16GB | `diffusion/hunyuan/` |
| qwen-image-2 | 16GB | `diffusion/qwen-image/` |
| qwen-image-edit | 12GB | `diffusion/qwen-image/` |
| stable-diffusion-xl | 10GB | `diffusion/stable-diffusion/` |

### Logos
| Modèle | VRAM | Dir | Notes |
|--------|------|-----|-------|
| flux-lora-logo-design | 16GB | `diffusion/logo/` | Shakker-Labs FLUX LoRA — guidance=3.5, steps=24, 1024×1024 |

### Vidéos
| Modèle | VRAM | Dir |
|--------|------|-----|
| mochi-1-preview | 22GB | `diffusion/mochi/` |
| ltx-video-0.9.8-distilled | 6GB | `diffusion/ltx/` |
| cogvideox-5b-i2v | 5GB | `diffusion/cogvideox/` |

### Supprimés (obsolètes/redondants)
- OpenJourney v4 (obsolète 2022)
- Realistic Vision V5 (redondant avec Hunyuan)
- CogVideoX 2B (8fps saccadé)
- HunyuanVideo 1.5 (redondant avec Mochi)
- Wan 2.2 (remplacé par CogVideoX 5B I2V)
- logo-redmond-v2 (SDXL 2023, obsolète)
- amazing-logos-v2 (SD 1.5 2023, obsolète)

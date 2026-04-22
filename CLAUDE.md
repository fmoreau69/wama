# CLAUDE.md — Instructions pour Claude Code (WAMA)

---

## 🔴 RÈGLE OBLIGATOIRE : PATCHES DE COMPATIBILITÉ VENV → `patches/apply_patches.py`

> **Toute correction manuelle dans `venv_linux/` ou `venv_win/` DOIT être ajoutée à `patches/apply_patches.py`.**

### Principe

Les fichiers dans `venv_linux/site-packages/` sont écrasés à chaque `pip install --upgrade`.
Un patch appliqué directement sans être enregistré dans `apply_patches.py` sera **perdu silencieusement**.

### Règle concrète

1. Tu identifies une incompatibilité dans une lib tierce (ex : import cassé, API supprimée).
2. Tu détermines le correctif (search → replace minimal).
3. Tu l'appliques via `apply_patch()` dans `patches/apply_patches.py` — **pas manuellement dans le venv**.
4. Tu lances `python patches/apply_patches.py` pour vérifier que le patch s'applique proprement.

### Format obligatoire dans `apply_patches.py`

```python
apply_patch(
    site / "package/module.py",
    search="texte original exact",
    replace="texte corrigé",
    description="N. package: description du problème et de la correction",
)
```

### Ce qui est déjà patché (ne pas recréer)

| # | Fichier | Problème |
|---|---------|----------|
| 1 | `boson_multimodal/.../modeling_higgs_audio.py` | transformers 4.57+ (7 patches) |
| 2 | `df/io.py` | torchaudio 2.x — `AudioMetaData` supprimé |
| 3 | `tts_service.py` | In-repo (vérification seulement) |
| 4 | `start_wama_prod.sh` | In-repo (vérification seulement) |
| 5 | `xformers/ops/seqpar.py` | torch 2.9.x — `GroupName` supprimé |

---

## 🔴 RÈGLE FONDAMENTALE : CENTRALISATION DANS `common/` — ZÉRO DUPLICATION

> **Cette règle prime sur toutes les autres décisions d'architecture.**

### Principe

Tout code utilisé par **plus d'une application** DOIT aller dans `wama/common/`.
Il est **interdit** de copier-coller du code d'une app vers une autre.
Si deux apps ont besoin de la même logique, elle va dans `common/` et les deux apps l'importent.

### S'applique à

| Couche | Exemples à centraliser dans `common/` |
|--------|---------------------------------------|
| **Python — utilitaires** | sélection backend VRAM-aware, singleton keep_loaded, safe_delete, duplication |
| **Python — tasks** | pattern batch (start, status, cancel), polling helpers |
| **Templates HTML** | modals paramètres (item + batch), cartes de file d'attente, barres de progression |
| **JavaScript** | csrfFetch, urlFor, polling loop, bindBatchActions, initSettingsModal |
| **CSS** | classes de composants partagés (cards, badges, progress bars) |

### Règles concrètes

1. **Avant d'écrire du code dans `wama/<app>/`** — chercher si la logique existe déjà dans `common/`.
   Si oui : importer. Si non et si réutilisable : créer dans `common/`.

2. **Jamais copier-coller entre apps** — si tu te retrouves à reproduire du code existant,
   c'est le signal qu'il faut d'abord extraire vers `common/`.

3. **Les modals "Paramètres item" et "Paramètres batch" sont structurellement identiques**
   entre toutes les apps génériques. Ils doivent à terme partager un composant commun.
   En attendant le refactoring : ne pas créer de nouveau modal sans vérifier `common/`.

4. **Le pattern singleton + keep_loaded + sélection VRAM-aware** doit venir de
   `wama/common/utils/backend_selector.py` — ne pas le ré-implémenter par app.

5. **Le JS de base** (polling, csrfFetch, urlFor, actions batch) doit venir de
   `wama/common/static/common/js/wama-app-base.js` une fois créé.
   En attendant : ne pas dupliquer, signaler le besoin dans `project_refactoring_common.md`.

### Ce qui existe déjà dans `common/` (à utiliser, ne pas recréer)

- `queue_duplication.py` : `duplicate_instance()`, `safe_delete_file()`
- `batch_parsers.py` : parsing fichiers batch (txt/csv/pdf/docx)
- `batch_import.js` : UI import batch avec détection automatique
- `wama-queue.js` : batch collapse + persistance localStorage
- `console_utils.py` : logs Redis structurés
- `media_paths.py` : helpers `upload_to_user_input/output`

### Roadmap refactoring (à faire, dans l'ordre)

Voir `memory/project_refactoring_common.md` pour le détail.
1. `common/utils/backend_selector.py` — sélection VRAM + règle singleton
2. `common/static/common/js/wama-app-base.js` — JS de base inter-apps
3. `common/templates/common/_settings_modal.html` — modal paramètres générique

---

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

## ⚠️ CONVENTIONS UI & ARCHITECTURE — TOUTES LES APPLICATIONS

> **Document de référence complet : [`WAMA_APP_CONVENTIONS.md`](WAMA_APP_CONVENTIONS.md)**
> Ce fichier contient les conventions détaillées, les patterns de code, la checklist
> de création d'app, et la table de conformité par application.
> **Le lire avant de créer ou modifier une application.**

### Résumé des règles critiques

**Boutons d'action — ordre obligatoire :**
`[⚙ Paramètres]  [▶ Start/Restart]  [⬇ Télécharger]  [⧉ Dupliquer]  [🗑 Supprimer]`

**Composants obligatoires de chaque file d'attente :**

| Composant | Implémentation |
|-----------|---------------|
| Bouton Paramètres (pos.1) | Modale avec tous les paramètres de l'item |
| Bouton Dupliquer (pos.4) | `duplicate_instance()` de `wama/common/utils/queue_duplication.py` |
| Bouton Supprimer (pos.5) | vue `delete()` + `safe_delete_file()` pour fichiers partagés |
| Bouton Démarrer individuel | sauf si traitement automatique au dépôt |
| Bouton "Démarrer tout" | vue `start_all()` |
| Bouton "Tout effacer" | vue `clear_all()` |
| Téléchargement résultat | vue `download()` |
| Barre de progression | `%` + statut + ETA (individuel, batch, queue) |
| Aperçu du résultat | Texte tronqué ou miniature, clic pour développer |
| Drag & drop zone | Toutes les apps acceptant des fichiers |

**❌ Non-conformités connues à corriger (voir table complète dans `WAMA_APP_CONVENTIONS.md §15`) :**
- Composer : bouton Dupliquer manquant + Download All manquant
- Toutes les apps : ETA non implémenté
- Toutes les apps : import dossier récursif non implémenté

**✅ Vérifier systématiquement** à chaque création d'une nouvelle application.

### Pattern de démarrage de tâche Celery (anti-race-condition)

```python
@require_POST
def start(request, pk):
    from django.db import transaction
    with transaction.atomic():
        item = MyModel.objects.select_for_update().get(pk=pk, user=user)
        if item.status == 'RUNNING':
            return JsonResponse({'error': 'Already running'}, status=400)
        # Révoquer ancienne tâche
        if item.task_id:
            try:
                from celery import current_app
                current_app.control.revoke(item.task_id, terminate=False)
            except Exception:
                pass
        item.status = 'RUNNING'
        item.task_id = ''
        item.save()
    task = my_task.delay(item.id)
    item.task_id = task.id
    item.save(update_fields=['task_id'])
```

---

## Collaboration wama-dev-ai (agent Ollama local)

wama-dev-ai est un agent de développement local (`localhost:11434`) avec accès direct
au codebase WAMA. Il travaille en complément de Claude (Anthropic).

### Principe : Claude réfléchit, wama-dev-ai exécute, l'humain valide.

### Phase 1 (actuelle) — Audit read-only

**wama-dev-ai PEUT :**
- Lire le codebase (tous les fichiers)
- Effectuer des recherches sémantiques (RAG + embeddings)
- Écrire des rapports dans `wama-dev-ai/outputs/`
- Appeler l'API WAMA en lecture seule (Phase 2 prochainement)

**wama-dev-ai NE PEUT PAS :**
- Écrire ou modifier des fichiers de production
- Faire des commits git
- Appliquer des changements sans validation humaine

### Format des rapports
Voir `wama-dev-ai/AUDIT_FORMAT.md` — JSON canonique avec `PENDING_HUMAN_VALIDATION`.

### Lecture des rapports par Claude
Au début de chaque session collaborative, lire les rapports récents dans `wama-dev-ai/outputs/`.
Le champ `claude_review_notes` contient les questions spécifiques à analyser.

### Sélection de modèles — wama-dev-ai vs WAMA

wama-dev-ai dispose d'une sélection RAM-aware avec fallback chains (`config.py : select_model_for_role()`).
WAMA utilise une sélection simplifiée par tier (`llm_utils.py : get_describer_model()`).
**À terme :** exposer la logique de `config.py` via MCP pour unifier la sélection dans WAMA.
**Ne pas précipiter** — garder les deux systèmes découplés jusqu'à Phase 4.

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

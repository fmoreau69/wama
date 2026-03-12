# WAMA — Library Patches

Patches nécessaires après une installation propre du venv.

## Appliquer tous les patches

```bash
cd /mnt/d/WAMA/web-app-for-media-automation
source venv_linux/bin/activate
python patches/apply_patches.py
```

---

## Résumé des patches

### 1. `boson_multimodal` — Higgs Audio V2 (transformers 4.57+ compat)

**Fichier** : `venv_linux/lib/python3.12/site-packages/boson_multimodal/model/higgs_audio/modeling_higgs_audio.py`

| # | Patch | Raison |
|---|-------|--------|
| 1a | `_audio_attn_out[2]` → `_audio_attn_out[2] if len(…) > 2 else None` | transformers 4.57+ retourne 2 valeurs au lieu de 3 |
| 1b | Idem pour `_self_attn_out[2]` | Même raison |
| 2a | `@torch.inference_mode()` → `@torch.no_grad()` sur `generate()` | Les ops inplace sont interdites en inference_mode |
| 2b | Idem sur `capture_model()` | Même raison |
| 3 | `get_max_length()` → `get_max_cache_shape()` avec fallback hasattr | Méthode renommée en 4.57+ |
| **4** | **Ajouter la mise à jour de `cache_position` dans `_update_model_kwargs_for_generation`** | **CAUSE RACINE de l'audio fragmenté/garbled** — sans ce patch, le masquage causal est incorrect à chaque step |
| 5 | Ajouter `synced_gpus=False`, `streamer=None`, `past_key_values_buckets=None` dans `_sample()` | Nouveaux args requis par 4.57+ |
| 6 | Pop `tokenizer` et `stop_strings` de `model_kwargs` au début de `_sample()` | Kwargs inconnus ajoutés par 4.57+ |
| 7 | Supprimer `cur_len=` et `max_length=` de `_has_unfinished_sequences()` | Args supprimés en 4.57+ |

### 2. `deepfilternet` — Compat torchaudio 2.9 (runtime shim)

**Pas de patch de fichier venv.** Le shim est appliqué à l'exécution dans :
`wama/enhancer/utils/audio_enhancer.py` → `DeepFilterNetBackend._patch_torchaudio_compat()`

Ce que le shim corrige :
- `torchaudio.backend.common.AudioMetaData` → supprimé en torchaudio 2.0
- `torchaudio.info()` → supprimé en torchaudio 2.9 (remplacé par TorchCodec)
- `torchaudio.load()` → redirigé vers soundfile (TorchCodec requiert FFmpeg)
- `torchaudio.save()` → redirigé vers soundfile

### 3. `tts_service.py` — Higgs Audio patches (dans le repo)

Déjà committé. Points clés :
- `output.usage.get("completion_tokens", 0)` — usage est un dict, pas un objet
- `temperature=0.7` — évite l'EOS prématuré (était 0.3)
- Auto-trim référence audio à 6s max
- `_higgs_engine.model.decode_graph_runners.clear()` dans `_load_higgs()`

### 4. `start_wama_prod.sh` — CUDA Graphs désactivés

```bash
export HIGGS_DISABLE_CUDA_GRAPHS=1
```

Doit être exporté avant le lancement du serveur TTS. Les CUDA graphs causent des
écritures KV cache aux mauvaises positions lors du replay → audio court/distordu.

---

## Installation deepfilternet

deepfilternet 0.5.6 requiert une compilation Rust (deepfilterlib) :

```bash
# Installer Rust si absent
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source ~/.cargo/env

# Installer deepfilternet (compile deepfilterlib ~2-3 min)
pip install deepfilternet

# Le modèle se télécharge automatiquement au premier lancement depuis AI-models/models/speech/deepfilternet/
```

## Installation resemble-enhance

```bash
pip install resemble-enhance soundfile
```

Le shim deepspeed (mock via MagicMock) est géré à l'exécution dans `audio_enhancer.py`.

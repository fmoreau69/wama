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

### 2. `deepfilternet` — Compat torchaudio (patch venv + shim runtime)

**Deux couches complémentaires** :
1. **PATCH 2 de `apply_patches.py`** réécrit `site-packages/df/io.py` : l'import
   `AudioMetaData` (supprimé en torchaudio 2.x) est enveloppé d'un `try/except` avec une
   dataclass de repli — **perdu à chaque `pip install --upgrade deepfilternet`, à rejouer** ;
2. un shim runtime dans :
`wama/enhancer/utils/audio_enhancer.py` → `DeepFilterNetBackend._patch_torchaudio_compat()`

Ce que le shim corrige :
- `torchaudio.backend.common.AudioMetaData` → supprimé en torchaudio 2.0
- `torchaudio.info()` → supprimé en torchaudio 2.9 (remplacé par TorchCodec)
- `torchaudio.load()` → redirigé vers soundfile (TorchCodec requiert FFmpeg)
- `torchaudio.save()` → redirigé vers soundfile

### 3. Higgs Audio — garde-fous in-repo (vérification seulement)

Déménagés le 2026-08-14 du service TTS (ex-`tts_service.py`, `wama/common/tts/service.py` depuis le 2026-10-28) vers le backend Higgs — aujourd'hui
`wama/common/backends/higgs_backend.py` (relevé le 2026-09-13 ; il vivait d'abord sous
`synthesizer/backends/`, chemin renommé depuis) — lors du passage des moteurs TTS sous contrat commun ; `apply_patches.py` PATCH 3 ne fait que VÉRIFIER
la présence des marqueurs. Points clés historiques :
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

### 5. `xformers` — torch 2.9.x (`GroupName` supprimé)

**Fichier** : `venv_linux/.../site-packages/xformers/ops/seqpar.py` (+ injection runtime).
torch 2.9 a supprimé `torch.distributed.distributed_c10d.GroupName` ; sans le patch, tout import
de xformers casse. Détail : `apply_patches.py` PATCH 5.

### 6. `vibevoice` — ASR : crash CUDA sur audio long

**Fichier** : `venv_linux/.../site-packages/vibevoice/.../modeling_vibevoice_asr.py`.
Le `lm_head` appliqué à la séquence complète fait déborder l'indexation int32 du GEMM CUDA sur
les audios longs (`cudaErrorUnknown`) ; le patch calcule les logits sur le **dernier token
seulement**. Détail : `apply_patches.py` PATCH 6.

### 7. `qwen-asr` — import `nagisa` rendu paresseux (2026-09-28)

**Fichier** : `venv_linux/.../site-packages/qwen_asr/inference/qwen3_forced_aligner.py`.
`qwen-asr==0.0.6` s'installe en `--no-deps` (ses pins rétrograderaient le venv) : son chemin
`transformers` tourne avec NOTRE 4.57.6. Le seul blocage est `import nagisa` (tokenizer japonais,
qui tire DyNet en C++) en tête de l'aligneur, chargé par `import qwen_asr` alors qu'il ne sert qu'au
japonais. Le patch l'enveloppe d'un `try/except`. Sans lui : `ModuleNotFoundError: nagisa`.

### 8. NeMo — `nv-one-logger` face à notre Lightning 2.6.1 (2026-09-28)

**Fichier** : `venv_linux/.../site-packages/nv_one_logger/training_telemetry/integration/pytorch_lightning.py`.
`nemo_toolkit[asr]==3.0.0` s'installe en `--no-deps` (ses pins rétrograderaient lightning,
protobuf et fsspec). La télémétrie déclare `save_checkpoint(weights_only: bool = False)` là où
Lightning 2.6 déclare `Optional[bool]` : le décorateur `overrides` vérifie la signature À L'IMPORT
et refuse, ce qui empêche `import nemo.collections.asr` (canary, parakeet). Le patch aligne la
signature.

### 9. `diffusers` — table module → distribution construite à la demande (2026-09-30)

**Fichier** : `venv_linux/.../site-packages/diffusers/utils/import_utils.py` (3 remplacements).
`packages_distributions()` était appelé À L'IMPORT : 68,5 s sur ce venv (lecture des `RECORD` de
182 distributions à travers `/mnt/d`), payées par chaque processus qui importe diffusers. La table
ne sert qu'à `get_dist_name` : elle est construite à la demande, depuis les `top_level.txt`
(0,9 s), les `RECORD` n'étant lus que pour un module introuvable. Même résultat, sans le coût.

### 10. `onnxruntime` — processeur contre GPU (vérification seulement, 2026-10-04)

Installées ensemble, la distribution processeur `onnxruntime` masque `onnxruntime-gpu` (même
module) : tout moteur ONNX (voix Kokoro, agrandisseur de l'Enhancer) retombe sur le processeur en
silence (1,3 s par phrase au lieu de 0,18 s). pip la réinstalle à chaque librairie qui dépend du
nom `onnxruntime`. Le script ne répare pas (des services en marche ont chargé ces paquets) : il
**dit** la commande. Garde côté tests : `wama/common/tests/tests_onnx_runtime.py`.

---

## Diffs appliqués à du code tiers recopié (hors `site-packages`)

`musetalk_local_2026-09-07.diff` et `triposr_pymcubes_lazy_rembg.diff` ne passent pas par
`apply_patches.py` : ils s'appliquent au code tiers VENDORISÉ (`wama/common/backends/vendor/`).
Leur domicile — dépôt d'origine, commit épinglé, backend consommateur — est
**`wama/common/backends/vendor/README.md`** ; il ne se recopie pas ici. ⚠ Le diff MuseTalk
(7 fichiers) n'est réappliqué par aucun script : « à outiller » (`PROJECT_STATUS`, 2026-09-07).

> ⚠ Ce README décrivait les patchs 1 à 6 seulement jusqu'au 2026-10-10 : 7 à 10 et les deux
> diffs y manquaient. La liste qui fait foi reste `apply_patches.py` (et la table de `AGENTS.md
> §Patches de compatibilité venv`).

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

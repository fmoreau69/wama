#!/usr/bin/env python3
"""
WAMA — Venv library patches
Run from the project root with the venv active:
    python patches/apply_patches.py

Each patch is a (search, replace, description) tuple.
The script checks whether the patch is already applied before replacing.
"""

import sys
import os
import re
from pathlib import Path

# ── Helpers ───────────────────────────────────────────────────────────────────

def find_site_packages(venv_dir: str) -> Path:
    base = Path(venv_dir)
    for p in base.glob("lib/python*/site-packages"):
        return p
    raise FileNotFoundError(f"site-packages not found under {venv_dir}")

def apply_patch(path: Path, search: str, replace: str, description: str) -> bool:
    """
    Apply one search→replace patch to *path*.
    Returns True if the patch was applied, False if it was already present.
    Raises ValueError if *search* is not found (patch may need updating).
    """
    text = path.read_text(encoding="utf-8")
    if replace in text:
        print(f"  [SKIP — already applied] {description}")
        return False
    if search not in text:
        print(f"  [WARN — search string not found] {description}")
        print(f"    → The library may have been updated; review manually.")
        return False
    patched = text.replace(search, replace, 1)
    path.write_text(patched, encoding="utf-8")
    print(f"  [OK] {description}")
    return True

# ── Locate venv ───────────────────────────────────────────────────────────────

script_dir = Path(__file__).parent
project_dir = script_dir.parent
venv_dir = project_dir / "venv_linux"

if not venv_dir.exists():
    print(f"ERROR: venv not found at {venv_dir}")
    sys.exit(1)

site = find_site_packages(str(venv_dir))
print(f"site-packages: {site}\n")

# =============================================================================
# PATCH 1 — boson_multimodal/model/higgs_audio/modeling_higgs_audio.py
#           (transformers 4.57+ compatibility — 9 patches)
# =============================================================================

higgs = site / "boson_multimodal/model/higgs_audio/modeling_higgs_audio.py"
print(f"=== {higgs.name} ===")

if not higgs.exists():
    print("  [SKIP — file not found]")
else:

    # ── 1a. Attention unpacking — audio_attn (returns 2 values in 4.57+) ────
    apply_patch(
        higgs,
        search='audio_present_key_value = _audio_attn_out[2]',
        replace='audio_present_key_value = _audio_attn_out[2] if len(_audio_attn_out) > 2 else None',
        description="1a. audio_attn unpacking: guard [2] index",
    )

    # ── 1b. Attention unpacking — self_attn ──────────────────────────────────
    apply_patch(
        higgs,
        search='present_key_value = _self_attn_out[2]',
        replace='present_key_value = _self_attn_out[2] if len(_self_attn_out) > 2 else None',
        description="1b. self_attn unpacking: guard [2] index",
    )

    # ── 2a. inference_mode → no_grad on generate() ──────────────────────────
    apply_patch(
        higgs,
        search='@torch.inference_mode()\n    def generate(',
        replace='@torch.no_grad()\n    def generate(',
        description="2a. generate(): inference_mode → no_grad (inplace ops forbidden)",
    )

    # ── 2b. inference_mode → no_grad on capture_model() ─────────────────────
    apply_patch(
        higgs,
        search='@torch.inference_mode()\n    def capture_model(',
        replace='@torch.no_grad()\n    def capture_model(',
        description="2b. capture_model(): inference_mode → no_grad",
    )

    # ── 3. get_max_length → get_max_cache_shape (removed in 4.57+) ──────────
    apply_patch(
        higgs,
        search='target_length = past_key_values.get_max_length()',
        replace=(
            'target_length = past_key_values.get_max_cache_shape() '
            "if hasattr(past_key_values, 'get_max_cache_shape') "
            'else past_key_values.get_max_length()'
        ),
        description="3. get_max_length → get_max_cache_shape with hasattr fallback",
    )

    # ── 4. cache_position not advanced — ROOT CAUSE of audio fragmentation ───
    # Add the cache_position update at the end of _update_model_kwargs_for_generation.
    # The patch inserts the update BEFORE the final `return model_kwargs`.
    apply_patch(
        higgs,
        search=(
            '                ],\n'
            '                    1,\n'
            '                )\n'
            '\n'
            '        return model_kwargs'
        ),
        replace=(
            '                ],\n'
            '                    1,\n'
            '                )\n'
            '\n'
            '        # Update cache_position to advance by num_new_tokens (mirrors standard GenerationMixin behaviour).\n'
            '        # Without this, cache_position stays at its initial prefill value, causing wrong causal masking\n'
            '        # in every audio decoding step and producing fragmented/garbled audio.\n'
            '        if "cache_position" in model_kwargs and model_kwargs["cache_position"] is not None:\n'
            '            model_kwargs["cache_position"] = model_kwargs["cache_position"][-1:] + num_new_tokens\n'
            '\n'
            '        return model_kwargs'
        ),
        description="4. cache_position not advanced — ROOT CAUSE of audio fragmentation",
    )

    # ── 5. _sample() default arguments (added in 4.57+, missing in Higgs) ───
    apply_patch(
        higgs,
        search=(
            '    def _sample(\n'
            '        self,\n'
            '        input_ids: torch.LongTensor,\n'
            '        logits_processor: LogitsProcessorList,\n'
            '        stopping_criteria: StoppingCriteriaList,\n'
            '        generation_config: GenerationConfig,\n'
            '        **model_kwargs,'
        ),
        replace=(
            '    def _sample(\n'
            '        self,\n'
            '        input_ids: torch.LongTensor,\n'
            '        logits_processor: LogitsProcessorList,\n'
            '        stopping_criteria: StoppingCriteriaList,\n'
            '        generation_config: GenerationConfig,\n'
            '        synced_gpus: bool = False,\n'
            '        streamer: Optional["BaseStreamer"] = None,\n'
            '        past_key_values_buckets: Optional[OrderedDict[int, Cache]] = None,\n'
            '        **model_kwargs,'
        ),
        description="5. _sample(): add synced_gpus/streamer/past_key_values_buckets defaults",
    )

    # ── 6. Strip extra kwargs (tokenizer / stop_strings) added in 4.57+ ─────
    apply_patch(
        higgs,
        search=(
            '        assert input_ids.shape[0] == 1, "Only support batch_size=1 in _sample()"\n'
            '\n'
            '        audio_out_bos_token_id'
        ),
        replace=(
            '        assert input_ids.shape[0] == 1, "Only support batch_size=1 in _sample()"\n'
            '\n'
            '        # Strip kwargs added by transformers 4.57+ that are not accepted by forward()\n'
            '        for _key in ("tokenizer", "stop_strings"):\n'
            '            model_kwargs.pop(_key, None)\n'
            '\n'
            '        audio_out_bos_token_id'
        ),
        description="6. _sample(): strip tokenizer/stop_strings from model_kwargs",
    )

    # ── 7. _has_unfinished_sequences() — cur_len/max_length removed in 4.57+ ─
    apply_patch(
        higgs,
        search=(
            'while self._has_unfinished_sequences(\n'
            '            this_peer_finished, synced_gpus, device=input_ids.device,\n'
            '            cur_len=cur_len, max_length=max_length\n'
            '        ):'
        ),
        replace=(
            'while self._has_unfinished_sequences(\n'
            '            this_peer_finished, synced_gpus, device=input_ids.device\n'
            '        ):'
        ),
        description="7. _has_unfinished_sequences(): remove cur_len/max_length args",
    )

print()

# =============================================================================
# PATCH 2 — df/io.py
#           deepfilternet 0.5.6 imports torchaudio.backend.common.AudioMetaData
#           which was removed in torchaudio 2.x.
#           Fix: wrap the import in try/except and provide a dataclass stub.
# =============================================================================

df_io = site / "df/io.py"
print(f"=== {df_io.name} (deepfilternet torchaudio 2.x compat) ===")

if not df_io.exists():
    print("  [SKIP — file not found]")
else:
    apply_patch(
        df_io,
        search="from torchaudio.backend.common import AudioMetaData",
        replace=(
            "try:\n"
            "    from torchaudio.backend.common import AudioMetaData\n"
            "except ImportError:\n"
            "    from dataclasses import dataclass\n"
            "\n"
            "    @dataclass\n"
            "    class AudioMetaData:\n"
            "        sample_rate: int\n"
            "        num_frames: int\n"
            "        num_channels: int\n"
            "        bits_per_sample: int\n"
            "        encoding: str"
        ),
        description="2. df/io.py: AudioMetaData dataclass stub (torchaudio.backend.common removed in 2.x)",
    )
print()

# =============================================================================
# PATCH 3 — backend Higgs du synthesizer (in-repo, vérification seulement)
#           Historique : ces garde-fous vivaient dans tts_service.py ; depuis le
#           passage des moteurs TTS sous contrat commun (2026-08-14), la partie
#           Higgs vit dans wama/common/backends/higgs_backend.py.
#           (Les aiguilles 'completion_tokens' / 'trim_audio' d'une version
#           antérieure étaient déjà mortes AVANT le déménagement — réalignées.)
#           ⚠ Chemin corrigé le 2026-09-13 : il visait encore
#           synthesizer/backends/, où le fichier n'existe plus — les 4 contrôles
#           rendaient [MISSING] à chaque passage, une fausse alarme permanente.
#           Trouvé en déclarant patches/README.md au catalogue (check_docs).
# =============================================================================

print("=== higgs_backend.py (in repo — vérification seulement) ===")
higgs = project_dir / "wama" / "common" / "backends" / "higgs_backend.py"
checks = [
    ('HIGGS_DISABLE_CUDA_GRAPHS', "CUDA graphs disabled"),
    ('temperature=0.7', "temperature=0.7 (was 0.3)"),
    ('MAX_REF_DURATION_S', "reference audio auto-trim to 6s"),
    ('_generation_lock', "sérialisation des générations (KV cache partagé)"),
]
for needle, desc in checks:
    if higgs.exists() and needle in higgs.read_text(encoding="utf-8"):
        print(f"  [OK — in repo] {desc}")
    else:
        print(f"  [MISSING] {desc} — check higgs_backend.py manually")
print()

# =============================================================================
# PATCH 4 — start_wama_prod.sh
#           HIGGS_DISABLE_CUDA_GRAPHS=1 must be exported before launching.
# =============================================================================

print("=== start_wama_prod.sh ===")
prod_sh = project_dir / "start_wama_prod.sh"
if prod_sh.exists() and "HIGGS_DISABLE_CUDA_GRAPHS" in prod_sh.read_text():
    print("  [OK — in repo] HIGGS_DISABLE_CUDA_GRAPHS=1")
else:
    print("  [MISSING] Add: export HIGGS_DISABLE_CUDA_GRAPHS=1")
print()

# =============================================================================
# PATCH 5 — xformers 0.0.35 / torch 2.9.x compat  (RUNTIME — no file patch)
#           GroupName was removed from torch.distributed.distributed_c10d in
#           torch 2.9.x.  xformers 0.0.35 references it in two files:
#             - xformers/ops/seqpar.py  (import statement)
#             - xformers/ops/sequence_parallel_fused_ops.py  (attribute access)
#           Both use it as a type annotation only (no runtime logic).
#           Fix: inject GroupName = str into the module BEFORE audiocraft loads
#           xformers.  This is done in audiocraft_backend.py::generate().
#           A defensive try/except was also applied to seqpar.py (see below),
#           but the runtime injection in the backend is the primary fix.
# =============================================================================

print("=== xformers GroupName (torch 2.9.x compat) ===")
seqpar = site / "xformers/ops/seqpar.py"
if seqpar.exists():
    content = seqpar.read_text(encoding="utf-8")
    # CRITIQUE : le fallback DOIT être `str`, pas `None`. `GroupName` sert d'ANNOTATION de
    # type dans ~10 custom_op de ce fichier ; en torch 2.9.x, `torch.library.infer_schema`
    # lit ces annotations à l'import → `None.__origin__` plante (AttributeError). `GroupName`
    # était un alias de str (nom de process group) → `= str` donne des annotations valides.
    if "GroupName = str" in content:
        print("  [OK — seqpar.py] GroupName = str fallback already applied")
    elif "GroupName = None" in content:
        # Corrige un ancien patch (= None) qui cassait infer_schema en torch 2.9.x.
        apply_patch(
            seqpar,
            search='    GroupName = None  # type: ignore[assignment,misc]  # removed in torch 2.9.x',
            replace='    GroupName = str  # type: ignore[assignment,misc]  # torch 2.9.x : GroupName supprimé (= str)',
            description="5a. seqpar.py: GroupName fallback None -> str (infer_schema torch 2.9.x)",
        )
    elif "GroupName" not in content:
        print("  [OK — seqpar.py] GroupName not referenced (xformers updated?)")
    else:
        apply_patch(
            seqpar,
            search='from torch.distributed.distributed_c10d import _resolve_process_group, GroupName',
            replace=(
                'from torch.distributed.distributed_c10d import _resolve_process_group\n'
                'try:\n'
                '    from torch.distributed.distributed_c10d import GroupName\n'
                'except ImportError:\n'
                '    GroupName = str  # type: ignore[assignment,misc]  # torch 2.9.x : GroupName supprimé (= str)'
            ),
            description="5a. seqpar.py: GroupName import — try/except fallback (= str)",
        )
spfo = site / "xformers/ops/sequence_parallel_fused_ops.py"
if spfo.exists():
    content = spfo.read_text(encoding="utf-8")
    if "dist.distributed_c10d.GroupName" not in content:
        print("  [OK — sequence_parallel_fused_ops.py] GroupName annotation already fixed / absent")
    else:
        # Deux annotations IDENTIQUES (fonctions différentes) : évaluées à l'import par
        # torch.library.custom_op → AttributeError (GroupName supprimé en torch 2.9.x).
        # GroupName = alias de str (nom de process group) → remplacer par str préserve
        # l'inférence de schéma du custom_op. Contexte suivant (gathered_/scattered_outputs)
        # pour distinguer les deux occurrences (apply_patch ne remplace que la 1re).
        apply_patch(
            spfo,
            search=(
                "    process_group_name: dist.distributed_c10d.GroupName,\n"
                "    gathered_outputs: List[torch.Tensor],"
            ),
            replace=(
                "    process_group_name: str,  # torch 2.9.x : GroupName supprimé (= str)\n"
                "    gathered_outputs: List[torch.Tensor],"
            ),
            description="5b. sequence_parallel_fused_ops.py: GroupName annotation (allgather) -> str",
        )
        apply_patch(
            spfo,
            search=(
                "    process_group_name: dist.distributed_c10d.GroupName,\n"
                "    scattered_outputs: List[torch.Tensor],"
            ),
            replace=(
                "    process_group_name: str,  # torch 2.9.x : GroupName supprimé (= str)\n"
                "    scattered_outputs: List[torch.Tensor],"
            ),
            description="5b. sequence_parallel_fused_ops.py: GroupName annotation (reducescatter) -> str",
        )
print("  [INFO] Fix FICHIER (5a seqpar.py + 5b sequence_parallel_fused_ops.py) : couvre TOUS les")
print("         consommateurs xformers (diffusers/MuseTalk, audiocraft…), pas seulement le backend")
print("         audiocraft. L'injection runtime GroupName=str y reste en ceinture+bretelles.")
print()

print("=== 6. VibeVoice ASR: lm_head sur audio long (crash CUDA 'unknown error') ===")
vibe_asr = site / "vibevoice/modular/modeling_vibevoice_asr.py"
if not vibe_asr.exists():
    print(f"  [SKIP] {vibe_asr} not found")
else:
    _content = vibe_asr.read_text(encoding="utf-8")
    if "PATCH WAMA (crash CUDA" in _content:
        print("  [OK — modeling_vibevoice_asr.py] patch lm_head déjà appliqué")
    else:
        apply_patch(
            vibe_asr,
            search=(
                "        hidden_states = outputs[0] if not return_dict else outputs.last_hidden_state\n"
                "        logits = self.lm_head(hidden_states)"
            ),
            replace=(
                "        hidden_states = outputs[0] if not return_dict else outputs.last_hidden_state\n"
                "        # PATCH WAMA (crash CUDA 'unknown error' sur audio long) : lm_head sur TOUTE la\n"
                "        # sequence produit [seq, vocab] ; sur ~50K tokens le nb d'elements depasse\n"
                "        # l'indexation int32 du kernel GEMM CUDA -> crash. En generation seul le\n"
                "        # dernier token est necessaire (ou logits_to_keep si fourni).\n"
                "        if labels is not None:\n"
                "            logits = self.lm_head(hidden_states)\n"
                "        else:\n"
                "            _ltk = kwargs.get('logits_to_keep', kwargs.get('num_logits_to_keep', 0))\n"
                "            if isinstance(_ltk, int) and _ltk > 0:\n"
                "                logits = self.lm_head(hidden_states[:, -_ltk:, :])\n"
                "            else:\n"
                "                logits = self.lm_head(hidden_states[:, -1:, :])"
            ),
            description="6. vibevoice modeling_vibevoice_asr.py: logits seulement sur le dernier token en generation (evite l'overflow int32 du GEMM CUDA sur audio long)",
        )
print()

print("=== 7. qwen-asr: import nagisa (japonais seul) rendu paresseux ===")
# qwen-asr==0.0.6 s'installe en --no-deps (backend QwenASRBackend, PIP_NO_DEPS) : il EPINGLE
# accelerate==1.12.0 (le code ne l'importe pas) et des dependances de demo/langues (gradio,
# flask, vllm, soynlp, nagisa). Mesure du 2026-09-28 : le chemin transformers tourne avec NOTRE
# transformers 4.57.6 et accelerate 1.6.0 — le seul blocage est `import nagisa` EN TETE de
# l'aligneur (tokenizer japonais, tire DyNet en C++), charge par `import qwen_asr` alors qu'il ne
# sert qu'a l'alignement du japonais. Sans ce patch : ModuleNotFoundError: nagisa.
qwen_aligner = site / "qwen_asr/inference/qwen3_forced_aligner.py"
if not qwen_aligner.exists():
    print(f"  [SKIP] {qwen_aligner} not found")
else:
    apply_patch(
        qwen_aligner,
        search="import nagisa\n",
        replace=(
            "try:\n"
            "    import nagisa  # PATCH WAMA : japonais seul — absent en --no-deps\n"
            "except ImportError:\n"
            "    nagisa = None\n"
        ),
        description="7. qwen_asr qwen3_forced_aligner.py: import nagisa paresseux (tokenizer japonais, inutile hors japonais)",
    )
print()

print("=== 8. NeMo: nv-one-logger face a notre Lightning 2.6.1 ===")
# nemo_toolkit[asr]==3.0.0 s'installe en --no-deps (backend NemoASRBackend, PIP_NO_DEPS) :
# honorer ses pins RETROGRADERAIT lightning 2.6.1 -> 2.4.0, protobuf 7 -> 6 et fsspec (mesure du
# 2026-09-28, `pip install --dry-run`). Avec NOS versions, un seul blocage : la telemetrie
# nv-one-logger declare `save_checkpoint(weights_only: bool = False)` la ou Lightning 2.6 declare
# `Optional[bool]` — le decorateur `overrides` verifie la signature A L'IMPORT et refuse
# (TypeError), ce qui empeche `import nemo.collections.asr`. Mesure apres ce patch : import OK,
# transcription francaise juste sur CPU (parakeet-tdt-0.6b-v3).
one_logger_ptl = site / "nv_one_logger/training_telemetry/integration/pytorch_lightning.py"
if not one_logger_ptl.exists():
    print(f"  [SKIP] {one_logger_ptl} not found")
else:
    apply_patch(
        one_logger_ptl,
        search="weights_only: bool = False, storage_options",
        replace="weights_only: Optional[bool] = None, storage_options",
        description="8. nv_one_logger pytorch_lightning.py: save_checkpoint(weights_only: Optional[bool]) (signature de Lightning 2.6)",
    )
print()

print("=== 9. diffusers: table module -> distribution construite A LA DEMANDE ===")
# Mesure du 2026-09-30 (lenteur de MuseTalk : 3 s de video en 505 s) : `import
# diffusers.utils.import_utils` coute 82 s de temps PROPRE a chaque processus qui importe
# diffusers (gunicorn, celery, sous-processus MuseTalk…). Cause : `packages_distributions()`
# appele A L'IMPORT — 68,5 s sur ce venv, parce qu'il lit le RECORD (`dist.files`) des 182
# distributions sans `top_level.txt`, a travers /mnt/d. La table ne sert qu'a `get_dist_name`
# (3 appels : optimum, aiter, modelopt). Patch : table construite a la demande, depuis les seuls
# `top_level.txt` (0,9 s), les RECORD n'etant lus que si le module y reste introuvable. Meme
# resultat (optimum -> optimum-quanto), sans le cout.
diffusers_import_utils = site / "diffusers/utils/import_utils.py"
if not diffusers_import_utils.exists():
    print(f"  [SKIP] {diffusers_import_utils} not found")
else:
    apply_patch(
        diffusers_import_utils,
        search="    _package_map = importlib_metadata.packages_distributions()  # load-once to avoid expensive calls\n",
        replace="    _package_map = None  # PATCH WAMA 9 : construite a la demande (_wama_package_map)\n",
        description="9a. diffusers import_utils.py: plus de packages_distributions() a l'import",
    )
    apply_patch(
        diffusers_import_utils,
        search="def _is_package_available(pkg_name: str, get_dist_name: bool = False) -> tuple[bool, str]:\n",
        replace=(
            "_wama_undeclared = None\n"
            "\n"
            "\n"
            "def _wama_package_map(pkg_name, package_map):\n"
            "    \"\"\"PATCH WAMA 9 : table module -> distributions, en deux temps — top_level.txt\n"
            "    d'abord (quelques Ko par distribution), RECORD seulement pour un module introuvable.\"\"\"\n"
            "    global _wama_undeclared\n"
            "    if package_map is None:\n"
            "        package_map, _wama_undeclared = defaultdict(list), []\n"
            "        try:\n"
            "            for dist in importlib_metadata.distributions():\n"
            "                declared = (dist.read_text(\"top_level.txt\") or \"\").split()\n"
            "                if not declared:\n"
            "                    _wama_undeclared.append(dist)\n"
            "                for pkg in declared:\n"
            "                    package_map[pkg].append(dist.metadata[\"Name\"])\n"
            "        except Exception:\n"
            "            pass\n"
            "    if pkg_name not in package_map and _wama_undeclared:\n"
            "        try:\n"
            "            for dist in _wama_undeclared:\n"
            "                names = {f.parts[0] if len(f.parts) > 1 else inspect.getmodulename(f)\n"
            "                         for f in (dist.files or [])} - {None}\n"
            "                for pkg in filter(lambda name: \".\" not in name, names):\n"
            "                    package_map[pkg].append(dist.metadata[\"Name\"])\n"
            "        except Exception:\n"
            "            pass\n"
            "        _wama_undeclared = []\n"
            "    return package_map\n"
            "\n"
            "\n"
            "def _is_package_available(pkg_name: str, get_dist_name: bool = False) -> tuple[bool, str]:\n"
        ),
        description="9b. diffusers import_utils.py: helper _wama_package_map (top_level.txt d'abord)",
    )
    apply_patch(
        diffusers_import_utils,
        search=(
            "        if _package_map is None:\n"
            "            _package_map = defaultdict(list)\n"
            "            try:\n"
            "                # Fallback for Python < 3.10\n"
            "                for dist in importlib_metadata.distributions():\n"
            "                    _top_level_declared = (dist.read_text(\"top_level.txt\") or \"\").split()\n"
            "                    # Infer top-level package names from file structure\n"
            "                    _inferred_opt_names = {\n"
            "                        f.parts[0] if len(f.parts) > 1 else inspect.getmodulename(f) for f in (dist.files or [])\n"
            "                    } - {None}\n"
            "                    _top_level_inferred = filter(lambda name: \".\" not in name, _inferred_opt_names)\n"
            "                    for pkg in _top_level_declared or _top_level_inferred:\n"
            "                        _package_map[pkg].append(dist.metadata[\"Name\"])\n"
            "            except Exception as _:\n"
            "                pass\n"
        ),
        replace=(
            "        # PATCH WAMA 9 : la table ne sert qu'a `get_dist_name` — construite a la demande.\n"
            "        if get_dist_name and (_package_map is None or pkg_name not in _package_map):\n"
            "            _package_map = _wama_package_map(pkg_name, _package_map)\n"
        ),
        description="9c. diffusers import_utils.py: table construite seulement pour get_dist_name",
    )
print()

# =============================================================================
# PATCH 10 — onnxruntime : la distribution PROCESSEUR ne doit pas cohabiter avec
#            la distribution GPU  (venv Linux — VÉRIFICATION SEULEMENT)
#            Les deux fournissent le MÊME module ; installées ensemble, la
#            version processeur masque l'autre et tout moteur ONNX (voix Kokoro,
#            agrandisseur de l'Enhancer) retombe sur le processeur EN SILENCE
#            (mesuré le 2026-10-04 : 1,3 s par phrase au lieu de 0,18 s).
#            pip la réinstalle dès qu'une librairie dépendant du nom
#            `onnxruntime` est installée (faster-whisper, kokoro-onnx, qwen-tts).
#            Pas de réparation automatique : elle touche des paquets que des
#            services en marche ont chargés — on DIT la commande.
#            Garde côté tests : wama/common/tests/tests_onnx_runtime.py.
# =============================================================================

print("=== onnxruntime (processeur vs GPU — vérification seulement) ===")
ort_cpu = sorted(site.glob("onnxruntime-[0-9]*.dist-info"))
ort_gpu = sorted(site.glob("onnxruntime_gpu-[0-9]*.dist-info"))
if ort_gpu and ort_cpu:
    gpu_version = ort_gpu[-1].name[len("onnxruntime_gpu-"):-len(".dist-info")]
    print("  [CONFLIT] onnxruntime (processeur) masque onnxruntime-gpu : le moteur ONNX tourne sur le processeur")
    print("            Réparer (services arrêtés ou relancés ensuite) :")
    print("              pip uninstall -y onnxruntime")
    print(f"              pip install --force-reinstall --no-deps onnxruntime-gpu=={gpu_version}")
elif ort_gpu:
    print("  [OK] onnxruntime-gpu seul (`pip check` signale 4 dépendances « onnxruntime » : attendu)")
else:
    print("  [SKIP] pas de onnxruntime-gpu dans ce venv")
print()

print("Done.")

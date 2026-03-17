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
#           deepfilternet 0.5.6 imports torchaudio.backend.common which was
#           removed in torchaudio 2.x. The shim is applied at runtime in
#           wama/enhancer/utils/audio_enhancer.py (_patch_torchaudio_compat).
#           No file patch needed here — just document.
# =============================================================================

print("=== df/io.py + resemble_enhance (torchaudio 2.9 compat) ===")
print("  [INFO] torchaudio 2.9 compat shim applied at module import time in:")
print("         wama/enhancer/utils/audio_enhancer.py :: _patch_torchaudio_compat() (module-level call)")
print("         Patches: torchaudio.backend.common stub, torchaudio.info(), torchaudio.load(), torchaudio.save()")
print("         Both ResembleEnhance and DeepFilterNet backends benefit from this single patch.")
print()

# =============================================================================
# PATCH 3 — tts_service.py (project root, not venv)
#           Already committed in the repo. Listed here for documentation only.
# =============================================================================

print("=== tts_service.py (project root — already in repo) ===")
tts = project_dir / "tts_service.py"
checks = [
    ('output.usage.get("completion_tokens"', "usage dict access via .get()"),
    ('HIGGS_DISABLE_CUDA_GRAPHS', "CUDA graphs disabled"),
    ('temperature=0.7', "temperature=0.7 (was 0.3)"),
    ('trim_audio', "reference audio auto-trim to 6s"),
]
for needle, desc in checks:
    if tts.exists() and needle in tts.read_text(encoding="utf-8"):
        print(f"  [OK — in repo] {desc}")
    else:
        print(f"  [MISSING] {desc} — check tts_service.py manually")
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
    if "GroupName = None" in content:
        print("  [OK — seqpar.py] try/except fallback already applied")
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
                '    GroupName = None  # type: ignore[assignment,misc]  # removed in torch 2.9.x'
            ),
            description="5a. seqpar.py: GroupName import — try/except fallback",
        )
print("  [INFO] Primary fix: audiocraft_backend.py injects GroupName=str before audiocraft import")
print("         Covers both seqpar.py and sequence_parallel_fused_ops.py in one shot.")
print()

print("Done.")

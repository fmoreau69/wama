"""Convert old yolov12n-seg.pt (qk+v) to new format (qkv) for ultralytics 8.4.14."""
import torch
from ultralytics.nn.tasks import SegmentationModel
import torch.nn.functional as F

OLD_PATH = '/mnt/d/WAMA/web-app-for-media-automation/AI-models/models/vision/yolo/segment/yolov12n-seg.pt.old'
NEW_PATH = '/mnt/d/WAMA/web-app-for-media-automation/AI-models/models/vision/yolo/segment/yolov12n-seg.pt'

# Load old checkpoint
ckpt = torch.load(OLD_PATH, map_location='cpu', weights_only=False)
old_model = ckpt['model']
old_sd = old_model.state_dict()

# Build a fresh model from the same yaml config
yaml_cfg = dict(old_model.yaml)
new_model = SegmentationModel(cfg=yaml_cfg, nc=yaml_cfg['nc'], verbose=False)
new_sd = new_model.state_dict()

# Find key differences
old_keys = set(old_sd.keys())
new_keys = set(new_sd.keys())
only_old = sorted(old_keys - new_keys)
only_new = sorted(new_keys - old_keys)

print(f"Keys only in old: {len(only_old)}")
print(f"Keys only in new: {len(only_new)}")
for k in only_old[:5]:
    print(f"  OLD: {k} {old_sd[k].shape}")
for k in only_new[:5]:
    print(f"  NEW: {k} {new_sd[k].shape}")

# Shape mismatches in common keys
common_keys = old_keys & new_keys
shape_diffs = [(k, old_sd[k].shape, new_sd[k].shape)
               for k in common_keys if old_sd[k].shape != new_sd[k].shape]
print(f"Shape mismatches: {len(shape_diffs)}")
for k, os, ns in sorted(shape_diffs):
    print(f"  {k}: old={os} new={ns}")

# Build converted state dict
converted_sd = {}

# Copy all common keys with matching shapes
for k in common_keys:
    if old_sd[k].shape == new_sd[k].shape:
        converted_sd[k] = old_sd[k]

# Handle pe kernel change (5x5 -> 7x7): zero-pad
for k, os, ns in shape_diffs:
    if 'pe.conv.weight' in k:
        # old: [C, 1, 5, 5] -> new: [C, 1, 7, 7]
        old_w = old_sd[k]
        # Pad: left=1, right=1, top=1, bottom=1
        new_w = F.pad(old_w, (1, 1, 1, 1), mode='constant', value=0)
        assert new_w.shape == ns, f"pe pad mismatch: {new_w.shape} != {ns}"
        converted_sd[k] = new_w
        print(f"  Padded pe: {k} {os} -> {new_w.shape}")
    else:
        print(f"  WARNING: unhandled shape mismatch: {k} {os} != {ns}")

# Handle qk+v -> qkv conversion
# Group old qk and v keys by their attn module prefix
attn_prefixes = set()
for k in only_old:
    if '.attn.qk.' in k:
        prefix = k.split('.attn.qk.')[0] + '.attn'
        attn_prefixes.add(prefix)

print(f"\nConverting {len(attn_prefixes)} AAttn modules (qk+v -> qkv)")

for prefix in sorted(attn_prefixes):
    # Get num_heads from the module
    # qk conv: [2*all_head_dim, in_dim, 1, 1]
    qk_conv_key = f"{prefix}.qk.conv.weight"
    v_conv_key = f"{prefix}.v.conv.weight"
    qkv_conv_key = f"{prefix}.qkv.conv.weight"

    qk_w = old_sd[qk_conv_key]  # [2*C, in, 1, 1]
    v_w = old_sd[v_conv_key]    # [C, in, 1, 1]

    C = v_w.shape[0]  # all_head_dim = num_heads * head_dim

    # Old qk output: [q_all(C), k_all(C)]
    q_w = qk_w[:C]   # [C, in, 1, 1]
    k_w = qk_w[C:]   # [C, in, 1, 1]

    # New qkv expects interleaved per-head: [q_h0, k_h0, v_h0, q_h1, k_h1, v_h1, ...]
    # Need to determine head_dim. Check new model's expected qkv shape.
    expected_shape = new_sd[qkv_conv_key].shape
    total_out = expected_shape[0]  # 3 * C
    assert total_out == 3 * C, f"qkv size mismatch: {total_out} != {3 * C}"

    # For the view(B, N, num_heads, 3*head_dim) to work correctly,
    # the channel ordering must be: [head0_qkv, head1_qkv, ...]
    # where head_i_qkv = [q_head_i, k_head_i, v_head_i]

    # Determine num_heads from the model
    # For C=64: num_heads=2, head_dim=32
    # For C=128: num_heads=4, head_dim=32
    head_dim = 32  # consistent across all AAttn modules
    num_heads = C // head_dim

    # Reshape to per-head
    q_heads = q_w.view(num_heads, head_dim, -1, 1, 1)  # [nh, hd, in, 1, 1]
    k_heads = k_w.view(num_heads, head_dim, -1, 1, 1)
    v_heads = v_w.view(num_heads, head_dim, -1, 1, 1)

    # Interleave: [q_h0, k_h0, v_h0, q_h1, k_h1, v_h1, ...]
    qkv_w = torch.cat([q_heads, k_heads, v_heads], dim=1)  # [nh, 3*hd, in, 1, 1]
    qkv_w = qkv_w.view(total_out, -1, 1, 1)  # [3*C, in, 1, 1]

    converted_sd[qkv_conv_key] = qkv_w
    print(f"  {prefix}: qk{qk_w.shape}+v{v_w.shape} -> qkv{qkv_w.shape}")

    # Same for batch norm params
    for bn_param in ['bn.weight', 'bn.bias', 'bn.running_mean', 'bn.running_var']:
        qk_p = old_sd[f"{prefix}.qk.{bn_param}"]
        v_p = old_sd[f"{prefix}.v.{bn_param}"]

        q_p = qk_p[:C]
        k_p = qk_p[C:]

        q_ph = q_p.view(num_heads, head_dim)
        k_ph = k_p.view(num_heads, head_dim)
        v_ph = v_p.view(num_heads, head_dim)

        qkv_p = torch.cat([q_ph, k_ph, v_ph], dim=1).view(-1)
        converted_sd[f"{prefix}.qkv.{bn_param}"] = qkv_p

    # num_batches_tracked
    converted_sd[f"{prefix}.qkv.bn.num_batches_tracked"] = old_sd[f"{prefix}.qk.bn.num_batches_tracked"]

# Verify all new keys are covered
missing = [k for k in new_keys if k not in converted_sd]
if missing:
    print(f"\nWARNING: {len(missing)} keys still missing:")
    for k in missing[:10]:
        print(f"  {k}: {new_sd[k].shape}")
else:
    print("\nAll keys converted successfully!")

# Load into new model
result = new_model.load_state_dict(converted_sd, strict=True)
print(f"Load result: {result}")

# Quick inference test
new_model.eval()
with torch.no_grad():
    dummy = torch.randn(1, 3, 640, 640)
    out = new_model(dummy)
    print(f"Inference test OK! Output: {type(out)}")

# Save as new checkpoint
ckpt['model'] = new_model
ckpt['model'].yaml = yaml_cfg
torch.save(ckpt, NEW_PATH)
import os
size_mb = os.path.getsize(NEW_PATH) / (1024 * 1024)
print(f"Saved: {NEW_PATH} ({size_mb:.1f} MB)")

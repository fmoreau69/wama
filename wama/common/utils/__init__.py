"""
Common utilities for WAMA.
"""

from .format_policy import (
    FORMAT_POLICY,
    FormatPolicyConfig,
    ModelFormat,
    RuntimeType,
    get_preferred_format,
    get_policy,
    get_category_for_model_type,
    get_category_for_source,
    should_auto_convert,
    get_convertible_formats,
    is_format_preferred,
    get_conversion_suggestion,
    get_policy_summary,
)

from .safetensors_utils import (
    get_model_format,
    convert_pt_to_safetensors,
    convert_bin_to_safetensors,
    batch_convert_to_safetensors,
    verify_safetensors,
    get_safetensors_info,
    compare_model_files,
)

from .onnx_utils import (
    convert_yolo_to_onnx,
    convert_pytorch_to_onnx,
    batch_convert_yolo_to_onnx,
    verify_onnx_model,
    get_onnx_runtime_info,
)

from .disk_utils import (
    check_disk_space,
    check_space_for_model,
    require_disk_space,
    get_disk_space,
    get_estimated_model_size,
    InsufficientDiskSpaceError,
    DiskSpaceCheck,
    ESTIMATED_MODEL_SIZES,
)

__all__ = [
    # Format Policy
    'FORMAT_POLICY',
    'FormatPolicyConfig',
    'ModelFormat',
    'RuntimeType',
    'get_preferred_format',
    'get_policy',
    'get_category_for_model_type',
    'get_category_for_source',
    'should_auto_convert',
    'get_convertible_formats',
    'is_format_preferred',
    'get_conversion_suggestion',
    'get_policy_summary',
    # Safetensors Utils
    'get_model_format',
    'convert_pt_to_safetensors',
    'convert_bin_to_safetensors',
    'batch_convert_to_safetensors',
    'verify_safetensors',
    'get_safetensors_info',
    'compare_model_files',
    # ONNX Utils
    'convert_yolo_to_onnx',
    'convert_pytorch_to_onnx',
    'batch_convert_yolo_to_onnx',
    'verify_onnx_model',
    'get_onnx_runtime_info',
    # Disk Utils
    'check_disk_space',
    'check_space_for_model',
    'require_disk_space',
    'get_disk_space',
    'get_estimated_model_size',
    'InsufficientDiskSpaceError',
    'DiskSpaceCheck',
    'ESTIMATED_MODEL_SIZES',
]

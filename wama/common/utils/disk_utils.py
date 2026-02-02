"""
Disk Space Utilities

Functions for checking and managing disk space before model downloads.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum safety margin in GB
DEFAULT_SAFETY_MARGIN_GB = 5.0

# Warning thresholds in GB
LOW_SPACE_WARNING_GB = 50.0
CRITICAL_SPACE_WARNING_GB = 20.0


@dataclass
class DiskSpaceCheck:
    """Result of a disk space check."""
    has_space: bool
    available_gb: float
    required_gb: float
    safety_margin_gb: float
    total_required_gb: float
    message: str
    is_critical: bool = False
    is_warning: bool = False


def get_disk_space(path: str = None) -> Optional[dict]:
    """
    Get disk space information.

    Args:
        path: Path to check. If None, uses the model storage path.

    Returns:
        Dict with 'total_gb', 'used_gb', 'free_gb', 'percent' or None if error.
    """
    try:
        from wama.common.services.system_monitor import SystemMonitor
        return SystemMonitor.get_disk_info(path or '/')
    except Exception as e:
        logger.error(f"Error getting disk space: {e}")
        return None


def check_disk_space(
    required_gb: float,
    safety_margin_gb: float = DEFAULT_SAFETY_MARGIN_GB,
    path: str = None
) -> DiskSpaceCheck:
    """
    Check if there's enough disk space for a download/operation.

    Args:
        required_gb: Required space in GB.
        safety_margin_gb: Additional safety margin in GB.
        path: Path to check. If None, uses system default.

    Returns:
        DiskSpaceCheck with the result.
    """
    disk_info = get_disk_space(path)

    if not disk_info:
        return DiskSpaceCheck(
            has_space=False,
            available_gb=0,
            required_gb=required_gb,
            safety_margin_gb=safety_margin_gb,
            total_required_gb=required_gb + safety_margin_gb,
            message="Could not determine disk space. Proceeding with caution.",
            is_warning=True,
        )

    available_gb = disk_info.get('free_gb', 0)
    total_required = required_gb + safety_margin_gb
    has_space = available_gb >= total_required

    # Determine warning levels
    is_critical = available_gb < CRITICAL_SPACE_WARNING_GB
    is_warning = available_gb < LOW_SPACE_WARNING_GB

    if has_space:
        if is_warning:
            message = (
                f"Space available but running low. "
                f"Available: {available_gb:.1f} GB, Required: {required_gb:.1f} GB. "
                f"Consider freeing up space after this download."
            )
        else:
            message = f"Sufficient space: {available_gb:.1f} GB available, {required_gb:.1f} GB required."
    else:
        message = (
            f"Insufficient disk space! "
            f"Available: {available_gb:.1f} GB, "
            f"Required: {required_gb:.1f} GB + {safety_margin_gb:.1f} GB safety margin = {total_required:.1f} GB. "
            f"Please free up at least {total_required - available_gb:.1f} GB before downloading."
        )

    return DiskSpaceCheck(
        has_space=has_space,
        available_gb=available_gb,
        required_gb=required_gb,
        safety_margin_gb=safety_margin_gb,
        total_required_gb=total_required,
        message=message,
        is_critical=is_critical,
        is_warning=is_warning,
    )


def check_space_for_model(
    model_size_gb: float,
    allow_on_warning: bool = True,
    path: str = None
) -> DiskSpaceCheck:
    """
    Check if there's enough space to download a model.

    This is a convenience wrapper around check_disk_space that:
    - Uses model size as the required space
    - Adds appropriate safety margin based on model size

    Args:
        model_size_gb: Estimated model size in GB.
        allow_on_warning: If True, returns has_space=True even with low space warning.
        path: Path to check.

    Returns:
        DiskSpaceCheck with the result.
    """
    # Scale safety margin with model size (min 5GB, max 20GB)
    safety_margin = min(20.0, max(DEFAULT_SAFETY_MARGIN_GB, model_size_gb * 0.2))

    check = check_disk_space(model_size_gb, safety_margin, path)

    # If we have space but it's just a warning, optionally allow the operation
    if check.has_space and check.is_warning and not allow_on_warning:
        check.has_space = False
        check.message += " Operation blocked due to low space warning. Set allow_on_warning=True to proceed anyway."

    return check


def require_disk_space(required_gb: float, path: str = None) -> None:
    """
    Raise an exception if there's not enough disk space.

    Use this as a guard before starting downloads.

    Args:
        required_gb: Required space in GB.
        path: Path to check.

    Raises:
        InsufficientDiskSpaceError: If not enough space available.
    """
    check = check_disk_space(required_gb, path=path)

    if not check.has_space:
        raise InsufficientDiskSpaceError(
            check.message,
            required_gb=check.required_gb,
            available_gb=check.available_gb,
        )


class InsufficientDiskSpaceError(Exception):
    """Raised when there's not enough disk space for an operation."""

    def __init__(
        self,
        message: str,
        required_gb: float = 0,
        available_gb: float = 0
    ):
        super().__init__(message)
        self.required_gb = required_gb
        self.available_gb = available_gb


# Estimated model sizes for common models (in GB)
ESTIMATED_MODEL_SIZES = {
    # Diffusion models
    'stable-diffusion-1.5': 4.0,
    'stable-diffusion-xl': 6.5,
    'stable-diffusion-3': 12.0,
    'wan-ti2v-1.3b': 8.0,
    'wan-ti2v-5b': 20.0,
    'wan-ti2v-14b': 55.0,
    'hunyuan-video': 25.0,
    'hunyuan-image': 15.0,
    'cogvideox': 18.0,
    'ltx-video': 12.0,
    'mochi': 15.0,

    # Vision models
    'yolo-v8-nano': 0.02,
    'yolo-v8-small': 0.05,
    'yolo-v8-medium': 0.1,
    'yolo-v8-large': 0.2,
    'yolo-v8-xlarge': 0.4,
    'sam-vit-b': 0.4,
    'sam-vit-l': 1.2,
    'sam-vit-h': 2.5,

    # Speech models
    'whisper-tiny': 0.08,
    'whisper-base': 0.15,
    'whisper-small': 0.5,
    'whisper-medium': 1.5,
    'whisper-large': 3.0,

    # VLM models
    'blip': 2.0,
    'blip2': 4.0,
    'bart-summarization': 1.5,

    # Upscaling models (ONNX)
    'realesrgan-x4plus': 0.07,
    'realesrgan-anime': 0.07,
    'bsrgan': 0.06,
}


def get_estimated_model_size(model_name: str) -> Optional[float]:
    """
    Get estimated size for a known model.

    Args:
        model_name: Model identifier.

    Returns:
        Estimated size in GB or None if unknown.
    """
    # Direct lookup
    if model_name in ESTIMATED_MODEL_SIZES:
        return ESTIMATED_MODEL_SIZES[model_name]

    # Partial match
    model_lower = model_name.lower()
    for key, size in ESTIMATED_MODEL_SIZES.items():
        if key in model_lower:
            return size

    return None

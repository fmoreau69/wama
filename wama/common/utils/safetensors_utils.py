"""
Safetensors Conversion Utilities

Provides functions to convert PyTorch models (.pt, .pth, .bin) to safetensors format.
Safetensors is a safe, fast, and portable format for storing tensors.

Benefits:
- Faster loading (memory-mapped)
- Safer (no arbitrary code execution)
- Smaller file size
- Cross-platform compatible
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

logger = logging.getLogger(__name__)


def get_model_format(model_path: str) -> str:
    """
    Detect the format of a model file.

    Args:
        model_path: Path to the model file

    Returns:
        Format string: 'pt', 'pth', 'safetensors', 'onnx', 'bin', 'gguf', or 'unknown'
    """
    path = Path(model_path)
    suffix = path.suffix.lower()

    format_map = {
        '.pt': 'pt',
        '.pth': 'pth',
        '.safetensors': 'safetensors',
        '.onnx': 'onnx',
        '.bin': 'bin',
        '.gguf': 'gguf',
        '.ckpt': 'ckpt',
    }

    return format_map.get(suffix, 'unknown')


def convert_pt_to_safetensors(
    model_path: str,
    output_path: Optional[str] = None,
    remove_original: bool = False,
) -> Tuple[bool, str, Optional[str]]:
    """
    Convert a PyTorch model (.pt/.pth) to safetensors format.

    Args:
        model_path: Path to the source .pt/.pth model file
        output_path: Optional output path for safetensors file. If None, creates in same directory
        remove_original: Whether to delete the original file after successful conversion

    Returns:
        Tuple of (success: bool, message: str, output_path: Optional[str])
    """
    try:
        import torch
        from safetensors.torch import save_file
    except ImportError as e:
        missing = 'safetensors' if 'safetensors' in str(e) else 'torch'
        return False, f"{missing} package not installed. Install with: pip install {missing}", None

    model_path = Path(model_path)
    if not model_path.exists():
        return False, f"Model file not found: {model_path}", None

    if model_path.suffix.lower() not in ['.pt', '.pth']:
        return False, f"Expected .pt or .pth file, got: {model_path.suffix}", None

    # Determine output path
    if output_path:
        output_path = Path(output_path)
    else:
        output_path = model_path.with_suffix('.safetensors')

    logger.info(f"Converting {model_path} to safetensors...")

    try:
        # Load the PyTorch model
        # Use weights_only=False for compatibility with older models
        state_dict = torch.load(str(model_path), map_location='cpu', weights_only=False)

        # Handle different checkpoint formats
        if isinstance(state_dict, dict):
            # Check for common checkpoint keys
            if 'state_dict' in state_dict:
                state_dict = state_dict['state_dict']
            elif 'model_state_dict' in state_dict:
                state_dict = state_dict['model_state_dict']
            elif 'model' in state_dict:
                state_dict = state_dict['model']

        # If it's a nn.Module, get state_dict
        if hasattr(state_dict, 'state_dict'):
            state_dict = state_dict.state_dict()

        # Ensure all values are tensors
        if not isinstance(state_dict, dict):
            return False, "Model file does not contain a valid state dict", None

        # Filter out non-tensor values and convert to contiguous tensors
        clean_state_dict = {}
        for key, value in state_dict.items():
            if isinstance(value, torch.Tensor):
                clean_state_dict[key] = value.contiguous()
            else:
                logger.debug(f"Skipping non-tensor key: {key} (type: {type(value).__name__})")

        if not clean_state_dict:
            return False, "No tensor data found in model file", None

        # Save as safetensors
        output_path.parent.mkdir(parents=True, exist_ok=True)
        save_file(clean_state_dict, str(output_path))

        # Verify the output
        file_size = output_path.stat().st_size / (1024 * 1024)  # MB
        logger.info(f"Successfully converted to: {output_path} ({file_size:.2f} MB)")

        # Remove original if requested
        if remove_original and output_path.exists():
            model_path.unlink()
            logger.info(f"Removed original file: {model_path}")

        return True, f"Successfully converted to {output_path}", str(output_path)

    except Exception as e:
        error_msg = f"Failed to convert model: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg, None


def convert_bin_to_safetensors(
    model_path: str,
    output_path: Optional[str] = None,
    remove_original: bool = False,
) -> Tuple[bool, str, Optional[str]]:
    """
    Convert a HuggingFace .bin model to safetensors format.

    Args:
        model_path: Path to the source .bin model file
        output_path: Optional output path for safetensors file
        remove_original: Whether to delete the original file after conversion

    Returns:
        Tuple of (success: bool, message: str, output_path: Optional[str])
    """
    try:
        import torch
        from safetensors.torch import save_file
    except ImportError as e:
        missing = 'safetensors' if 'safetensors' in str(e) else 'torch'
        return False, f"{missing} package not installed. Install with: pip install {missing}", None

    model_path = Path(model_path)
    if not model_path.exists():
        return False, f"Model file not found: {model_path}", None

    if model_path.suffix.lower() != '.bin':
        return False, f"Expected .bin file, got: {model_path.suffix}", None

    # Determine output path
    if output_path:
        output_path = Path(output_path)
    else:
        output_path = model_path.with_suffix('.safetensors')

    logger.info(f"Converting {model_path} to safetensors...")

    try:
        # Load the .bin file (pickle format)
        state_dict = torch.load(str(model_path), map_location='cpu', weights_only=False)

        # Ensure it's a dict of tensors
        if not isinstance(state_dict, dict):
            return False, "Model file does not contain a valid state dict", None

        # Filter and convert tensors
        clean_state_dict = {}
        for key, value in state_dict.items():
            if isinstance(value, torch.Tensor):
                clean_state_dict[key] = value.contiguous()

        if not clean_state_dict:
            return False, "No tensor data found in model file", None

        # Save as safetensors
        output_path.parent.mkdir(parents=True, exist_ok=True)
        save_file(clean_state_dict, str(output_path))

        file_size = output_path.stat().st_size / (1024 * 1024)
        logger.info(f"Successfully converted to: {output_path} ({file_size:.2f} MB)")

        if remove_original and output_path.exists():
            model_path.unlink()
            logger.info(f"Removed original file: {model_path}")

        return True, f"Successfully converted to {output_path}", str(output_path)

    except Exception as e:
        error_msg = f"Failed to convert model: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg, None


def batch_convert_to_safetensors(
    models_dir: str,
    recursive: bool = True,
    skip_existing: bool = True,
    remove_originals: bool = False,
    extensions: List[str] = None,
) -> Dict[str, Tuple[bool, str]]:
    """
    Convert multiple PyTorch models in a directory to safetensors format.

    Args:
        models_dir: Directory containing model files
        recursive: Search subdirectories recursively (default: True)
        skip_existing: Skip if safetensors already exists (default: True)
        remove_originals: Remove original files after conversion (default: False)
        extensions: List of extensions to convert (default: ['.pt', '.pth', '.bin'])

    Returns:
        Dictionary mapping model paths to (success, message) tuples
    """
    if extensions is None:
        extensions = ['.pt', '.pth', '.bin']

    models_dir = Path(models_dir)
    if not models_dir.exists():
        return {"error": (False, f"Directory not found: {models_dir}")}

    # Find all model files
    model_files = []
    for ext in extensions:
        if recursive:
            model_files.extend(models_dir.rglob(f'*{ext}'))
        else:
            model_files.extend(models_dir.glob(f'*{ext}'))

    if not model_files:
        return {"info": (True, f"No model files found in {models_dir}")}

    results = {}
    for model_file in model_files:
        safetensors_path = model_file.with_suffix('.safetensors')

        # Skip if safetensors already exists
        if skip_existing and safetensors_path.exists():
            results[str(model_file)] = (True, f"Safetensors already exists: {safetensors_path}")
            continue

        # Convert based on extension
        if model_file.suffix.lower() in ['.pt', '.pth']:
            success, message, _ = convert_pt_to_safetensors(
                str(model_file),
                str(safetensors_path),
                remove_original=remove_originals,
            )
        elif model_file.suffix.lower() == '.bin':
            success, message, _ = convert_bin_to_safetensors(
                str(model_file),
                str(safetensors_path),
                remove_original=remove_originals,
            )
        else:
            success, message = False, f"Unsupported extension: {model_file.suffix}"

        results[str(model_file)] = (success, message)

    return results


def verify_safetensors(safetensors_path: str) -> Tuple[bool, str, Optional[Dict]]:
    """
    Verify a safetensors file is valid and get its metadata.

    Args:
        safetensors_path: Path to the safetensors file

    Returns:
        Tuple of (valid: bool, message: str, metadata: Optional[Dict])
    """
    try:
        from safetensors import safe_open
    except ImportError:
        return False, "safetensors package not installed. Install with: pip install safetensors", None

    safetensors_path = Path(safetensors_path)
    if not safetensors_path.exists():
        return False, f"File not found: {safetensors_path}", None

    try:
        with safe_open(str(safetensors_path), framework="pt") as f:
            metadata = {
                'keys': list(f.keys()),
                'num_tensors': len(f.keys()),
                'tensors': {},
            }

            total_size = 0
            for key in f.keys():
                tensor = f.get_tensor(key)
                tensor_info = {
                    'shape': list(tensor.shape),
                    'dtype': str(tensor.dtype),
                    'size_bytes': tensor.numel() * tensor.element_size(),
                }
                metadata['tensors'][key] = tensor_info
                total_size += tensor_info['size_bytes']

            metadata['total_size_mb'] = round(total_size / (1024 * 1024), 2)

        return True, "Model is valid", metadata

    except Exception as e:
        return False, f"Model validation failed: {str(e)}", None


def get_safetensors_info() -> Dict[str, Any]:
    """
    Get information about safetensors installation.

    Returns:
        Dictionary with installation information
    """
    info = {
        'safetensors_installed': False,
        'version': None,
        'torch_installed': False,
        'torch_version': None,
    }

    try:
        import safetensors
        info['safetensors_installed'] = True
        info['version'] = getattr(safetensors, '__version__', 'unknown')
    except ImportError:
        pass

    try:
        import torch
        info['torch_installed'] = True
        info['torch_version'] = torch.__version__
    except ImportError:
        pass

    return info


def compare_model_files(
    original_path: str,
    converted_path: str,
    tolerance: float = 1e-6,
) -> Tuple[bool, str, Optional[Dict]]:
    """
    Compare original and converted model files to verify conversion accuracy.

    Args:
        original_path: Path to original model file (.pt, .pth, .bin)
        converted_path: Path to converted safetensors file
        tolerance: Numerical tolerance for comparison

    Returns:
        Tuple of (match: bool, message: str, details: Optional[Dict])
    """
    try:
        import torch
        from safetensors import safe_open
    except ImportError:
        return False, "Required packages not installed", None

    try:
        # Load original
        original_state = torch.load(original_path, map_location='cpu', weights_only=False)
        if isinstance(original_state, dict):
            if 'state_dict' in original_state:
                original_state = original_state['state_dict']
            elif 'model_state_dict' in original_state:
                original_state = original_state['model_state_dict']

        # Load converted
        converted_state = {}
        with safe_open(converted_path, framework="pt") as f:
            for key in f.keys():
                converted_state[key] = f.get_tensor(key)

        # Compare
        details = {
            'original_keys': len(original_state) if isinstance(original_state, dict) else 0,
            'converted_keys': len(converted_state),
            'matching_keys': 0,
            'mismatched_keys': [],
            'missing_keys': [],
        }

        if not isinstance(original_state, dict):
            return False, "Original is not a state dict", details

        for key in original_state:
            if not isinstance(original_state[key], torch.Tensor):
                continue

            if key not in converted_state:
                details['missing_keys'].append(key)
                continue

            if torch.allclose(original_state[key], converted_state[key], atol=tolerance):
                details['matching_keys'] += 1
            else:
                details['mismatched_keys'].append(key)

        if details['missing_keys'] or details['mismatched_keys']:
            return False, "Conversion mismatch detected", details

        return True, "Conversion verified successfully", details

    except Exception as e:
        return False, f"Comparison failed: {str(e)}", None

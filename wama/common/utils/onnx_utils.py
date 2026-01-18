"""
ONNX Conversion Utilities

Provides functions to convert PyTorch models (.pt) to ONNX format for production deployment.
ONNX models offer better performance and portability across different platforms.

Supported model types:
- YOLO models (via ultralytics export)
- Generic PyTorch models (via torch.onnx.export)
"""

import os
import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

logger = logging.getLogger(__name__)


def convert_yolo_to_onnx(
    model_path: str,
    output_path: Optional[str] = None,
    imgsz: int = 640,
    half: bool = False,
    dynamic: bool = True,
    simplify: bool = True,
    opset: int = 12,
) -> Tuple[bool, str, Optional[str]]:
    """
    Convert a YOLO model (.pt) to ONNX format using ultralytics export.

    Args:
        model_path: Path to the source .pt model file
        output_path: Optional output path for ONNX file. If None, creates in same directory
        imgsz: Image size for export (default: 640)
        half: Use FP16 half-precision (default: False, use FP32)
        dynamic: Enable dynamic axes for variable batch/image sizes (default: True)
        simplify: Simplify ONNX model using onnx-simplifier (default: True)
        opset: ONNX opset version (default: 12)

    Returns:
        Tuple of (success: bool, message: str, output_path: Optional[str])
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        return False, "ultralytics package not installed. Install with: pip install ultralytics", None

    model_path = Path(model_path)
    if not model_path.exists():
        return False, f"Model file not found: {model_path}", None

    if not model_path.suffix == '.pt':
        return False, f"Expected .pt file, got: {model_path.suffix}", None

    # Determine output path
    if output_path:
        output_path = Path(output_path)
    else:
        output_path = model_path.with_suffix('.onnx')

    logger.info(f"Converting {model_path} to ONNX...")
    logger.info(f"Parameters: imgsz={imgsz}, half={half}, dynamic={dynamic}, simplify={simplify}, opset={opset}")

    try:
        # Load the YOLO model
        model = YOLO(str(model_path))

        # Export to ONNX
        export_path = model.export(
            format='onnx',
            imgsz=imgsz,
            half=half,
            dynamic=dynamic,
            simplify=simplify,
            opset=opset,
        )

        # Move to desired output path if different
        if export_path and Path(export_path) != output_path:
            shutil.move(export_path, output_path)
            export_path = str(output_path)

        logger.info(f"Successfully exported to: {export_path}")
        return True, f"Successfully converted to {export_path}", export_path

    except Exception as e:
        error_msg = f"Failed to convert model: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg, None


def convert_pytorch_to_onnx(
    model: Any,
    output_path: str,
    input_shape: Tuple[int, ...],
    input_names: List[str] = None,
    output_names: List[str] = None,
    dynamic_axes: Dict[str, Dict[int, str]] = None,
    opset_version: int = 12,
) -> Tuple[bool, str]:
    """
    Convert a generic PyTorch model to ONNX format.

    Args:
        model: PyTorch model (nn.Module)
        output_path: Path for the output ONNX file
        input_shape: Shape of input tensor (e.g., (1, 3, 640, 640))
        input_names: Names for input tensors (default: ['input'])
        output_names: Names for output tensors (default: ['output'])
        dynamic_axes: Dynamic axes configuration for variable sizes
        opset_version: ONNX opset version (default: 12)

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        import torch
        import torch.onnx
    except ImportError:
        return False, "PyTorch not installed"

    if input_names is None:
        input_names = ['input']
    if output_names is None:
        output_names = ['output']

    logger.info(f"Converting PyTorch model to ONNX: {output_path}")

    try:
        # Create dummy input
        dummy_input = torch.randn(*input_shape)

        # Set model to evaluation mode
        model.eval()

        # Export to ONNX
        torch.onnx.export(
            model,
            dummy_input,
            output_path,
            export_params=True,
            opset_version=opset_version,
            do_constant_folding=True,
            input_names=input_names,
            output_names=output_names,
            dynamic_axes=dynamic_axes,
        )

        logger.info(f"Successfully exported to: {output_path}")
        return True, f"Successfully converted to {output_path}"

    except Exception as e:
        error_msg = f"Failed to convert model: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


def batch_convert_yolo_to_onnx(
    models_dir: str,
    output_dir: Optional[str] = None,
    recursive: bool = True,
    **kwargs
) -> Dict[str, Tuple[bool, str]]:
    """
    Convert multiple YOLO models in a directory to ONNX format.

    Args:
        models_dir: Directory containing .pt model files
        output_dir: Output directory for ONNX files (default: same as source)
        recursive: Search subdirectories recursively (default: True)
        **kwargs: Additional arguments passed to convert_yolo_to_onnx

    Returns:
        Dictionary mapping model paths to (success, message) tuples
    """
    models_dir = Path(models_dir)
    if not models_dir.exists():
        return {"error": (False, f"Directory not found: {models_dir}")}

    # Find all .pt files
    if recursive:
        pt_files = list(models_dir.rglob('*.pt'))
    else:
        pt_files = list(models_dir.glob('*.pt'))

    if not pt_files:
        return {"info": (True, f"No .pt files found in {models_dir}")}

    results = {}
    for pt_file in pt_files:
        # Determine output path
        if output_dir:
            output_dir_path = Path(output_dir)
            # Preserve directory structure
            relative_path = pt_file.relative_to(models_dir)
            onnx_path = output_dir_path / relative_path.with_suffix('.onnx')
            onnx_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            onnx_path = pt_file.with_suffix('.onnx')

        # Skip if ONNX already exists
        if onnx_path.exists():
            results[str(pt_file)] = (True, f"ONNX already exists: {onnx_path}")
            continue

        # Convert
        success, message, _ = convert_yolo_to_onnx(
            str(pt_file),
            str(onnx_path),
            **kwargs
        )
        results[str(pt_file)] = (success, message)

    return results


def verify_onnx_model(onnx_path: str) -> Tuple[bool, str, Optional[Dict]]:
    """
    Verify an ONNX model is valid and get its metadata.

    Args:
        onnx_path: Path to the ONNX model file

    Returns:
        Tuple of (valid: bool, message: str, metadata: Optional[Dict])
    """
    try:
        import onnx
    except ImportError:
        return False, "onnx package not installed. Install with: pip install onnx", None

    onnx_path = Path(onnx_path)
    if not onnx_path.exists():
        return False, f"File not found: {onnx_path}", None

    try:
        # Load and check model
        model = onnx.load(str(onnx_path))
        onnx.checker.check_model(model)

        # Extract metadata
        metadata = {
            'ir_version': model.ir_version,
            'opset_version': model.opset_import[0].version if model.opset_import else None,
            'producer_name': model.producer_name,
            'producer_version': model.producer_version,
            'inputs': [],
            'outputs': [],
        }

        # Get input info
        for inp in model.graph.input:
            input_info = {
                'name': inp.name,
                'shape': [d.dim_value if d.dim_value else d.dim_param for d in inp.type.tensor_type.shape.dim],
                'dtype': inp.type.tensor_type.elem_type,
            }
            metadata['inputs'].append(input_info)

        # Get output info
        for out in model.graph.output:
            output_info = {
                'name': out.name,
                'shape': [d.dim_value if d.dim_value else d.dim_param for d in out.type.tensor_type.shape.dim],
                'dtype': out.type.tensor_type.elem_type,
            }
            metadata['outputs'].append(output_info)

        return True, "Model is valid", metadata

    except Exception as e:
        return False, f"Model validation failed: {str(e)}", None


def get_onnx_runtime_info() -> Dict[str, Any]:
    """
    Get information about available ONNX runtime and providers.

    Returns:
        Dictionary with runtime information
    """
    info = {
        'onnxruntime_installed': False,
        'version': None,
        'providers': [],
        'gpu_available': False,
    }

    try:
        import onnxruntime as ort
        info['onnxruntime_installed'] = True
        info['version'] = ort.__version__
        info['providers'] = ort.get_available_providers()
        info['gpu_available'] = 'CUDAExecutionProvider' in info['providers']
    except ImportError:
        pass

    return info


# Convenience function for Django management command
def convert_anonymizer_models_to_onnx(
    output_subdir: str = 'onnx',
    **kwargs
) -> Dict[str, Tuple[bool, str]]:
    """
    Convert all Anonymizer YOLO models to ONNX format.

    Args:
        output_subdir: Subdirectory name for ONNX models (default: 'onnx')
        **kwargs: Additional arguments for conversion

    Returns:
        Dictionary mapping model paths to results
    """
    from wama.settings import BASE_DIR

    models_dir = BASE_DIR / "AI-models" / "anonymizer" / "models--ultralytics--yolo"
    output_dir = models_dir.parent / output_subdir if output_subdir else None

    return batch_convert_yolo_to_onnx(
        str(models_dir),
        str(output_dir) if output_dir else None,
        **kwargs
    )

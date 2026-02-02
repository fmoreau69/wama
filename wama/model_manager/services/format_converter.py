"""
Format Converter Service

Centralized service for model format conversions.
Integrates with the format policy to provide automatic and manual conversion capabilities.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class ConversionResult:
    """Result of a model conversion operation."""
    success: bool
    message: str
    source_path: str
    target_path: Optional[str] = None
    source_format: str = ''
    target_format: str = ''
    size_before_mb: float = 0
    size_after_mb: float = 0


@dataclass
class ConversionSuggestion:
    """Suggestion for a model format conversion."""
    model_id: str
    model_path: str
    current_format: str
    suggested_format: str
    category: str
    reason: str
    priority: int = 0  # Higher = more important


class FormatConverter:
    """
    Centralized service for model format conversions.

    Supports:
    - .pt/.pth → .safetensors
    - .bin → .safetensors
    - .pt (YOLO) → .onnx
    - Generic PyTorch → .onnx
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._initialized = getattr(self, '_initialized', False)
        if self._initialized:
            return
        self._initialized = True

    def convert_model(
        self,
        model_path: str,
        target_format: str,
        model_type: Optional[str] = None,
        keep_original: bool = True,
        **kwargs
    ) -> ConversionResult:
        """
        Convert a model to a different format.

        Args:
            model_path: Path to the source model file
            target_format: Target format ('safetensors', 'onnx')
            model_type: Type hint for conversion ('yolo', 'diffusion', 'generic')
            keep_original: Whether to keep the original file
            **kwargs: Additional arguments for specific converters

        Returns:
            ConversionResult with conversion details
        """
        from wama.common.utils.safetensors_utils import get_model_format

        source_path = Path(model_path)
        if not source_path.exists():
            return ConversionResult(
                success=False,
                message=f"Source file not found: {model_path}",
                source_path=model_path,
            )

        source_format = get_model_format(model_path)
        size_before = source_path.stat().st_size / (1024 * 1024)

        # Route to appropriate converter
        if target_format.lower() == 'safetensors':
            result = self._convert_to_safetensors(
                model_path, source_format, keep_original
            )
        elif target_format.lower() == 'onnx':
            result = self._convert_to_onnx(
                model_path, source_format, model_type, keep_original, **kwargs
            )
        else:
            return ConversionResult(
                success=False,
                message=f"Unsupported target format: {target_format}",
                source_path=model_path,
                source_format=source_format,
            )

        # Add size info
        result.source_format = source_format
        result.target_format = target_format
        result.size_before_mb = round(size_before, 2)

        if result.success and result.target_path:
            target_path = Path(result.target_path)
            if target_path.exists():
                result.size_after_mb = round(
                    target_path.stat().st_size / (1024 * 1024), 2
                )

        return result

    def _convert_to_safetensors(
        self,
        model_path: str,
        source_format: str,
        keep_original: bool,
    ) -> ConversionResult:
        """Convert a model to safetensors format."""
        from wama.common.utils.safetensors_utils import (
            convert_pt_to_safetensors,
            convert_bin_to_safetensors,
        )

        if source_format in ['pt', 'pth']:
            success, message, output_path = convert_pt_to_safetensors(
                model_path,
                remove_original=not keep_original,
            )
        elif source_format == 'bin':
            success, message, output_path = convert_bin_to_safetensors(
                model_path,
                remove_original=not keep_original,
            )
        else:
            return ConversionResult(
                success=False,
                message=f"Cannot convert {source_format} to safetensors",
                source_path=model_path,
            )

        return ConversionResult(
            success=success,
            message=message,
            source_path=model_path,
            target_path=output_path,
        )

    def _convert_to_onnx(
        self,
        model_path: str,
        source_format: str,
        model_type: Optional[str],
        keep_original: bool,
        **kwargs
    ) -> ConversionResult:
        """Convert a model to ONNX format."""
        from wama.common.utils.onnx_utils import (
            convert_yolo_to_onnx,
            convert_pytorch_to_onnx,
        )

        if source_format not in ['pt', 'pth']:
            return ConversionResult(
                success=False,
                message=f"Cannot convert {source_format} to ONNX",
                source_path=model_path,
            )

        # Use YOLO-specific converter if appropriate
        if model_type == 'yolo' or self._is_yolo_model(model_path):
            success, message, output_path = convert_yolo_to_onnx(
                model_path,
                imgsz=kwargs.get('imgsz', 640),
                half=kwargs.get('half', False),
                dynamic=kwargs.get('dynamic', True),
                simplify=kwargs.get('simplify', True),
                opset=kwargs.get('opset', 12),
            )

            if success and not keep_original:
                try:
                    Path(model_path).unlink()
                except Exception as e:
                    logger.warning(f"Could not remove original: {e}")

            return ConversionResult(
                success=success,
                message=message,
                source_path=model_path,
                target_path=output_path,
            )

        # Generic PyTorch conversion requires input shape
        input_shape = kwargs.get('input_shape')
        if not input_shape:
            return ConversionResult(
                success=False,
                message="Generic PyTorch to ONNX conversion requires input_shape parameter",
                source_path=model_path,
            )

        try:
            import torch
            model = torch.load(model_path, map_location='cpu', weights_only=False)
            output_path = str(Path(model_path).with_suffix('.onnx'))

            success, message = convert_pytorch_to_onnx(
                model,
                output_path,
                input_shape=input_shape,
                input_names=kwargs.get('input_names'),
                output_names=kwargs.get('output_names'),
                dynamic_axes=kwargs.get('dynamic_axes'),
                opset_version=kwargs.get('opset', 12),
            )

            if success and not keep_original:
                try:
                    Path(model_path).unlink()
                except Exception as e:
                    logger.warning(f"Could not remove original: {e}")

            return ConversionResult(
                success=success,
                message=message,
                source_path=model_path,
                target_path=output_path if success else None,
            )
        except Exception as e:
            return ConversionResult(
                success=False,
                message=f"Conversion failed: {str(e)}",
                source_path=model_path,
            )

    def _is_yolo_model(self, model_path: str) -> bool:
        """Check if a model is a YOLO model based on path or content."""
        path_lower = model_path.lower()
        return 'yolo' in path_lower or 'ultralytics' in path_lower

    def auto_convert_on_download(
        self,
        model_path: str,
        category: str,
    ) -> Optional[str]:
        """
        Apply format policy after a model is downloaded.

        Args:
            model_path: Path to the downloaded model
            category: Model category (e.g., 'vision', 'diffusion')

        Returns:
            Path to converted file, or None if no conversion needed/performed
        """
        from wama.common.utils.format_policy import (
            get_policy,
            is_format_preferred,
        )
        from wama.common.utils.safetensors_utils import get_model_format

        policy = get_policy(category)
        if not policy or not policy.auto_convert:
            return None

        current_format = get_model_format(model_path)
        if is_format_preferred(current_format, category):
            return None

        result = self.convert_model(
            model_path,
            policy.preferred_format,
            keep_original=policy.keep_original,
        )

        return result.target_path if result.success else None

    def get_conversion_options(self, model_path: str) -> List[str]:
        """
        Get available conversion options for a model.

        Args:
            model_path: Path to the model file

        Returns:
            List of formats the model can be converted to
        """
        from wama.common.utils.safetensors_utils import get_model_format

        current_format = get_model_format(model_path)
        options = []

        if current_format in ['pt', 'pth']:
            options.extend(['safetensors', 'onnx'])
        elif current_format == 'bin':
            options.append('safetensors')
        elif current_format == 'ckpt':
            options.extend(['safetensors', 'onnx'])

        return options

    def scan_and_suggest(
        self,
        models_dir: Optional[str] = None,
    ) -> List[ConversionSuggestion]:
        """
        Scan models and suggest conversions based on policy.

        Args:
            models_dir: Directory to scan (default: AI_MODELS_DIR)

        Returns:
            List of conversion suggestions
        """
        from wama.common.utils.format_policy import (
            FORMAT_POLICY,
            get_conversion_suggestion,
            get_category_for_source,
        )
        from wama.common.utils.safetensors_utils import get_model_format

        if models_dir is None:
            models_dir = str(settings.AI_MODELS_DIR / "models")

        suggestions = []
        models_path = Path(models_dir)

        if not models_path.exists():
            return suggestions

        # Define category mapping based on directory structure
        dir_to_category = {
            'diffusion': 'diffusion',
            'vision': 'vision',
            'speech': 'speech',
            'upscaling': 'upscaling',
            'vision-language': 'vlm',
        }

        # Scan for model files
        for ext in ['*.pt', '*.pth', '*.bin']:
            for model_file in models_path.rglob(ext):
                # Determine category from path
                category = 'diffusion'  # Default
                for dir_name, cat in dir_to_category.items():
                    if dir_name in str(model_file):
                        category = cat
                        break

                current_format = get_model_format(str(model_file))
                suggested = get_conversion_suggestion(current_format, category)

                if suggested:
                    policy = FORMAT_POLICY.get(category)
                    suggestions.append(ConversionSuggestion(
                        model_id=model_file.stem,
                        model_path=str(model_file),
                        current_format=current_format,
                        suggested_format=suggested,
                        category=category,
                        reason=f"Policy recommends {suggested} for {category} models",
                        priority=2 if policy and policy.auto_convert else 1,
                    ))

        # Sort by priority (descending)
        suggestions.sort(key=lambda x: x.priority, reverse=True)
        return suggestions

    def batch_convert(
        self,
        model_paths: List[str],
        target_format: str,
        model_type: Optional[str] = None,
        keep_originals: bool = True,
        **kwargs
    ) -> Dict[str, ConversionResult]:
        """
        Convert multiple models to a target format.

        Args:
            model_paths: List of model file paths
            target_format: Target format for all models
            model_type: Model type hint
            keep_originals: Whether to keep original files
            **kwargs: Additional converter arguments

        Returns:
            Dict mapping model paths to conversion results
        """
        results = {}
        for model_path in model_paths:
            results[model_path] = self.convert_model(
                model_path,
                target_format,
                model_type=model_type,
                keep_original=keep_originals,
                **kwargs
            )
        return results

    def get_format_stats(self, models_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Get statistics about model formats in the models directory.

        Args:
            models_dir: Directory to analyze

        Returns:
            Dict with format counts and policy compliance stats
        """
        from wama.common.utils.format_policy import (
            get_format_stats_template,
            is_format_preferred,
            FORMAT_POLICY,
        )
        from wama.common.utils.safetensors_utils import get_model_format

        if models_dir is None:
            models_dir = str(settings.AI_MODELS_DIR / "models")

        stats = get_format_stats_template()
        compliance = {'compliant': 0, 'non_compliant': 0}
        by_category = {}

        models_path = Path(models_dir)
        if not models_path.exists():
            return {'formats': stats, 'compliance': compliance, 'by_category': by_category}

        # Scan all model files
        extensions = ['*.pt', '*.pth', '*.safetensors', '*.onnx', '*.bin', '*.gguf']

        dir_to_category = {
            'diffusion': 'diffusion',
            'vision': 'vision',
            'speech': 'speech',
            'upscaling': 'upscaling',
            'vision-language': 'vlm',
        }

        for ext in extensions:
            for model_file in models_path.rglob(ext):
                fmt = get_model_format(str(model_file))
                stats[fmt] = stats.get(fmt, 0) + 1

                # Determine category
                category = 'diffusion'
                for dir_name, cat in dir_to_category.items():
                    if dir_name in str(model_file):
                        category = cat
                        break

                # Track by category
                if category not in by_category:
                    by_category[category] = get_format_stats_template()
                by_category[category][fmt] = by_category[category].get(fmt, 0) + 1

                # Check compliance
                if is_format_preferred(fmt, category):
                    compliance['compliant'] += 1
                else:
                    compliance['non_compliant'] += 1

        total = compliance['compliant'] + compliance['non_compliant']
        compliance['percentage'] = round(
            (compliance['compliant'] / total * 100) if total > 0 else 100, 1
        )

        return {
            'formats': stats,
            'compliance': compliance,
            'by_category': by_category,
            'total_models': total,
        }

"""
AI Upscaler module - Simplified integration of QualityScaler for Django.

This module provides a simplified interface to AI upscaling models
based on the QualityScaler project by Djdefrag.

Original: https://github.com/Djdefrag/QualityScaler
License: MIT
"""

import os
import cv2
import numpy as np
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Import centralized model configuration
try:
    from .model_config import ENHANCER_MODELS, get_models_directory, get_model_path
    MODEL_CONFIG_AVAILABLE = True
except ImportError:
    MODEL_CONFIG_AVAILABLE = False
    ENHANCER_MODELS = {}

# Model information - use centralized config or fallback
MODELS_INFO = {
    key: {
        'scale': config['scale'],
        'vram_usage': config['vram_usage'],
        'description': config['description'],
        'file': config['file']
    }
    for key, config in ENHANCER_MODELS.items()
} if MODEL_CONFIG_AVAILABLE else {
    'RealESR_Gx4': {
        'scale': 4,
        'vram_usage': 2.5,
        'description': 'Fast general-purpose 4x upscaler',
        'file': 'RealESR_Gx4_fp16.onnx'
    },
    'RealESR_Animex4': {
        'scale': 4,
        'vram_usage': 2.5,
        'description': 'Fast anime-oriented 4x upscaler',
        'file': 'RealESR_Animex4_fp16.onnx'
    },
    'BSRGANx2': {
        'scale': 2,
        'vram_usage': 0.75,
        'description': 'High-quality 2x upscaler',
        'file': 'BSRGANx2_fp16.onnx'
    },
    'BSRGANx4': {
        'scale': 4,
        'vram_usage': 0.75,
        'description': 'High-quality 4x upscaler',
        'file': 'BSRGANx4_fp16.onnx'
    },
    'RealESRGANx4': {
        'scale': 4,
        'vram_usage': 2.5,
        'description': 'Highest quality 4x upscaler (slow)',
        'file': 'RealESRGANx4_fp16.onnx'
    },
    'IRCNN_Mx1': {
        'scale': 1,
        'vram_usage': 4.0,
        'description': 'Medium denoising (no upscaling)',
        'file': 'IRCNN_Mx1_fp16.onnx'
    },
    'IRCNN_Lx1': {
        'scale': 1,
        'vram_usage': 4.0,
        'description': 'Strong denoising (no upscaling)',
        'file': 'IRCNN_Lx1_fp16.onnx'
    },
}


class AIUpscaler:
    """
    AI-based image upscaler using ONNX Runtime.

    Supports multiple GPU backends:
    - CUDA (Linux/WSL with NVIDIA GPU) - recommended for Linux
    - DirectML (Windows with GPU) - recommended for Windows
    - CoreML (macOS)
    - CPU (fallback)

    The appropriate backend is automatically selected based on availability.

    This is a simplified version of QualityScaler's AI_upscale class,
    adapted for Django/Celery integration.
    """

    def __init__(
        self,
        model_name: str = 'RealESR_Gx4',
        models_dir: Optional[str] = None,
        device_id: int = 0,
        tile_size: int = 0,
    ):
        """
        Initialize the AI Upscaler.

        Args:
            model_name: Name of the AI model to use
            models_dir: Directory containing ONNX models (auto-detected if None)
            device_id: GPU device ID (0=first GPU, 1=second GPU, etc.)
            tile_size: Size of tiles for processing large images (0=auto)
        """
        self.model_name = model_name
        self.device_id = device_id
        self.tile_size = tile_size

        # Get model info
        if model_name not in MODELS_INFO:
            raise ValueError(f"Unknown model: {model_name}")

        self.model_info = MODELS_INFO[model_name]
        self.scale_factor = self.model_info['scale']

        # Find models directory
        if models_dir is None:
            if MODEL_CONFIG_AVAILABLE:
                models_dir = str(get_models_directory())
            else:
                from wama.settings import BASE_DIR
                models_dir = os.path.join(BASE_DIR, 'AI-models', 'enhancer', 'onnx')

        self.models_dir = models_dir
        self.model_path = os.path.join(models_dir, self.model_info['file'])

        # Check if model exists
        if not os.path.exists(self.model_path):
            logger.warning(f"Model file not found: {self.model_path}")
            logger.info(f"Please download models from QualityScaler repository")

        # ONNX Runtime session (lazy loading)
        self.session = None

    def _load_model(self):
        """Lazy load the ONNX model."""
        if self.session is not None:
            return

        try:
            import onnxruntime as ort

            # Get available providers
            available_providers = ort.get_available_providers()
            logger.info(f"Available ONNX providers: {available_providers}")

            # Build provider list based on what's available (priority order)
            providers = []

            # CUDA (Linux/WSL with NVIDIA GPU)
            if 'CUDAExecutionProvider' in available_providers:
                providers.append(('CUDAExecutionProvider', {'device_id': self.device_id}))
                logger.info(f"Using CUDA GPU (device {self.device_id})")

            # TensorRT (Linux with NVIDIA GPU - fastest)
            if 'TensorrtExecutionProvider' in available_providers:
                # TensorRT is faster but CUDA is more compatible, keep CUDA as primary
                pass

            # DirectML (Windows with GPU)
            if 'DmlExecutionProvider' in available_providers:
                providers.append(('DmlExecutionProvider', {'device_id': self.device_id}))
                logger.info(f"Using DirectML GPU (device {self.device_id})")

            # CoreML (macOS)
            if 'CoreMLExecutionProvider' in available_providers:
                providers.append('CoreMLExecutionProvider')
                logger.info("Using CoreML (macOS)")

            # Always add CPU as fallback
            providers.append('CPUExecutionProvider')

            if len(providers) == 1:
                logger.warning("No GPU provider available, using CPU only (slow)")

            # Create inference session
            self.session = ort.InferenceSession(
                self.model_path,
                providers=providers
            )

            # Log which provider is actually being used
            actual_providers = self.session.get_providers()
            logger.info(f"Loaded model: {self.model_name}")
            logger.info(f"Active providers: {actual_providers}")

        except ImportError:
            raise ImportError(
                "onnxruntime is required for AI upscaling. "
                "Install it with: pip install onnxruntime-gpu (Linux) or onnxruntime-directml (Windows)"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load model {self.model_name}: {e}")

    def upscale_image(
        self,
        image: np.ndarray,
        blend_factor: float = 0.0,
    ) -> np.ndarray:
        """
        Upscale an image using AI.

        Args:
            image: Input image (BGR, uint8)
            blend_factor: Blend with original (0.0=full AI, 1.0=original)

        Returns:
            Upscaled image (BGR, uint8)
        """
        # Load model if not already loaded
        self._load_model()

        # Get input dimensions
        h, w = image.shape[:2]

        # Determine if tiling is needed
        if self.tile_size > 0:
            max_size = self.tile_size
        else:
            # Auto-calculate tile size based on VRAM
            # Simplified: use 512 for low VRAM models, 1024 for high VRAM
            max_size = 512 if self.model_info['vram_usage'] < 2.0 else 1024

        # Use tiling if image is large
        if max(h, w) > max_size:
            logger.info(f"Using tiled upscaling (tile size: {max_size})")
            upscaled = self._upscale_with_tiling(image, max_size)
        else:
            upscaled = self._upscale_simple(image)

        # Apply blending if requested
        if blend_factor > 0 and self.scale_factor > 1:
            original_resized = cv2.resize(
                image,
                (upscaled.shape[1], upscaled.shape[0]),
                interpolation=cv2.INTER_LANCZOS4
            )
            upscaled = cv2.addWeighted(
                upscaled,
                1.0 - blend_factor,
                original_resized,
                blend_factor,
                0
            )

        return upscaled

    def _upscale_simple(self, image: np.ndarray) -> np.ndarray:
        """Upscale image without tiling."""
        # Convert BGR to RGB
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # Normalize to [0, 1]
        normalized = rgb.astype(np.float32) / 255.0

        # Add batch dimension and transpose to NCHW
        input_tensor = np.transpose(normalized, (2, 0, 1))[np.newaxis, ...]

        # Run inference
        output = self.session.run(None, {self.session.get_inputs()[0].name: input_tensor})[0]

        # Remove batch dimension and transpose back to HWC
        output = np.transpose(output[0], (1, 2, 0))

        # Denormalize and clip
        output = np.clip(output * 255.0, 0, 255).astype(np.uint8)

        # Convert RGB back to BGR
        bgr = cv2.cvtColor(output, cv2.COLOR_RGB2BGR)

        return bgr

    def _upscale_with_tiling(
        self,
        image: np.ndarray,
        tile_size: int,
        overlap: int = 16
    ) -> np.ndarray:
        """
        Upscale large image using tile-based approach.

        Args:
            image: Input image
            tile_size: Size of each tile
            overlap: Overlap between tiles to avoid seams

        Returns:
            Upscaled image
        """
        h, w = image.shape[:2]
        output_h = h * self.scale_factor
        output_w = w * self.scale_factor

        # Create output image
        output = np.zeros((output_h, output_w, 3), dtype=np.uint8)

        # Calculate tile positions
        stride = tile_size - overlap
        y_positions = list(range(0, h, stride))
        x_positions = list(range(0, w, stride))

        # Ensure we cover the entire image
        if y_positions[-1] + tile_size < h:
            y_positions.append(h - tile_size)
        if x_positions[-1] + tile_size < w:
            x_positions.append(w - tile_size)

        # Process each tile
        for y in y_positions:
            for x in x_positions:
                # Extract tile with boundary checks
                y_end = min(y + tile_size, h)
                x_end = min(x + tile_size, w)
                tile = image[y:y_end, x:x_end]

                # Upscale tile
                upscaled_tile = self._upscale_simple(tile)

                # Place in output (with proper overlap handling)
                out_y = y * self.scale_factor
                out_x = x * self.scale_factor
                out_y_end = out_y + upscaled_tile.shape[0]
                out_x_end = out_x + upscaled_tile.shape[1]

                # Simple placement (could be improved with blending)
                output[out_y:out_y_end, out_x:out_x_end] = upscaled_tile

        return output

    def close(self):
        """Release resources."""
        if self.session is not None:
            del self.session
            self.session = None


def upscale_image_file(
    input_path: str,
    output_path: str,
    model_name: str = 'RealESR_Gx4',
    denoise: bool = False,
    blend_factor: float = 0.0,
    progress_callback=None,
) -> Tuple[int, int]:
    """
    Upscale an image file.

    Args:
        input_path: Path to input image
        output_path: Path to save output image
        model_name: AI model to use
        denoise: Apply denoising before upscaling
        blend_factor: Blend factor with original
        progress_callback: Optional callback(progress_percent)

    Returns:
        Tuple of (output_width, output_height)
    """
    if progress_callback:
        progress_callback(10)

    # Read input image
    image = cv2.imread(input_path)
    if image is None:
        raise ValueError(f"Could not read image: {input_path}")

    if progress_callback:
        progress_callback(20)

    # Apply denoising if requested
    if denoise:
        logger.info("Applying denoising")
        denoiser = AIUpscaler(model_name='IRCNN_Mx1')
        image = denoiser.upscale_image(image)
        denoiser.close()

    if progress_callback:
        progress_callback(40)

    # Upscale
    logger.info(f"Upscaling with {model_name}")
    upscaler = AIUpscaler(model_name=model_name)
    upscaled = upscaler.upscale_image(image, blend_factor=blend_factor)
    upscaler.close()

    if progress_callback:
        progress_callback(80)

    # Save output
    cv2.imwrite(output_path, upscaled)

    if progress_callback:
        progress_callback(100)

    return upscaled.shape[1], upscaled.shape[0]  # width, height

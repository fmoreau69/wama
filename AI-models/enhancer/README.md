# Enhancer ONNX Models - Installation Guide

## Overview

This directory contains ONNX models for AI-powered image and video upscaling in WAMA Enhancer.
All AI models for WAMA are centralized in the `AI-models/` directory at project root.

```
AI-models/enhancer/onnx/
├── RealESR_Gx4_fp16.onnx          (~2.4 MB)  - General purpose 4x upscaler (Recommended)
├── RealESR_Animex4_fp16.onnx      (~1.2 MB)  - Anime/Manga 4x upscaler
├── BSRGANx2_fp16.onnx             (~33 MB)   - High quality 2x upscaler
├── BSRGANx4_fp16.onnx             (~33 MB)   - High quality 4x upscaler
├── RealESRGANx4_fp16.onnx         (~33 MB)   - Highest quality 4x upscaler
├── IRCNN_Mx1_fp16.onnx            (~372 KB)  - Medium denoising (no upscaling)
└── IRCNN_Lx1_fp16.onnx            (~372 KB)  - Strong denoising (no upscaling)
```

**Total Size**: ~101 MB (all models)

## Quick Download

### Method 1: Automatic Download (Python Script)

```bash
# From project root
python wama/enhancer/management/commands/download_enhancer_models.py --all
```

### Method 2: Manual Download

1. **Download from QualityScaler Releases**:
   - Visit: https://github.com/Djdefrag/QualityScaler/releases
   - Download latest release
   - Extract the `AI-onnx` folder

2. **Copy to WAMA**:
   ```bash
   cp /path/to/QualityScaler/AI-onnx/*.onnx AI-models/enhancer/onnx/
   ```

### Method 3: Download from Hugging Face

```bash
cd AI-models/enhancer/onnx/
wget https://huggingface.co/svjack/AI-onnx/resolve/main/RealESR_Gx4_fp16.onnx
wget https://huggingface.co/svjack/AI-onnx/resolve/main/RealESR_Animex4_fp16.onnx
# ... etc
```

## Model Details

### Upscaling Models

#### RealESR_Gx4 (Recommended for beginners)
- **Scale**: 4x
- **Size**: ~2.4 MB
- **VRAM**: ~2.5 GB
- **Speed**: ⚡⚡⚡ Fast
- **Quality**: ⭐⭐⭐ Good
- **Use Case**: General purpose photos, fast processing

#### RealESR_Animex4
- **Scale**: 4x
- **Size**: ~1.2 MB
- **VRAM**: ~2.5 GB
- **Speed**: ⚡⚡⚡ Fast
- **Quality**: ⭐⭐⭐ Good
- **Use Case**: Anime, manga, illustrations

#### BSRGANx2
- **Scale**: 2x
- **Size**: ~33 MB
- **VRAM**: ~0.75 GB
- **Speed**: ⚡⚡ Medium
- **Quality**: ⭐⭐⭐⭐ Very Good
- **Use Case**: High quality 2x upscaling

#### BSRGANx4
- **Scale**: 4x
- **Size**: ~33 MB
- **VRAM**: ~0.75 GB
- **Speed**: ⚡⚡ Medium
- **Quality**: ⭐⭐⭐⭐ Very Good
- **Use Case**: High quality 4x upscaling

#### RealESRGANx4 (Best quality)
- **Scale**: 4x
- **Size**: ~33 MB
- **VRAM**: ~2.5 GB
- **Speed**: ⚡ Slow
- **Quality**: ⭐⭐⭐⭐⭐ Excellent
- **Use Case**: Maximum quality, production work

### Denoising Models

#### IRCNN_Mx1 (Medium)
- **Scale**: 1x (no upscaling)
- **Size**: ~372 KB
- **VRAM**: ~4 GB
- **Speed**: ⚡⚡ Medium
- **Use Case**: Medium noise reduction

#### IRCNN_Lx1 (Strong)
- **Scale**: 1x (no upscaling)
- **Size**: ~372 KB
- **VRAM**: ~4 GB
- **Speed**: ⚡ Slow
- **Use Case**: Strong noise reduction for very noisy images

## Usage Recommendations

### For Beginners
Start with **RealESR_Gx4**:
- Lightweight (~2.4 MB)
- Fast processing
- Good quality
- Works well on most images

### For Anime/Manga
Use **RealESR_Animex4**:
- Optimized for anime art style
- Preserves line art
- Reduces artifacts

### For Maximum Quality
Use **RealESRGANx4**:
- Best quality results
- Slower processing
- Requires more VRAM
- Best for final production

### For Noisy Images
Combine upscaling + denoising:
1. Apply **IRCNN_Mx1** or **IRCNN_Lx1** first
2. Then apply upscaling model

## Technical Requirements

### GPU (Required)
- **Windows**: DirectML-compatible GPU
- **Linux**: CUDA-compatible GPU (NVIDIA)
- **Minimum VRAM**: 2 GB
- **Recommended VRAM**: 4+ GB

### Software Dependencies
```bash
# Windows
pip install onnxruntime-directml

# Linux with CUDA
pip install onnxruntime-gpu

# CPU only (slow)
pip install onnxruntime
```

### System Requirements
- **RAM**: 8 GB minimum, 16 GB recommended
- **Disk Space**: 200 MB for all models
- **OS**: Windows 10+, Linux (Ubuntu 20.04+), macOS

## Performance Benchmarks

### Image Upscaling (GPU: GTX 1660 Ti)

| Input Size | Model | Time | Output Size |
|------------|-------|------|-------------|
| 512×512 | RealESR_Gx4 | ~2s | 2048×2048 |
| 1920×1080 | RealESR_Gx4 | ~8s | 7680×4320 (8K) |
| 1920×1080 | RealESRGANx4 | ~15s | 7680×4320 (8K) |
| 4096×4096 | BSRGANx2 | ~25s | 8192×8192 |

### Video Upscaling

| Video | Frames | Model | Estimated Time |
|-------|--------|-------|----------------|
| 720p 30fps 10s | 300 | RealESR_Gx4 | ~5 min |
| 1080p 30fps 30s | 900 | BSRGANx2 | ~10 min |
| 1080p 60fps 60s | 3600 | RealESRGANx4 | ~2 hours |

*Times vary based on GPU performance*

## Troubleshooting

### Models Not Found
```
Error: Model file not found: RealESR_Gx4_fp16.onnx
```

**Solution**:
1. Check `AI-models/enhancer/onnx/` exists
2. Download models using methods above
3. Verify file permissions

### Out of Memory
```
CUDA out of memory / DML error
```

**Solution**:
1. Use lighter models (BSRGANx2/x4)
2. Process smaller images
3. Close other GPU applications
4. Reduce tile size in settings

### Slow Processing
**Solution**:
1. Verify GPU is being used (not CPU)
2. Use faster models (RealESR_Gx4)
3. Update GPU drivers
4. Check DirectML/CUDA installation

## Model Sources

- **QualityScaler**: https://github.com/Djdefrag/QualityScaler/releases
- **Hugging Face Mirror**: https://huggingface.co/svjack/AI-onnx
- **Original Research**:
  - Real-ESRGAN: https://github.com/xinntao/Real-ESRGAN
  - BSRGAN: https://github.com/cszn/BSRGAN

## Credits

- **Djdefrag** - QualityScaler project
- **Tencent ARC** - Real-ESRGAN
- **cszn** - BSRGAN, IRCNN
- **Microsoft** - ONNX Runtime, DirectML

## License

Models are provided by QualityScaler project (MIT License).
See original repositories for specific model licenses.

# WAMA AI Models - Centralized Repository

This directory contains all AI models used by WAMA applications, organized by domain for better management and reusability.

## Directory Structure

```
AI-models/models/
├── diffusion/                    # Image/Video generation models
│   ├── hunyuan/                  # Hunyuan Video models
│   ├── stable-diffusion/         # Stable Diffusion models (HuggingFace cache)
│   └── wan/                      # Wan AI video generation models
│
├── llm/                          # Large Language Models (future)
│
├── speech/                       # Speech/Audio models
│   ├── bark/                     # Bark TTS (~1.2GB)
│   ├── coqui/                    # Coqui XTTS v2 (~1.8GB)
│   └── whisper/                  # OpenAI Whisper STT
│
├── upscaling/                    # Image/Video upscaling
│   └── onnx/                     # ONNX upscaling models (~101MB)
│
├── vision/                       # Computer vision models
│   ├── sam/                      # Segment Anything Models (Meta)
│   │   └── sam3/                 # SAM3 (HuggingFace cache)
│   └── yolo/                     # YOLO models (Ultralytics)
│       ├── classify/             # Image classification
│       ├── detect/               # Object detection
│       │   ├── faces/            # Face detection
│       │   ├── faces&plates/     # Face + License plate detection
│       │   └── plates/           # License plate detection
│       ├── obb/                  # Oriented bounding box
│       ├── pose/                 # Pose estimation
│       └── segment/              # Instance segmentation
│
└── vision-language/              # Multimodal models
    ├── bart/                     # BART summarization (~1.6GB)
    ├── bert/                     # BERT multilingual
    └── blip/                     # BLIP image captioning (~1.8GB)
```

## Models by Application

### Describer (Image/Video/Audio Description)
| Model | Directory | Size | Description |
|-------|-----------|------|-------------|
| BLIP | `vision-language/blip/` | ~1.8GB | Image captioning |
| BART | `vision-language/bart/` | ~1.6GB | Text summarization |
| Whisper | `speech/whisper/` | ~0.3GB | Audio transcription |

### Enhancer (Upscaling)
| Model | File | Size | Description |
|-------|------|------|-------------|
| RealESR_Gx4 | `upscaling/onnx/RealESR_Gx4_fp16.onnx` | ~2.4MB | General 4x upscaling |
| RealESR_Animex4 | `upscaling/onnx/RealESR_Animex4_fp16.onnx` | ~1.2MB | Anime 4x upscaling |
| BSRGANx2 | `upscaling/onnx/BSRGANx2_fp16.onnx` | ~33MB | BSRGAN 2x |
| BSRGANx4 | `upscaling/onnx/BSRGANx4_fp16.onnx` | ~33MB | BSRGAN 4x |
| RealESRGANx4 | `upscaling/onnx/RealESRGANx4_fp16.onnx` | ~33MB | RealESRGAN 4x |
| IRCNN_Mx1 | `upscaling/onnx/IRCNN_Mx1_fp16.onnx` | ~372KB | Denoising (medium) |
| IRCNN_Lx1 | `upscaling/onnx/IRCNN_Lx1_fp16.onnx` | ~372KB | Denoising (light) |

### Synthesizer (Text-to-Speech)
| Model | Directory | Size | Description |
|-------|-----------|------|-------------|
| Coqui XTTS v2 | `speech/coqui/` | ~1.8GB | Multilingual TTS with voice cloning |
| Bark | `speech/bark/` | ~1.2GB | Expressive TTS with sound effects |

### Imager (Image/Video Generation)
| Model | Directory | Size | Description |
|-------|-----------|------|-------------|
| Stable Diffusion | `diffusion/stable-diffusion/` | Variable | Image generation |
| Wan AI T2V | `diffusion/wan/` | ~5-25GB | Text-to-video |
| Wan AI I2V | `diffusion/wan/` | ~25GB | Image-to-video |
| Hunyuan Video | `diffusion/hunyuan/` | ~25GB | High-quality video generation |
| Hunyuan Image | `diffusion/hunyuan/` | ~12GB | Image generation |

### Anonymizer (Privacy Protection)
| Model | Directory | Size | Description |
|-------|-----------|------|-------------|
| YOLO11 (n/s/m/l/x) | `vision/yolo/detect/` | ~5-115MB | Object detection |
| YOLO Face | `vision/yolo/detect/faces/` | Variable | Face detection |
| YOLO Plate | `vision/yolo/detect/plates/` | Variable | License plate detection |
| SAM3 | `vision/sam/sam3/` | ~3GB | Text-prompted segmentation |

---

## Installation Guide

### 1. ONNX Upscaling Models (Enhancer)

Download pre-trained ONNX models from:
- **GitHub**: [xinntao/Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)
- **Direct download**: See links below

```bash
# Download to upscaling/onnx/
cd AI-models/models/upscaling/onnx/

# RealESRGAN models
wget https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-x4plus.onnx -O RealESRGANx4_fp16.onnx

# Or use provided download script
python download_onnx_models.py
```

### 2. Coqui TTS Models (Synthesizer)

Models download automatically on first use, or manually:

```python
from TTS.api import TTS

# This downloads XTTS v2 to speech/coqui/
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
```

Set environment variable to use centralized directory:
```bash
export COQUI_TTS_HOME="AI-models/models/speech/coqui"
```

### 3. Bark TTS Models (Synthesizer)

Models download automatically on first use:

```python
from bark import SAMPLE_RATE, generate_audio, preload_models

# Set cache directory before import
os.environ["XDG_CACHE_HOME"] = "AI-models/models/speech/bark"
preload_models()
```

### 4. YOLO Models (Anonymizer)

Download from Ultralytics:

```python
from ultralytics import YOLO

# Download and save to vision/yolo/detect/
model = YOLO("yolo11n.pt")
model.save("AI-models/models/vision/yolo/detect/yolo11n.pt")
```

Available models:
- **Detection**: yolo11n, yolo11s, yolo11m, yolo11l, yolo11x
- **Segmentation**: yolo11n-seg, yolo11s-seg, etc.
- **Pose**: yolo11n-pose, yolo11s-pose, etc.
- **Classification**: yolo11n-cls, yolo11s-cls, etc.
- **OBB**: yolo11n-obb, yolo11s-obb, etc.

### 5. SAM3 Models (Anonymizer)

Requires HuggingFace authentication (gated model):

```bash
# Login to HuggingFace
huggingface-cli login

# Request access at https://huggingface.co/facebook/sam3
# Then models download automatically on first use
```

### 6. Stable Diffusion Models (Imager)

Models download automatically via HuggingFace Diffusers:

```python
from diffusers import StableDiffusionPipeline

# Downloads to diffusion/stable-diffusion/
pipe = StableDiffusionPipeline.from_pretrained(
    "dreamlike-art/dreamlike-diffusion-1.0",
    cache_dir="AI-models/models/diffusion/stable-diffusion"
)
```

### 7. Wan Video Models (Imager)

```python
# Set environment variable
os.environ["WAN_CACHE_DIR"] = "AI-models/models/diffusion/wan"

# Models download on first use
# Wan2.1-T2V-1.3B-Diffusers: ~5GB
# Wan2.2-I2V-A14B-Diffusers: ~25GB
```

### 8. BLIP/BART Models (Describer)

```python
from transformers import BlipProcessor, BlipForConditionalGeneration

# Downloads to vision-language/blip/
model = BlipForConditionalGeneration.from_pretrained(
    "Salesforce/blip-image-captioning-large",
    cache_dir="AI-models/models/vision-language/blip"
)
```

---

## Disk Space Summary

| Category | Total Size | Notes |
|----------|------------|-------|
| Vision-Language | ~4GB | BLIP + BART + BERT |
| Speech | ~3.5GB | Coqui + Bark + Whisper |
| Upscaling | ~101MB | All ONNX models |
| Vision (YOLO) | ~230MB | Base detection models |
| Vision (SAM3) | ~3GB | Segmentation model |
| Diffusion (SD) | ~4-8GB | Per model |
| Diffusion (Wan) | ~5-50GB | Depends on variants |
| Diffusion (Hunyuan) | ~25-40GB | Video/Image models |

**Minimum**: ~15GB (base models only)
**Full installation**: ~100GB+ (all models and variants)

---

## Configuration

### Django Settings (settings.py)

```python
MODEL_PATHS = {
    'vision': {
        'root': AI_MODELS_DIR / "models" / "vision",
        'yolo': AI_MODELS_DIR / "models" / "vision" / "yolo",
        'sam': AI_MODELS_DIR / "models" / "vision" / "sam",
    },
    'upscaling': {
        'root': AI_MODELS_DIR / "models" / "upscaling",
        'onnx': AI_MODELS_DIR / "models" / "upscaling" / "onnx",
    },
    'speech': {
        'root': AI_MODELS_DIR / "models" / "speech",
        'whisper': AI_MODELS_DIR / "models" / "speech" / "whisper",
        'coqui': AI_MODELS_DIR / "models" / "speech" / "coqui",
        'bark': AI_MODELS_DIR / "models" / "speech" / "bark",
    },
    'diffusion': {
        'root': AI_MODELS_DIR / "models" / "diffusion",
        'wan': AI_MODELS_DIR / "models" / "diffusion" / "wan",
        'hunyuan': AI_MODELS_DIR / "models" / "diffusion" / "hunyuan",
        'stable_diffusion': AI_MODELS_DIR / "models" / "diffusion" / "stable-diffusion",
    },
    'vision_language': {
        'root': AI_MODELS_DIR / "models" / "vision-language",
        'blip': AI_MODELS_DIR / "models" / "vision-language" / "blip",
        'bart': AI_MODELS_DIR / "models" / "vision-language" / "bart",
    },
}
```

---

## Git Strategy

Model files are **excluded from Git** by default (see `.gitignore`).

To include specific models in version control:
```bash
# Edit .gitignore to allow specific models
# Then commit
git add AI-models/models/upscaling/onnx/
git commit -m "Add ONNX upscaling models"
```

---

## Troubleshooting

### Models not loading
1. Check the model directory exists and contains files
2. Verify `cache_dir` parameter in `from_pretrained()` calls
3. Check HuggingFace authentication for gated models

### HuggingFace cache structure
Models from HuggingFace use this structure:
```
models--org--name/
├── blobs/       # Actual model weights
├── refs/        # Version references
└── snapshots/   # Model snapshots by commit hash
```

### Disk space issues
Use `du -sh AI-models/models/*` to check space usage per category.

---

## Support

For issues with specific models, consult:
- **YOLO**: [Ultralytics Docs](https://docs.ultralytics.com/)
- **SAM3**: [HuggingFace Model Card](https://huggingface.co/facebook/sam3)
- **Stable Diffusion**: [Diffusers Docs](https://huggingface.co/docs/diffusers/)
- **Coqui TTS**: [Coqui TTS Docs](https://tts.readthedocs.io/)
- **Bark**: [Bark GitHub](https://github.com/suno-ai/bark)

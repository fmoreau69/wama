# WAMA AI Models

This directory contains all AI models used by WAMA applications, centralized for better organization and management.

## Directory Structure

```
AI-models/
├── README.md           # This file
├── .gitignore          # Excludes model files from Git
├── manager.py          # Model management utilities
├── registry.json       # Model registry
│
├── models/             # All AI models (see models/README.md for details)
│   ├── diffusion/      # Image/Video generation (SD, Wan, Hunyuan)
│   ├── llm/            # Large Language Models
│   ├── speech/         # TTS/STT (Bark, Coqui, Whisper)
│   ├── upscaling/      # ONNX upscaling models
│   ├── vision/         # YOLO, SAM (detection, segmentation)
│   └── vision-language/# BLIP, BART, BERT
│
├── external/           # External model sources/configs
└── sources/            # Model source definitions
```

## Quick Start

See **[models/README.md](models/README.md)** for:
- Complete directory structure
- Model download instructions
- Disk space requirements
- Configuration guide

## Why Centralize AI Models?

1. **Domain Organization**: Models grouped by function (vision, speech, diffusion)
2. **Reusability**: Same model can be used by multiple applications
3. **Easy Backup**: All models in one place
4. **Visibility**: Clear overview of all AI models used
5. **Maintainability**: Single location for model downloads and updates

## Git Strategy

Model files are **excluded from Git** by default (see `.gitignore`).
This keeps the repository lightweight. Models are downloaded on first use.

## Total Disk Usage (Approximate)

| Category | Size |
|----------|------|
| Vision-Language (BLIP, BART, BERT) | ~4GB |
| Speech (Coqui, Bark, Whisper) | ~3.5GB |
| Upscaling (ONNX) | ~101MB |
| Vision (YOLO, SAM3) | ~3.2GB |
| Diffusion (varies) | ~10-100GB |

**Minimum**: ~15GB (base models)
**Full installation**: ~100GB+ (all variants)

## Support

For detailed model documentation and troubleshooting, see [models/README.md](models/README.md).

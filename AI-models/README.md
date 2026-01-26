# WAMA AI Models

This directory contains all AI models used by WAMA applications, centralized for better organization and management.

## Directory Structure

```
AI-models/
├── README.md (this file)
├── .gitignore
│
├── synthesizer/
│   ├── DOWNLOAD_MODELS.md
│   ├── tts/
│   │   └── tts_models/
│   │       └── multilingual/
│   │           └── multi-dataset/
│   │               └── xtts_v2/ (~1.8GB)
│   └── bark/
│       ├── README.md
│       └── [models auto-downloaded] (~1.2GB)
│
├── enhancer/
│   ├── README.md
│   └── onnx/
│       ├── RealESR_Gx4_fp16.onnx (~2.4MB)
│       ├── RealESR_Animex4_fp16.onnx (~1.2MB)
│       ├── BSRGANx2_fp16.onnx (~33MB)
│       ├── BSRGANx4_fp16.onnx (~33MB)
│       ├── RealESRGANx4_fp16.onnx (~33MB)
│       ├── IRCNN_Mx1_fp16.onnx (~372KB)
│       └── IRCNN_Lx1_fp16.onnx (~372KB)
│
├── imager/
│   ├── README.md
│   └── wan/
│       └── models--Wan-AI--*/  (auto-downloaded)
│           ├── Wan2.1-T2V-1.3B-Diffusers (~5GB)
│           └── Wan2.2-I2V-A14B-Diffusers (~25GB)
│
└── anonymizer/ (planned migration)
    └── yolo/
        ├── yolov8n.pt
        ├── yolov8s.pt
        └── ...
```

## Why Centralize AI Models?

1. **Separation of Concerns**: Code, models, and media are clearly separated
2. **Easy Backup**: All models in one place, easy to backup or exclude from Git
3. **Visibility**: Clear overview of all AI models used by WAMA
4. **Maintainability**: Single location for model downloads and updates
5. **Consistency**: Same structure pattern across all WAMA applications

## Model Downloads

Each subdirectory contains its own documentation with specific instructions:

- **Synthesizer TTS (Coqui)**: `synthesizer/DOWNLOAD_MODELS.md`
- **Synthesizer Bark**: `synthesizer/bark/README.md`
- **Enhancer ONNX**: `enhancer/README.md`
- **Imager Wan Video**: `imager/README.md`
- **Anonymizer YOLO**: (coming soon)

## Git Strategy

By default, model files are **excluded from Git** (see `.gitignore`).
This keeps the repository lightweight. Users download models separately using provided scripts.

### Option 1: Exclude from Git (Default)
```bash
# Models are downloaded locally by each user
python download_tts_models.py
```

### Option 2: Include in Git (Alternative)
If you want to commit models to Git (e.g., for private deployments):
```bash
# Remove specific patterns from .gitignore
# Then commit the models
git add AI-models/synthesizer/tts/
git commit -m "Add TTS models for offline deployment"
```

## Migration Status

- ✅ **Synthesizer TTS (Coqui)**: Migrated to `AI-models/synthesizer/tts/`
- ✅ **Synthesizer Bark**: Migrated to `AI-models/synthesizer/bark/`
- ✅ **Enhancer ONNX**: Migrated to `AI-models/enhancer/onnx/`
- ✅ **Imager Wan Video**: Configured in `AI-models/imager/wan/`
- ⏳ **Anonymizer YOLO**: Still in `wama/anonymizer/AI-yolo/` (future migration)

## Total Disk Usage

Current model sizes (approximate):

- Synthesizer TTS (xtts_v2): ~1.8GB
- Synthesizer Bark: ~1.2GB
- Enhancer ONNX (all 7 models): ~101MB
- Imager Wan TI2V 5B: ~16GB
- Imager Wan T2V 14B: ~25GB (optional, high-end GPU required)
- Imager Wan I2V 14B: ~25GB (optional, high-end GPU required)
- Anonymizer YOLO (all models): ~TBD

**Estimated Total**: ~8.1GB (without I2V) / ~33GB (with all models)

## Updating Models

To update to newer model versions:

1. Delete old model files in the respective subdirectory
2. Run the download script again:
   ```bash
   python download_tts_models.py
   ```

## Support

For issues with specific models, see the respective `DOWNLOAD_MODELS.md` in each subdirectory.

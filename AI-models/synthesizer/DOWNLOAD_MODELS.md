# TTS Models - Installation Guide

## Overview

This directory stores TTS (Text-to-Speech) models locally to avoid slow downloads during runtime.
All AI models for WAMA are now centralized in the `AI-models/` directory at project root.

```
AI-models/
└── synthesizer/
    └── tts/
        └── tts_models/
            └── multilingual/
                └── multi-dataset/
                    └── xtts_v2/
                        ├── config.json
                        ├── model.pth
                        ├── vocab.json
                        └── ...
```

## Quick Download

Run the download script from the project root:

```bash
python download_tts_models.py
```

This will download the default model (xtts_v2) to `AI-models/synthesizer/tts/`.

## Manual Download (Alternative)

If the script doesn't work, you can manually download models using the TTS library:

```bash
# Activate virtual environment
source venv_linux/bin/activate  # On Linux/WSL
# or
venv\Scripts\activate  # On Windows

# Set environment variables
export COQUI_TOS_AGREED=1
export TTS_HOME=/path/to/AI-models/synthesizer/tts

# Download model using TTS CLI
tts --model_name tts_models/multilingual/multi-dataset/xtts_v2 --text "test" --out_path test.wav

# Clean up test file
rm test.wav
```

## Directory Structure

After downloading, the structure should look like:

```
AI-models/synthesizer/tts/
└── tts/
    └── tts_models--multilingual--multi-dataset--xtts_v2/
        ├── config.json
        ├── model.pth (~1.8GB)
        ├── speakers_xtts.pth (~7.4MB)
        ├── vocab.json (~353KB)
        └── hash.md5
```

## Available Models

### Default: XTTS v2
- **Name**: `tts_models/multilingual/multi-dataset/xtts_v2`
- **Size**: ~1.8GB
- **Features**: Multilingual, voice cloning support
- **Languages**: English, French, Spanish, German, Italian, Portuguese, Polish, Turkish, Russian, Dutch, Czech, Arabic, Chinese, Japanese, Korean, Hungarian

### Alternative Models (Optional)

You can also download these models if needed:

- `tts_models/en/vctk/vits` - Fast English TTS
- `tts_models/en/ljspeech/tacotron2-DDC` - Classic Tacotron2

## Troubleshooting

### Slow downloads on WSL
If downloads are slow from WSL, download from Windows and copy to WSL:

```powershell
# On Windows PowerShell
python download_tts_models.py

# Then copy to WSL (from WSL terminal)
cp -r /mnt/d/path/to/AI-models/synthesizer/tts/* /path/to/wsl/AI-models/synthesizer/tts/
```

### Permission issues
```bash
chmod -R 755 AI-models/synthesizer/tts
```

## Testing

After downloading, test the models by starting a Synthesizer preview in the web interface.
The models should load without any download delay.

## Centralized AI Models

WAMA uses a centralized `AI-models/` directory to store all AI models:

- **Anonymizer**: `AI-models/anonymizer/yolo/` (planned migration)
- **Enhancer**: `AI-models/enhancer/onnx/` (planned migration)
- **Synthesizer**: `AI-models/synthesizer/tts/` ✅ (current)

This centralization:
- Separates code, models, and media
- Simplifies backups and .gitignore management
- Provides clear visibility of all AI models used by WAMA

## References

- TTS Library: https://github.com/coqui-ai/TTS
- Model Zoo: https://github.com/coqui-ai/TTS#model-zoo

# Face Analyzer - Installation Guide

## Dependencies

Face Analyzer requires several Python packages for computer vision and machine learning.

### Quick Install

```bash
cd wama_lab/face_analyzer
pip install -r requirements.txt
```

### Manual Install

```bash
# Core packages
pip install opencv-python>=4.8.0
pip install numpy>=1.24.0
pip install scipy>=1.11.0

# Face detection (MediaPipe)
pip install mediapipe>=0.10.0

# Emotion recognition (choose one or both)
pip install fer>=22.5.0        # Lightweight, fast
pip install deepface>=0.0.79   # Full analysis (emotions + age + gender)
# Note: Both use TensorFlow (~500MB-1GB)
```

## Emotion Recognition Backends

Face Analyzer supports two backends for emotion recognition:

### FER (Facial Expression Recognition)
- **Pros**: Fast, lightweight
- **Cons**: Emotions only (no age/gender)
- **Best for**: Real-time analysis with limited resources

### DeepFace (Recommended)
- **Pros**: More accurate emotions + age estimation + gender detection
- **Cons**: Slower, requires more memory
- **Best for**: Comprehensive facial analysis

You can switch between backends in the interface:
- **Backend émotions**: FER (rapide) / DeepFace (complet)
- **Âge & Genre**: Enable/disable age and gender detection (DeepFace only)

## Verification

Test the installation:

```bash
cd /path/to/wama
python -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django
django.setup()

from wama_lab.face_analyzer.pipeline import FaceAnalysisPipeline
print('Face Analyzer imports OK')

import mediapipe
print(f'MediaPipe version: {mediapipe.__version__}')

import cv2
print(f'OpenCV version: {cv2.__version__}')

# Check FER
try:
    from fer import FER
    print('FER backend: OK')
except ImportError:
    print('FER backend: NOT INSTALLED')

# Check DeepFace
try:
    from deepface import DeepFace
    print('DeepFace backend: OK (age + gender enabled)')
except ImportError:
    print('DeepFace backend: NOT INSTALLED')
"
```

## Django Migrations

Run migrations after installation:

```bash
python manage.py makemigrations face_analyzer
python manage.py migrate face_analyzer
```

## Logging

Face Analyzer logs are output to the console with the following format:
```
[2024-01-15 10:30:45] [wama_lab.face_analyzer.views] [INFO] Face Analyzer index accessed by user: admin
```

Log levels:
- DEBUG: Detailed processing information (frame processing times, etc.)
- INFO: General operations (session creation, video processing start/end)
- WARNING: Non-critical issues (no face detected, etc.)
- ERROR: Critical errors with stack traces

To change the log level in Django settings:

```python
LOGGING = {
    'version': 1,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'wama_lab.face_analyzer': {
            'handlers': ['console'],
            'level': 'DEBUG',  # Change to 'INFO' for less verbose output
        },
    },
}
```

## Troubleshooting

### MediaPipe Issues

If MediaPipe fails to initialize:
```bash
# Reinstall with specific version
pip uninstall mediapipe
pip install mediapipe==0.10.9
```

### TensorFlow/CUDA Issues

FER uses TensorFlow. If you encounter CUDA errors:
```bash
# Use CPU-only TensorFlow
pip uninstall tensorflow
pip install tensorflow-cpu
```

### Memory Issues

For low-memory systems, disable emotion recognition (most memory-intensive):
- Uncheck "Emotions" in the analysis options before starting

## Access

Once installed, access Face Analyzer at:
- URL: `http://your-server/lab/face-analyzer/`
- Navigation: Applications menu > WAMA Lab > Face Analyzer

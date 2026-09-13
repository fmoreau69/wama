# Anonymizer Module Refactoring

## Overview
The anonymizer module has been refactored to improve code organization and maintainability by extracting utility functions into separate modules.

## New Structure

```
anonymizer/
├── __init__.py
├── anonymize.py          # Main Anonymize class
├── bounds.py             # Bounds utility class
├── blur_utils.py         # Blurring functions
├── ffmpeg_utils.py       # FFmpeg-related utilities
└── media_utils.py        # Media file utilities
```

## Module Descriptions

### `anonymize.py`
Main module containing the `Anonymize` class that orchestrates the anonymization process.

**Key Responsibilities:**
- Model loading and configuration
- Image and video processing orchestration
- Results handling

### `blur_utils.py`
Utilities for applying blur effects to detected objects.

**Functions:**
- `blur_detection()`: Apply blur to a single detection
- `apply_progressive_blur()`: Apply elliptical gradient blur
- `apply_simple_blur()`: Apply simple Gaussian blur
- `normalize_blur_ratio()`: Ensure blur ratio is valid (positive and odd)

### `ffmpeg_utils.py`
FFmpeg integration utilities for audio/video processing.

**Functions:**
- `get_ffmpeg_path()`: Locate FFmpeg executable on the system
- `adapt_path_for_ffmpeg()`: Convert paths for FFmpeg (handles WSL paths)
- `copy_audio_to_video()`: Merge audio from original video to processed video
- `is_wsl()`: Detect if running in WSL environment

### `media_utils.py`
General media file utilities.

**Functions:**
- `is_image()`: Check if a file is an image based on MIME type

### `bounds.py`
Utility class for handling bounding box operations (unchanged).

## Usage

### From Django app (`wama/anonymizer/`)
```python
from anonymizer import anonymize

model = anonymize.Anonymize()
model.load_model(**kwargs)
model.process(**kwargs)
```

### Direct usage of utilities
```python
from anonymizer.blur_utils import normalize_blur_ratio, blur_detection
from anonymizer.media_utils import is_image
from anonymizer.ffmpeg_utils import get_ffmpeg_path

# Example usage
blur_ratio = normalize_blur_ratio(20)  # Returns 21 (next odd number)
is_img = is_image('file.jpg')  # Returns True
ffmpeg = get_ffmpeg_path()  # Returns path to ffmpeg executable
```

## Benefits of Refactoring

1. **Modularity**: Functions are organized by their purpose
2. **Reusability**: Utility functions can be easily imported and reused
3. **Maintainability**: Easier to locate and modify specific functionality
4. **Testability**: Individual modules can be tested independently
5. **Clarity**: Main `Anonymize` class is cleaner and more focused

## Backward Compatibility

The refactoring maintains full backward compatibility:
- The main `Anonymize` class interface remains unchanged
- All existing imports from `wama/anonymizer/tasks.py` continue to work
- No changes required to the Django integration

## Testing

All functionality has been verified:
- ✅ Python syntax validation for all modules
- ✅ Import tests from Django app
- ✅ Basic functionality tests (blur normalization, image detection, ffmpeg path)
- ✅ Django app check passes

# Model Organization Changes

## Summary

The YOLO models directory has been reorganized to categorize models by type (detect, segment, classify, pose, obb). This improves model selection in the UI with grouped dropdowns and makes the model directory more maintainable.

## What Changed

### Before
```
anonymizer/models/
├── yolov8n.pt
├── yolov8n-seg.pt
├── yolov8m_faces&plates_720p.pt
├── ... (all models in flat structure)
```

### After
```
anonymizer/models/
├── detect/              # Detection models
│   ├── yolov8n.pt
│   ├── yolov8m_faces&plates_720p.pt
│   └── ... (11 models)
├── segment/             # Segmentation models
│   └── yolov8n-seg.pt
├── classify/            # (empty, ready for future models)
├── pose/                # (empty, ready for future models)
├── obb/                 # (empty, ready for future models)
└── *.pt                 # Legacy models (kept for backward compatibility)
```

## User Interface Changes

### Model Selection Dropdown (UserSettings)

The model selection dropdown in Global Settings now shows models grouped by type:

**Before:**
- Flat list of all models

**After:**
- **Detection** (11 models)
  - yolov8n.pt
  - yolov8m_faces&plates_720p.pt
  - ...
- **Segmentation** (1 model)
  - yolov8n-seg.pt
- **Legacy (Root Directory)** (12 models)
  - *(backward compatibility)*

## Backward Compatibility

✅ **Fully backward compatible** - No breaking changes!

1. **Existing model references continue to work**
   - `model_to_use = 'yolov8n.pt'` still works
   - System searches both root and subdirectories

2. **Legacy models preserved**
   - All models copied (not moved) to subdirectories
   - Original files remain in root for compatibility

3. **Path resolution enhanced**
   - `get_model_path('yolov8n.pt')` finds model in root OR subdirectories
   - `get_model_path('detect/yolov8n.pt')` uses explicit categorized path

## Code Changes

### Updated Files

1. **`wama/anonymizer/utils/yolo_utils.py`**
   - Added `MODEL_TYPES` constant
   - Enhanced `get_model_path()` to search subdirectories
   - Added `list_models_by_type()` function
   - Added `get_model_choices_grouped()` for Django forms

2. **`wama/anonymizer/forms.py`**
   - Updated `UserSettingsForm` to use grouped choices
   - Updated `UserSettingsEdit` to use grouped choices
   - Added model_to_use field to forms

### New Files

1. **`anonymizer/models/README.md`** - Documentation
2. **`anonymizer/models/CHANGES.md`** - This file
3. **`anonymizer/models/migrate_models.py`** - Migration script

## Testing Results

✅ All tests passed:

1. **Path resolution tests**
   - Root models found correctly
   - Categorized models found correctly
   - Auto-detection works across subdirectories

2. **Django integration tests**
   - Forms load correctly with grouped choices
   - Model selection dropdown displays properly
   - No breaking changes in existing code

3. **Backward compatibility tests**
   - Old model references still work
   - `get_model_path()` finds models in both locations
   - Existing UserSettings records remain valid

## Migration Status

**Current State:** Models are COPIED to subdirectories (duplicated)

**Benefits:**
- Zero downtime
- No breaking changes
- Can roll back easily

**Optional Next Step:**
To remove duplicates from root directory (after verification):
```bash
cd anonymizer/models
python migrate_models.py --cleanup
```

⚠️ **Warning:** Only run cleanup after confirming all systems work with new structure!

## API Changes

### New Functions

```python
# List all models organized by type
from wama.anonymizer.utils.yolo_utils import list_models_by_type
models = list_models_by_type()
# {'detect': ['yolov8n.pt', ...], 'segment': ['yolov8n-seg.pt']}

# Get grouped choices for forms
from wama.anonymizer.utils.yolo_utils import get_model_choices_grouped
choices = get_model_choices_grouped()
# [('Detection', [('detect/yolov8n.pt', 'yolov8n.pt'), ...]), ...]
```

### Enhanced Functions

```python
# get_model_path() now searches subdirectories
from wama.anonymizer.utils.yolo_utils import get_model_path

# All these work:
path1 = get_model_path('yolov8n.pt')              # Finds in root
path2 = get_model_path('detect/yolov8n.pt')      # Explicit path
path3 = get_model_path('yolov8n-seg.pt')         # Auto-finds in segment/
```

## Benefits

1. **Better Organization**
   - Models grouped by task type
   - Easier to find specific models
   - Clear purpose for each directory

2. **Improved UI**
   - Grouped dropdown in settings
   - Easier model selection
   - Clear model categorization

3. **Maintainability**
   - Easy to add new models to correct category
   - Clear structure for future expansion
   - Better documentation

4. **Scalability**
   - Ready for new model types (classify, pose, obb)
   - Clean separation of concerns
   - Room for growth

## Rollback Procedure

If needed, rollback is simple since original files are preserved:

1. Revert code changes in `yolo_utils.py` and `forms.py`
2. Original models still in root directory
3. No database changes required

---

**Date:** 2025-12-06
**Status:** ✅ Complete and tested
**Breaking Changes:** None

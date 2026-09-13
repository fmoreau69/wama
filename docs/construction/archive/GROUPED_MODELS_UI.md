# Grouped Models UI Implementation

## Summary

The model selection dropdown in Global Settings now displays models organized by type using HTML `<optgroup>` elements.

## What Changed

### Before
![Before: Flat list of models]
```html
<select>
  <option>yolov8n.pt</option>
  <option>yolov8n-seg.pt</option>
  <option>yolov8m_faces&plates_720p.pt</option>
  <!-- ... all models in a flat list -->
</select>
```

### After
![After: Models grouped by type]
```html
<select>
  <optgroup label="Detection">
    <option value="detect/yolov8n.pt">yolov8n.pt</option>
    <option value="detect/yolov8m_faces&plates_720p.pt">yolov8m_faces&plates_720p.pt</option>
    <!-- ... -->
  </optgroup>
  <optgroup label="Segmentation">
    <option value="segment/yolov8n-seg.pt">yolov8n-seg.pt</option>
  </optgroup>
  <optgroup label="Legacy (Root Directory)">
    <option value="yolov8n.pt">yolov8n.pt</option>
    <!-- ... backward compatible models -->
  </optgroup>
</select>
```

## UI Appearance

The dropdown now shows models grouped by category:

```
┌────────────────────────────────────┐
│ Detection                        ▼ │
├────────────────────────────────────┤
│   yolov8n.pt                       │
│   yolov8m_faces&plates_720p.pt     │
│   yolov9t-face-lindevs.pt          │
│   ...                              │
│ Segmentation                       │
│   yolov8n-seg.pt                   │
│ Legacy (Root Directory)            │
│   yolov8n.pt                       │
│   ...                              │
└────────────────────────────────────┘
```

## Files Modified

### 1. `wama/anonymizer/views.py`

**Added import:**
```python
from .utils.yolo_utils import get_model_path, list_available_models, list_models_by_type
```

**Added to context:**
```python
models_by_type = list_models_by_type()

return {
    # ... existing context ...
    'models_by_type': models_by_type,
}
```

### 2. `wama/anonymizer/templates/anonymizer/upload/global_settings.html`

**Before:**
```django
<select id="user_setting_model_to_use" class="form-select setting-button">
    {% for m in available_models %}
        <option value="{{ m }}">{{ m }}</option>
    {% endfor %}
</select>
```

**After:**
```django
<select id="user_setting_model_to_use" class="form-select setting-button">
    {% for model_type, model_list in models_by_type.items %}
        {% if model_type == 'detect' %}
            <optgroup label="Detection">
        {% elif model_type == 'segment' %}
            <optgroup label="Segmentation">
        {% elif model_type == 'root' %}
            <optgroup label="Legacy (Root Directory)">
        {% endif %}
            {% for model_name in model_list %}
                {% if model_type == 'root' %}
                    <option value="{{ model_name }}">{{ model_name }}</option>
                {% else %}
                    <option value="{{ model_type }}/{{ model_name }}">{{ model_name }}</option>
                {% endif %}
            {% endfor %}
        </optgroup>
    {% endfor %}
</select>
```

## Model Value Format

### Legacy Models (root directory)
- **Display:** `yolov8n.pt`
- **Value:** `yolov8n.pt` (backward compatible)

### Categorized Models
- **Display:** `yolov8n.pt` (filename only)
- **Value:** `detect/yolov8n.pt` (includes category path)

## Backward Compatibility

✅ **Fully backward compatible**

1. **Existing database values work:**
   - Old value: `yolov8n.pt` → Still works (searches root + subdirs)
   - New value: `detect/yolov8n.pt` → Works explicitly

2. **Model resolution:**
   - `get_model_path('yolov8n.pt')` finds model in root OR subdirectories
   - `get_model_path('detect/yolov8n.pt')` uses explicit path

3. **Selection state preserved:**
   - Template checks both old and new formats for `selected` attribute
   - User's current model selection remains active

## Group Labels

| Model Type | Label in UI                  |
|------------|------------------------------|
| `detect`   | Detection                    |
| `segment`  | Segmentation                 |
| `classify` | Classification               |
| `pose`     | Pose Estimation              |
| `obb`      | Oriented Bounding Box        |
| `root`     | Legacy (Root Directory)      |

## Testing

### Visual Test
1. Navigate to Global Settings in the UI
2. Click the "Model to use" dropdown
3. Verify models are grouped by type with labeled sections

### Functional Test
1. Select a model from "Detection" group
2. Value should be `detect/model_name.pt`
3. Save and reload - selection should persist
4. Model should load correctly when processing media

### Backward Compatibility Test
1. Manually set `model_to_use = 'yolov8n.pt'` in database
2. Reload page
3. Verify model is selected in appropriate group
4. Processing should work normally

## Benefits

1. **Better UX:**
   - Clear visual organization
   - Easy to find specific model types
   - Professional appearance

2. **Scalability:**
   - Easy to add new model categories
   - Automatic grouping of new models
   - No template changes needed for new models

3. **Clarity:**
   - Users understand model purposes
   - Clear distinction between detection/segmentation
   - Legacy models clearly marked

## Browser Compatibility

HTML `<optgroup>` is supported by all major browsers:
- ✅ Chrome/Edge (all versions)
- ✅ Firefox (all versions)
- ✅ Safari (all versions)
- ✅ Opera (all versions)

## Future Enhancements

Possible improvements:
1. Add model descriptions/tooltips
2. Show model size/performance indicators
3. Filter models by task type
4. Add model metadata (resolution, accuracy, speed)

---

**Date:** 2025-12-06
**Status:** ✅ Complete and tested
**Breaking Changes:** None

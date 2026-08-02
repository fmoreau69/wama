"""
Forms LEGACY de l'anonymizer — en sursis (palier 2 du port : modales `WamaParams`
rendues depuis le schéma, ces ModelForms disparaîtront avec elles).

D'ici là, UNE règle : plus aucune borne recopiée. Les min/max/step des sliders sont
DÉRIVÉS de `params.py` (schema_for_app) — les copies locales avaient déjà divergé
(blur_ratio 1–49/2 ici contre 1–100/1 au schéma, roi_enlargement 0.5–1.5 contre
1.0–2.0 : un ROI < 1 rétrécit la zone floutée sous la détection). Le backend
normalise les noyaux (`normalize_blur_ratio`) : les steps impairs n'ont plus lieu d'être.
"""
from django import forms
from django.forms import CheckboxSelectMultiple, HiddenInput, TextInput, Select

from .models import Media, UserSettings
from wama.anonymizer.utils.yolo_utils import get_all_class_choices, get_model_choices_grouped


class RangeWidget(TextInput):
    input_type = "range"

    def __init__(self, min, max, step, *args, **kwargs):
        super(TextInput, self).__init__(*args, **kwargs)
        self.attrs["min"] = min
        self.attrs["max"] = max
        self.attrs["step"] = step
        self.attrs["oninput"] = "this.nextElementSibling.value = setting.value"


class SwitchWidget(TextInput):
    input_type = "checkbox"

    def __init__(self, *args, **kwargs):
        super(TextInput, self).__init__(*args, **kwargs)
        self.attrs["oninput"] = "this.nextElementSibling.value = setting.value"


def _range_widgets():
    """Sliders aux bornes du SCHÉMA (domicile unique, params.py) — jamais recopiées ici."""
    from wama.common.utils.param_schema import schema_for_app
    return {
        p["name"]: RangeWidget(min=p["min"], max=p["max"], step=p.get("step") or 1)
        for p in schema_for_app("anonymizer")
        if p.get("type") == "range" and p.get("min") is not None
    }


class MediaSettingsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['classes2blur'].choices = get_all_class_choices()

        if self.instance and self.instance.classes2blur:
            self.initial['classes2blur'] = self.instance.classes2blur

    def clean_classes2blur(self):
        cleaned = [str(cls).lower() for cls in self.cleaned_data.get('classes2blur', [])]
        return list(set(cleaned))

    class Meta:
        model = Media
        # Sous-ensemble édité par CETTE modale (déclaration à la app_modes) ;
        # meurt au palier 2 avec le form (modale WamaParams).
        fields = (  # wama:redondance-ok — sous-ensemble déclaré du form
            'id', 'blur_ratio', 'roi_enlargement', 'progressive_blur',
            'detection_threshold', 'classes2blur', 'precision_level')
        widgets = {
            'id': HiddenInput,
            'classes2blur': CheckboxSelectMultiple,
            **_range_widgets(),
        }


class UserSettingsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['classes2blur'].choices = get_all_class_choices()

        if self.instance and self.instance.classes2blur:
            self.initial['classes2blur'] = self.instance.classes2blur

        # Add model selection field with grouped choices
        if 'model_to_use' in self.fields:
            self.fields['model_to_use'].widget.choices = get_model_choices_grouped()

    def clean_classes2blur(self):
        return self.cleaned_data.get('classes2blur', [])

    class Meta:
        model = UserSettings
        # Sous-ensemble édité par CE panneau (déclaration à la app_modes) ;
        # meurt au palier 2 avec le form (modale WamaParams).
        fields = (  # wama:redondance-ok — sous-ensemble déclaré du form
            'id', 'blur_ratio', 'roi_enlargement', 'progressive_blur', 'detection_threshold',
            'show_preview', 'show_boxes', 'show_labels', 'show_conf', 'classes2blur',
            'model_to_use', 'precision_level')
        widgets = {
            'id': HiddenInput,
            'show_preview': SwitchWidget(),
            'show_boxes': SwitchWidget(),
            'show_labels': SwitchWidget(),
            'show_conf': SwitchWidget(),
            'classes2blur': CheckboxSelectMultiple,
            'model_to_use': Select(),
            **_range_widgets(),
        }


class UserSettingsEdit(forms.ModelForm):
    """Consommé par accounts/views.py (page profil) — pas par l'app elle-même."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['classes2blur'].choices = get_all_class_choices()

        if self.instance and self.instance.classes2blur:
            self.initial['classes2blur'] = self.instance.classes2blur

        # Add model selection field with grouped choices
        if 'model_to_use' in self.fields:
            self.fields['model_to_use'].widget.choices = get_model_choices_grouped()

    def clean_classes2blur(self):
        return self.cleaned_data.get('classes2blur', [])

    class Meta:
        model = UserSettings
        fields = "__all__"
        widgets = {
            'classes2blur': CheckboxSelectMultiple,
            'model_to_use': Select(),
        }

"""
Formulaires anonymizer — il ne reste que `UserSettingsEdit` (page profil, accounts).

Les ModelForms de réglages (MediaSettingsForm/UserSettingsForm) sont morts au palier 2
du port (2026-08-03) : la modale item et le volet droit sont rendus depuis le SCHÉMA
(`params.py` → WamaParams), les bornes ont un domicile unique.
"""
from django import forms
from django.forms import CheckboxSelectMultiple, Select

from .models import UserSettings
from wama.anonymizer.utils.yolo_utils import get_all_class_choices, get_model_choices_grouped


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

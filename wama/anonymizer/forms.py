from django import forms
from django.forms import CheckboxSelectMultiple, HiddenInput, TextInput, Select
from .models import Media, GlobalSettings, UserSettings
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


# class CustomWidget(RangeWidget):
#     template_name = 'medias/upload/setting_button.html'
#
#     def __init__(self, name, min, max, step, *args, **kwargs):
#         super(CustomWidget, self).__init__(*args, **kwargs)
#         self.attrs["name"] = name
#         self.attrs["min"] = min
#         self.attrs["max"] = max
#         self.attrs["step"] = step
#         self.attrs["oninput"] = "this.nextElementSibling.value = setting.value"
#         dir(self)
#
#     def render(self, name, value, attrs=None, renderer=None):
#         if value is None:
#             value = 0
#         context = {
#             'name': name,
#             'value': value,
#             'min': self.attrs["min"],
#             'max': self.attrs["max"],
#             'step': self.attrs["step"]
#         }
#         return render_to_string(self.template_name, context)


class MediaForm(forms.ModelForm):
    class Meta:
        model = Media
        fields = ('file', )
        widgets = {'classes2blur': CheckboxSelectMultiple}


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
        fields = ('id', 'blur_ratio', 'roi_enlargement', 'progressive_blur',
                  'detection_threshold', 'classes2blur', 'precision_level')
        widgets = {
            'id': HiddenInput,
            'blur_ratio': RangeWidget(min=1, max=49, step=2),
            'roi_enlargement': RangeWidget(min=0.5, max=1.5, step=.05),
            'progressive_blur': RangeWidget(min=3, max=31, step=2),
            'detection_threshold': RangeWidget(min=0, max=1, step=.05),
            'precision_level': RangeWidget(min=0, max=100, step=5),
            'classes2blur': CheckboxSelectMultiple,
        }


class GlobalSettingsForm(forms.ModelForm):
    class Meta:
        model = GlobalSettings
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super(GlobalSettingsForm, self).__init__(*args, **kwargs)


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
        fields = ('id', 'blur_ratio', 'roi_enlargement', 'progressive_blur', 'detection_threshold',
                  'show_preview', 'show_boxes', 'show_labels', 'show_conf', 'classes2blur', 'model_to_use', 'precision_level')
        widgets = {
            'id': HiddenInput,
            'blur_ratio': RangeWidget(min=1, max=49, step=2),
            'roi_enlargement': RangeWidget(min=0.5, max=1.5, step=.05),
            'progressive_blur': RangeWidget(min=3, max=31, step=2),
            'detection_threshold': RangeWidget(min=0, max=1, step=.05),
            'precision_level': RangeWidget(min=0, max=100, step=5),
            'show_preview': SwitchWidget(),
            'show_boxes': SwitchWidget(),
            'show_labels': SwitchWidget(),
            'show_conf': SwitchWidget(),
            'classes2blur': CheckboxSelectMultiple,
            'model_to_use': Select(),
        }


class UserSettingsEdit(forms.ModelForm):
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

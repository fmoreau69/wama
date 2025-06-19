from django import forms
from django.template.loader import render_to_string
from django.forms import CheckboxSelectMultiple, HiddenInput, TextInput
from .models import Media, GlobalSettings, UserSettings
from wama.medias.utils.yolo_utils import get_yolo_class_choices


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
    def __init__(self,  *args, **kwargs):
        super(MediaSettingsForm, self).__init__(*args, **kwargs)
        self.fields['classes2blur'].choices = get_yolo_class_choices()

        if self.instance and self.instance.classes2blur:
            self.initial['classes2blur'] = self.instance.classes2blur.split(',')

    def clean_classes2blur(self):
        data = self.cleaned_data.get('classes2blur', [])
        return ','.join(data)  # on stocke dans le modèle sous forme CSV

    class Meta:
        model = Media
        fields = ('id', 'blur_ratio', 'progressive_blur', 'roi_enlargement',
                  'detection_threshold', 'classes2blur')
        widgets = {
            'id': HiddenInput,
            'blur_ratio': RangeWidget(min=1, max=49, step=2),
            'progressive_blur': RangeWidget(min=3, max=31, step=2),
            'roi_enlargement': RangeWidget(min=0.5, max=1.5, step=.05),
            'detection_threshold': RangeWidget(min=0, max=1, step=.05),
            'classes2blur': CheckboxSelectMultiple
        }


class GlobalSettingsForm(forms.ModelForm):
    class Meta:
        model = GlobalSettings
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super(GlobalSettingsForm, self).__init__(*args, **kwargs)


class UserSettingsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(UserSettingsForm, self).__init__(*args, **kwargs)
        self.fields['classes2blur'].choices = get_yolo_class_choices()

        if self.instance and self.instance.classes2blur:
            self.initial['classes2blur'] = self.instance.classes2blur.split(',')

    def clean_classes2blur(self):
        data = self.cleaned_data.get('classes2blur', [])
        return ','.join(data)

    class Meta:
        model = UserSettings
        fields = ('id', 'blur_ratio', 'progressive_blur', 'roi_enlargement', 'detection_threshold',
                  'show_preview', 'show_boxes', 'show_labels', 'show_conf', 'classes2blur')
        widgets = {
            'id': HiddenInput,
            'blur_ratio': RangeWidget(min=1, max=49, step=2),
            'progressive_blur': RangeWidget(min=3, max=31, step=2),
            'roi_enlargement': RangeWidget(min=0.5, max=1.5, step=.05),
            'detection_threshold': RangeWidget(min=0, max=1, step=.05),
            'show_preview': SwitchWidget(),
            'show_boxes': SwitchWidget(),
            'show_labels': SwitchWidget(),
            'show_conf': SwitchWidget(),
            'classes2blur': CheckboxSelectMultiple,
        }


class UserSettingsEdit(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(UserSettingsEdit, self).__init__(*args, **kwargs)
        self.fields['classes2blur'].choices = get_yolo_class_choices()

        if self.instance and self.instance.classes2blur:
            self.initial['classes2blur'] = self.instance.classes2blur.split(',')

    def clean_classes2blur(self):
        data = self.cleaned_data.get('classes2blur', [])
        return ','.join(data)

    class Meta:
        model = UserSettings
        fields = "__all__"
        widgets = {'classes2blur': CheckboxSelectMultiple}

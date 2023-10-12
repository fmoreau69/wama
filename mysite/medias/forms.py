from django import forms
from django.forms import CheckboxSelectMultiple, HiddenInput, TextInput
from .models import Media, Option, UserDetails


class RangeWidget(TextInput):
    input_type = "range"

    def __init__(self, min, max, step, *args, **kwargs):
        super(TextInput, self).__init__(*args, **kwargs)
        self.attrs["min"] = min
        self.attrs["max"] = max
        self.attrs["step"] = step
        self.attrs["oninput"] = "this.nextElementSibling.value = option.value"


class MediaForm(forms.ModelForm):
    class Meta:
        model = Media
        fields = ('file', )
        widgets = {'classes2blur': CheckboxSelectMultiple}


class OptionForm(forms.ModelForm):
    class Meta:
        model = Media
        fields = ('id', 'blur_ratio', 'rounded_edges', 'roi_enlargement', 'detection_threshold', 'classes2blur')
        widgets = {'id': HiddenInput,
                   'blur_ratio': RangeWidget(min=0, max=50, step=1),
                   'rounded_edges': RangeWidget(min=0, max=50, step=1),
                   'roi_enlargement': RangeWidget(min=0.5, max=1.5, step=.05),
                   'detection_threshold': RangeWidget(min=0, max=1, step=.05),
                   'classes2blur': CheckboxSelectMultiple
                   }


class GlobalSettingsForm(forms.ModelForm):
    class Meta:
        model = Option
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super(GlobalSettingsForm, self).__init__(*args, **kwargs)


class UserDetailsEdit(forms.ModelForm):
    class Meta:
        model = UserDetails
        fields = "__all__"

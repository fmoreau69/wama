from django import forms

from .models import Media, Option


class MediaForm(forms.ModelForm):
    class Meta:
        model = Media
        fields = ('file', )


class OptionForm(forms.ModelForm):
    class Meta:
        model = Option
        fields = "__all__"

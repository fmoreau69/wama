from django.forms import CheckboxSelectMultiple, TextInput, SelectMultiple, FileInput


class CustomCheckMultiple(CheckboxSelectMultiple):
    """
    Base class to create multiple checkboxes widget exploiting gentella template.
    :param ctrl_button: Dict containing attrs and text for controller button.
    The key 'text' contains button text and the key 'attrs' contains a nested dict
     listing html attributes and values :\n
    ctrl_button = {text:'String',  attrs: {attr_name: attr_value, ...}}\n
    :param vdt_button: Sets the validation button. Same dict as ctrl_button with an
    additional key called 'enable'. If enable is True, the button will be rendered.
    :param option_attrs: Dict ; customise checkboxes attributes.\n
    {attr_name: attr_value, ...}\n
    """
    def __init__(self,
                 ctrl_button={'text': '', 'attrs': {}},
                 vdt_button={'text': 'Save changes', 'attrs': {}, 'enable': False},
                 option_attrs={'class': 'flat'},
                 *args, **kwargs):
        super(CustomCheckMultiple, self).__init__(*args, **kwargs)
        self.ui_id = None
        # To customise buttons
        self.ctrl_button = dict()
        self.ctrl_button['text'] = ctrl_button['text'] if 'text' in ctrl_button.keys() else ''
        self.ctrl_button['attrs'] = ctrl_button['attrs'] if 'attrs' in ctrl_button.keys() else {}
        self.vdt_button = dict()
        self.vdt_button['text'] = vdt_button['text'] if 'text' in vdt_button.keys() else ''
        self.vdt_button['attrs'] = vdt_button['attrs'] if 'attrs' in vdt_button.keys() else {}
        self.vdt_button['enable'] = vdt_button['enable'] if 'enable' in vdt_button.keys() else False
        # To  customise option attrs :
        self.option_inherits_attrs = False  # If true, widget attrs are copied to option
        self.option_attrs = option_attrs

    # Overload get_context method to add some variable to draw template
    def get_context(self,  name, value, attrs):
        context = super(CustomCheckMultiple, self).get_context(name, value, attrs)
        context['widget']['ui_id'] = self.ui_id
        context['widget']['ctrl_button'] = self.ctrl_button
        context['widget']['vdt_button'] = self.vdt_button
        return context

    # Custom attrs insertion
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        context = super(CustomCheckMultiple, self).create_option(name, value, label, selected, index, subindex, attrs)
        context['attrs'].update(self.option_attrs)
        context['attrs'].update({'data-label': context['label']})  # allows to perform js search
        return context

    # try to remove that, it looks useless
    def id_for_label(self, id_, index=None):
        if index is None:
            return super().id_for_label(id_)
        return super().id_for_label(id_, index)

    class Media:
        css = {'all': ('vendors/iCheck/skins/flat/grey.css',)}
        js = ('vendors/iCheck/icheck.js', )


class CheckMultiple(CheckboxSelectMultiple):
    def __init__(self, *args, **kwargs):
        super(CheckMultiple, self).__init__(*args, **kwargs)
        self.template_name = "common/forms/widgets/checkbox_multiple.html"

    class Media:
        css = {'all': ('vendors/iCheck/skins/flat/grey.css',)}
        js = ('vendors/iCheck/icheck.js', 'js/checkbox-multiple.js')


class CheckMultipleGroups(CheckboxSelectMultiple):
    def __init__(self, *args, **kwargs):
        super(CheckMultipleGroups, self).__init__(*args, **kwargs)
        self.template_name = "common/forms/widgets/checkbox_multiple_groups.html"

    class Media:
        css = {'all': ('vendors/iCheck/skins/flat/grey.css',)}
        js = ('vendors/iCheck/icheck.js', 'js/checkbox-multiple.js')


class CheckMultipleGroupsUncollapse(CheckboxSelectMultiple):
    def __init__(self, *args, **kwargs):
        super(CheckMultipleGroupsUncollapse, self).__init__(*args, **kwargs)
        self.template_name = "common/forms/widgets/checkbox_multiple_groups_uncollapse.html"

    class Media:
        css = {'all': ('vendors/iCheck/skins/flat/grey.css',)}
        js = ('vendors/iCheck/icheck.js', 'js/checkbox-multiple.js')


class MenuCheckMultiple(CustomCheckMultiple):
    """
    This widget provides multiple checkbox in a dropdown menu
    """
    def __init__(self, menu_class=None, *args, **kwargs):
        super(MenuCheckMultiple, self).__init__(*args, **kwargs)
        self.template_name = "common/forms/widgets/checkbox_multiple_menu.html"
        # Attrs will be applied to main ul element
        self.parent_class = menu_class
        self.attrs.update({'class': "dropdown-menu", "role": "menu"})

    def get_context(self,  name, value, attrs):
        context = super(MenuCheckMultiple, self).get_context(name, value, attrs)
        if self.parent_class is not None:
            context['widget']['parent_class'] = self.parent_class
        return context


class ModalCheckMultiple(CustomCheckMultiple):
    """
    This widget provides multiple checkbox in a modal menu
    :param modal_title: String ; To define modal's title. Blank if not set.
    """
    def __init__(self, modal_title='', *args, **kwargs):
        super(ModalCheckMultiple, self).__init__(*args, **kwargs)
        self.template_name = "common/forms/widgets/checkbox_multiple_modal.html"
        self.modal_title = modal_title
        # Attrs will be applied to main ul element
        self.attrs = {'class': "to_do modal-menu"}

    def get_context(self, name, value, attrs):
        context = super(ModalCheckMultiple, self).get_context(name, value, attrs)
        # Modal title can be different from label and button title
        context['widget']['modal_title'] = self.modal_title
        return context


class RangeInput(TextInput):
    """
    This widget allows to select a value range.
    :param min_value: Number (int or float) ; Minimum selectable value.
    :param max_value: Number (int or float) ; Maximum selectable value.
    :param prefix: String ; String to render before the displayed values.
    """
    def __init__(self, min_value, max_value, prefix="", postfix="", *args, **kwargs):
        super(RangeInput, self).__init__(*args, **kwargs)
        if 'class' in self.attrs.keys():
            self.attrs['class'] = '{} range'.format(self.attrs['class'])
        else:
            self.attrs['class'] = 'range'
        self.attrs['data-min'] = min_value
        self.attrs['data-max'] = max_value
        self.attrs['data-prefix'] = prefix

    class Media:
        css = {'all': ('vendors/normalize-css/normalize.css',
                       'vendors/ion.rangeSlider/css/ion.rangeSlider.css',
                       )
               }
        js = ("vendors/ion.rangeSlider/js/ion.rangeSlider.min.js",)


class TagInput(SelectMultiple):
    """
    Tags editing widget : allows to assign tags, add new tags or delete assignations.
    dependencies :
        - autocomplete.js
        - tags_input.js
        - "edit_tags" view (ajax)
        - "autocomplete" view
    """
    def __init__(self, model_name, *args, **kwargs):
        super(TagInput, self).__init__(*args, **kwargs)
        self.attrs.update({'class': 'custom-tags', 'data-model': model_name})

    class Media:
        js = ("js/tags_input.js",
              "vendors/devbridge-autocomplete/dist/jquery.autocomplete.min.js")


class DropZone(FileInput):
    template_name = 'accounts/dropzone.html'

    def __init__(self, *args, **kwargs):
        self.inner_text = kwargs.pop('inner_text', None)
        super(DropZone, self).__init__(*args, **kwargs)

    def get_context(self, name, value, attrs):
        context = super(DropZone, self).get_context(name, value, attrs)
        context['inner_text'] = self.inner_text
        return context

    class Media:
        css = {'all': ("vendors/dropzone-5.7.0/dist/min/dropzone.min.css",
                       'css/dropzone.css',)}
        js = ("vendors/dropzone-5.7.0/dist/min/dropzone.min.js",
              )

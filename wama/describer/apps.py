from django.apps import AppConfig


class DescriberConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.describer'
    verbose_name = 'Describer - AI Content Description'

    def ready(self):
        # Register for unified preview
        from wama.common.utils.preview_utils import register_app_preview
        from .models import Description

        register_app_preview(
            app_name='describer',
            model_class=Description,
            file_field='input_file',
            user_field='user',
            properties_field='properties'
        )

from django.apps import AppConfig


class MediaLibraryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.media_library'
    verbose_name = 'Médiathèque'

    def ready(self):
        """Enregistre la médiathèque comme SURFACE du registre d'aperçu.

        C'est ce registre que lit `api_partage` (`common/views.py`) pour résoudre le modèle
        d'une cible : sans cette ligne, la route commune répond « surface inconnue » et la
        médiathèque devrait garder son endpoint maison — le doublon qu'on retire ici même.
        L'aperçu commun `/common/preview/media_library/<pk>/` s'ouvre du même geste ; sa garde
        est celle du registre (propriétaire ou staff, `preview_registry.check_permission`).
        """
        from wama.common.utils.preview_utils import register_app_preview
        from .models import UserAsset
        register_app_preview('media_library', UserAsset,
                             file_field='file', duration_field='duration')

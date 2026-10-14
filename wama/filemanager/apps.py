from django.apps import AppConfig


class FilemanagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.filemanager'
    verbose_name = 'File Manager'

    def ready(self):
        # Outil gardé par la politique d'accès depuis le 2026-10-13 (décision de Fabien) — un
        # VOLET, sans page : il se déclare en outil sans page ; ses routes (`/filemanager/…`) se
        # résolvent par leur 1er segment, comme toute app.
        from wama.common.app_registry import register_pageless_tool
        register_pageless_tool('filemanager', world='transverse', label='Gestionnaire de fichiers',
                               icon='fa-folder-tree', probe='/filemanager/api/tree/',
                               description="Le volet de vos dossiers : imports, envois vers les apps.")

from django.apps import AppConfig

class AnonymizerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.anonymizer'

    def ready(self):
        import wama.anonymizer.signals

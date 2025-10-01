from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Media
from .views import ensure_global_settings, init_user_settings
from django.contrib.auth import get_user_model

User = get_user_model()

@receiver(post_save, sender=Media)
def initialize_global_settings(sender, instance, created, **kwargs):
    if created:
        # Initialise global settings si elles n'existent pas
        ensure_global_settings()

        # Initialise les settings pour tous les utilisateurs existants
        for user in User.objects.all():
            init_user_settings(user)

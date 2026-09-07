from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Media, UserSettings
from .views import ensure_global_settings

User = get_user_model()


@receiver(post_save, sender=Media)
def initialize_global_settings(sender, instance, created, **kwargs):
    """À la création d'un média : les réglages GLOBAUX existent, et ceux du DÉPOSANT aussi.

    ⚠ Corrigé le 2026-09-07 (trouvé par `common/tests_import_contract`). La version
    précédente appelait `init_user_settings()` pour **TOUS les utilisateurs** — c'est-à-dire
    qu'elle RÉINITIALISAIT aux défauts les réglages de tout le monde (précision, segmentation,
    aperçu, `GSValues_customised = 0`) à chaque dépôt de n'importe qui, et commençait par
    `close_old_connections()` en plein cycle de requête (connexion fermée au milieu d'un
    `TestCase` : « the connection is closed »). Sous gunicorn Django rouvrait, donc rien ne
    plantait — seuls les réglages disparaissaient. Ce que le signal VEUT : garantir qu'une
    ligne de réglages existe pour le déposant. `get_or_create` ne touche jamais une ligne
    existante ; la RÉINITIALISATION reste un geste explicite (`reset_user_settings`).
    """
    if not created:
        return
    ensure_global_settings()
    if instance.user_id:
        UserSettings.objects.get_or_create(user_id=instance.user_id)

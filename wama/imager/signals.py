"""
Signaux Imager.

1. Notification de fin/échec (la tâche a de NOMBREUX points de sortie en échec — validations de
   backend, VRAM, etc. — qu'un signal couvre d'un seul endroit, succès inclus). Notifie sur
   **transition** du statut vers un état terminal (SUCCESS/FAILURE), une seule fois. Évite les
   requêtes inutiles sur les saves de progression (update_fields sans 'status').

2. Enrichissement du prompt À L'INGESTION. Imager a SIX handlers de création (txt2img, file2img,
   describe2img, img2img, txt2vid, img2vid) : un signal `post_save(created=True)` les couvre tous
   d'un seul endroit, au lieu de six patches — et couvre aussi la création par batch et par l'API
   de l'assistant. Les champs traités viennent de la DÉCLARATION (`PROMPT_TARGETS`), pas d'ici.
"""
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from wama.imager.models import ImageGeneration

_TERMINAL = {'SUCCESS', 'FAILURE'}
_SKIP = '__skip__'


@receiver(pre_save, sender=ImageGeneration)
def _stash_old_status(sender, instance, update_fields=None, **kwargs):
    if not instance.pk:
        instance._old_status = None
        return
    # Save de progression (sans 'status') → inutile de comparer.
    if update_fields is not None and 'status' not in update_fields:
        instance._old_status = _SKIP
        return
    instance._old_status = sender.objects.filter(pk=instance.pk).values_list('status', flat=True).first()


@receiver(post_save, sender=ImageGeneration)
def _notify_terminal(sender, instance, created, **kwargs):
    old = getattr(instance, '_old_status', _SKIP)
    if old == _SKIP:
        return
    new = instance.status
    if new in _TERMINAL and old not in _TERMINAL:
        try:
            from wama.common.utils.notifications import notify_job
            success = (new == 'SUCCESS')
            is_video = bool(getattr(instance, 'output_video', None))
            label = 'Imager (vidéo)' if is_video else 'Imager'
            name = getattr(instance, 'name', '') or f"génération #{instance.pk}"
            detail = (getattr(instance, 'error_message', '') or '') if not success else ''
            notify_job(getattr(instance, 'user', None), label, name, success, detail=detail)
        except Exception:
            pass
        instance._old_status = new  # éviter une re-notification sur un save suivant


@receiver(post_save, sender=ImageGeneration)
def _enrich_prompt_at_ingest(sender, instance, created, **kwargs):
    """
    Met en file l'enrichissement du prompt dès la création de la card.

    ASYNCHRONE volontairement : la passe LLM coûte ~1,3 s à chaud mais ~12 s à froid (chargement
    des poids) — inacceptable dans la requête HTTP de dépôt. La card apparaît tout de suite ; le
    prompt enrichi arrive juste après et le polling de la file l'affiche.

    Garde-fou : si l'utilisateur lance la génération avant que l'enrichissement soit revenu, la
    tâche de génération enrichit elle-même (la pipeline reste appelée au lancement) — il n'y a donc
    pas de fenêtre où le prompt partirait non enrichi.
    """
    if not created or getattr(instance, 'prompt_processed', ''):
        return
    if not (getattr(instance, 'prompt', '') or '').strip():
        return
    try:
        from django.db import transaction
        from wama.imager.tasks import enrich_prompt_at_ingest_task

        pk = instance.pk
        # `on_commit` et pas `delay()` direct : si la création est dans une transaction (batch,
        # vue atomique, import), le worker peut prendre la tâche AVANT le commit et ne pas
        # trouver la ligne. Hors transaction, on_commit s'exécute immédiatement.
        transaction.on_commit(lambda: enrich_prompt_at_ingest_task.delay(pk))
    except Exception:
        pass  # broker indisponible → la tâche de génération enrichira au lancement (fail-safe)

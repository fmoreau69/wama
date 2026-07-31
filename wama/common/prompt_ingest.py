"""
Enrichissement de prompt à l'INGESTION — branchement générique, zéro code par app.

Avant : chaque app devait écrire son propre récepteur `post_save` + sa propre tâche Celery pour
enrichir le prompt d'une card à sa création (fait à la main sur imager le 30/07). Vingt lignes à
recopier par app, donc dix occasions de diverger — exactement ce que la règle de centralisation
interdit.

Ici, le branchement est **déduit de la déclaration** : toute app dont `PROMPT_TARGETS` porte un
champ `enrich=True` ET qui nomme son modèle (`'model': '<app_label>.<ModelName>'`) reçoit le
comportement. Rien à écrire dans l'app.

Le récepteur est volontairement minimal : il ne décide rien, il met en file. Toute la logique
(quels champs, quel skill, quel glossaire) vit dans `app_metadata.enrich_instance_prompts()`.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_connected = []


def _on_created(sender, instance, created, **kwargs):
    """Met en file l'enrichissement à la création. Fail-safe : ne casse jamais un dépôt."""
    if not created:
        return
    if (getattr(instance, 'prompt_processed', '') or '').strip():
        return                                   # déjà traité (duplication de card, import)
    if not (getattr(instance, 'prompt', '') or '').strip():
        return                                   # rien à enrichir

    try:
        from django.db import transaction

        from wama.common.tasks import enrich_prompt_at_ingest_task

        label = sender._meta.app_label
        name = sender._meta.model_name
        pk = instance.pk
        # `on_commit` et pas `delay()` direct : si la création est dans une transaction (batch,
        # import, vue atomique), le worker peut prendre la tâche AVANT le commit et ne pas
        # trouver la ligne. Hors transaction, on_commit s'exécute immédiatement.
        transaction.on_commit(
            lambda: enrich_prompt_at_ingest_task.delay(label, name, pk))
    except Exception as exc:                      # broker indisponible, etc.
        # Pas de régression : la pipeline enrichira au lancement de la tâche de traitement.
        logger.debug(f"[prompt_ingest] mise en file ignorée ({exc})")


def register_prompt_ingest_receivers():
    """
    Connecte le récepteur sur tout modèle DÉCLARÉ enrichissable. Appelé depuis `CommonConfig.ready()`.

    Un modèle est concerné s'il est nommé par `PROMPT_TARGETS[app][i]['model']` et que la cible
    porte `enrich=True`. Un modèle qui n'a pas encore les champs du mixin `PromptScoped` est
    ignoré : l'app garde exactement son comportement d'avant tant qu'elle n'a pas migré.
    """
    from django.apps import apps as django_apps
    from django.db.models.signals import post_save

    from wama.common.utils.app_metadata import PROMPT_TARGETS

    for app_label, targets in PROMPT_TARGETS.items():
        for tgt in targets:
            if not tgt.get('enrich') or not tgt.get('model'):
                continue
            try:
                model = django_apps.get_model(tgt['model'])
            except Exception as exc:
                logger.debug(f"[prompt_ingest] modèle {tgt['model']} introuvable ({exc})")
                continue
            if not hasattr(model, 'prompt_processed'):
                continue                          # pas (encore) porté sur `PromptScoped`
            if model in _connected:
                continue
            post_save.connect(_on_created, sender=model,
                              dispatch_uid=f"prompt_ingest:{tgt['model']}")
            _connected.append(model)
            logger.debug(f"[prompt_ingest] branché sur {tgt['model']}")

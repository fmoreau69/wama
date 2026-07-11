"""
Studio (méta-app) — persistance des pipelines et des exécutions.

Le GRAPHE est un JSON auto-porteur (nodes + links), sérialisé par wama-studio.js :
    {"nodes": [{"id", "app", "x", "y", "params": {...}}],
     "links": [{"from": "<nodeId>", "to": "<nodeId>", "to_port": "<group>"}]}

`StudioRun.node_states` trace l'exécution nœud par nœud :
    {"<nodeId>": {"status": "PENDING|RUNNING|SUCCESS|FAILURE",
                  "item_id": <id de l'objet créé dans l'app>,
                  "output": "<chemin MEDIA relatif>", "error": ""}}
"""
from django.contrib.auth import get_user_model
from django.db import models

from wama.common.models import ProcessingTimeMixin

User = get_user_model()


class StudioPipeline(models.Model):
    """Un pipeline sauvegardé (graphe nommé, rechargeable dans le canvas)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='studio_pipelines')
    name = models.CharField(max_length=120)
    graph = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='uniq_studio_pipeline_user_name'),
        ]

    def __str__(self):
        return f"{self.name} ({self.user_id})"


class StudioRun(ProcessingTimeMixin, models.Model):
    """Une exécution de pipeline (graphe figé au lancement + états par nœud)."""
    STATUS_CHOICES = [
        ('PENDING', 'En attente'),
        ('RUNNING', 'En cours'),
        ('SUCCESS', 'Terminé'),
        ('FAILURE', 'Erreur'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='studio_runs')
    pipeline = models.ForeignKey(StudioPipeline, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name='runs')
    graph = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    task_id = models.CharField(max_length=255, blank=True, default='')
    node_states = models.JSONField(default=dict)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"run #{self.pk} [{self.status}]"

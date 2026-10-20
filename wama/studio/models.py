"""
Studio — persistance des pipelines et des exécutions.

Le GRAPHE est un JSON auto-porteur (nodes + links), sérialisé par wama-studio.js :
    {"nodes": [{"id", "app", "x", "y", "params": {...}}],
     "links": [{"from": "<nodeId>", "to": "<nodeId>", "to_port": "<group>"}]}
`app` porte l'identifiant de palette : une app, un nœud d'entrée/sortie, ou `function:<clé>` pour
une fonction du catalogue (depuis le 2026-09-09, lu par `manifests.builtin.pipeline.node_kind`).

`StudioRun.node_states` trace l'exécution nœud par nœud :
    {"<nodeId>": {"status": "PENDING|RUNNING|SUCCESS|FAILURE",
                  "item_id": <id de l'objet créé dans l'app>,
                  "output": "<chemin MEDIA relatif>", "error": ""}}

⏳ Précisé le 2026-09-15 → WAMA_APP_GENERATION_ROUTE.md §10.6 (4.1, 4.2) : ces états s'aligneront
sur le vocabulaire COMMUN (les 5 états JOB_* de `wama.common.models`, dont AWAITING_RESOURCES,
+ STALE) ; la cible remplace `node_states` par UNE LIGNE D'EXÉCUTION PAR PROCESS (généralisation
d'`AnalysisPass` de cam_analyzer), commune à tous les mondes.
"""
from django.contrib.auth import get_user_model
from django.db import models

from wama.common.models import (JOB_STATUS_CHOICES, ProcessingTimeMixin, ScopedManager,
                                ScopedVisibility)

User = get_user_model()


class StudioPipeline(ScopedVisibility):
    """Un pipeline sauvegardé (graphe nommé, rechargeable dans le canvas).

    Un objet de TRAVAIL, comme une card (décision de Fabien, 2026-10-19, `ROADMAP §29` étape 4) :
    il naît privé à son auteur et se partage par le mécanisme commun (`WAMA_COLLABORATION §4.7`) —
    lu par `listable_by` / `visible_or_404`, supprimé par `owned_or_404`. L'administrateur n'y voit
    pas tout. Un pipeline SYSTÈME est un pipeline déclaré en code (`register_pipeline_source`)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='studio_pipelines')
    name = models.CharField(max_length=120)
    graph = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Le défaut du mixin (privé), posé AUSSI en base : le code en service avant sa relance
    # enregistre un pipeline sans cette colonne.
    visibility = models.CharField(max_length=12, choices=ScopedVisibility.VIS_CHOICES,
                                  default=ScopedVisibility.VIS_PRIVATE,
                                  db_default=ScopedVisibility.VIS_PRIVATE, db_index=True)

    objects = ScopedManager()

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='uniq_studio_pipeline_user_name'),
        ]

    def __str__(self):
        return f"{self.name} ({self.user_id})"


class StudioRun(ProcessingTimeMixin, models.Model):
    """Une exécution de pipeline (graphe figé au lancement + états par nœud)."""
    #: Vocabulaire COMMUN (wama.common.models) — plus de copie par app.
    STATUS_CHOICES = JOB_STATUS_CHOICES
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='studio_runs')
    pipeline = models.ForeignKey(StudioPipeline, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name='runs')
    graph = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    task_id = models.CharField(max_length=255, blank=True, default='')
    node_states = models.JSONField(default=dict)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    #: Le run de LOT dont celui-ci est un ÉLÉMENT (2026-10-20, `STUDIO_VISION §Entrées du
    #: Studio`) : plusieurs fichiers de travail ou un fichier de lot = un lot, et le pipeline tourne
    #: une fois par élément — une card mère et ses filles. Vide pour un run ordinaire.
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True,
                               related_name='elements')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        # Titre lu au journal et au calendrier (`str(obj)`) : le NOM du pipeline dit ce qui a
        # tourné, « run #14 [FAILURE] » ne le disait pas — et l'état est déjà affiché à côté.
        name = self.pipeline.name if self.pipeline_id and self.pipeline else 'Pipeline'
        return f"{name} — exécution #{self.pk}"

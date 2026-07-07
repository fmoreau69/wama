"""
Briques de modèles COMMUNES (cf. BATCH_MODEL_AUDIT.md).

`BatchMixin` : comportement partagé des modèles « Batch » unifiés des apps de file.
C'est un **mixin Python sans champ** → aucune migration. Le modèle concret doit fournir :
  - `items`      : related_name des `BatchItem` (membres).
  - `total`      : entier maintenu par les signaux `batch_sync` (= nombre de membres).
  - `batch_file` : fichier batch partagé (optionnel).

Usage :  class BatchTranscript(BatchMixin, models.Model): ...

`ProcessingTimeMixin` : durée RÉELLE de traitement (mesurée par le worker, persistée) — modèle
ABSTRAIT (une migration additive par app concrète).
"""

from django.db import models


class ProcessingTimeMixin(models.Model):
    """Durée RÉELLE de traitement, en secondes. Le worker la CALCULE déjà (il la passe au learner
    ETA via record_run) ; on la PERSISTE ici pour qu'elle reste affichée après rechargement
    (CARD_DESIGN §10.6 : le réel, en regard de la prédiction ETA). Généralise le
    processing_seconds/processing_display de transcriber = source unique.

    Modèle ABSTRAIT → chaque app concrète hérite le champ. Champ identique à celui de transcriber
    (default=0) → transcriber converge sans altération de colonne."""

    processing_seconds = models.FloatField(default=0)

    class Meta:
        abstract = True

    @property
    def processing_display(self) -> str:
        """Durée de traitement formatée (ex. '12 min 30 s' / '45 s'). '' si non mesurée."""
        s = int(self.processing_seconds or 0)
        if s <= 0:
            return ''
        m, sec = divmod(s, 60)
        return (f"{m} min {sec:02d} s" if m else f"{sec} s")


class BatchMixin:
    """Sémantique + cycle de fichiers communs aux modèles Batch (tout est batch ; unitaire = card unique)."""

    @property
    def is_unitary(self) -> bool:
        """True si le batch n'a qu'un seul membre → s'affiche en card unique.
        S'appuie sur `total` (maintenu exact par le signal batch_sync) → pas de requête."""
        return self.total == 1

    def cleanup_files(self) -> None:
        """Supprime le fichier batch partagé s'il n'est plus référencé. Défensif.
        Appelable aussi explicitement sur les chemins bulk (queryset.delete ne passe pas par delete())."""
        try:
            from wama.common.utils.queue_duplication import safe_delete_file
            if hasattr(self, 'batch_file'):
                safe_delete_file(self, 'batch_file')
        except Exception:
            pass

    def delete(self, *args, **kwargs):
        # Un batch nettoie son fichier partagé quand il est supprimé (quel que soit le déclencheur :
        # vue, signal de batch vidé, cascade). Centralise un nettoyage jusque-là éparpillé.
        self.cleanup_files()
        return super().delete(*args, **kwargs)

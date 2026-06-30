"""
Briques de modèles COMMUNES (cf. BATCH_MODEL_AUDIT.md).

`BatchMixin` : comportement partagé des modèles « Batch » unifiés des apps de file.
C'est un **mixin Python sans champ** → aucune migration. Le modèle concret doit fournir :
  - `items`      : related_name des `BatchItem` (membres).
  - `total`      : entier maintenu par les signaux `batch_sync` (= nombre de membres).
  - `batch_file` : fichier batch partagé (optionnel).

Usage :  class BatchTranscript(BatchMixin, models.Model): ...
"""


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

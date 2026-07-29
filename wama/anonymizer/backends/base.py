"""
Contrat des détecteurs de l'Anonymizer — spécialisation métier de `BaseModelBackend`.

CONTEXTE (2026-07-29) — l'anonymizer n'avait AUCUN `backends/` : ses trois porteurs de modèle
GPU (`Anonymize` et `DetectionOnlyProcessor` → YOLO, `SAM3Processor` → SAM3) avaient déjà la
FORME du contrat (`load_model()`, parfois `unload()`/`cleanup()`) sans en hériter. Résultat :
aucune déclaration d'empreinte au gouverneur de ressources, alors que l'anonymizer est l'app
qui enchaîne les sous-tâches GPU les plus lourdes (chord `detect_with_model`/`merge_and_blur`).

Cette classe fait UNE chose : mapper le verbe historique `load_model()` sur le `load()` du
contrat commun, pour que l'empreinte soit déclarée **sans toucher un seul appelant**. C'est le
même motif que `ImageGenerationBackend` (imager) et `SpeechToTextBackend` (transcriber) — et
c'est ce motif, pas le rattachement des classes concrètes une par une, qui fait la couverture :
`__init_subclass__` enveloppe les `load`/`unload` définis à N'IMPORTE QUELLE profondeur.
"""

from wama.common.backends.base import BaseModelBackend


class DetectionBackend(BaseModelBackend):
    """Porteur d'un modèle de détection/segmentation (YOLO, SAM3) chargé sur GPU."""

    # Les dépendances et l'empreinte se déclarent dans les classes CONCRÈTES : YOLO
    # (ultralytics, ~2 Go) et SAM3 (~3 Go) n'ont ni les mêmes paquets ni le même poids.

    def load_model(self, *args, **kwargs):
        """
        Nom historique conservé pour tous les appelants (tasks, parallel_detection, core/*).

        ⚠️ NE PAS remplacer par un alias de classe (`load_model = load`) : l'alias capturerait la
        fonction AVANT que `__init_subclass__` n'enveloppe `load`, et les appelants passeraient
        donc à côté de la déclaration VRAM — le mécanisme serait présent et inopérant. C'est la
        délégation via `self.load(...)` qui garantit que TOUS les chemins traversent l'enveloppe.
        """
        return self.load(*args, **kwargs)

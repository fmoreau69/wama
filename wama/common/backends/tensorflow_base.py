"""Ce qu'un moteur TensorFlow a de commun — le service qui le charge, et où il se mesure.

Un mixin : un backend TensorFlow dérive de lui ET du contrat de sa tâche, dans cet ordre. Il dit le
processus qui le charge (`SERVED_BY`, `tensorflow_service/service.py`), et TOUT accès à TensorFlow
passe par `tensorflow_service.runtime.tensorflow()`, qui prépare le processus : sur la carte dans le
service, hors de la carte dans le repli de l'appelant.

⚠ Il ne dérive PAS de `BaseModelBackend` : l'inventaire lit l'abstraction par AST en remontant chaque
branche (`backend_inventory._class_backends`), sans l'ordre de résolution de Python. Une seconde
branche jusqu'au contrat commun ferait passer tout backend concret pour abstrait, donc introuvable.
"""
import threading
from typing import Optional

from wama.common.tensorflow_service import runtime

#: Le service TensorFlow, par sa clé au registre des sources (`external_sources.SOURCES`) : le nom
#: sous lequel il se déclare tenant et le `SERVED_BY` de ses backends, le nom aussi que la surveillance
#: lui donne (`scripts/wama_services.sh`).
TENSORFLOW_SERVICE = 'tensorflow_service'


class TensorFlowBackend:
    """Un modèle que TensorFlow exécute — dans le service, ou sur le processeur chez l'appelant."""

    SERVED_BY = TENSORFLOW_SERVICE
    #: Le service n'a pas de PyTorch : l'enveloppe du gouverneur en tient compte (`base`).
    NO_TORCH_IN_PROCESS = True

    def __init__(self):
        super().__init__()
        self._load_lock = threading.Lock()
        if not runtime.on_the_card():
            # Hors de la carte, cette instance n'y tient rien : pas de ligne au registre, et aucune
            # mesure (`_holds_no_local_vram`) — elle importerait PyTorch dans un gunicorn.
            self.recommended_vram_gb = 0

    def ensure_loaded(self, model_id: Optional[str] = None) -> None:
        """Le modèle chargé UNE fois, quels que soient les appels simultanés."""
        if self.is_loaded:
            return
        with self._load_lock:
            if not self.is_loaded:
                self.load(model_id)

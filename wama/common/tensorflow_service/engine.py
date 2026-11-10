"""Le moteur du service TensorFlow — le même dans le service et dans le repli du processus appelant.

Une demande dit sa TÂCHE (le contrat, `backend_inventory.TASK_CONTRACTS`), son MOTEUR et ses MODÈLES
(l'identifiant que déclare le `SUPPORTED_MODELS` de chaque backend ; vide pour un moteur dont les
poids n'ont pas de ligne de catalogue : FER). La classe se résout par la porte commune
(`backend_for_engine`, le moteur partagé départagé par la liste de chacun), l'instance est celle que
garde `backend_instance`. Les réponses des modèles se fusionnent : le contrat rend un dictionnaire
par modèle (`FaceAnalysisBackend.analyze_face`). Rien ici ne connaît le visage : un modèle TensorFlow
à venir y entre par son contrat.
"""
from __future__ import annotations

import threading
from typing import Iterable, Optional

#: Une demande à la fois : l'instance est partagée (gunicorn sert par fils, le service par un pool),
#: et rien dans Keras ni dans l'interpréteur TFLite de FER ne promet des appels simultanés.
_one_at_a_time = threading.Lock()

#: Classes déjà résolues. Une classe ne change qu'avec le CODE, donc pas sans redémarrage (même règle
#: que `backend_inventory._LINEAGE_CACHE`) : le temps réel appelle ceci à chaque image.
_classes: dict = {}


def backend_class(task: str, engine: str, model_id: str = ''):
    """La classe qui sert `model_id` sous `engine` pour `task`. LÈVE `ModelNotServed` si aucune."""
    key = (task, engine, model_id)
    if key not in _classes:
        from wama.common.backends.manager import ModelNotServed, backend_for_engine
        found = backend_for_engine(engine, model_id, task=task)
        if found is None:
            raise ModelNotServed(f"« {engine} » / « {model_id} » : aucun backend de la tâche {task}.")
        _classes[key] = found
    return _classes[key]


def backend(task: str, engine: str, model_id: str = ''):
    """L'instance gardée chargée de ce modèle (une par classe, `backend_instance`)."""
    from wama.common.backends.manager import backend_instance
    return backend_instance(backend_class(task, engine, model_id))


def run(task: str, engine: str, models: Iterable[str], image, options: Optional[dict] = None) -> Optional[dict]:
    """Passe `image` à chaque modèle, chargé si besoin, et fusionne leurs réponses. None : aucun
    modèle n'a rien trouvé (pas de visage)."""
    merged: dict = {}
    with _one_at_a_time:
        for model_id in models:
            instance = backend(task, engine, model_id)
            instance.ensure_loaded(model_id or None)
            merged.update(instance.process(image=image, **(options or {})) or {})
    return merged or None

"""
Client COMMUN du service TensorFlow (`service.py`, uvicorn 127.0.0.1:8004). Même patron que les
clients de voix, de vectorisation et de confidentialité : tout le monde passe par ici.

    run('face-analysis', engine='deepface', models=[…], image=<ndarray>, options={…}) → dict | None

Service éteint, en démarrage, ou sans place sur la carte ⇒ le MÊME moteur s'exécute dans ce processus,
TensorFlow tenu HORS de la carte (`runtime`, décision du 2026-11-08) : on perd la vitesse, pas le
résultat. Service éteint, ce processus le DEMANDE (`service_supervision.ask_for_service`) : la
surveillance le relance, et les images suivantes repartent vers lui.

L'image part en `.npy`, sans perte : c'est le tableau que le moteur recevait quand il tournait dans
l'appelant. Un JPEG aurait changé les résultats.
"""
from __future__ import annotations

import io
import json
import logging
from typing import Iterable, Optional

from . import engine as local_engine

logger = logging.getLogger(__name__)

#: Le délai d'UNE demande. Il couvre le premier chargement de l'âge ou du genre, à la demande.
TIMEOUT_S = 180


class TensorFlowServiceError(RuntimeError):
    """Le service a répondu par une erreur : l'analyse a échoué, ce n'est pas « rien trouvé »."""


def service_url() -> str:
    from wama.common.external_sources import base_url
    return base_url('tensorflow_service')


def run(task: str, *, engine: str, models: Iterable[str], image, options: Optional[dict] = None,
        timeout: float = TIMEOUT_S) -> Optional[dict]:
    """La réponse fusionnée des `models` sur `image`, par le service ou par le moteur en processus."""
    import numpy as np
    import requests

    from wama.common.backends.tensorflow_base import TENSORFLOW_SERVICE
    from wama.common.external_sources import proxies_for
    from wama.common.utils.service_supervision import ask_for_service

    models = list(models)
    buffer = io.BytesIO()
    np.save(buffer, image, allow_pickle=False)
    params = json.dumps({'task': task, 'engine': engine, 'models': models, 'options': options or {}})
    try:
        response = requests.post(f'{service_url()}/run', params={'params': params},
                                 data=buffer.getvalue(),
                                 headers={'Content-Type': 'application/octet-stream'},
                                 proxies=proxies_for(TENSORFLOW_SERVICE), timeout=(2, timeout))
    except requests.ConnectionError:
        logger.info('[tensorflow] service injoignable à %s — moteur exécuté dans ce processus',
                    service_url())
        ask_for_service(TENSORFLOW_SERVICE)
        return local_engine.run(task, engine, models, image, options)
    except requests.Timeout:
        logger.warning('[tensorflow] délai dépassé (%s s) — moteur exécuté dans ce processus', timeout)
        return local_engine.run(task, engine, models, image, options)
    if response.status_code == 503:
        return local_engine.run(task, engine, models, image, options)
    if response.status_code != 200:
        raise TensorFlowServiceError(f'service TensorFlow : HTTP {response.status_code} '
                                     f'({response.text[:200]})')
    return response.json()['result']

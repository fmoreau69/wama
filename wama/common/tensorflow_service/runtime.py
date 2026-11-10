"""La préparation d'un processus qui se sert de TensorFlow — UNE fois, avant le premier import.

TOUT backend TensorFlow passe par `tensorflow()` (garde : `tests_tensorflow_service`). Deux modes, et
ce sont les deux décisions du 2026-11-08 (`WAMA_MANIFEST_SPEC §7.1`) :

  • SUR LA CARTE : le service (`service.py`) le déclare par `use_the_card()`. Le `libnvJitLink` de la
    roue est préchargé avant TensorFlow. Mesuré le 2026-11-08 : la `libcusparse.so.12` de TensorFlow
    2.21 demande `__nvJitLink*_12_8`, et le processus résout `libnvJitLink.so.12` par le cache du
    système, qui rend la copie du CUDA 12.0 d'Ubuntu : « Cannot dlopen some GPU libraries », aucune
    carte. PyTorch le corrige pour lui-même (`torch/__init__._load_global_deps`) ; le service n'a
    pas de PyTorch.
  • HORS DE LA CARTE, partout ailleurs : le repli du processus appelant (`service_client`), un
    gunicorn ou un worker. TensorFlow y travaille sur le processeur, parce qu'il ne rend jamais sa
    mémoire de carte avant la fin du processus et que, dans un worker où PyTorch est déjà sur la
    carte, c'est le cas que la doctrine `USE_TF=0` (`wama_worker_env`) existe pour éviter.
"""
from __future__ import annotations

import ctypes
import importlib.metadata
import logging
import threading

logger = logging.getLogger(__name__)

#: La roue qui porte le `libnvJitLink` que les autres roues CUDA attendent.
NVJITLINK_DISTRIBUTION = 'nvidia-nvjitlink-cu12'

_lock = threading.RLock()
_tensorflow = None
_on_the_card = False


def use_the_card() -> None:
    """Ce processus sert TensorFlow sur la carte — appelé par le service, avant le premier import."""
    global _on_the_card
    with _lock:
        if _tensorflow is not None:
            raise RuntimeError('TensorFlow est déjà importé : la carte se déclare avant.')
        _on_the_card = True


def on_the_card() -> bool:
    return _on_the_card


def preload_wheel_nvjitlink() -> bool:
    """Charge la copie de la ROUE, en global, avant que TensorFlow ne résolve le nom par le système.
    Rend vrai si elle a été chargée ; sans la roue (une installation sans CUDA), rien à faire."""
    try:
        files = importlib.metadata.files(NVJITLINK_DISTRIBUTION) or ()
    except importlib.metadata.PackageNotFoundError:
        return False
    for entry in files:
        if entry.name.startswith('libnvJitLink.so'):
            ctypes.CDLL(str(entry.locate()), mode=ctypes.RTLD_GLOBAL)
            return True
    return False


def tensorflow():
    """Le module `tensorflow`, préparé pour ce processus : la seule façon d'y accéder."""
    global _tensorflow, _on_the_card
    with _lock:
        if _tensorflow is not None:
            return _tensorflow
        if _on_the_card:
            preload_wheel_nvjitlink()
        import tensorflow as tf
        if _on_the_card:
            if not tf.config.list_physical_devices('GPU'):
                logger.warning('[tensorflow] aucune carte visible : le service tourne sur le processeur')
                _on_the_card = False
        else:
            try:
                tf.config.set_visible_devices([], 'GPU')
            except RuntimeError:
                # Le contexte est déjà ouvert : quelqu'un a importé TensorFlow hors de cette porte.
                logger.exception('[tensorflow] contexte déjà ouvert, la carte reste visible')
        _tensorflow = tf
        return tf

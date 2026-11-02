"""Amorce des SOUS-PROCESSUS Python que WAMA lance (moteurs vendorisés : MuseTalk, CodeFormer).

Ce fichier n'est jamais importé par WAMA : son DOSSIER est mis en tête du `PYTHONPATH` d'un enfant
(`resource_governor.capped_child_env`), et Python exécute `sitecustomize` au démarrage de tout
interpréteur. Il pose le même plafond d'allocateur CUDA que les processus de WAMA, au premier
import de torch (`configure_cuda_process_when_torch_loads`) — jusqu'au 2026-11-02 les enfants en
étaient exempts, alors qu'un débordement VRAM sous WSL2 fait paniquer la VM entière.

Le gouverneur est chargé PAR SON CHEMIN, sans le paquet `wama` (dont l'`__init__` monte Celery et
Django) : ses imports de module sont ceux de la bibliothèque standard. Ce fichier masque le
`sitecustomize` du système (le crochet d'erreurs d'apport sous Ubuntu), pour l'enfant seulement.
"""
import importlib.util
import os
import sys

_GOVERNOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'resource_governor.py')

try:
    _spec = importlib.util.spec_from_file_location('wama_child_resource_governor', _GOVERNOR)
    _governor = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _governor      # ses classes de données résolvent leur module
    _spec.loader.exec_module(_governor)
    _governor.configure_cuda_process_when_torch_loads()
except Exception:   # l'amorce ne fait jamais échouer le moteur qu'elle précède
    pass

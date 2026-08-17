"""Backends du describer — contrat commun + registre `BackendManager` (brique commune)."""
from wama.common.backends.manager import BackendManager

from .blip_backend import BlipBackend

#: Registre/singletons — brique commune (remplace le boilerplate de manager par-app).
MANAGER = BackendManager('describer')
MANAGER.register('blip', BlipBackend)


def get_blip() -> BlipBackend:
    """Instance singleton (keep_loaded) du backend BLIP."""
    return MANAGER.get_backend('blip')


__all__ = ['BlipBackend', 'MANAGER', 'get_blip']

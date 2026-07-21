"""
WAMA — Système de MANIFESTES (fondation).

Voir `WAMA_MANIFEST_SPEC.md` (racine) pour le formalisme complet.

Principe : union discriminée par `manifest_kind`. Chaque manifeste = ENVELOPPE COMMUNE
(`Envelope`, world/visibility/scope/…) + `body` spécifique au kind, validé contre le kind
enregistré dans `MANIFEST_KINDS`. L'INGEST est idempotent / transactionnel / réversible / traçable,
avec un mode `verify` (diff projection↔état courant) et un SANDBOX (`visibility=private`, promote après
test). Le manifeste est la SOURCE AUTORITAIRE ; les registres fonctionnels restent inchangés et sont
des PROJECTIONS re-synchronisables.

API publique stable :
    from wama.common.manifests import (
        Envelope, WORLDS, VISIBILITIES,
        MANIFEST_KINDS, register_kind, get_kind, ManifestKind,
        validate, ingest, verify, un_ingest, extract, promote,
    )
"""

from .envelope import Envelope, WORLDS, VISIBILITIES
from .kinds import MANIFEST_KINDS, register_kind, get_kind, ManifestKind
from .ingest import validate, ingest, verify, un_ingest, extract, promote

# Enregistrement des kinds fournis (import pour effet de bord : peuple MANIFEST_KINDS).
from . import builtin as _builtin  # noqa: F401

__all__ = [
    'Envelope', 'WORLDS', 'VISIBILITIES',
    'MANIFEST_KINDS', 'register_kind', 'get_kind', 'ManifestKind',
    'validate', 'ingest', 'verify', 'un_ingest', 'extract', 'promote',
]

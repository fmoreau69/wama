"""
Registre des KINDS de manifeste — c'est ce qui EMPÊCHE de mélanger des manifestes sans rapport.

Chaque kind fournit :
  - `validate(body) -> list[str]`   : erreurs de structure du `body` (au-delà de l'enveloppe).
  - `extract(key) -> dict | None`   : LIT l'état courant des registres → produit un manifeste complet
                                      (enveloppe + body). Base du round-trip (spec §2).
  - `verify(manifest) -> list[dict]` : diff manifeste ↔ état courant (facultatif ; défaut = compare au
                                      résultat de `extract`).
  - `project(manifest) -> None`     : ÉCRIT les entrées dérivées dans les registres (facultatif au début ;
                                      projection write-back = chantier ultérieur, cf. spec §6).
  - `un_project(manifest) -> None`  : retire les entrées dérivées (réversibilité).

Un kind SANS `project` est « store+verify only » : le manifeste est stocké et diffable, mais n'écrit
pas encore dans les registres fonctionnels (posture prudente, briques inchangées).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class ManifestKind:
    kind: str
    validate: Callable[[dict], list]                 # body -> [erreurs]
    extract: Optional[Callable[[str], Optional[dict]]] = None   # key -> manifeste complet
    verify: Optional[Callable[[dict], list]] = None             # manifeste -> [diffs]
    # Write-back (facultatif). Contrat RÉEL, tenu par `project_app` comme par `project_library` :
    #   (manifeste: dict, *, apply: bool = False) -> dict
    # `apply=False` = DRY-RUN qui retourne le PLAN ; `apply=True` écrit (idempotent, transactionnel)
    # et retourne ce qui a changé. L'ancienne annotation `Callable[[dict], None]` décrivait ni les
    # arguments ni le retour et faisait diagnostiquer à tort les deux implémentations existantes.
    project: Optional[Callable[..., dict]] = None
    un_project: Optional[Callable[..., dict]] = None
    description: str = ''


MANIFEST_KINDS: dict[str, ManifestKind] = {}


def register_kind(mk: ManifestKind) -> ManifestKind:
    if mk.kind in MANIFEST_KINDS:
        raise ValueError(f"kind '{mk.kind}' déjà enregistré")
    MANIFEST_KINDS[mk.kind] = mk
    return mk


def get_kind(kind: str) -> ManifestKind:
    try:
        return MANIFEST_KINDS[kind]
    except KeyError:
        raise KeyError(
            f"manifest_kind '{kind}' inconnu (enregistrés: {', '.join(sorted(MANIFEST_KINDS)) or '—'})"
        )

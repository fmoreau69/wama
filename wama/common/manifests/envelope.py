"""
Enveloppe COMMUNE à tous les manifestes (union discriminée par `manifest_kind`).

L'enveloppe porte l'IDENTITÉ transverse et la CONFIDENTIALITÉ (diffusion), distincte du gating de
permission (`body.access`, kind `app`). Le `body` est spécifique au kind et validé ailleurs
(`kinds.py`). Ici on valide UNIQUEMENT les champs d'enveloppe — indépendants du kind.

Langue : les chaînes lisibles (`name`, `description`, …) sont en ANGLAIS canonique (pivot i18n WAMA) ;
le manifeste ne porte PAS ses propres traductions (cf. WAMA_MANIFEST_SPEC §1.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# Mondes CLOS (partition de tête ; cf. spec §1.1). Le monde classe la FINALITÉ de l'app, pas son contenu.
WORLDS = ('media', 'data', 'lab', 'transverse')

# Visibilités = ScopedVisibility (confidentialité / diffusion). SANDBOX = 'private'.
VISIBILITIES = ('private', 'project', 'unit', 'public')

SCHEMA_VERSION = '1.0'


@dataclass
class Envelope:
    """Champs communs à TOUS les kinds. `body` = charge utile spécifique au kind."""

    manifest_kind: str                       # app | function | dataset | model | pipeline | project
    key: str                                 # identifiant unique DANS le kind (= slug d'app, code projet…)
    name: str                                # anglais canonique
    world: str = 'transverse'                # media | data | lab | transverse
    schema_version: str = SCHEMA_VERSION
    description: str = ''                     # anglais canonique
    owner: Optional[str] = None              # username créateur ; None = système/builtin
    visibility: str = 'private'              # private (=sandbox) | project | unit | public
    scope_project: Optional[str] = None      # code Project (si visibility=project)
    scope_org_unit: Optional[str] = None     # code OrgUnit (si visibility=unit)
    projects: list = field(default_factory=list)   # traçabilité qualité (['ENA', …])
    source: dict = field(default_factory=dict)     # {type: builtin|library|folder|extract, ref: '...'}
    body: dict = field(default_factory=dict)       # spécifique au kind

    # ── Validation d'enveloppe (indépendante du kind) ──────────────────────────
    def envelope_errors(self) -> list[str]:
        errs: list[str] = []
        if not self.manifest_kind:
            errs.append("manifest_kind manquant")
        if not self.key or not isinstance(self.key, str):
            errs.append("key manquant ou non-str")
        elif not _is_key(self.key):
            errs.append(f"key '{self.key}' contient des caractères interdits (autorisés: alphanumérique + -_:./ )")
        if not self.name:
            errs.append("name manquant")
        if self.world not in WORLDS:
            errs.append(f"world '{self.world}' invalide (attendu: {', '.join(WORLDS)})")
        if self.visibility not in VISIBILITIES:
            errs.append(f"visibility '{self.visibility}' invalide (attendu: {', '.join(VISIBILITIES)})")
        if self.visibility == 'project' and not self.scope_project:
            errs.append("visibility=project exige scope_project (code)")
        if self.visibility == 'unit' and not self.scope_org_unit:
            errs.append("visibility=unit exige scope_org_unit (code)")
        if not isinstance(self.projects, list):
            errs.append("projects doit être une liste")
        if not isinstance(self.source, dict):
            errs.append("source doit être un dict {type, ref}")
        if not isinstance(self.body, dict):
            errs.append("body doit être un dict")
        return errs

    # ── (dé)sérialisation ──────────────────────────────────────────────────────
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Envelope":
        known = {f for f in cls.__dataclass_fields__}   # noqa: E1133 (dataclass fields)
        kwargs = {k: v for k, v in (d or {}).items() if k in known}
        # tolérance : tout champ inconnu de l'enveloppe est ignoré ici (peut appartenir au body brut)
        return cls(**kwargs)

    def to_dict(self) -> dict:
        return asdict(self)


def _is_key(s: str) -> bool:
    """Identifiant d'enveloppe : baseline SÛRE mais namespacée (les model_key valent p.ex.
    'huggingface:Qwen/Qwen-Image', avec ':' '/' et majuscules). Un kind peut imposer plus strict
    dans son `validate` (ex. `app` → slug minuscule). Interdit les espaces et caractères de contrôle."""
    return bool(s) and all(c.isalnum() or c in '-_:./' for c in s)

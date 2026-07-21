"""
Moteur d'INGEST — validate → (sandbox) store → verify → promote → un-ingest.

Propriétés NON négociables (spec §2) :
  - IDEMPOTENT      : ré-ingérer (même kind+key) = UPDATE, jamais de doublon.
  - TRANSACTIONNEL  : tout-ou-rien (@transaction.atomic).
  - RÉVERSIBLE      : `un_ingest` retire la ligne (+ un_project si le kind écrit des dérivés).
  - TRAÇABLE        : `source` conservé ; les dérivés (quand projection) portent `_manifest_key`.
  - VERIFY          : `verify` diffe la projection-depuis-manifeste contre l'état courant des registres.

SANDBOX = un manifeste `visibility='private'`. `promote()` le fait passer au commun (project/unit/public)
après test — réutilise EXACTEMENT ScopedVisibility, pas un nouveau système.

Le manifeste est la SOURCE AUTORITAIRE. Les entrées dérivées ne s'éditent JAMAIS à la main.
"""

from __future__ import annotations

from typing import Any, Optional

from django.db import transaction

from .envelope import Envelope
from .kinds import get_kind


# ── Validation ─────────────────────────────────────────────────────────────────
def validate(manifest: dict) -> list[str]:
    """Erreurs d'enveloppe + erreurs de body (déléguées au kind). Liste vide = valide."""
    env = Envelope.from_dict(manifest)
    errs = list(env.envelope_errors())
    if env.manifest_kind:
        try:
            kind = get_kind(env.manifest_kind)
        except KeyError as e:
            return errs + [str(e)]
        body = manifest.get('body', {}) or {}
        try:
            errs += list(kind.validate(body) or [])
        except Exception as e:   # un validateur ne doit jamais casser l'ingest
            errs.append(f"validateur '{kind.kind}' a levé: {e!r}")
    return errs


# ── Store (idempotent, transactionnel, sandbox par défaut) ──────────────────────
@transaction.atomic
def ingest(manifest: dict, *, user=None, promote_to: Optional[str] = None,
           strict: bool = True):
    """Crée ou met à jour la ligne `Manifest` (idempotent sur kind+key).

    Par défaut le manifeste reste en SANDBOX (`visibility='private'`). Passer `promote_to` pour publier
    directement (project/unit/public) — sinon on teste d'abord, puis `promote()`.
    `strict=True` → lève ValueError si invalide ; sinon stocke quand même avec `errors` renseigné.
    """
    from ..models import Manifest  # import tardif (chargement des apps)

    errs = validate(manifest)
    if errs and strict:
        raise ValueError("Manifeste invalide:\n- " + "\n- ".join(errs))

    env = Envelope.from_dict(manifest)
    visibility = promote_to or env.visibility or 'private'

    obj, _created = Manifest.objects.select_for_update().get_or_create(
        manifest_kind=env.manifest_kind, key=env.key,
        defaults={'name': env.name},
    )
    obj.name = env.name
    obj.world = env.world
    obj.schema_version = env.schema_version
    obj.description = env.description
    obj.owner = user if user is not None else obj.owner
    obj.visibility = visibility
    obj.scope_project = env.scope_project or ''
    obj.scope_org_unit = env.scope_org_unit or ''
    obj.projects = env.projects
    obj.source = env.source
    obj.body = env.body
    obj.errors = errs
    obj.save()
    return obj


def promote(obj, visibility: str, *, scope_project: str = '', scope_org_unit: str = ''):
    """Fait sortir un manifeste du sandbox vers le commun. Le GATING (droit de promouvoir vers telle
    unité/tel projet) est fait par la couche vue (réutilise user_scope_org_ids / user_projects)."""
    obj.visibility = visibility
    obj.scope_project = scope_project
    obj.scope_org_unit = scope_org_unit
    obj.save(update_fields=['visibility', 'scope_project', 'scope_org_unit', 'updated_at'])
    return obj


# ── Extraction (LIT les registres → manifeste) ──────────────────────────────────
def extract(kind: str, key: str) -> Optional[dict]:
    """Produit le manifeste d'un objet EXISTANT en lisant les registres courants (round-trip)."""
    mk = get_kind(kind)
    if not mk.extract:
        raise NotImplementedError(f"kind '{kind}' n'implémente pas extract()")
    return mk.extract(key)


# ── Verify (diff manifeste ↔ état courant) ──────────────────────────────────────
def verify(manifest: dict) -> list[dict]:
    """Retourne la liste des écarts entre le manifeste fourni et l'état courant des registres.

    Si le kind fournit `verify`, on l'utilise. Sinon : on `extract` l'état courant et on diffe les `body`.
    Chaque écart = {path, manifest, current}. Liste vide = fidèle.
    """
    env = Envelope.from_dict(manifest)
    mk = get_kind(env.manifest_kind)
    if mk.verify:
        return list(mk.verify(manifest) or [])
    if not mk.extract:
        raise NotImplementedError(f"kind '{env.manifest_kind}' n'a ni verify ni extract")
    current = mk.extract(env.key) or {}
    return diff_dicts(manifest.get('body', {}) or {}, current.get('body', {}) or {})


# ── Un-ingest (réversible) ───────────────────────────────────────────────────────
@transaction.atomic
def un_ingest(kind: str, key: str) -> bool:
    from ..models import Manifest
    mk = get_kind(kind)
    qs = Manifest.objects.select_for_update().filter(manifest_kind=kind, key=key)
    obj = qs.first()
    if not obj:
        return False
    if mk.un_project:
        mk.un_project(obj.as_manifest())
    obj.delete()
    return True


# ── Utilitaire de diff récursif ──────────────────────────────────────────────────
def diff_dicts(a: Any, b: Any, path: str = '') -> list[dict]:
    """Écarts a(=manifeste) vs b(=courant). Ordre des listes ignoré pour les listes de scalaires."""
    out: list[dict] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out += diff_dicts(a.get(k, _MISSING), b.get(k, _MISSING), f"{path}.{k}" if path else k)
    elif isinstance(a, list) and isinstance(b, list):
        if _all_scalar(a) and _all_scalar(b):
            if sorted(map(_norm, a)) != sorted(map(_norm, b)):
                out.append({'path': path, 'manifest': a, 'current': b})
        else:
            n = max(len(a), len(b))
            for i in range(n):
                ai = a[i] if i < len(a) else _MISSING
                bi = b[i] if i < len(b) else _MISSING
                out += diff_dicts(ai, bi, f"{path}[{i}]")
    else:
        if _norm(a) != _norm(b):
            out.append({'path': path, 'manifest': _show(a), 'current': _show(b)})
    return out


class _Missing:
    def __repr__(self):
        return '∅'


_MISSING = _Missing()


def _all_scalar(xs) -> bool:
    return all(not isinstance(x, (dict, list)) for x in xs)


def _norm(x):
    if x is _MISSING:
        return _MISSING
    if isinstance(x, tuple):
        return list(x)
    return x


def _show(x):
    return '∅ (absent)' if x is _MISSING else x

"""
Kind `function` — EXTRAIT de `FUNCTION_CATALOG` (FunctionSpec) avec repli sur `UserFunction` (DB).

Les fonctions-cartes (WAMA Data) sont DÉJÀ un formalisme (WAMA_DATA_FUNCTION_CARDS.md) : E/S typées sur
`data_types`, params, binding (pure|app|user). Ce kind les enveloppe sans les redéfinir : le body = le
`to_dict()` de la FunctionSpec (moins name/description hissés dans l'enveloppe).

`key` = clé de fonction. Binding : `pure` (fonction data pure) | `app` (bornée à une app, ex.
cam_analyzer) | `user` (UserFunction créée en DB, scoped).
"""

from __future__ import annotations

from typing import Optional

from ..kinds import ManifestKind, register_kind

FUNCTION_BINDINGS = {'pure', 'app', 'user'}


def validate_function_body(body: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(body, dict):
        return ["body 'function' doit être un dict"]
    b = body.get('binding')
    if b and b not in FUNCTION_BINDINGS:
        errs.append(f"binding '{b}' invalide ({', '.join(sorted(FUNCTION_BINDINGS))})")
    for side in ('inputs', 'outputs'):
        v = body.get(side)
        if v is not None and not isinstance(v, list):
            errs.append(f"{side} doit être une liste de ports")
    if 'params' in body and not isinstance(body['params'], list):
        errs.append("params doit être une liste")
    return errs


def _envelope_from_spec(key: str, d: dict, *, owner=None, visibility='public',
                        scope_org_unit=None, scope_project=None) -> dict:
    body = {k: v for k, v in d.items() if k not in ('name', 'description')}
    return {
        'manifest_kind': 'function',
        'key': key,
        'schema_version': '1.0',
        'name': d.get('name', key),
        'description': d.get('description', ''),
        'world': 'data',                 # les fonctions-cartes vivent dans WAMA Data
        'owner': owner,
        'visibility': visibility,
        'scope_org_unit': scope_org_unit,
        'scope_project': scope_project,
        'projects': d.get('projects', []) or [],
        'source': {'type': 'extract', 'ref': f'FUNCTION_CATALOG:{key}'},
        'body': body,
    }


def extract_function(key: str) -> Optional[dict]:
    # 1) catalogue code (FunctionSpec)
    from wama.common.data import function_catalog as fc
    try:
        fc.load_all()
    except Exception:
        pass
    spec = fc.FUNCTION_CATALOG.get(key)
    if spec is not None:
        return _envelope_from_spec(key, spec.to_dict())

    # 2) repli : UserFunction (DB, autorée, scoped)
    try:
        from wama.common.models import UserFunction
        uf = UserFunction.objects.filter(key=key).first()
    except Exception:
        uf = None
    if uf is not None:
        d = uf.to_dict()
        env = _envelope_from_spec(
            key, d,
            owner=uf.owner.get_username() if getattr(uf, 'owner_id', None) else None,
            visibility=uf.visibility,
            scope_org_unit=uf.scope_org_unit.code if getattr(uf, 'scope_org_unit_id', None) else None,
            scope_project=uf.scope_project.code if getattr(uf, 'scope_project_id', None) else None,
        )
        env['source'] = {'type': 'extract', 'ref': f'UserFunction:{key}'}
        return env
    return None


# ── PROJECTION (write-back) — binding `user` SEUL ────────────────────────────────
# Le manifeste `function` d'un LLM/chercheur se projette vers `UserFunction` (DB, scopée) —
# fermeture de la boucle « manifeste → registre → page /model-manager/functions/ » signalée
# ouverte le 2026-08-11. Les fonctions `pure`/`app` vivent dans le catalogue CODE
# (FUNCTION_CATALOG) : leur write-back = code-gen, refusé ici. Traçabilité : tag
# `_manifest-gen` posé à la création — il BORNE ce que `un_write_back_function` a le droit
# de supprimer (une fonction créée par un utilisateur dans l'UI n'est JAMAIS retirée).
_TAG_GEN = '_manifest-gen'
_CHAMPS_FONCTION = ('category', 'tags', 'projects', 'inputs', 'outputs', 'params', 'impl')


def write_back_function(manifest: dict, *, apply: bool = False) -> dict:
    """Projette un manifeste `function` (binding=user) vers `UserFunction`. Dry-run par défaut,
    idempotent (update_or_create par key), réversible (tag `_manifest-gen`). Refuse la collision
    avec une fonction SYSTÈME du catalogue code."""
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from wama.common.models import UserFunction, OrgUnit

    key = manifest.get('key') or ''
    body = manifest.get('body') or {}
    binding = body.get('binding') or 'user'
    if not key:
        return {'function': None, 'error': "manifeste sans `key`"}
    if binding != 'user':
        return {'function': key, 'binding': binding, 'changed': [],
                'skipped': f"binding '{binding}' = catalogue CODE (FUNCTION_CATALOG) — code-gen, "
                           f"pas de projection runtime"}
    from wama.common.data import function_catalog as fc
    try:
        fc.load_all()
    except Exception:
        pass
    if key in fc.FUNCTION_CATALOG:
        return {'function': key, 'error': "collision : une fonction SYSTÈME porte déjà cette clé"}

    owner_name = manifest.get('owner') or body.get('owner') or ''
    owner = get_user_model().objects.filter(username=owner_name).first() if owner_name else None
    if owner is None:
        return {'function': key, 'error': "owner requis (username existant) pour une fonction "
                                          "`user` — l'enveloppe n'en porte pas de résoluble"}

    voulu = {c: body.get(c) if body.get(c) is not None else ([] if c != 'impl' else '')
             for c in _CHAMPS_FONCTION}
    voulu['name'] = manifest.get('name') or key
    voulu['description'] = manifest.get('description') or ''
    voulu['visibility'] = manifest.get('visibility') or 'private'
    unit_code = manifest.get('scope_org_unit') or ''
    unit = OrgUnit.objects.filter(code=unit_code).first() if unit_code else None

    existant = UserFunction.objects.filter(key=key).first()
    actuel = None
    if existant is not None:
        actuel = {c: getattr(existant, c) for c in _CHAMPS_FONCTION}
        actuel.update({'name': existant.name, 'description': existant.description,
                       'visibility': existant.visibility})
    deltas = sorted(c for c, v in voulu.items() if actuel is None or actuel.get(c) != v)

    if not apply:
        return {'function': key, 'created': existant is None, 'owner': owner_name,
                'would_change': deltas, 'target': voulu,
                'unresolved_org_unit': unit_code if unit_code and unit is None else None}
    tags = list(voulu['tags'] or [])
    if _TAG_GEN not in tags:
        tags.append(_TAG_GEN)
    voulu['tags'] = tags
    with transaction.atomic():
        obj, cree = UserFunction.objects.update_or_create(
            key=key, defaults={**voulu, 'owner': owner, 'scope_org_unit': unit})
    return {'function': key, 'created': cree, 'changed': deltas,
            '_manifest_key': f'function:{key}'}


def un_write_back_function(manifest: dict, *, apply: bool = False) -> dict:
    """Retire la `UserFunction` projetée — UNIQUEMENT si elle porte le tag `_manifest-gen`
    (réversibilité bornée à ce que la projection a créé, jamais une fonction autorée en UI)."""
    from wama.common.models import UserFunction

    key = manifest.get('key') or ''
    obj = UserFunction.objects.filter(key=key).first()
    if obj is None:
        return {'function': key, 'removed': False, 'reason': 'absente du registre'}
    if _TAG_GEN not in (obj.tags or []):
        return {'function': key, 'removed': False,
                'reason': "fonction autorée en UI (pas de tag _manifest-gen) — retrait refusé"}
    if not apply:
        return {'function': key, 'would_remove': True}
    obj.delete()
    return {'function': key, 'removed': True}


register_kind(ManifestKind(
    kind='function',
    validate=validate_function_body,
    extract=extract_function,
    write_back=write_back_function,
    un_write_back=un_write_back_function,
    description="Fonction-carte WAMA Data (extrait de FUNCTION_CATALOG ou UserFunction) : E/S typées sur "
                "data_types + params + binding (pure|app|user). PROJECTION binding=user → UserFunction "
                "(tag _manifest-gen, réversible) ; pure/app = catalogue code (code-gen).",
))

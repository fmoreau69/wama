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


register_kind(ManifestKind(
    kind='function',
    validate=validate_function_body,
    extract=extract_function,
    description="Fonction-carte WAMA Data (extrait de FUNCTION_CATALOG ou UserFunction) : E/S typées sur "
                "data_types + params + binding (pure|app|user).",
))

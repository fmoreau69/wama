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
    # Facettes de port (rôle en entrée, estimateur en sortie — 2026-09-09) : la MÊME règle que
    # le catalogue, pour qu'un manifeste ingéré ne puisse pas déclarer ce que le code refuse.
    from wama.common.catalog.function_catalog import validate_port_facet
    for side, sens in (('inputs', 'input'), ('outputs', 'output')):
        v = body.get(side)
        if v is None:
            continue
        if not isinstance(v, list):
            errs.append(f"{side} doit être une liste de ports")
            continue
        for p in v:
            if isinstance(p, dict):
                errs.extend(f"{side}: {m}" for m in validate_port_facet(p, sens))
    if 'params' in body and not isinstance(body['params'], list):
        errs.append("params doit être une liste")
    return errs


def _spec_world(spec) -> Optional[str]:
    """Monde d'une fonction du catalogue = celui de l'APP qui la porte (route §10.6 point 6.1).

    Liée à une app (`binding: app`) : l'app qu'elle nomme. Pure : l'app Django qui contient son
    implémentation. Le monde se lit ensuite dans la déclaration de cette app (`app_world`) —
    il était écrit `'data'` en dur ici, donc faux pour les fonctions du Lab. None si l'app ne se
    trouve pas ou n'a rien déclaré : le manifeste est alors refusé, pas rangé par défaut.
    """
    from wama.common.app_registry import app_world
    from wama.common.catalog.function_catalog import spec_app
    app = spec_app(spec)
    return app_world(app) if app else None


def _envelope_from_spec(key: str, d: dict, *, world, owner=None, visibility='public',
                        scope_org_unit=None, scope_project=None) -> dict:
    body = {k: v for k, v in d.items() if k not in ('name', 'description')}
    return {
        'manifest_kind': 'function',
        'key': key,
        'schema_version': '1.0',
        'name': d.get('name', key),
        'description': d.get('description', ''),
        'world': world,
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
    from wama.common.catalog import function_catalog as fc
    try:
        fc.load_all()
    except Exception:
        pass
    spec = fc.FUNCTION_CATALOG.get(key)
    if spec is not None:
        return _envelope_from_spec(key, spec.to_dict(), world=_spec_world(spec))

    # 2) repli : UserFunction (DB, autorée, scoped)
    try:
        from wama.common.models import UserFunction
        uf = UserFunction.objects.filter(key=key).first()
    except Exception:
        uf = None
    if uf is not None:
        from ..ownership import envelope_of
        # Une fonction UTILISATEUR naît dans le Calculator, module du monde Data (route §10.6
        # point 6.3 B) : elle n'a pas d'app porteuse d'où déduire son monde.
        env = _envelope_from_spec(key, uf.to_dict(), world='data', **envelope_of(uf))
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
    from django.db import transaction
    from wama.common.models import UserFunction

    from ..ownership import row_fields

    key = manifest.get('key') or ''
    body = manifest.get('body') or {}
    binding = body.get('binding') or 'user'
    if not key:
        return {'function': None, 'error': "manifeste sans `key`"}
    if binding != 'user':
        return {'function': key, 'binding': binding, 'changed': [],
                'skipped': f"binding '{binding}' = catalogue CODE (FUNCTION_CATALOG) — code-gen, "
                           f"pas de projection runtime"}
    from wama.common.catalog import function_catalog as fc
    try:
        fc.load_all()
    except Exception:
        pass
    if key in fc.FUNCTION_CATALOG:
        return {'function': key, 'error': "collision : une fonction SYSTÈME porte déjà cette clé"}

    owner_name = manifest.get('owner') or body.get('owner') or ''
    fields = row_fields({**manifest, 'owner': owner_name})
    owner = fields['owner']
    if owner is None:
        return {'function': key, 'error': "owner requis (username existant) pour une fonction "
                                          "`user` — l'enveloppe n'en porte pas de résoluble"}

    voulu = {c: body.get(c) if body.get(c) is not None else ([] if c != 'impl' else '')
             for c in _CHAMPS_FONCTION}
    voulu['name'] = manifest.get('name') or key
    voulu['description'] = manifest.get('description') or ''
    voulu['visibility'] = fields['visibility']

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
                'unresolved_org_unit': fields['unresolved'].get('scope_org_unit'),
                'unresolved_project': fields['unresolved'].get('scope_project')}
    tags = list(voulu['tags'] or [])
    if _TAG_GEN not in tags:
        tags.append(_TAG_GEN)
    voulu['tags'] = tags
    with transaction.atomic():
        obj, cree = UserFunction.objects.update_or_create(
            key=key, defaults={**voulu, 'owner': owner, 'scope_org_unit': fields['scope_org_unit'],
                               'scope_project': fields['scope_project']})
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

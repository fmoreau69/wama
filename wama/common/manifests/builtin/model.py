"""
Kind `model` — EXTRAIT du catalogue `AIModel` (source unique de lecture, model_manager).

Comme `app`, c'est un kind EXTRAIT (l'objet existe en DB) → `extract(key)` + round-trip.

Principe DÉCLARATIF (important) : le manifeste capte ce que le modèle EST (identité, capacités, besoins,
formats), PAS l'état runtime de CETTE installation (`is_loaded`/`is_available`/`is_downloaded`/`local_path`/
timestamps). Un manifeste est portable ; l'état d'install/charge est volatile et propre à l'hôte → EXCLU.
Le round-trip diffe donc les seuls champs déclaratifs.

`key` = `model_key` (format 'source:model_id', p.ex. 'huggingface:Qwen/Qwen-Image' — d'où la clé
d'enveloppe namespacée, cf. envelope._is_key).
"""

from __future__ import annotations

from typing import Optional

from ..kinds import ManifestKind, register_kind


def _model_types() -> set:
    from wama.model_manager.models import ModelType
    return set(ModelType.values)


def _model_sources() -> set:
    from wama.model_manager.models import ModelSource
    return set(ModelSource.values)


def validate_model_body(body: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(body, dict):
        return ["body 'model' doit être un dict"]

    ident = body.get('identity') or {}
    if not isinstance(ident, dict):
        errs.append("identity doit être un dict")
    else:
        mt = ident.get('model_type')
        if mt and mt not in _model_types():
            errs.append(f"identity.model_type '{mt}' hors ModelType ({', '.join(sorted(_model_types()))})")
        src = ident.get('source')
        if src and src not in _model_sources():
            errs.append(f"identity.source '{src}' hors ModelSource ({', '.join(sorted(_model_sources()))})")

    res = body.get('resources') or {}
    if res and not isinstance(res, dict):
        errs.append("resources doit être un dict")
    elif isinstance(res, dict):
        for k in ('vram_gb', 'ram_gb', 'disk_gb'):
            v = res.get(k)
            if v is not None and (not isinstance(v, (int, float)) or v < 0):
                errs.append(f"resources.{k} doit être un nombre ≥ 0 (reçu {v!r})")

    caps = body.get('capabilities')
    if caps is not None and not isinstance(caps, dict):
        errs.append("capabilities doit être un dict (JSON de capacités)")
    return errs


def extract_model(key: str) -> Optional[dict]:
    from wama.model_manager.models import AIModel

    m = AIModel.objects.filter(model_key=key).first()
    if m is None:
        return None

    body = {
        # identité déclarative
        'identity': {
            'model_type': m.model_type,
            'source': m.source,
            'hf_id': m.hf_id or None,
            'description_short': m.description_short or None,
        },
        # besoins (pilotent select_model VRAM-aware)
        'resources': {
            'vram_gb': m.vram_gb,
            'ram_gb': m.ram_gb,
            'disk_gb': m.disk_gb,
        },
        # formats & conversions
        'formats': {
            'format': m.format or None,
            'preferred_format': m.preferred_format or None,
            'can_convert_to': getattr(m, 'can_convert_to', None) or [],
        },
        # capacités fonctionnelles = source unique (filtrage UI, sélection par tâche, compat I/O)
        'capabilities': m.capabilities or {},
        # provenance / proposition (méta déclarative, pas de l'état de charge)
        'provenance': {
            'backend_ref': getattr(m, 'backend_ref', '') or None,
            'is_proposed': getattr(m, 'is_proposed', False),
            'proposal_kind': getattr(m, 'proposal_kind', '') or None,
            'confidence': getattr(m, 'confidence', None),
            'update_complexity': getattr(m, 'update_complexity', '') or None,
        },
        'extra_info': m.extra_info or {},
    }

    return {
        'manifest_kind': 'model',
        'key': m.model_key,
        'schema_version': '1.0',
        'name': m.name,
        'description': m.description or '',
        'world': 'transverse',          # les modèles sont des assets transverses
        'visibility': 'public',
        'projects': [],
        'source': {'type': 'extract', 'ref': f'AIModel:{m.model_key}'},
        'body': body,
    }


register_kind(ManifestKind(
    kind='model',
    validate=validate_model_body,
    extract=extract_model,
    description="Modèle IA (extrait d'AIModel) : identité/besoins/formats/capacités déclaratifs. "
                "Exclut l'état runtime (loaded/available/downloaded/local_path/timestamps).",
))

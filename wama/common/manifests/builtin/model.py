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
        ref = ident.get('platform_ref')
        if ref:
            from wama.model_manager.models import AIModel
            plateforme = str(ref).partition(':')[0]
            connues = sorted(AIModel._URL_PAR_PLATEFORME)
            if ':' not in str(ref):
                errs.append(f"identity.platform_ref '{ref}' doit s'ecrire '<plateforme>:<identifiant>'")
            elif plateforme not in connues:
                errs.append(f"identity.platform_ref plateforme '{plateforme}' inconnue ({', '.join(connues)})")

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
            # Licence et identite plateforme : declarees ici, projetees dans AIModel.
            # L'URL de la page n'est PAS portee — elle se derive de `platform_ref`
            # (AIModel.platform_url), sinon un changement de schema d'adresse chez une
            # plateforme perimerait autant de chaines stockees qu'il y a de modeles.
            'license': m.license or None,
            # `author` voyage AVEC `license` : une licence à attribution est inapplicable sans
            # le nom à citer, donc les séparer reviendrait à porter une obligation sans le moyen
            # de la tenir.
            'author': m.author or None,
            'platform_ref': m.platform_ref or None,
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


# Champs DECLARATIFS d'un modele — les seuls qu'un manifeste ait autorite a poser.
# Tout le reste (is_downloaded, is_loaded, local_path, vram_gb, capabilities, quality_index…) est
# soit de l'etat runtime, soit le produit de la DECOUVERTE : un manifeste n'a pas a en decider.
_CHAMPS_PROJETES = [
    ('license', lambda m, b: (b.get('identity') or {}).get('license') or ''),
    ('author', lambda m, b: (b.get('identity') or {}).get('author') or ''),
    ('platform_ref', lambda m, b: (b.get('identity') or {}).get('platform_ref') or ''),
    # `hf_id` rejoint les champs projetés (2026-08-12) : c'est un fait d'identité de PLATEFORME,
    # de la même nature que `platform_ref`, et la découverte ne sait pas le produire pour les
    # modèles trouvés par scan disque. Il n'était pas projetable tant que `model_sync` le
    # remettait à vide à chaque passe — ce n'est plus le cas.
    ('hf_id', lambda m, b: (b.get('identity') or {}).get('hf_id') or ''),
]


def write_back_model(manifest: dict, *, apply: bool = False) -> dict:
    """
    Projette le manifeste vers `AIModel` — la jambe manifeste → registre pour le kind `model`.

    ⚠ DIFFERENCE ASSUMEE avec `library` : on ne CREE jamais une ligne. Une librairie se declare,
    un modele se DECOUVRE — il existe parce que des poids sont sur le disque. Faire naitre un
    AIModel depuis un manifeste fabriquerait un modele fantome, sans fichier, que la selection
    pourrait retenir. Si la cible est absente, on le DIT et on ne fait rien.

    Ne projette que `license` et `platform_ref` : ce sont les deux champs que le catalogue ne
    sait pas deduire seul (releve le 2026-08-05 — 0/129 modeles portaient une licence, et le lien
    plateforme etait conditionne a `hf_id`, absent sur les 70 modeles decouverts par scan disque).
    """
    from django.db import transaction

    from wama.model_manager.models import AIModel

    body = manifest.get('body') or {}
    key = manifest.get('key') or ''   # meme emplacement que pour `library` — verifie, pas suppose
    if not key:
        return {'model': None, 'erreur': "manifeste sans `key`"}

    voulu = {champ: calc(manifest, body) for champ, calc in _CHAMPS_PROJETES}
    cible = AIModel.objects.filter(model_key=key).first()
    if cible is None:
        return {'model': key, 'absent': True, 'target': voulu,
                'erreur': "aucun AIModel de cette cle — un modele se decouvre, il ne se cree pas "
                          "depuis un manifeste. Lancer `sync_models` d'abord."}

    actuel = {champ: getattr(cible, champ) for champ, _ in _CHAMPS_PROJETES}
    deltas = {c: {'de': actuel.get(c), 'vers': v} for c, v in voulu.items() if actuel.get(c) != v}
    preserves = ['is_downloaded', 'is_loaded', 'local_path', 'capabilities', 'vram_gb']

    if not apply:
        return {'model': key, 'would_change': sorted(deltas), 'target': voulu,
                'preserved': preserves}

    with transaction.atomic():
        for champ, valeur in voulu.items():
            setattr(cible, champ, valeur)
        cible.save(update_fields=list(voulu))
    return {'model': key, 'changed': sorted(deltas), 'preserved': preserves}


def un_write_back_model(manifest: dict, *, apply: bool = False) -> dict:
    """
    Réversibilité : vide les champs déclaratifs projetés, sans toucher au reste.

    On ne supprime PAS la ligne `AIModel` — elle n'a pas été créée par le manifeste (cf.
    `write_back_model`), elle existe parce que des poids sont sur le disque. La révoquer
    reviendrait à faire disparaître du catalogue un modèle bel et bien installé.
    """
    from wama.model_manager.models import AIModel

    key = manifest.get('key') or ''
    cible = AIModel.objects.filter(model_key=key).first()
    if cible is None:
        return {'model': key, 'absent': True}

    vides = {champ: '' for champ, _ in _CHAMPS_PROJETES}
    portes = sorted(c for c in vides if getattr(cible, c))
    if not apply:
        return {'model': key, 'would_clear': portes, 'preserved': ['la ligne AIModel elle-même']}

    for champ, valeur in vides.items():
        setattr(cible, champ, valeur)
    cible.save(update_fields=list(vides))
    return {'model': key, 'cleared': portes, 'preserved': ['la ligne AIModel elle-même']}


register_kind(ManifestKind(
    kind='model',
    validate=validate_model_body,
    extract=extract_model,
    write_back=write_back_model,
    un_write_back=un_write_back_model,
    description="Modèle IA (extrait d'AIModel) : identité/besoins/formats/capacités déclaratifs. "
                "Exclut l'état runtime (loaded/available/downloaded/local_path/timestamps).",
))

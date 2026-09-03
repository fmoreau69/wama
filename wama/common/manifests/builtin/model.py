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

    prompts = body.get('prompts')
    if prompts is not None and not isinstance(prompts, dict):
        errs.append("prompts doit être un dict")
    elif isinstance(prompts, dict):
        contract = prompts.get('contract')
        if contract is not None and not isinstance(contract, str):
            errs.append("prompts.contract doit être une chaîne (markdown, anglais)")

    errs += _validate_composition(body.get('composition'))
    return errs


def _validate_composition(compo) -> list[str]:
    """
    Anatomie d'un modèle COMPOSÉ (2026-08-27, cas d'école MiniMax-Music3 : 5 GGUF = 1 modèle).

    `composition.components` = [{role, pattern[, format]}] — le rôle nomme la fonction du
    composant dans la chaîne (language_model, transformer, vocoder…), le pattern désigne son
    fichier (motif glob HF `allow_patterns`). `composition.runtime` = {engine[, …]} — le
    moteur d'exécution que le backend composé invoquera. Vocabulaire des rôles OUVERT (chaque
    architecture a le sien) ; la forme, elle, est fermée. Absent/vide = modèle mono-fichier,
    cas général.
    """
    if compo is None or compo == {}:
        return []
    if not isinstance(compo, dict):
        return ["composition doit être un dict {components, runtime}"]
    errs: list[str] = []

    comps = compo.get('components')
    if comps is not None:
        if not isinstance(comps, list) or not comps:
            errs.append("composition.components doit être une liste non vide")
        else:
            roles: set = set()
            for i, c in enumerate(comps):
                if not isinstance(c, dict):
                    errs.append(f"composition.components[{i}] doit être un dict")
                    continue
                role, pattern = c.get('role'), c.get('pattern')
                if not role or not isinstance(role, str):
                    errs.append(f"composition.components[{i}] : 'role' requis (chaîne)")
                elif role in roles:
                    errs.append(f"composition.components : role '{role}' dupliqué")
                else:
                    roles.add(role)
                if not pattern or not isinstance(pattern, str):
                    errs.append(f"composition.components[{role or i}] : 'pattern' requis "
                                "(motif de fichier, style allow_patterns)")
                fmt = c.get('format')
                if fmt is not None and not isinstance(fmt, str):
                    errs.append(f"composition.components[{role or i}] : 'format' doit être une chaîne")

    runtime = compo.get('runtime')
    if runtime is not None:
        if not isinstance(runtime, dict):
            errs.append("composition.runtime doit être un dict")
        elif not runtime.get('engine') or not isinstance(runtime.get('engine'), str):
            errs.append("composition.runtime : 'engine' requis (chaîne — le moteur que le "
                        "backend composé invoque)")

    inconnues = set(compo) - {'components', 'runtime'}
    if inconnues:
        errs.append(f"composition : clés inconnues {sorted(inconnues)} (components|runtime)")
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
        # contrat de sortie du prompt (fait DÉCLARÉ comme license — le skill d'app porte la
        # méthode, le modèle porte son contrat ; cf. prompt_skills/README.md, 2026-08-26)
        'prompts': {
            'contract': m.prompt_contract or None,
        },
        # anatomie d'un modèle composé + moteur d'exécution (fait DÉCLARÉ, 2026-08-27) —
        # {} pour un modèle mono-fichier, le cas général.
        'composition': getattr(m, 'composition', None) or {},
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
        # Composition (SPEC §7.3) : la LIBRAIRIE que le moteur de ce modèle exige — la
        # jambe qui manquait à la matrice d'intégration (audit du 2026-09-03 : `app→modèle`
        # et `app→librairie` étaient déclarés, `modèle→librairie` vivait UNIQUEMENT dans le
        # `PIP_PACKAGES` du backend, c'est-à-dire dans du code Python).
        'requires': _requires_librairies(body),
        'body': body,
    }


def _requires_librairies(body: dict) -> list:
    """Librairies à citer dans le `requires` d'un manifeste de modèle.

    RÈGLE — la MÊME que la jambe `library` d'une app (`library_index.librairies_de`), et
    pour la même raison : deux conditions CUMULATIVES.
      1. le BACKEND qui sert le moteur déclaré du modèle exige la distribution
         (fait déclaré au contrat commun : `PIP_PACKAGES`/`REQUIRED_PACKAGES`) ;
      2. la distribution est SEMÉE au corpus `manifests/libraries/` (décision humaine).

    La 2ᵉ n'est pas cosmétique : `ingest.valider()` traite une référence `requires`
    pendante comme une ERREUR — citer une lib non semée invaliderait le manifeste du
    modèle, donc l'app qui le requiert. Best-effort : jamais bloquant (un inventaire
    indisponible ne doit pas empêcher d'extraire un manifeste).
    """
    engine = ((body.get('composition') or {}).get('runtime') or {}).get('engine')
    if not engine:
        return []
    try:
        from wama.common.backends.manager import engine_backends
        from wama.common.services.library_index import SOCLE_PLATEFORME, _normalise, semees
        cls = engine_backends().get(engine)
        if cls is None:
            return []
        # Nom de DISTRIBUTION seul : `pip_install_spec` rend des pins exacts
        # (« qwen-tts==0.1.1 ») ; une référence `requires` désigne la lib, pas sa version.
        dists = {s.partition('==')[0].strip() for s in (cls.pip_install_spec() or [])}
        sem = semees()
        return [{'kind': 'library', 'key': d} for d in sorted(dists)
                if _normalise(d) in sem and _normalise(d) not in SOCLE_PLATEFORME]
    except Exception:
        logger.debug("[manifest:model] inventaire des librairies indisponible", exc_info=True)
        return []


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
    # Contrat de sortie du prompt (2026-08-26) : fait déclaré de même nature que `license` —
    # la découverte ne peut pas le produire, et `capabilities` (réécrit par le sync) ne peut
    # pas le porter. Injecté au system prompt d'enrichissement (prompt_enrichment).
    ('prompt_contract', lambda m, b: (b.get('prompts') or {}).get('contract') or ''),
    # Anatomie d'un modèle composé (2026-08-27) : même nature déclarée. Consommée par
    # l'installation (allow_patterns dérivés) et par le backend composé (quoi charger, avec
    # quel moteur). Vide = modèle mono-fichier.
    ('composition', lambda m, b: b.get('composition') or {}),
]

#: Champ projeté SOUS CONDITION — cf. `_capabilities_projectable`.
_CAPABILITIES_FIELD = ('capabilities', lambda m, b: b.get('capabilities') or {})


def _capabilities_projectable(target) -> bool:
    """Le manifeste a-t-il autorité pour poser `capabilities` sur CETTE ligne ?

    OUI seulement si personne d'autre ne les produit : un modèle **orphelin de déclaration**,
    catalogué par le balayage générique des snapshots HF (aucune app ne le déclare, donc la
    découverte n'a rien à en dire et sa `capabilities` reste vide).

    NON dès qu'une app le déclare : c'est alors la DÉCOUVERTE qui fait autorité — elle lit les
    flags sur les classes de backend (`supports_cloning`…) et les `languages` du `model_config`.
    La règle « un modèle se DÉCOUVRE » n'est donc pas entamée : on ne comble qu'un VIDE, on ne
    conteste jamais un fait.

    Motif (2026-08-31, route F4b) : sans cette porte, un modèle installé par la prospection ne
    peut JAMAIS acquérir de capacités — donc jamais apparaître dans une app filtrée par capacité.
    Le sync ne les efface plus (`model_sync` : un `{}` de découverte ne remplace plus un fait).
    """
    if getattr(target, 'backend_ref', ''):
        return False                     # une app le sert : la découverte parle pour lui
    return not (getattr(target, 'capabilities', None) or {})


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

    # Capacités : projetées UNIQUEMENT sur un modèle orphelin de déclaration (cf. la fonction).
    champs = list(_CHAMPS_PROJETES)
    if _capabilities_projectable(cible) and (body.get('capabilities') or {}):
        champs.append(_CAPABILITIES_FIELD)
        voulu[_CAPABILITIES_FIELD[0]] = _CAPABILITIES_FIELD[1](manifest, body)

    actuel = {champ: getattr(cible, champ) for champ, _ in champs}
    deltas = {c: {'de': actuel.get(c), 'vers': v} for c, v in voulu.items() if actuel.get(c) != v}
    preserves = ['is_downloaded', 'is_loaded', 'local_path', 'vram_gb']
    if not any(c == _CAPABILITIES_FIELD[0] for c, _ in champs):
        preserves.append('capabilities')

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

    # Le « vide » respecte le type du champ : '' pour les textes, {} pour composition (JSON).
    vides = {champ: ({} if champ == 'composition' else '') for champ, _ in _CHAMPS_PROJETES}
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

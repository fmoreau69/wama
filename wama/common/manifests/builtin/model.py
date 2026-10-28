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

import logging
import re
from typing import Optional

from ..kinds import ManifestKind, register_kind
from ..ownership import envelope_of

logger = logging.getLogger(__name__)


def _model_types() -> set:
    from wama.model_manager.models import ModelType
    return set(ModelType.values)


def _model_sources() -> set:
    from wama.model_manager.models import ModelSource
    return set(ModelSource.values)


#: Champs d'identité RETIRÉS du formalisme — `hf_id` le 2026-10-27 (`platform_ref` seul, R181). Un
#: manifeste qui en porte un est REFUSÉ : il ne serait plus lu par personne, et un LLM nourri
#: d'anciens exemples peut encore l'écrire (les rôles wama-dev-ai l'ôtent par cette même liste).
RETIRED_IDENTITY_FIELDS = ('hf_id',)


def validate_model_body(body: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(body, dict):
        return ["body 'model' doit être un dict"]

    ident = body.get('identity') or {}
    if not isinstance(ident, dict):
        errs.append("identity doit être un dict")
    else:
        for field in RETIRED_IDENTITY_FIELDS:
            if field in ident:
                errs.append(f"identity.{field} est retiré du formalisme : déclarer identity.platform_ref")
        mt = ident.get('model_type')
        if mt and mt not in _model_types():
            errs.append(f"identity.model_type '{mt}' hors ModelType ({', '.join(sorted(_model_types()))})")
        src = ident.get('source')
        if src and src not in _model_sources():
            errs.append(f"identity.source '{src}' hors ModelSource ({', '.join(sorted(_model_sources()))})")
        ref = ident.get('platform_ref')
        if ref:
            # Les plateformes DÉCLARÉES au registre des sources (`model_platforms`, 2026-10-22) —
            # la même liste que celle qui rend le lien de la card.
            from wama.common.external_sources import model_platforms
            plateforme = str(ref).partition(':')[0]
            connues = sorted(model_platforms())
            if ':' not in str(ref):
                errs.append(f"identity.platform_ref '{ref}' doit s'ecrire '<plateforme>:<identifiant>'")
            elif plateforme not in connues:
                errs.append(f"identity.platform_ref plateforme '{plateforme}' inconnue ({', '.join(connues)})")
        # Regime d'acces : vocabulaire FERME, et surtout PAS de booleen. HF rend `False`, WAMA
        # ecrit 'no' — accepter les deux ferait deux ecritures du meme fait, dont une seule se
        # projetterait. Absent = inconnu, ce qui est une reponse legitime (et differente de 'no').
        pubs = ident.get('publications')
        if pubs is not None and (not isinstance(pubs, list)
                                 or not all(isinstance(p, str) and p for p in pubs)):
            errs.append("identity.publications doit être une liste d'identifiants arXiv "
                        "(chaînes, ex. « 2601.14251 »)")
        # Modèle de BASE (2026-10-27) : le vocabulaire du Hub, en paire — sans sa relation, un
        # `base_model` ne dit pas si la ligne EST ce modèle (quantification) ou s'appuie dessus.
        base, relation = ident.get(_BASE_MODEL_KEY), ident.get(_BASE_RELATION_KEY)
        if (base is None) != (relation is None):
            errs.append(f"identity.{_BASE_MODEL_KEY} et identity.{_BASE_RELATION_KEY} vont "
                        "ensemble (le dépôt de base et ce que la ligne en est)")
        elif base is not None:
            if not isinstance(base, str) or base.strip().count('/') != 1:
                errs.append(f"identity.{_BASE_MODEL_KEY} {base!r} doit être un dépôt du Hub "
                            "« org/nom »")
            from wama.model_manager.models import BASE_MODEL_RELATIONS
            if relation not in BASE_MODEL_RELATIONS:
                errs.append(f"identity.{_BASE_RELATION_KEY} {relation!r} hors du vocabulaire du "
                            f"Hub ({', '.join(BASE_MODEL_RELATIONS)})")
        gated = ident.get('gated')
        if gated is not None and gated not in ('no', 'auto', 'manual'):
            errs.append(f"identity.gated {gated!r} invalide — 'no' (verifie libre), 'auto' "
                        "(acceptation en ligne) ou 'manual' (approbation humaine) ; "
                        "omettre la cle quand c'est INCONNU, ne jamais ecrire un booleen")

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
    elif isinstance(caps, dict):
        # Entrées : ids d'INPUT_TYPES, vocabulaire FERMÉ (2026-09-29). Le 1er manifeste écrit par
        # un rôle LLM pour un modèle texte→image déclarait `inputs_optional: [seed, steps, cfg]` —
        # des RÉGLAGES, pas des entrées — et passait pour « VALIDE ». Mesuré avant d'ajouter la
        # règle : 0 valeur hors vocabulaire sur tout le catalogue.
        from wama.common.utils.app_modes import INPUT_TYPES
        for key in ('inputs_required', 'inputs_optional'):
            off = [v for v in (caps.get(key) or []) if v not in INPUT_TYPES]
            if off:
                errs.append(f"capabilities.{key} {off} hors INPUT_TYPES "
                            f"({', '.join(sorted(INPUT_TYPES))}) — une entrée est une DONNÉE "
                            "fournie au modèle, pas un réglage (seed, steps…)")

    prompts = body.get('prompts')
    if prompts is not None and not isinstance(prompts, dict):
        errs.append("prompts doit être un dict")
    elif isinstance(prompts, dict):
        contract = prompts.get('contract')
        if contract is not None and not isinstance(contract, str):
            errs.append("prompts.contract doit être une chaîne (markdown, anglais)")

    errs += _validate_composition(body.get('composition'))
    errs += _validate_quality(body.get('quality'))
    return errs


def _validate_quality(quality) -> list[str]:
    """`quality.defect` = {label, reason, source} — un DÉFAUT MESURÉ, validé par un administrateur
    (2026-10-28). Les trois sont des chaînes non vides, et la source porte sa DATE : un constat sans
    date vieillit en silence."""
    if quality is None or quality == {}:
        return []
    if not isinstance(quality, dict):
        return ["quality doit être un dict {defect}"]
    errs = [f"quality : clés inconnues {sorted(set(quality) - {'defect'})} (defect)"] \
        if set(quality) - {'defect'} else []
    defect = quality.get('defect')
    if defect is None:
        return errs
    if not isinstance(defect, dict):
        return errs + ["quality.defect doit être un dict {label, reason, source}"]
    for key in ('label', 'reason', 'source'):
        if not isinstance(defect.get(key), str) or not defect[key].strip():
            errs.append(f"quality.defect.{key} requis (chaîne non vide)")
    if isinstance(defect.get('source'), str) and not re.search(r'20\d\d-\d\d-\d\d', defect['source']):
        errs.append("quality.defect.source doit porter sa date (AAAA-MM-JJ)")
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
                role, pattern, repo = c.get('role'), c.get('pattern'), c.get('repo')
                if not role or not isinstance(role, str):
                    errs.append(f"composition.components[{i}] : 'role' requis (chaîne)")
                elif role in roles:
                    errs.append(f"composition.components : role '{role}' dupliqué")
                else:
                    roles.add(role)
                # DEUX façons de nommer un morceau, et il en faut EXACTEMENT une (2026-09-04) :
                #   `pattern` — un motif de FICHIER dans le dépôt du modèle (cas d'origine :
                #               MiniMax-Music3, 5 GGUF dans un seul dépôt) ;
                #   `repo`    — un dépôt HF FRÈRE, publié à part mais sans existence propre
                #               pour l'usage (pyannote : la « recette » diarization-3.1 ne
                #               contient qu'un config.yaml, ses poids SONT segmentation-3.0 et
                #               wespeaker-…-LM, qu'elle nomme elle-même).
                # Le schéma n'admettait que `pattern` : déclarer la diarisation était donc
                # impossible, et c'est ce qui poussait à écrire les noms en dur dans le
                # substrat. Un formalisme qui ne sait pas dire un cas réel se fait contourner.
                if not pattern and not repo:
                    errs.append(f"composition.components[{role or i}] : 'pattern' (motif de "
                                "fichier dans le dépôt du modèle) ou 'repo' (dépôt HF frère) "
                                "requis — l'un des deux nomme le morceau")
                elif pattern and repo:
                    errs.append(f"composition.components[{role or i}] : 'pattern' ET 'repo' "
                                "déclarés — un morceau est dans le dépôt OU dans un autre, "
                                "pas les deux")
                elif pattern and not isinstance(pattern, str):
                    errs.append(f"composition.components[{role or i}] : 'pattern' doit être une chaîne")
                elif repo and (not isinstance(repo, str) or '/' not in repo):
                    errs.append(f"composition.components[{role or i}] : 'repo' doit être un "
                                "identifiant de dépôt « org/nom »")
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
            # Regime d'ACCES au depot amont (False | 'auto' | 'manual'). Absent tant qu'il est
            # INCONNU — un manifeste muet dit « je ne sais pas », alors qu'un `false` ecrit
            # affirmerait « libre » sur un depot jamais interroge.
            **({'gated': m.gated} if m.gated else {}),
            # Publications rattachées par l'auteur (identifiants arXiv, 2026-10-10) — fait
            # DÉCLARÉ comme la licence, absent tant qu'aucune carte ne l'a dit.
            **({_PUBLICATIONS_KEY: list((m.extra_info or {})[_PUBLICATIONS_KEY])}
               if (m.extra_info or {}).get(_PUBLICATIONS_KEY) else {}),
            # Modèle de BASE d'une ligne qui DÉCLARE sa relation (2026-10-27 : le canonique d'un
            # GGUF, `quantized`) — fait de même nature que les publications, absent sinon. Le
            # `base_model` d'une LoRA reste dans `extra_info` : il vient de la déclaration d'app.
            **_base_model_identity(m.extra_info or {}),
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
        # Défaut MESURÉ validé par un administrateur (2026-10-28) — absent tant qu'aucun ne l'est.
        **({'quality': {'defect': dict((m.extra_info or {})[_QUALITY_DEFECT_KEY])}}
           if (m.extra_info or {}).get(_QUALITY_DEFECT_KEY) else {}),
        # provenance / proposition (méta déclarative, pas de l'état de charge)
        'provenance': {
            'backend_ref': getattr(m, 'backend_ref', '') or None,
            'is_proposed': getattr(m, 'is_proposed', False),
            'proposal_kind': getattr(m, 'proposal_kind', '') or None,
            'confidence': getattr(m, 'confidence', None),
            'update_complexity': getattr(m, 'update_complexity', '') or None,
        },
        # Les publications (et le modèle de base déclaré) sont portés par `identity` : pas une
        # seconde fois ici.
        'extra_info': {k: v for k, v in (m.extra_info or {}).items()
                       if k not in (_PUBLICATIONS_KEY, _QUALITY_DEFECT_KEY)
                       and k not in _base_model_identity(m.extra_info or {})},
    }

    # Provenance LUE sur la ligne (`ROADMAP §29` étape 3) — elle y naît, au geste d'installation.
    # Un modèle système garde exactement l'enveloppe d'avant (public, sans propriétaire ni portée) :
    # les champs vides ne s'écrivent pas, le corpus ne bouge pas.
    envelope = envelope_of(m)
    return {
        'manifest_kind': 'model',
        'key': m.model_key,
        'schema_version': '1.0',
        'name': m.name,
        'description': m.description or '',
        'world': 'transverse',          # les modèles sont des assets transverses
        'visibility': envelope.pop('visibility'),
        **{k: v for k, v in envelope.items() if v},
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
        # L'inventaire STATIQUE (`backend_inventory._DeclaredEngine`, 2026-09-07) rend un porteur
        # sans classe : on résout alors la classe par le chemin commun (`resolve_backend`). Sans
        # ce retour, l'`AttributeError` tombait dans le `except` ci-dessous et tout modèle dont le
        # moteur n'est vu QUE par cet inventaire sortait sans `requires` (mesuré le 2026-10-16 :
        # MuScriptor, dont le manifeste autoré citait muscriptor et beat-this).
        if not hasattr(cls, 'pip_install_spec'):
            from wama.common.services.backend_inventory import resolve_backend
            cls = resolve_backend(engine)
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


# Champs DECLARATIFS d'un modele — projetes tels quels par le manifeste. `capabilities` se
# projette a part, par FUSION clé par clé (`merged_capabilities`, route F4b). Tout le reste
# (is_downloaded, is_loaded, local_path, vram_gb, quality_index…) est soit de l'etat runtime,
# soit un FAIT mesure par la decouverte : un manifeste n'a pas a en decider.
_CHAMPS_PROJETES = [
    ('license', lambda m, b: (b.get('identity') or {}).get('license') or ''),
    ('author', lambda m, b: (b.get('identity') or {}).get('author') or ''),
    ('platform_ref', lambda m, b: (b.get('identity') or {}).get('platform_ref') or ''),
    # Contrat de sortie du prompt (2026-08-26) : fait déclaré de même nature que `license` —
    # la découverte ne peut pas le produire, et `capabilities` (réécrit par le sync) ne peut
    # pas le porter. Injecté au system prompt d'enrichissement (prompt_enrichment).
    ('prompt_contract', lambda m, b: (b.get('prompts') or {}).get('contract') or ''),
]

#: Champ projeté PAR FUSION, clé par clé — cf. `merged_capabilities`.
_CAPABILITIES_FIELD = 'capabilities'

#: Regime d'acces — projete SEULEMENT si le manifeste le DECLARE (2026-09-07).
#: Il ne peut pas rejoindre `_CHAMPS_PROJETES` : ces lambdas rendent '' quand la cle manque, ce
#: qui EFFACERAIT un regime connu des qu'un manifeste muet passerait. Or ici le vide n'est pas
#: une valeur, c'est l'absence de mesure — « je ne sais pas » n'autorise pas a oublier ce qu'on
#: savait. Meme raison que `merged_capabilities`, autre cause.
_GATED_FIELD = ('gated', lambda m, b: (b.get('identity') or {}).get('gated') or '')

#: Anatomie d'un modèle composé (2026-08-27) — même nature déclarée que `license` : le manifeste
#: a autorité, la découverte jamais. Consommée par l'installation (`allow_patterns` dérivés), par
#: le backend composé (quoi charger, avec quel moteur) et, depuis le 2026-09-19, par le poids PAR
#: COMPOSANT (`components_for_spec`).
#:
#: 🔴 SORTIE de `_CHAMPS_PROJETES` le 2026-09-20, pour la RAISON DÉJÀ ÉCRITE au-dessus pour
#: `gated` : ces lambdas rendent leur vide quand la clé manque, donc un manifeste MUET
#: EFFAÇAIT l'anatomie de la ligne. Le risque n'était pas théorique — **131 des 141 manifestes
#: de modèle ne portent aucun `components`** (relevé du 2026-09-20), et l'anatomie de 28 modèles
#: vient d'y entrer : un seul `apply_manifests` sur un manifeste en retard suffisait à la perdre,
#: en silence, juste après l'avoir déclarée.
#: *Un champ dont le VIDE n'est pas une valeur mais une absence de mesure ne se projette qu'au
#: DÉCLARÉ* — et la révocation délibérée reste la voie pour effacer (`un_write_back_model`).
_COMPOSITION_FIELD = ('composition', lambda m, b: b.get('composition') or {})

#: Publications (2026-10-10) : projetées dans `extra_info` (clé collante de `model_sync`), et
#: seulement si le manifeste les DÉCLARE — même règle que `gated` et `composition`. Pas de colonne
#: dédiée : un champ ajouté au modèle est servi par gunicorn avant que sa migration passe.
_PUBLICATIONS_KEY = 'publications'

#: Modèle de BASE (2026-10-27) — le vocabulaire de la carte d'un modèle du Hub (`base_model` +
#: `base_model_relation`), projeté dans `extra_info` comme les publications : au déclaré, en paire.
#: C'est le second fait que `hf_id` portait (le modèle canonique d'un GGUF tiré par Ollama, que le
#: banc apparie), séparé de `platform_ref` (d'où viennent les poids).
_BASE_MODEL_KEY = 'base_model'
_BASE_RELATION_KEY = 'base_model_relation'

#: Défaut MESURÉ validé par un administrateur (2026-10-28) — `body.quality.defect`, projeté dans
#: `extra_info` (clé collante de `model_sync`) et seulement s'il est DÉCLARÉ, comme les publications.
#: Sœur de `exclusion` (une décision humaine qui ÉCARTE un modèle, `is_available=False`, masqué
#: partout) : un défaut GRISE le modèle avec sa raison et le sort du tirage automatique, il reste
#: listé. Lu par `model_quality.declared_defect`.
_QUALITY_DEFECT_KEY = 'quality_defect'


def _base_model_identity(extra_info: dict) -> dict:
    """`{base_model, base_model_relation}` d'une ligne qui DÉCLARE sa relation, `{}` sinon."""
    if not extra_info.get(_BASE_RELATION_KEY):
        return {}
    return {_BASE_MODEL_KEY: extra_info.get(_BASE_MODEL_KEY),
            _BASE_RELATION_KEY: extra_info[_BASE_RELATION_KEY]}


def merged_capabilities(target, declared: dict) -> dict:
    """`capabilities` de la ligne APRÈS projection du manifeste — fusion CLÉ PAR CLÉ.

    Deux régimes, selon qui produit les capacités de CETTE ligne :

      • une app la sert (`backend_ref` posé) : la DÉCOUVERTE fait autorité — elle lit les flags
        sur les classes de backend (`supports_cloning`…) et les `languages` du `model_config`.
        Le manifeste ne fait que COMBLER les clés qu'elle n'a pas écrites ; il ne conteste
        jamais une valeur établie ;
      • ligne orpheline de déclaration (balayage générique des snapshots HF, Ollama, cloud) :
        personne d'autre ne les produit, le manifeste fait autorité clé par clé — et les clés
        qu'il ne nomme pas restent ce qu'elles sont (un manifeste muet n'efface rien).

    Jusqu'au 2026-09-18 la porte était « tout ou rien » (`_capabilities_projectable`, route F4b
    du 31/08) : le manifeste ne posait ses capacités que sur une ligne orpheline ENCORE VIDE.
    Mesuré sur 8 modèles installés depuis le 02/09 : la tâche du spec, écrite directement en
    base, fermait la porte, et plus aucune capacité (modalités, entrées, langues) ne pouvait
    ensuite venir du manifeste. Une porte à usage unique n'est pas une règle d'autorité — la
    fusion par clé, si. Le sync, lui, n'efface toujours rien (`model_sync` : un `{}` de
    découverte ne remplace pas un fait).
    """
    actuel = dict(getattr(target, 'capabilities', None) or {})
    declared = dict(declared or {})
    if getattr(target, 'backend_ref', ''):
        return {**declared, **actuel}      # la découverte garde ses valeurs, le manifeste comble
    return {**actuel, **declared}          # ligne orpheline : le manifeste tranche clé par clé


def write_back_model(manifest: dict, *, apply: bool = False) -> dict:
    """
    Projette le manifeste vers `AIModel` — la jambe manifeste → registre pour le kind `model`.

    ⚠ DIFFERENCE ASSUMEE avec `library` : on ne CREE jamais une ligne. Une librairie se declare,
    un modele se DECOUVRE — il existe parce que des poids sont sur le disque. Faire naitre un
    AIModel depuis un manifeste fabriquerait un modele fantome, sans fichier, que la selection
    pourrait retenir. Si la cible est absente, on le DIT et on ne fait rien.

    Projette les champs DECLARATIFS (`_CHAMPS_PROJETES` : licence, auteur, plateforme,
    contrat de prompt), `gated`, `composition`, les publications et le modèle de base seulement
    s'ils sont DECLARES (leur vide est une absence de mesure, pas une valeur), et `capabilities`
    par FUSION clé par clé
    (`merged_capabilities`). Le releve d'origine (2026-08-05) ne projetait que `license`
    et `platform_ref` : 0/129 modeles portaient une licence, et le lien plateforme etait
    conditionne a `hf_id`, absent sur les 70 modeles decouverts par scan disque.

    La PROVENANCE (propriétaire, portée) n'est pas projetée : pour un modèle elle naît sur la
    ligne, au geste d'installation, et le manifeste la lit (sens SORTANT, `ROADMAP §29` étape 3).
    Un manifeste en retard ne rend donc jamais un modèle privé à quelqu'un, ni ne publie un modèle
    privé. Elle ne change que par la promotion (`ownership.promote_row`).
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

    # Capacités : fusion clé par clé (cf. `merged_capabilities`) — projetée seulement si elle
    # change quelque chose, pour que `changed`/`preserved` disent la vérité.
    champs = [c for c, _ in _CHAMPS_PROJETES]
    merged = merged_capabilities(cible, body.get('capabilities') or {})
    if merged != (cible.capabilities or {}):
        champs.append(_CAPABILITIES_FIELD)
        voulu[_CAPABILITIES_FIELD] = merged
    # Regime d'acces : seulement si DECLARE — sinon la ligne garde ce qu'elle sait (cf. _GATED_FIELD).
    if (body.get('identity') or {}).get('gated'):
        champs.append(_GATED_FIELD[0])
        voulu[_GATED_FIELD[0]] = _GATED_FIELD[1](manifest, body)
    # Anatomie : meme regle, et pour la meme raison (cf. _COMPOSITION_FIELD) — un manifeste muet
    # ne doit pas effacer une composition connue.
    if body.get('composition'):
        champs.append(_COMPOSITION_FIELD[0])
        voulu[_COMPOSITION_FIELD[0]] = _COMPOSITION_FIELD[1](manifest, body)
    # Publications : au déclaré seulement, fusionnées dans `extra_info` sans toucher au reste.
    pubs = (body.get('identity') or {}).get(_PUBLICATIONS_KEY)
    if pubs:
        champs.append('extra_info')
        voulu['extra_info'] = {**(cible.extra_info or {}), _PUBLICATIONS_KEY: list(pubs)}
    # Modèle de base : même règle — au déclaré seulement, la paire fusionnée dans `extra_info`.
    base = {k: (body.get('identity') or {}).get(k) for k in (_BASE_MODEL_KEY, _BASE_RELATION_KEY)}
    if all(base.values()):
        if 'extra_info' not in champs:
            champs.append('extra_info')
        voulu['extra_info'] = {**voulu.get('extra_info', cible.extra_info or {}), **base}
    # Défaut mesuré : même règle — au déclaré seulement (un manifeste muet ne dégrise rien).
    defect = (body.get('quality') or {}).get('defect')
    if defect:
        if 'extra_info' not in champs:
            champs.append('extra_info')
        voulu['extra_info'] = {**voulu.get('extra_info', cible.extra_info or {}),
                               _QUALITY_DEFECT_KEY: dict(defect)}

    actuel = {champ: getattr(cible, champ) for champ in champs}
    deltas = {c: {'de': actuel.get(c), 'vers': v} for c, v in voulu.items() if actuel.get(c) != v}
    preserves = ['is_downloaded', 'is_loaded', 'local_path', 'vram_gb']
    if _CAPABILITIES_FIELD not in champs:
        preserves.append('capabilities')
    if _GATED_FIELD[0] not in champs:
        preserves.append('gated')
    if _COMPOSITION_FIELD[0] not in champs:
        preserves.append(_COMPOSITION_FIELD[0])

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
    # ⚠ `composition` a quitté `_CHAMPS_PROJETES` (elle ne se projette plus qu'au DÉCLARÉ), mais
    # la RÉVOCATION doit continuer de l'effacer : c'est le geste délibéré, la seule voie qui a le
    # droit de le faire. L'oublier ici aurait laissé une anatomie derrière une révocation.
    vides = {champ: '' for champ, _ in _CHAMPS_PROJETES}
    vides[_COMPOSITION_FIELD[0]] = {}
    # Le défaut mesuré aussi (2026-10-28) : la révocation est le geste qui DÉGRISE.
    if _QUALITY_DEFECT_KEY in (cible.extra_info or {}):
        vides['extra_info'] = {k: v for k, v in cible.extra_info.items() if k != _QUALITY_DEFECT_KEY}
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

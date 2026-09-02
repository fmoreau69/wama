"""
Sélection intelligente de modèles — centralisée pour toutes les apps WAMA.

S'appuie sur le catalogue `AIModel` (source de vérité : téléchargé ? chargé ? VRAM,
capacités via `capabilities` — canonique ; `extra_info` = opérationnel/transition) et la
VRAM live (`memory_monitor`). Unifie les logiques
jusque-là dupliquées par app (anonymizer `ModelSelector`, transcriber `manager`, et le
`backend_selector` VRAM-aware qui était planifié).

Principe : model_manager = cerveau + source de vérité ; les apps appellent ce service
(ou en font de fins adaptateurs). Voir `memory/project_model_manager_centralization.md`.
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def get_free_vram_gb() -> Optional[float]:
    """VRAM libre (Go) du GPU le plus libre, ou None si indéterminable."""
    try:
        from .memory_monitor import WAMAMemoryMonitor
        gpus = WAMAMemoryMonitor().get_gpu_usage()
        if gpus:
            return max((g.free_gb for g in gpus), default=None)
    except Exception as e:
        logger.debug(f"[model_selector] free VRAM indéterminable : {e}")
    return None


def _specialization_ok(model, requested) -> bool:
    """
    Un modèle SPÉCIALISÉ (`capabilities['specialisation']`) n'entre dans un lot que si
    l'appelant demande sa spécialité — sinon il concourt à armes inégales dans un pool
    généraliste (cas `translategemma:12b`, spécialiste traduction que rien ne distinguait :
    Ollama lui rend `completion, vision` comme à un généraliste). Réciproquement, demander
    une spécialité ne retient QUE les modèles qui la portent. Cf. `SPECIALISATIONS_OLLAMA`.
    """
    # ⚠ `'specialisation'` reste tel quel : c'est une CLÉ DE DONNÉES stockée en base
    # (frontière de la règle de nommage — ce qui est stocké reste, ce qui est calculé
    # se renomme). Seuls les identifiants passent à l'anglais.
    spec = (model.capabilities or {}).get('specialisation')
    return spec == requested if requested else not spec


def _supports(model, requires, classes) -> bool:
    """Filtre capacités via `capabilities` (source canonique) — `requires` = clés truthy ;
    `classes` ⊆ capabilities['classes'].

    Réconciliation C1 (REMOVAL_LEDGER F3) : `capabilities` est LA source (lue aussi par WamaModelCaps,
    lang_routing, get_registry_models). `extra_info` = repli de TRANSITION (ancien emplacement, +
    l'alias historique `class_list` des modèles YOLO) tant que la découverte n'a pas tout basculé.
    """
    caps = model.capabilities or {}
    ei = model.extra_info or {}
    if requires and not all(caps.get(k) or ei.get(k) for k in requires):
        return False
    if classes:
        supported = set(caps.get('classes') or ei.get('classes') or ei.get('class_list') or [])
        if not set(classes).issubset(supported):
            return False
    return True


def _rank_key(pool, domain=None):
    """
    Fabrique la clé de tri « (déjà chargé, qualité) » pour CE lot de candidats.

    ⚠ POURQUOI LA CLÉ DÉPEND DU LOT. L'ancienne version faisait
    `quality_index if not None else vram_gb`, c'est-à-dire qu'elle comparait **deux échelles
    incommensurables** : l'indice va de −26,7 (embeddings) à 58,7 (qwen3.6:35b), la VRAM de 0,1
    à 24 Go. Un modèle porteur d'un indice battait donc mécaniquement tout modèle qui n'en avait
    pas, quel que soit son mérite — et poser un premier indice mesuré sur un YOLO aurait suffi à
    fausser toute la sélection vision (constaté le 2026-08-12 en préparant la boucle qualité).

    Règle : on ne compare des indices QUE si tout le lot en a un ; sinon on retombe sur `vram_gb`
    pour TOUT LE MONDE. On ne mélange jamais les deux. `NULL` reste « inconnu », pas « mauvais ».

    Étage BENCHMARK (2026-08-19, échelle des signaux : a priori < benchmark tiers < mesure
    interne) : même règle de lot, un étage au-dessus — si TOUT le lot porte un
    `benchmark_index` (mesure tierce Artificial Analysis, `sync_benchmarks`), c'est lui qui
    ordonne ; sinon l'a priori si tout le lot en a un ; sinon la VRAM. Trois échelles,
    jamais mélangées — une couverture benchmark PARTIELLE retombe donc sur l'a priori,
    ce qui est l'incitation à compléter l'appariement, pas un bug.

    Effet sur l'existant : nul tant que `sync_benchmarks` n'a pas tourné (benchmark_index
    NULL partout → étage inerte) ; ensuite, les lots 100 % appariés (LLM Ollama) passent
    sur la mesure tierce.
    """
    # L'ÉCHELLE DES SIGNAUX vit désormais dans `_quality_scalars` (02/09) — un seul
    # domicile pour le TRI (ici) et le SCORE pondéré du curseur (`_best_by_vram`) :
    # sous-indice de domaine (2026-08-19 : qwen3.8 = 52,0 en général, 68,1 en coding —
    # un rôle codegen trie là-dessus) si TOUT le lot le porte, sinon benchmark tiers
    # COMPARABLE (jamais `benchmark_index` nu : un WER se trie à l'envers d'un Elo, seul
    # le module qui écrit l'échelle connaît son sens), sinon a priori, sinon VRAM.
    scalars, _ = _quality_scalars(pool, domain)

    def sort_key(m):
        return (m.is_loaded, scalars[id(m)])
    return sort_key


#: Curseur de QUALITÉ — échelle CONTINUE 0-100 (décision Fabien 02/09, remplaçant les
#: 3 politiques discrètes du même matin : « l'intention ne devrait pas être un
#: branchement, elle devrait être un POIDS dans le score » — 3 crans ne savaient
#: désigner que 3 candidats sur N). La valeur voyage TELLE QUELLE (0-100) de l'UI au
#: score ; les presets sont des POSITIONS NOMMÉES sur l'échelle, pas des stratégies.
QUALITY_DEFAULT = 50
#: (clé, libellé, position) — trio canonique Rapide/Équilibré/Qualité (« Précis » était
#: trop étroit face à une conversion ou une synthèse ; le converter garde sa nuance en
#: sous-libellé local « Rapide (web) »). Partagé par le slider (graduations), les barres
#: de presets de LOT et le filemanager — un seul domicile.
QUALITY_PRESETS = (
    ('fast', 'Rapide', 15),
    ('balanced', 'Équilibré', 50),
    ('quality', 'Qualité', 85),
)
#: Au-delà de ce cran, la qualité prime au point d'ASSUMER le coût : le budget VRAM
#: cesse de borner (offload ou attente AWAITING_RESOURCES) et la préférence au modèle
#: RÉSIDENT s'efface (un petit modèle déjà chargé ne vole plus le tirage).
QUALITY_OFFLOAD_THRESHOLD = 80

#: Tolérance : les 3 politiques de la 1ʳᵉ implémentation (stockées quelques heures) et
#: les clés de presets résolvent vers leur position — rien de reçu ne casse un lancement.
_NAMED_QUALITY = {'fast': 15, 'balanced': 50, 'precise': 85, 'quality': 85}


def _quality_weight(value) -> float:
    """0-100 (nombre, chaîne, ou position nommée) → poids [0,1]. Inconnu = équilibré."""
    if isinstance(value, str):
        named = _NAMED_QUALITY.get(value.strip().lower())
        if named is not None:
            value = named
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = QUALITY_DEFAULT
    return max(0.0, min(100.0, v)) / 100.0


def _quality_scalars(pool, domain=None):
    """Valeur de QUALITÉ scalaire par modèle — l'ÉCHELLE DES SIGNAUX, en un seul domicile.

    Même règle de lot que partout (a priori < benchmark tiers < mesure interne, jamais
    deux échelles mélangées) : sous-indice de domaine si TOUT le lot le porte, sinon
    benchmark comparable, sinon a priori, sinon la VRAM en PROXY assumé. `_rank_key`
    (le tri) et le score pondéré (le curseur) lisent tous deux ce barème.

    Retour : ({id(m): valeur}, proxy_vram) — le drapeau dit si la « qualité » n'est que
    la taille (utile aux appelants pour doser leur confiance).
    """
    def _sub_index(m):
        return ((getattr(m, 'benchmark_meta', None) or {}).get('sous_indices') or {}).get(domain)

    from .benchmark_sync import benchmarks_comparable, valeur_ordonnable
    domain_usable = bool(domain) and bool(pool) and all(
        _sub_index(m) is not None for m in pool)
    tous_benchmarkes = benchmarks_comparable(pool)
    tous_qualifies = bool(pool) and all(m.quality_index is not None for m in pool)

    if domain_usable:
        return {id(m): _sub_index(m) for m in pool}, False
    if tous_benchmarkes:
        return {id(m): valeur_ordonnable(m) for m in pool}, False
    if tous_qualifies:
        return {id(m): m.quality_index for m in pool}, False
    return {id(m): (m.vram_gb or 0) for m in pool}, True


def _minmax(valeurs: dict) -> dict:
    """Normalisation min-max d'un dict {clé: nombre} vers [0,1] (lot constant → 0.5)."""
    if not valeurs:
        return {}
    lo, hi = min(valeurs.values()), max(valeurs.values())
    if hi == lo:
        return {k: 0.5 for k in valeurs}
    return {k: (v - lo) / (hi - lo) for k, v in valeurs.items()}


def _best_by_vram(models, budget_gb: Optional[float], domain=None, quality_intent=None):
    """
    Parmi `models`, le meilleur compromis QUALITÉ/COÛT au poids du CURSEUR (0-100) :

        score = w·qualité + (1−w)·légèreté        (w = curseur/100, valeurs min-max du lot)

    - curseur bas → la légèreté domine (chargement + inférence rapides — la « preview ») ;
    - curseur haut (≥ QUALITY_OFFLOAD_THRESHOLD) → le budget cesse de borner : l'offload
      ou l'attente AWAITING_RESOURCES est le prix ASSUMÉ de la qualité ;
    - entre les deux, CHAQUE cran déplace réellement l'arbitrage — sur N candidats
      admissibles, tous sont atteignables (c'était l'objection de Fabien aux 3 politiques).

    ⚠ Le nom `_best_by_vram` est conservé mais il ne dit plus la vérité depuis longtemps :
    « le plus gros qui tient » assimilait volume et qualité, ce qu'un MoE dément
    frontalement (`qwen3.6:35b` : la qualité d'un 36B au coût de calcul d'un 3B). La VRAM
    reste une CONTRAINTE (budget) et un COÛT (le terme légèreté), plus un critère seule.

    Deux gardes MESURÉES (02/09) :
    - une VRAM inconnue (None/0) n'est pas « gratuite » : coût = PIRE du lot — Audio8
      (vram_gb=0, jamais mesurée) battait Kokoro (0,5 mesuré) sur « rapide » par accident ;
    - à score égal, la QUALITÉ départage (epsilon) — indispensable quand le lot n'a que le
      proxy VRAM : qualité et coût sont alors le MÊME axe, le score serait plat à w=0,5 ;
      l'epsilon y rétablit le comportement historique (« le plus qualitatif qui tient »).
    """
    w = _quality_weight(quality_intent)
    depasse_budget = (w * 100.0) >= QUALITY_OFFLOAD_THRESHOLD
    if budget_gb is None or depasse_budget:
        pool = models
    else:
        fit = [m for m in models if (m.vram_gb or 0) <= budget_gb]
        if not fit:
            return min(models, key=lambda m: (m.vram_gb or 0))
        pool = fit

    q = _minmax(_quality_scalars(pool, domain)[0])
    # Coût = VRAM MESURÉE, normalisée sur les seuls modèles qui en ont une ; inconnue → 1.0.
    mesures = {id(m): m.vram_gb for m in pool if m.vram_gb}
    c = _minmax(mesures)

    def score(m):
        cout = c.get(id(m), 1.0)
        return w * q[id(m)] + (1.0 - w) * (1.0 - cout) + 1e-6 * q[id(m)]

    return max(pool, key=score)


def select_model(
    source: Optional[str] = None,
    *,
    model_type: Optional[str] = None,
    requires: Optional[List[str]] = None,
    classes: Optional[List[str]] = None,
    prefer_loaded: bool = True,
    downloaded_only: bool = True,
    vram_budget_gb: Optional[float] = None,
    candidates: Optional[List[str]] = None,
    name_contains: Optional[str] = None,
    priority: Optional[List[str]] = None,
    availability_probe=None,
    benchmark_domain: Optional[str] = None,
    specialization: Optional[str] = None,
    quality_intent=None,
):
    """
    Choisit le meilleur `AIModel` pour `source` (valeur ModelSource), ou None.

    Args:
        source:          app/source ('transcriber', 'anonymizer', 'imager', …).
        model_type:      filtre ModelType ('speech', 'vision', …).
        requires:        capacités requises (clés truthy de `capabilities` ; repli `extra_info`).
        classes:         classes à couvrir (⊆ `capabilities['classes']` — ex. anonymizer).
        prefer_loaded:   si un candidat est déjà RÉSIDENT, le renvoyer d'office (règle
                         keep_loaded — évite un rechargement coûteux en batch). Résidence =
                         `is_loaded` (que seul Ollama tient, via /api/ps) OU le registre VRAM
                         partagé, qui traverse les process — voir le corps de la fonction.
        downloaded_only: ne considérer que les modèles téléchargés.
        vram_budget_gb:  budget VRAM explicite ; si None, lecture de la VRAM libre live.
        candidates:      restreindre à une liste de model_key.
        name_contains:   sous-chaîne (model_key ou name), insensible à la casse.
        priority:        ordre de préférence (sous-chaînes de model_key/name). Si fourni,
                         DOMINE la VRAM : le 1er palier de priorité ayant des candidats
                         l'emporte (utile aux apps « par moteur » à défaut délibéré, ex.
                         Transcriber whisper-first — ≠ logique VRAM-greedy).
        availability_probe: callable(AIModel)->bool — disponibilité RUNTIME au-delà du
                         catalogue (ex. import Python réellement possible). Permet de
                         couvrir les apps « backend-class » sans se fier au seul
                         is_downloaded du catalogue.
        benchmark_domain: domaine de compétence à privilégier ('coding', 'math' —
                         `benchmark_meta['sous_indices']`, alimenté par `sync_benchmarks`).
                         Trie sur CE domaine si TOUT le lot le porte, sinon redescend d'un
                         étage. « Le meilleur » dépend de ce qu'on demande : qwen3.8 vaut
                         52,0 en général mais 68,1 en coding.
        specialization:  spécialité EXIGÉE ('translation'…). Sans elle, les modèles
                         spécialisés sont ÉCARTÉS du lot (cf. `_specialization_ok`).
        quality_intent:  curseur de qualité 0-100 (cf. `_best_by_vram` — poids dans le
                         score, jamais un branchement). ≥ QUALITY_OFFLOAD_THRESHOLD :
                         budget et préférence au RÉSIDENT s'effacent (un petit modèle
                         déjà chargé ne vole pas le tirage quand la qualité prime).
                         Positions nommées tolérées ('fast'/'balanced'/'quality').

    Returns:
        AIModel | None.
    """
    from ..models import AIModel

    # `source=None` (2026-08-31) : sélection PAR CAPACITÉ, tous producteurs confondus —
    # symétrique de `get_registry_models`. C'est le mode des surfaces qui ne sont pas des
    # apps (vocalisation de l'assistant, nœud studio, passerelle converter→enhancer) : elles
    # demandent « ce qui sait faire X », pas « ce que l'app Y déclare ».
    # ⚠ `model_type` devient alors OBLIGATOIRE : sans app pour borner le lot, c'est la
    # CATÉGORIE qui empêche de charger un modèle de vision pour parler. On lève plutôt que
    # de deviner — cette fonction va faire CHARGER le modèle choisi.
    if not source and not model_type:
        raise ValueError(
            "select_model : préciser `source` (une app) ou `model_type` (une catégorie). "
            "Une sélection sans borne piocherait dans tout le catalogue.")
    qs = AIModel.objects.filter(is_available=True)
    if source:
        qs = qs.filter(source=source)
    else:
        qs = qs.filter(is_proposed=False)   # un candidat de prospection n'a pas de poids
    if downloaded_only:
        qs = qs.filter(is_downloaded=True)
    if model_type:
        qs = qs.filter(model_type=model_type)
    if candidates:
        qs = qs.filter(model_key__in=candidates)

    models = list(qs)
    if name_contains:
        nc = name_contains.lower()
        models = [m for m in models if nc in m.model_key.lower() or nc in (m.name or '').lower()]

    models = [m for m in models if _supports(m, requires, classes)
              and _specialization_ok(m, specialization)]

    # Grisage AUTOMATIQUE (décision Fabien 02/09, solde le pending du 31/08) : un modèle
    # POSITIVEMENT sans backend (moteur déclaré qu'aucun inventaire ne sert) sort de la
    # SÉLECTION — un tirage inlançable est toujours faux (vécu : chatterbox prévu à
    # curseur 50, refus garanti au lancement). Verdict permissif et RELU à chaque appel :
    # le backend qui apparaît ré-autorise tout seul. Le SELECT, lui, continue d'afficher
    # ces modèles — grisés avec la raison (get_registry_models) — jamais d'exclusion de
    # liste (INPUT_MODEL_MATCHING §2).
    try:
        from wama.common.backends.manager import backend_missing
        exclus = [m for m in models if backend_missing(m)]
        if exclus:
            logger.info("[model_selector] exclus du tirage (sans backend) : %s",
                        [m.model_key for m in exclus])
            models = [m for m in models if m not in exclus]
    except Exception as e:
        logger.debug(f"[model_selector] inventaire de backends indisponible : {e}")

    # Disponibilité runtime (au-delà du catalogue) : ex. l'import Python du backend.
    if availability_probe:
        def _probe(m):
            try:
                return bool(availability_probe(m))
            except Exception as e:
                logger.debug(f"[model_selector] probe a échoué pour {m.model_key}: {e}")
                return False
        models = [m for m in models if _probe(m)]

    if not models:
        logger.info(f"[model_selector] aucun modèle pour source={source} "
                    f"(type={model_type}, classes={classes}, requires={requires})")
        return None

    budget = vram_budget_gb if vram_budget_gb is not None else get_free_vram_gb()

    # Résidence RÉELLE, lue une fois (un appel Redis, pas un par palier de priorité).
    # `AIModel.is_loaded` seul rendait `prefer_loaded` inerte : rien dans le dépôt
    # n'écrit jamais `is_loaded=True`, et de toute façon un modèle vit dans le process
    # qui l'a chargé (worker Celery, service TTS) — invisible du process qui arbitre.
    # Le registre VRAM partagé, lui, traverse les process. On garde `is_loaded` en plus :
    # il reste la vérité pour les sources qui la tiennent vraiment (Ollama via /api/ps).
    residents = set()
    if prefer_loaded:
        try:
            from wama.common.services.resource_governor import resident_models
            residents = set(resident_models())
        except Exception as e:
            logger.debug(f"[model_selector] résidence indisponible : {e}")

    def _pick(pool):
        # keep_loaded prioritaire, puis meilleur compromis — SAUF au-delà du seuil de
        # qualité : la résidence est un raccourci de COÛT, et la qualité paie ce coût.
        _w = _quality_weight(quality_intent)
        if prefer_loaded and (_w * 100.0) < QUALITY_OFFLOAD_THRESHOLD:
            loaded = [m for m in pool if m.is_loaded or m.model_key in residents]
            if loaded:
                return _best_by_vram(loaded, budget, benchmark_domain, quality_intent)
        return _best_by_vram(pool, budget, benchmark_domain, quality_intent)

    # Priorité explicite : le 1er palier ayant des candidats l'emporte (domine la VRAM).
    if priority:
        for p in priority:
            pl = p.lower()
            tier = [m for m in models if pl in m.model_key.lower() or pl in (m.name or '').lower()]
            if tier:
                choice = _pick(tier)
                logger.info(f"[model_selector] {source} → {choice.model_key} (priorité « {p} »)")
                return choice

    choice = _pick(models)
    logger.info(f"[model_selector] {source} → {choice.model_key} (vram_gb={choice.vram_gb}, budget={budget})")
    return choice


def list_models(source: str, downloaded_only: bool = True) -> List[dict]:
    """Liste des modèles d'une source (dicts to_dict — description courte/longue + vram)."""
    from ..models import AIModel
    qs = AIModel.objects.filter(source=source, is_available=True)
    if downloaded_only:
        qs = qs.filter(is_downloaded=True)
    return [m.to_dict() for m in qs]


def matches_inputs(model, available_inputs=None, task: Optional[str] = None,
                   consumes=None) -> bool:
    """
    Ce modèle est-il utilisable avec les entrées dont on dispose ? (appariement entrée↔modèle)

    VOCABULAIRE CANONIQUE UNIQUEMENT (`common/utils/model_capabilities.CANONICAL_CAPABILITIES`) :
    `task`, `inputs_required`, `inputs_optional`, avec des ids d'`INPUT_TYPES`. Ne jamais
    inventer de drapeau ad hoc (`t2v`, `i2v`, `video`…) : c'est le vocabulaire hétérogène que
    `model_capabilities.py` a été écrit pour supprimer, et `INPUT_MODEL_MATCHING.md` en fait la
    règle — un modèle DÉCLARE ce qu'il consomme, personne ne le devine.

    Deux questions DISTINCTES, et il faut souvent les deux :
      - `available_inputs` — FAISABILITÉ : ses entrées requises sont-elles toutes disponibles ?
      - `consumes`        — UTILITÉ : consomme-t-il vraiment l'entrée que je lui donne
                            (en requise OU en optionnelle) ?

    Sans `consumes`, « j'ai une image à animer » retiendrait aussi un modèle texte→vidéo pur :
    ses entrées requises sont satisfaites… mais il IGNORERAIT l'image. Avec `consumes`, un
    modèle qui sait faire les deux (LTX : image en optionnelle) reste éligible, là où filtrer
    sur `task='image-to-video'` l'aurait écarté à tort au profit d'un modèle plus lourd.

    Extrait de `composer/utils/auto_model.py` (1er adopteur, 2026-07-21), qui portait cette
    logique en propre — c'est elle qui doit servir à TOUTES les apps.
    """
    caps = getattr(model, 'capabilities', None) or {}
    if task and caps.get('task') and caps.get('task') != task:
        return False
    required = set(caps.get('inputs_required') or [])
    if consumes and not set(consumes).issubset(required | set(caps.get('inputs_optional') or [])):
        return False
    if available_inputs is None:
        return True
    return required.issubset(set(available_inputs))


def full_gpu_budget_gb(headroom_gb: float = 4.0) -> Optional[float]:
    """
    Budget VRAM au-delà duquel un modèle imposerait de l'offload CPU.

    ⚠️ N'ajoute qu'UNE chose au comportement par défaut : la MARGE. `select_model` prend déjà
    la VRAM libre comme budget quand `vram_budget_gb` est omis — il répond donc « ça rentre »,
    pas « ça tourne sans offload ». Or `MemoryManager.get_memory_strategy()` bascule en
    MODEL_OFFLOAD dès qu'il ne reste pas cette marge pour les activations : viser le budget
    brut, c'est viser un offload évitable. Même valeur des deux côtés, sinon les deux couches
    se contredisent.

    Réutilise `get_free_vram_gb()` — la MÊME source que le budget par défaut de `select_model`,
    pour qu'un tirage avec et sans marge parlent de la même VRAM.
    """
    free = get_free_vram_gb()
    return max(0.0, free - headroom_gb) if free else None


def select_model_id(source: Optional[str] = None, requires=None,
                    requested: Optional[str] = None,
                    fallback: Optional[str] = None, avoid_offload: bool = True,
                    modality: Optional[str] = None, task: Optional[str] = None,
                    available_inputs=None, consumes=None, **kwargs) -> Optional[str]:
    """
    Tirage d'un modèle pour une app, rendu comme un `model_id` nu (sans le préfixe "source:").

    GÉNÉRIQUE — aucune modalité, aucun type de média, aucun nom d'app ici : une app déclare sa
    capacité au manifeste et passe la chaîne correspondante dans `requires`.

    Args:
        requested:     choix explicite de l'utilisateur, respecté TEL QUEL (même s'il impose
                       un offload : c'est alors un choix assumé, pas une surprise).
        fallback:      rendu si le catalogue ne propose rien (première install, sync jamais
                       lancé, model_manager indisponible).
        avoid_offload: ne tirer que parmi les modèles qui tiennent entièrement sur le GPU.
    """
    if requested and requested not in ('', 'auto'):
        return requested
    try:
        # Le filtrage canonique (modalité / tâche / entrées disponibles) passe par la même
        # brique de listage que l'UI : une seule route, un seul vocabulaire.
        cand = kwargs.pop('candidates', None)
        # `source=None` : tirage PAR CAPACITÉ, sans nommer d'app (assistant, studio,
        # passerelles). On borne alors par la CATÉGORIE, dérivée de la tâche — mesuré le
        # 2026-08-31 : `model_type='speech'` SEUL rend `vibevoice-asr` (reconnaissance) ou
        # `deepfilternet` (débruitage) pour une demande de SYNTHÈSE, car la catégorie
        # `speech` les contient tous. Catégorie ET tâche : l'une sans l'autre se trompe,
        # dans les deux sens (les capacités seules laissaient passer un modèle de vision).
        if not source:
            mt = kwargs.get('model_type')
            if not mt and task:
                from .prospector import _TASK_MODEL_TYPE
                mt = _TASK_MODEL_TYPE.get(task)
            if mt:
                kwargs['model_type'] = mt
        if modality or task or consumes or available_inputs is not None:
            ids = [d['id'] for d in get_registry_models(
                source, modality=modality, task=task,
                available_inputs=available_inputs, consumes=consumes,
                model_type=kwargs.get('model_type'))[1]]
            cand = [i for i in cand if i in ids] if cand else ids
            # Sans source, `get_registry_models` rend déjà des clés ENTIÈRES : ne pas
            # préfixer (on fabriquerait « None:kokoro »).
            if source:
                cand = [f'{source}:{i}' for i in cand]
        chosen = select_model(
            source=source,
            requires=requires,
            candidates=cand,
            vram_budget_gb=full_gpu_budget_gb() if avoid_offload else None,
            **kwargs,
        )
    except Exception as exc:
        logger.debug("[Select] %s : tirage indisponible (%s) → repli %s", source, exc, fallback)
        return fallback
    if chosen is None:
        logger.info("[Select] %s : aucun modèle %s ne tient dans le budget GPU → repli %s "
                    "(offload probable)", source, requires or '', fallback)
        return fallback
    logger.info("[Select] %s %s → %s (%s Go)",
                source, requires or '', chosen.model_id, chosen.vram_gb)
    # Le RETOUR suit le même espace de clés que la REQUÊTE — la règle que
    # `get_registry_models` applique déjà, et qui manquait ici (mesuré 2026-09-01).
    #
    # `source` nommé  → id NU (`bark`) : l'appelant connaît la source, il l'a nommée, et ses
    #                   valeurs stockées sont historiquement nues (imager, composer).
    # `source=None`   → clé ENTIÈRE (`synthesizer:bark`) : la requête a traversé TOUS les
    #                   producteurs, donc le suffixe seul ne désigne plus personne. Deux
    #                   producteurs peuvent porter le même — c'est exactement la raison pour
    #                   laquelle `get_registry_models` rend la clé entière dans ce mode.
    #
    # ⚠ Sans cette symétrie, un tirage AUTOMATIQUE par capacité rendait `'bark'` là où l'app
    # stocke et sait router `'synthesizer:bark'` : option introuvable dans le select, chip
    # affichant la clé brute, capacités non résolues. Le tirage aurait « marché » en rendant
    # une valeur que plus rien en aval ne reconnaît.
    return chosen.model_id if source else chosen.model_key


def get_registry_models(source: Optional[str] = None, allowed_ids=None,
                        downloaded_only: bool = False,
                        requires=None, modality: Optional[str] = None,
                        task: Optional[str] = None, available_inputs=None, consumes=None,
                        model_type: Optional[str] = None):
    """
    (choices, info) pour le <select> d'une app, PILOTÉ par le registre AIModel (verrou n°1).

    - choices : [(model_id, nom)]  — model_id = model_key sans le préfixe "source:"
    - info    : [{id, name, description, vram, capabilities, downloaded}]

    ⚠ `source=None` (2026-08-31, route F4b) : requête PAR CAPACITÉ SEULE, tous producteurs
    confondus. C'est le mode qui rend les PASSERELLES gratuites — une surface qui n'est pas
    une app (vocalisation de l'assistant, nœud studio, appel du converter vers l'enhancer)
    demande « ce qui sait faire X », pas « ce que l'app Y déclare ». `AIModel.source` est
    mono-valué : y ancrer les options rebâtit une cloison entre surfaces qui partagent le
    même parc (l'avatarizer emprunte déjà les moteurs TTS du synthesizer).
    Dans ce mode, l'`id` rendu est le `model_key` ENTIER : sans préfixe de source, deux
    producteurs pourraient porter le même suffixe et l'appelant ne saurait plus qui il vise.

    `allowed_ids` (optionnel) : restreint aux modèles que le backend sait CHARGER — sécurité,
    on ne propose jamais un modèle non chargeable. Retourne ([], []) si le registre n'a rien
    pour cette source → l'appelant doit alors faire un repli sur sa liste backend.

    Filtres de capacité, tous en VOCABULAIRE CANONIQUE (cf. `INPUT_MODEL_MATCHING.md`) :
      - `modality`        : 'image' | 'video' | 'audio' | … (appartenance à `modalities`)
      - `task`            : 'text-to-image', 'image-to-video', … (format HF)
      - `available_inputs`: ids d'`INPUT_TYPES` dont on dispose → ne garde que les modèles
                            dont les `inputs_required` sont satisfaites
      - `requires`        : drapeaux booléens `supports_*` (usage historique)

    Une app NOMME ce dont elle dispose ; elle n'écrit aucun filtre par type de média, et
    aucune fonction ne porte de modalité dans son nom.
    """
    from ..models import AIModel, canonical_task
    # Le catalogue parle NOTRE vocabulaire de tâches ; l'appelant (manifeste, prospection,
    # UI) parle parfois celui de HuggingFace. On traduit AVANT de comparer — sans quoi la
    # requête ne trouve rien et le repli ci-dessous sert toute la catégorie, en silence.
    task = canonical_task(task)
    qs = AIModel.objects.filter(is_available=True)
    if source:
        qs = qs.filter(source=source)
    else:
        # Une requête par capacité ne doit jamais rendre un CANDIDAT de prospection : il n'a
        # pas de poids sur le disque (`is_proposed` = proposé, pas installé).
        qs = qs.filter(is_proposed=False)
        # ⚠ ANCRAGE PAR CATÉGORIE (recadrage Fabien, 2026-08-31) — la pièce que j'avais
        # ratée. `model_type` est la TAXONOMIE du catalogue : renseignée sur **101/101**
        # modèles (mesuré), y compris ceux qu'aucune app ne déclare. Elle ne se DEVINE pas :
        # elle vient de la SOURCE elle-même — `pipeline_tag` du dépôt HF ou capacité déclarée
        # au registre Ollama — traduite par `_TASK_MODEL_TYPE` ; c'est cette même réponse qui
        # décide ensuite du dossier d'installation, que le balayage générique relit. Le
        # dossier est donc le dernier maillon d'une chaîne qui commence chez l'éditeur, pas
        # une déduction de rangement. Sans elle, la requête ne s'appuyait que sur
        # `capabilities.task` — or
        # `matches_inputs` est PERMISSIF par choix (un modèle qui ne déclare rien n'est
        # jamais exclu) : `LocateAnything-3B` (`model_type='vision'`, `capabilities={}`)
        # remontait donc dans une demande `text-to-speech`.
        # La catégorie est le filtre GROSSIER et toujours vrai ; les capacités affinent.
        # Ensemble, ils rendent le permissif SÛR : un modèle fraîchement installé, pas
        # encore décrit finement, reste proposable DANS SA CATÉGORIE — jamais ailleurs.
        mt = model_type
        if not mt and task:
            # Table task → model_type DÉJÀ écrite pour la prospection : on la réutilise,
            # on n'en invente pas une seconde. Elle est indexée sur les tags HF : on y
            # entre donc par la PROJECTION de notre tâche (`TASK_TO_PLATFORM_TAGS`),
            # jamais par notre valeur brute — sinon `transcription` n'y trouve rien.
            # Table DIRECTE (notre tâche → notre catégorie). L'aller-retour par le tag
            # HuggingFace ne pouvait pas répondre pour les 4 tâches qui n'en ont pas
            # (`lip-sync`, `text-to-music`, `text-to-audio`, `obb`) : elles perdaient leur
            # ancrage de catégorie, donc la garde contre un modèle d'une autre famille.
            from ..models import model_type_for_task
            mt = model_type_for_task(task)
        if mt:
            qs = qs.filter(model_type=mt)
    if downloaded_only:
        qs = qs.filter(is_downloaded=True)
    qs = qs.order_by('-vram_gb', 'name')
    models = [m for m in qs
              if _supports(m, requires, None)
              and (modality is None or modality in ((m.capabilities or {}).get('modalities') or []))
              and matches_inputs(m, available_inputs, task, consumes)]
    if (requires or modality or task or consumes or available_inputs is not None) and not models:
        # Le catalogue n'a pas (encore) les capacités — typiquement avant le premier
        # `sync_models` qui suit un enrichissement de l'ingest. On sert la liste NON filtrée
        # plutôt qu'un <select> vide : dégrader la précision, jamais la disponibilité.
        logger.info("[Registry] %s : aucun modèle ne correspond (requires=%s modality=%s "
                    "task=%s inputs=%s) → liste non filtrée (un sync_models peuplera les "
                    "capacités)", source, requires, modality, task, available_inputs)
        models = list(qs)
    choices, info = [], []
    for m in models:
        # Sans source déclarée, la clé ENTIÈRE est l'identité (cf. docstring) ; avec une
        # source, on garde le suffixe — c'est ce que les selects d'app portent déjà.
        mid = (m.model_key if not source
               else (m.model_key.split(':', 1)[1] if ':' in m.model_key else m.model_key))
        if allowed_ids is not None and mid not in allowed_ids:
            continue
        choices.append((mid, m.name))
        # `backend_missing` : raison si le modèle est POSITIVEMENT inlançable (grisage
        # automatique 02/09) — le select l'AFFICHE grisé avec la raison, la sélection
        # l'exclut ; '' sinon. Relu à chaque appel (ré-autorisation automatique).
        try:
            from wama.common.backends.manager import backend_missing
            sans_backend = backend_missing(m) or ''
        except Exception:
            sans_backend = ''
        info.append({
            'id': mid,
            'name': m.name,
            'description': m.description_short or m.description or '',
            'vram': f"{int(m.vram_gb)}GB" if m.vram_gb else '',
            'capabilities': m.capabilities or {},
            'downloaded': m.is_downloaded,
            'backend_missing': sans_backend,
        })
    return choices, info


def describe_model(model_key: str, tier: str = 'short') -> str:
    """Description d'un modèle. tier='short' → une ligne (fallback long) ; 'long' → paragraphe."""
    from ..models import AIModel
    m = AIModel.objects.filter(model_key=model_key).first()
    if not m:
        return ''
    if tier == 'long':
        return m.description or m.description_short or ''
    return m.description_short or m.description or ''

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
    """VRAM libre (Go) du GPU le plus libre, MOINS ce que d'autres process ont réservé.

    ⚠⚠ LA DÉDUCTION A ÉTÉ AJOUTÉE LE 2026-09-08 (revérification demandée par Fabien : « ce n'est
    pas géré par le model manager et le gouverneur ? »). Elle l'était à MOITIÉ, et c'est pire
    qu'un manque franc : la sélection auto ÉTAIT VRAM-aware — `budget = get_free_vram_gb()`, et
    `_best_by_vram` écarte ce qui n'entre pas — mais elle lisait la mesure NAÏVE du pilote. Or le
    gouverneur porte déjà la bonne (`effective_free_gb`), dont la docstring dit exactement ce qui
    manquait : « `mem_get_info()` ne voit que le présent et ignore qu'un autre process s'apprête
    à prendre 18 Go ». Deux tâches lancées de front voyaient donc toutes deux le GPU libre, et
    passaient — c'est le scénario de superposition que le gouverneur existe pour empêcher.

    On ne remplace PAS l'appel par `effective_free_gb()` : celle-ci rend `0.0` quand torch est
    absent, ce qui vaudrait « aucun budget » et écarterait TOUS les modèles. Ici, `None` veut dire
    « budget inconnu, ne contraint pas » — sémantique préservée : on garde la sonde du moniteur
    et on lui retranche le registre partagé. Une seule mesure de référence, deux appelants.
    """
    try:
        from .memory_monitor import WAMAMemoryMonitor
        gpus = WAMAMemoryMonitor().get_gpu_usage()
        if not gpus:
            return None
        libre = max((g.free_gb for g in gpus), default=None)
        if libre is None:
            return None
    except Exception as e:
        logger.debug(f"[model_selector] free VRAM indéterminable : {e}")
        return None
    try:
        from wama.common.services.resource_governor import unseen_reserved_gb
        # Sonde PAR PROCESS (total − alloué de CE process) : on retranche ce qu'elle ne voit pas
        # encore, mais pas les empreintes que ce process a lui-même allouées — elles sont déjà
        # hors de `libre`. Jusqu'au 2026-09-14 on retranchait tout, et un résident comptait double.
        reserve = unseen_reserved_gb('process')
    except Exception as e:      # registre indisponible : on ne DÉGRADE pas, on rend le brut
        logger.debug(f"[model_selector] registre de réservations indisponible : {e}")
        return libre
    if reserve:
        logger.info(f"[model_selector] budget VRAM : {libre:.1f} Go libres − {reserve:.1f} Go "
                    f"réservés par d'autres process = {max(0.0, libre - reserve):.1f} Go")
    return max(0.0, libre - reserve)


def _specialization_ok(model, requested) -> bool:
    """
    Un modèle SPÉCIALISÉ (`capabilities['specialisation']`) n'entre dans un lot que si
    l'appelant demande sa spécialité — sinon il concourt à armes inégales dans un pool
    généraliste (cas `translategemma:12b`, spécialiste traduction que rien ne distinguait :
    Ollama lui rend `completion, vision` comme à un généraliste). Réciproquement, demander
    une spécialité ne retient QUE les modèles qui la portent. Cf. `FAMILLES_OLLAMA`.
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


def _rank_key(pool, family=None):
    """
    Fabrique la clé de tri « (déjà chargé, qualité) » pour CE lot de candidats.

    ⚠ POURQUOI LA CLÉ DÉPEND DU LOT. L'ancienne version faisait
    `quality_index if not None else vram_gb`, c'est-à-dire qu'elle comparait **deux échelles
    incommensurables** : l'indice va de −26,7 (embeddings) à 58,7 (qwen3.6:35b), la VRAM de 0,1
    à 24 Go. Un modèle porteur d'un indice battait donc mécaniquement tout modèle qui n'en avait
    pas, quel que soit son mérite — et poser un premier indice mesuré sur un YOLO aurait suffi à
    fausser toute la sélection vision (constaté le 2026-08-12 en préparant la boucle qualité).

    Règle : on ne mélange JAMAIS deux échelles, et `NULL` reste « inconnu », pas « mauvais ».

    Étage BENCHMARK (2026-08-19, échelle des signaux : a priori < benchmark tiers < mesure
    interne) : le sous-indice de domaine, sinon le `benchmark_index` tiers COMPARABLE
    (Artificial Analysis, `sync_benchmarks`), sinon l'a priori, sinon la VRAM.

    ⚠ CE PARAGRAPHE DISAIT « si TOUT le lot le porte … sinon on retombe pour TOUT LE MONDE »
    jusqu'au 2026-09-26 — c'est FAUX depuis. Un étage se juge désormais sur le SOUS-ENSEMBLE
    qu'il couvre (`_quality_scalars`) : un seul modèle non mesuré ne fait plus tomber le lot
    entier sur la taille. Il perd sa place au classement (dernier ici), il ne la fait plus
    perdre aux autres. La phrase retirée ajoutait que la couverture partielle était « une
    incitation à compléter l'appariement, pas un bug » : elle l'était en intention, elle
    faisait tirer le PLUS GROS en pratique (mesuré sur le tirage dev — qwen3.6:35b préféré à
    qwen3.8 qui le bat de 16 points en coding et pèse 6 Go de moins).

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
    scalars, _ = _quality_scalars(pool, family)

    # ⚠ `.get` depuis le 2026-09-26 : l'échelle ne couvre plus que le sous-ensemble
    # COMPARABLE, donc un modèle hors échelle n'a pas de valeur. Il passe DERNIER (`-inf`)
    # plutôt que de faire tomber tout le lot d'un étage — ce qu'il provoquait avant.
    # Dernier, pas « nul » : il reste choisi s'il est le seul candidat.
    def sort_key(m):
        return (m.is_loaded, scalars.get(id(m), float('-inf')))
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


def is_cloud(model) -> bool:
    """Ce modèle s'exécute-t-il CHEZ UN TIERS ? Lit le champ DÉCLARÉ (`AIModel.execution`),
    jamais un proxy.

    ⚠ Le proxy tentant — `vram_gb == 0` — est FAUX : il confond « je n'ai pas mesuré sa
    VRAM » (inconnu, donc prudence) et « il n'en consomme aucune ici » (distant, donc hors
    de cet axe). C'est cette confusion qui faisait d'un modèle distant le PIRE du lot sur
    les deux axes à la fois (cf. `_quality_scalars` et le terme de coût de `_best_by_vram`).
    """
    from wama.model_manager.models import EXECUTION_CLOUD
    return getattr(model, 'execution', None) == EXECUTION_CLOUD


def _quality_scalars(pool, family=None):
    """Valeur de QUALITÉ scalaire par modèle — l'ÉCHELLE DES SIGNAUX, en un seul domicile.

    Même règle qu'avant sur le FOND (a priori < benchmark tiers < mesure interne, jamais
    deux échelles mélangées) : sous-indice de domaine, sinon benchmark comparable, sinon
    a priori, sinon la VRAM en PROXY assumé. `_rank_key` (le tri) et le score pondéré
    (le curseur) lisent tous deux ce barème.

    ⚠⚠ CE QUI CHANGE LE 2026-09-26 (demande de Fabien) : UN ÉTAGE SE JUGE SUR LE
    SOUS-ENSEMBLE QU'IL COUVRE, plus sur « tout le lot ou rien ».

    Le « tout ou rien » visait juste — ne jamais normaliser deux échelles ensemble — mais il
    punissait le lot entier pour UN modèle non mesuré, et le repli est la VRAM, c'est-à-dire
    la TAILLE. Mesuré ce jour sur le tirage de développement :

        qwen3.8:latest    coding 58,2   17 Go     ← le meilleur, et le plus léger
        qwen3.6:35b       coding 41,9   23 Go     ← celui qui était tiré
        albert:gemma-4-31b-it   coding 43,4
        albert:gpt-oss-120b     coding ABSENT     ← à lui seul, il faisait tomber l'étage

    Un seul score manquant → repli VRAM → « le meilleur » devenait « le plus gros », ce que
    la docstring de `_best_by_vram` dément elle-même (un MoE : la qualité d'un 36B au coût
    d'un 3B). *Un lot ne se juge pas au modèle qu'on n'a pas mesuré.*

    On compare donc CEUX QUI PARTAGENT L'ÉCHELLE, et le pool effectif du classement est
    restreint à eux (l'appelant lit les clés du dict) : un modèle non mesuré ne gagne pas
    par défaut, et ne fait plus perdre les autres. L'étage benchmark garde sa double
    condition — mesuré ET échelle unique — appliquée au sous-ensemble mesuré.

    ⚠ LE PROXY VRAM NE COUVRE QUE LE LOCAL. Un modèle distant n'a pas de taille ici ; le
    classer à 0 en faisait le pire du lot, alors que sa VRAM est nulle par NATURE et non par
    médiocrité. Il sort donc de cet étage — c'est la distinction local/distant demandée par
    Fabien le 26/09, désormais lue sur le champ `execution` et non devinée d'un `vram_gb`.

    Retour : ({id(m): valeur} sur le sous-ensemble COMPARABLE, proxy_vram) — le drapeau dit
    si la « qualité » n'est que la taille (utile aux appelants pour doser leur confiance).
    """
    def _family_score(m):
        return ((getattr(m, 'benchmark_meta', None) or {}).get('family_scores') or {}).get(family)

    from .benchmark_sync import benchmarks_comparable, orderable_value

    batch = list(pool)
    if not batch:
        return {}, False

    if family:
        covered = [m for m in batch if _family_score(m) is not None]
        if covered:
            return {id(m): _family_score(m) for m in covered}, False

    # Étage benchmark TIERS : le sous-ensemble mesuré doit AUSSI partager une seule échelle
    # (un Elo et un Intelligence Index ne se classent pas ensemble — `benchmarks_comparable`).
    measured = [m for m in batch if getattr(m, 'benchmark_index', None) is not None]
    if measured and benchmarks_comparable(measured):
        return {id(m): orderable_value(m) for m in measured}, False

    # Étage RANG CENTILE — la lecture INTER-ÉCHELLES (branché le 2026-09-26, demande de Fabien).
    # `benchmark_sync.percentile_rank` a été écrit le 01/09 pour exactement cette question
    # (« ramener toute valeur entre 0 et 100 pour pouvoir comparer »), il est calculé et STOCKÉ
    # à chaque synchro… et la sélection ne le lisait pas. Mesuré le 26/09 : **55 modèles
    # mesurés sur 55 en portent un**, sur 11 échelles — dont les distants, qu'Albert note en
    # `aa_intelligence_index` et Anthropic en `arena_elo_text`. Sans cet étage, un lot mixte
    # local+Albert+Anthropic tombait d'un cran, et le cran d'après est la TAILLE.
    #
    # ⚠ Il vient APRÈS la valeur brute, jamais avant : à échelle unique, le score exact dit
    # plus que le rang. Il ne perd personne au passage — le rang est écrit en même temps que
    # `benchmark_index`, donc il couvre exactement le même sous-ensemble.
    # ⚠⚠ SES DEUX RÉSERVES, écrites dans sa docstring et à redire partout où il sert :
    # il est ORDINAL (90ᵉ et 80ᵉ centile ne veulent pas dire « 10 % meilleur »), et il dépend
    # de la POPULATION de son banc, qui contient des modèles fermés qu'on ne fait pas tourner —
    # être médian chez AA n'est pas être médian chez soi. C'est un classement raisonnable entre
    # mondes, pas une mesure commune : c'est pourquoi il ne PRIME pas sur l'échelle unique.
    ranked = [m for m in batch
              if ((getattr(m, 'benchmark_meta', None) or {}).get('percentile_rank')) is not None]
    if ranked:
        return ({id(m): m.benchmark_meta['percentile_rank'] for m in ranked}, False)

    rated = [m for m in batch if m.quality_index is not None]
    if rated:
        return {id(m): m.quality_index for m in rated}, False

    sized = [m for m in batch if not is_cloud(m) and m.vram_gb]
    if sized:
        return {id(m): m.vram_gb for m in sized}, True

    # Rien de comparable dans ce lot : aucun ne prime, l'appelant départagera autrement
    # (résidence, ordre du catalogue). Mieux vaut l'égalité qu'un classement inventé.
    return {id(m): 0 for m in batch}, True


def _minmax(values: dict) -> dict:
    """Normalisation min-max d'un dict {clé: nombre} vers [0,1] (lot constant → 0.5)."""
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 0.5 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def abilities_of(model) -> list:
    """Libellés des aptitudes déclarées par `model`, lus dans `ModelAbility` (+ sa spécialité).
    (Nommée `aptitudes_of` du 17 au 19/09 : identifiant français, corrigé.)

    ⚠ `ModelAbility` (`models.py`) est LE vocabulaire des aptitudes, écrit le 2026-08-05 — et il
    n'avait AUCUN consommateur. Le 17/09 j'avais écrit ici une table `APTITUDES` qui le doublait
    avec d'autres libellés : réinvention relevée par Fabien (« n'a-t-on pas réinventé quelque chose
    qui était simplement mal exploité ? »). Ce que les « rôles » de l'assistant disaient en
    épinglant des noms de modèles, le catalogue le dit par ces aptitudes — dérivées, jamais saisies.

    `completion` n'est pas affichée : c'est l'aptitude qui DÉFINIT le domaine d'un select de
    conversation, tous ses modèles la portent.
    """
    from ..models import ModelAbility

    caps = getattr(model, 'capabilities', None) or {}
    labels = [str(a.label) for a in ModelAbility
              if a is not ModelAbility.COMPLETION and caps.get(a.value)]
    specialisation = caps.get('specialisation')
    if specialisation:
        labels.append(f"spécialité : {specialisation}")
    return labels


def _type_filter(model_type) -> dict:
    """Filtre de CATÉGORIE, une ou plusieurs séparées par des virgules.

    Une surface peut couvrir deux catégories sans que ce soit un fourre-tout : l'assistant
    converse avec des `llm` ET des `vlm` (les modèles Claude et les modèles vision d'Albert
    répondent en texte). Le domaine reste DÉCLARÉ au schéma — ce n'est pas une absence de borne.
    """
    types = [t.strip() for t in str(model_type or '').split(',') if t.strip()]
    if not types:
        return {}
    return {'model_type__in': types} if len(types) > 1 else {'model_type': types[0]}


def _best_by_vram(models, budget_gb: Optional[float], family=None, quality_intent=None):
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

    # L'échelle ne couvre que les modèles COMPARABLES entre eux (2026-09-26) : le classement
    # se fait sur eux, pas sur le lot entier. Un modèle que rien ne mesure ne gagne pas par
    # défaut — et il ne fait plus tomber les autres d'un étage.
    values, _ = _quality_scalars(pool, family)
    rankable = [m for m in pool if id(m) in values] or pool
    q = _minmax(values)

    # Coût = VRAM. Trois cas, et on ne les confond plus (Fabien, 26/09) :
    #   • LOCAL mesuré        → sa VRAM ;
    #   • LOCAL jamais mesuré → PIRE coût du lot (garde du 02/09 : Audio8, `vram_gb=0` faute
    #     de mesure, battait Kokoro (0,5 mesuré) sur « rapide » par accident) ;
    #   • DISTANT             → **0** : il ne prend rien sur CETTE carte. Ce n'est pas une
    #     faveur, c'est la mesure.
    #
    # ⚠⚠ LE SÉLECTEUR N'ARBITRE PAS local/distant — **c'est l'utilisateur qui le définit**
    # (`UserProfile.cloud_policy` : 100 % local / cloud si WAMA est saturé / cloud autorisé),
    # appliqué EN AMONT par `allowed_cloud_keys` → `select_model(cloud_keys=…)`. Un distant
    # qui arrive jusqu'ici a DÉJÀ été autorisé par son propriétaire : lui opposer ici une
    # préférence pour le local trancherait une seconde fois, ailleurs, une question déjà
    # tranchée. (J'avais écrit cette préférence le matin même — retirée le jour même.)
    #
    # ⏳ POURQUOI `cost_tier` N'EST PAS LU ICI (question tranchée le 26/09). Le coût propre
    # d'un distant EST déclaré (`AIModel.cost_tier` : free / subscription / metered, posé par
    # source dans `external_sources`) et n'a aujourd'hui aucun consommateur qui l'ORDONNE. Le
    # brancher dans ce score demanderait d'inventer l'ordre ET des poids, et surtout de mettre
    # des euros et des gigaoctets dans un même min-max — l'équivalence que l'échelle des
    # signaux interdit. Or WAMA arbitre déjà « où partent mes données, à quel prix » à
    # l'ADMISSION, pas au classement : `cloud_policy` (l'utilisateur) et `hosting == sovereign`
    # (`dev_cloud_keys`) décident QUI entre dans le lot. C'est là qu'un arbitrage de coût a son
    # domicile — pas dans un second lieu qui divergerait du premier.
    costs = {id(m): (0.0 if is_cloud(m) else m.vram_gb)
             for m in pool if is_cloud(m) or m.vram_gb}
    c = _minmax(costs)

    def score(m):
        cout = c.get(id(m), 1.0)
        return w * q.get(id(m), 0.0) + (1.0 - w) * (1.0 - cout) + 1e-6 * q.get(id(m), 0.0)

    return max(rankable, key=score)


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
    benchmark_family: Optional[str] = None,
    specialization: Optional[str] = None,
    quality_intent=None,
    cloud_keys=None,
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
        benchmark_family: famille d'épreuves du banc tiers à privilégier ('coding', 'math' —
                         `benchmark_meta['family_scores']`, alimenté par `sync_benchmarks`).
                         Nommé `benchmark_domain` jusqu'au 2026-09-19 : « domaine » désignait
                         déjà le workflow d'une app et le thème de l'assistant.
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
        cloud_keys:      `model_key` des modèles DISTANTS que l'appelant AUTORISE (clés de
                         l'utilisateur × son niveau cloud — `cloud_models.allowed_cloud_keys`).
                         ⚠ NON-RÉGRESSION (ROADMAP §8d) : sans elle, aucun modèle distant
                         n'entre au tirage, qui est donc IDENTIQUE à celui d'avant le verrou
                         levé — sinon les scores de banc des grands modèles distants
                         gagneraient tout, en silence.

    Returns:
        AIModel | None.
    """
    from django.db.models import Q
    from ..models import AIModel, EXECUTION_CLOUD, EXECUTION_LOCAL

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
    # Distant : seulement ce que l'appelant autorise (cf. `cloud_keys`). Un modèle distant n'a
    # pas de poids ici : « téléchargé » ne le concerne pas, l'autorisation en tient lieu.
    if cloud_keys:
        qs = qs.filter(Q(execution=EXECUTION_LOCAL) | Q(model_key__in=list(cloud_keys)))
    else:
        qs = qs.exclude(execution=EXECUTION_CLOUD)
    if source:
        qs = qs.filter(source=source)
    else:
        qs = qs.filter(is_proposed=False)   # un candidat de prospection n'a pas de poids
    if downloaded_only:
        qs = qs.filter(Q(is_downloaded=True) | Q(execution=EXECUTION_CLOUD))
    if model_type:
        qs = qs.filter(**_type_filter(model_type))
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
                return _best_by_vram(loaded, budget, benchmark_family, quality_intent)
        return _best_by_vram(pool, budget, benchmark_family, quality_intent)

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
                # ⚠ Même table que `get_registry_models` depuis le 2026-09-19 : cette ligne
                # lisait `prospector._TASK_MODEL_TYPE` pendant que le listage lisait
                # `models.model_type_for_task` — deux tables pour un seul fait, dans la MÊME
                # brique. Elles ne se contredisaient pas (mesuré), mais la table de la
                # prospection ignorait 20 de nos tâches : la borne par catégorie ne
                # s'activait pas pour elles.
                from ..models import model_type_for_task
                mt = model_type_for_task(task)
            if mt:
                kwargs['model_type'] = mt
        if modality or task or consumes or available_inputs is not None:
            ids = [d['id'] for d in get_registry_models(
                source, modality=modality, task=task,
                available_inputs=available_inputs, consumes=consumes,
                model_type=kwargs.get('model_type'),
                cloud_keys=kwargs.get('cloud_keys'))[1]]
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
                        model_type: Optional[str] = None, cloud_keys=None):
    """
    (choices, info) pour le <select> d'une app, PILOTÉ par le registre AIModel (verrou n°1).

    `cloud_keys` : modèles DISTANTS autorisés (même contrat que `select_model`) — sans elle,
    aucun modèle distant n'est listé, comme avant le verrou levé.

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
    from django.db.models import Q
    from ..models import EXECUTION_CLOUD, EXECUTION_LOCAL
    if cloud_keys:
        qs = qs.filter(Q(execution=EXECUTION_LOCAL) | Q(model_key__in=list(cloud_keys)))
    else:
        qs = qs.exclude(execution=EXECUTION_CLOUD)
    # ⚠ Un `model_type` EXPLICITE borne le domaine dans les DEUX modes (2026-09-08). Il ne
    # jouait que dans la branche sans `source` : un appelant qui combinait les deux — ce que
    # l'endpoint `api/models/options/` documente pourtant comme deux paramètres de domaine —
    # le voyait IGNORÉ EN SILENCE. Mesuré sur l'enhancer : `{source: 'enhancer',
    # model_type: 'upscaling'}` rendait ses **9** modèles, les 2 moteurs audio compris — un
    # select d'upscaling aurait proposé un débruiteur de voix. *Un filtre ignoré ne rend pas
    # une erreur : il rend une liste qui a l'air juste.*
    # L'INFÉRENCE `task` → `model_type`, elle, reste réservée au mode SANS source : là-bas
    # elle est l'ancrage de catégorie qui rend le permissif sûr ; ici la source ancre déjà.
    if model_type:
        qs = qs.filter(**_type_filter(model_type))
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
        # au registre Ollama — traduite par `model_type_for_task` ; c'est cette même réponse qui
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
            qs = qs.filter(**_type_filter(mt))
    if downloaded_only:
        qs = qs.filter(Q(is_downloaded=True) | Q(execution=EXECUTION_CLOUD))
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
            # Aptitudes DÉRIVÉES (cf. `abilities_of`) : un select les affiche s'il le déclare.
            'abilities': abilities_of(m),
            # DISTANT ou LOCAL : « à télécharger » n'a de sens que pour des poids locaux.
            'execution': m.execution,
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

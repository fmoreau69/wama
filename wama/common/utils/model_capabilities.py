"""
Vocabulaire CANONIQUE des capacités modèle (`AIModel.capabilities`) — SOURCE UNIQUE.

Contexte (audit consolidation 2026-07-01, cf. `UI_MECHANISMS_CONSOLIDATION.md` §0ter/§0quater) :
`AIModel.capabilities` est LA source unique lue par les consommateurs de génération :
  • `WamaModelCaps` (JS)          → filtre options/champs selon le modèle sélectionné ;
  • `lang_routing.py`            → décide traduction/routing via `capabilities['languages']` ;
  • `app_metadata._resolve_model`→ passe caps + type à la PromptPipeline ;
  • `model_selector`             → (à réconcilier) sélection VRAM-aware par capacité.

Mais les dicts produits par `model_registry._discover_<app>_models()` employaient un vocabulaire
HÉTÉROGÈNE (`multilingual` bool vs `languages_count` int vs `languages` array ; `native_diarization`
vs le flag backend `supports_diarization`). Ce module fige le vocabulaire commun + fournit des helpers
de lecture (dérivés) et un normaliseur des clés LEGACY — sans que chaque consommateur ré-invente la
sémantique. Module PUR (aucune dépendance Django) : importable par model_manager (producteur) ET
par common (consommateurs, ex. lang_routing) sans cycle.

Règle : `capabilities` = FAITS de capacité (ci-dessous). Le opérationnel (eta a-priori, install,
requires runtime) reste dans `AIModel.extra_info` — ne pas mélanger (divergence C1 de l'audit).
"""
from __future__ import annotations

from typing import Any, Dict, List

# Sentinelle « toutes langues / agnostique » — cohérente avec lang_routing (`'*' in langs`).
ANY_LANGUAGE = "*"

#: Vocabulaire FERMÉ de `modalities` — il ne vivait que dans la description de la clé ci-dessous
#: (2026-09-19) ; `check_model_taxonomy` vérifie désormais les défauts par tâche contre lui.
MODALITIES = ("image", "video", "audio", "document", "text")

# ── Vocabulaire canonique : clé → description (documentation vivante) ──────────
# Les valeurs indiquent le TYPE attendu. Un modèle ne déclare que les clés pertinentes pour son type.
CANONICAL_CAPABILITIES: Dict[str, str] = {
    # Communes / structurelles
    "modalities":          "list[str] ⊂ {image,video,audio,document,text} — média(s) traité(s)",
    # ⚠ Homonyme inter-mondes (question de Fabien, 2026-08-28) : `task='segment'` est la
    # segmentation SPATIALE (masques de pixels, taxonomie YOLO/SAM) — sans rapport avec le
    # type `DataType.SEGMENTS` du monde Data (portions de TEMPS bornées, cf.
    # `common/catalog/data_types.py`, type SEGMENTS, qui porte l'avertissement miroir). Les deux
    # vocabulaires ne se comparent JAMAIS par égalité de nom : un port parle en DataType,
    # un modèle parle en task, et la traduction se DÉCLARE dans le binding.
    "task":                "str — identifiant de tâche façon HF (ex. 'text-to-image', 'segment')",
    #: Les MÉTIERS d'un modèle qui en exerce plusieurs — `task` reste le principal (celui que
    #: lisent l'appariement et la sélection), `tasks` les énumère TOUS. Écrite par la découverte
    #: (`model_registry`, depuis le raccourci `tasks` des `model_config.py`) et lue par
    #: `benchmark_sync._local_categories`, qui donne alors UN BANC PAR MÉTIER au lieu d'un seul.
    #: ⚠ DÉCLARÉE ICI depuis le 2026-09-19 seulement : elle circulait sur 13 lignes (imager :
    #: les TI2V, qui font texte→vidéo ET image→vidéo) et était lue par les bancs, sans figurer
    #: au vocabulaire qui se dit « source unique ». Un audit de capacités ne la reconnaissait
    #: donc pas — exactement le trou que ce fichier existe pour fermer.
    "tasks":               "list[str] — tous les métiers exercés (`task` = le principal)",
    "languages":           "list[str] — codes ISO gérés ; ['*'] = agnostique/toutes langues",
    "context_length":      "int — fenêtre de contexte (llm/vlm)",
    # Capacités d'un LLM/VLM — un ENSEMBLE, pas une tâche unique (cf. models.py §ModelTask :
    # « qwen3.6:35b rend [completion, vision, tools, thinking] ; `tools`/`thinking` n'ont aucun
    # équivalent HF »). Écrites par la découverte Ollama (`_capacites_canoniques`) et lues par
    # `select_model(requires=…)` / `llm_utils`. DÉCLARÉES ICI depuis le 2026-08-19 : elles
    # circulaient sans figurer au vocabulaire qui se dit « source unique » — la carte ignorait
    # l'axe LLM tout entier (relevé en répondant à la question de Fabien sur les sous-catégories).
    "completion":          "bool — génération de texte (chat/instruct) ; faux pour un embedding",
    "vision":              "bool — entrée IMAGE native (multimodal)",
    "audio":               "bool — entrée AUDIO native (gemma4 12b/e4b)",
    "tools":               "bool — appel d'outils (function calling) — décisif pour l'assistant",
    "thinking":            "bool — mode raisonnement explicite (chaîne de pensée)",
    "embedding":           "bool — produit des vecteurs, PAS du texte",
    "abilities":           "list[str] — capacités BRUTES telles que déclarées par Ollama",
    #: Ce POUR QUOI le modèle est fait, quand ce n'est pas « tout » — 3e axe, DÉCLARÉ par un
    #: humain (`model_registry.FAMILLES_OLLAMA`), jamais découvert. Un modèle qui le
    #: porte sort du pool généraliste sauf demande explicite.
    "specialisation":      "str — domaine de spécialité (ex. 'translation') ; exclut du pool généraliste",
    # Capacités booléennes (préfixe supports_ — ALIGNÉ sur les flags backend)
    "supports_diarization": "bool — diarisation locuteur native (⇐ ex-`native_diarization`)",
    "supports_timestamps":  "bool — horodatage mot/segment",
    #: Une capacité peut être RESTREINTE À CERTAINES LANGUES — le booléen seul ment alors.
    #: Cas mesuré (2026-08-20) : Kokoro calcule les timestamps mot pendant la synthèse
    #: (`join_timestamps`, dérivés de `pred_dur`, donc exacts par construction) mais SEULEMENT
    #: pour l'anglais — `pipeline.py:374` teste `lang_code in 'ab'` et la branche non-anglaise
    #: yield un Result SANS `tokens`. Mettre `supports_timestamps=False` perdrait la capacité
    #: anglaise ; le mettre à True mentirait en français. D'où cette borne.
    #: ABSENTE = la capacité vaut pour toutes les langues du modèle (cas général).
    "timestamp_languages":  "list[str] — langues où `supports_timestamps` s'applique ; absent = toutes",
    #: Le PENDANT de `languages`, ajouté le 2026-08-29 : une langue peut n'être ni gérée ni
    #: refusée. Kokoro rabat 8 langues sur son pipeline anglais — il rend du son, avec une voix
    #: anglaise. Les mettre dans `languages` mentirait (le catalogue les annoncerait servies) ;
    #: les taire ferait dire à l'UI « impossible » là où un fichier sort. D'où cette 3ᵉ valeur.
    #: ABSENT = le moteur n'a pas de repli — cas général, et le défaut à préférer.
    "fallback_languages":   "list[str] — langues ACCEPTÉES par un pipeline d'emprunt, hors `languages` ; absent = aucune",
    "supports_hotwords":    "bool — biais lexical / hotwords",
    "supports_streaming":   "bool — inférence en flux (temps réel)",
    "supports_cloning":     "bool — clonage de voix (TTS)",
    # Détection / segmentation
    "classes":             "list[str] — classes détectables (YOLO)",
    "text_promptable":     "bool — segmentation par prompt texte (SAM3)",
    # Upscaling
    "scale":               "int — facteur d'agrandissement (x2, x4)",
    # Indices d'UI (champs de réglage pertinents pour ce moteur) — cf. enhancer
    "params":              "list[str] — noms de paramètres UI pertinents pour ce moteur",
    # Appariement card d'entrée ↔ modèles (INPUT_MODEL_MATCHING.md) : ids d'INPUT_TYPES
    # (app_modes.py). L'union sur les modèles d'une app DÉRIVE les slots de sa card d'entrée ;
    # une entrée fournie hors des inputs d'un modèle le DÉSACTIVE (avec raison, jamais caché).
    "inputs_required":     "list[str] — entrées REQUISES par le modèle (lancement gaté sinon)",
    "inputs_optional":     "list[str] — entrées ACCEPTÉES en option (ex. reference_melody)",
    # Limites NATIVES d'un modèle vidéo (2026-09-23, Fabien : « les paramètres modale/inspecteur
    # tirent leurs infos des capacités des modèles »). Déclarées par l'app (`model_config`),
    # transportées par la découverte, lues par l'écran (`WamaParams`, `cap_from`) ET par la
    # tâche — un seul fait pour les deux. Avant, la tâche les codait en dur par moteur et
    # l'écran ne les connaissait pas : 15 s proposées, 5 produites.
    "fps":                 "int — cadence NATIVE (images/s) d'un modèle vidéo ; imposée à la sortie",
    "max_frames":          "int — images produites au plus en UN passage",
    "max_duration_s":      "float — durée native maximale (max_frames / fps) : borne la zone NATIVE",
    "native_resolution":   "str 'LxH' — résolution d'entraînement ; en dessous la qualité baisse",
    #: Comment le modèle va AU-DELÀ de `max_duration_s` — absent = il ne va pas au-delà (la
    #: durée est bornée). 'segments' = passages image→vidéo enchaînés, chacun repartant de la
    #: dernière image du précédent : c'est une EXTRAPOLATION, la continuité n'est pas garantie.
    "duration_extension":  "str — 'continuation' (le segment suivant reprend les dernières images : "
                           "mouvement continu) | 'segments' (repart d'UNE image : extrapolé) ; absent = borné",
    "continuation_frames": "int — images de la fin d'un passage qui conditionnent le suivant (continuation)",
    #: Réglages d'ÉCHANTILLONNAGE recommandés par l'éditeur (2026-09-24) — un modèle DISTILLÉ se
    #: dégrade avec les réglages d'un modèle plein (LTX distillé lancé à 30 pas / guidage 15).
    #: Rappelés sous les champs (`cap_from`, mode note), pas imposés : c'est le rôle du backend
    #: quand la distillation l'exige (FastWan DMD).
    "recommended_steps":    "int — nombre de pas recommandé par l'éditeur",
    "recommended_guidance": "float — guidage (CFG) recommandé ; 1.0 = sans guidage",
}


def sampling_caps_from_declaration(config: Dict[str, Any]) -> Dict[str, Any]:
    """`recommended_steps` / `recommended_guidance` depuis `default_steps` /
    `default_guidance_scale` d'une déclaration d'app (image comme vidéo)."""
    out: Dict[str, Any] = {}
    if config.get("default_steps"):
        out["recommended_steps"] = int(config["default_steps"])
    if config.get("default_guidance_scale") is not None:
        out["recommended_guidance"] = float(config["default_guidance_scale"])
    return out


def video_caps_from_declaration(config: Dict[str, Any], tokens=()) -> Dict[str, Any]:
    """Les capacités VIDÉO tirées d'une déclaration d'app (`fps`, `max_frames`, `resolution`
    'LxH') — la traduction vit ICI et non dans la boucle de découverte, pour être testable sans
    la recopier (leçon de `derive_inputs_from_tasks`). La prolongation par segments n'est
    déclarée que pour un modèle qui fait IMAGE→VIDÉO (jeton `i2v`) : c'est elle qui repart de
    la dernière image. Un modèle texte→vidéo seul reste borné."""
    out: Dict[str, Any] = {}
    fps, max_frames = config.get("fps"), config.get("max_frames")
    if fps:
        out["fps"] = int(fps)
    if max_frames:
        out["max_frames"] = int(max_frames)
    if fps and max_frames:
        out["max_duration_s"] = round(float(max_frames) / float(fps), 2)
        # La CONTINUATION prime : déclarée par l'app quand le moteur sait se conditionner sur
        # plusieurs images (LTX). Sinon, un modèle image→vidéo peut repartir d'UNE image.
        if config.get("continuation_frames"):
            out["duration_extension"] = "continuation"
            out["continuation_frames"] = int(config["continuation_frames"])
        elif "i2v" in set(tokens or ()):
            out["duration_extension"] = "segments"
    res = config.get("resolution")
    if isinstance(res, str) and "x" in res:
        out["native_resolution"] = res
    return out


def video_limits(caps: Dict[str, Any]) -> Dict[str, Any]:
    """Les limites vidéo d'un modèle, lues UNE fois : `{fps, max_frames, max_duration_s,
    extension}` (valeurs None si non déclarées). Lecteur commun de la tâche et des tests —
    la même lecture que l'écran fait en JS sur les mêmes clés."""
    caps = caps or {}
    fps = caps.get("fps")
    max_frames = caps.get("max_frames")
    max_s = caps.get("max_duration_s")
    if max_s is None and fps and max_frames:
        max_s = round(float(max_frames) / float(fps), 2)
    return {"fps": fps, "max_frames": max_frames, "max_duration_s": max_s,
            "extension": caps.get("duration_extension"),
            "continuation_frames": caps.get("continuation_frames")}

# Clés LEGACY → remplacement canonique (pour normaliser les dicts existants).
#   `multilingual`/`languages_count` = MORTES (aucun lecteur) → converties en `languages` si possible.
_LEGACY_KEYS = {
    "native_diarization": "supports_diarization",
}


# ── Helpers de LECTURE (dérivés — les consommateurs passent par ici, pas de sémantique dupliquée) ──
def get_languages(caps: Dict[str, Any]) -> List[str]:
    """Langues gérées, ou [] si non déclaré (le repli par type est géré par lang_routing)."""
    v = (caps or {}).get("languages")
    return list(v) if isinstance(v, (list, tuple)) else ([] if v is None else [str(v)])


def is_multilingual(caps: Dict[str, Any]) -> bool:
    """Vrai si le modèle gère >1 langue ou est agnostique ('*'). Remplace l'ex-clé `multilingual`."""
    langs = get_languages(caps)
    return ANY_LANGUAGE in langs or len(langs) > 1


def languages_count(caps: Dict[str, Any]) -> int:
    """Nombre de langues déclarées (0 si inconnu). Remplace l'ex-clé `languages_count`."""
    langs = [l for l in get_languages(caps) if l != ANY_LANGUAGE]
    return len(langs)


def supports(caps: Dict[str, Any], flag: str) -> bool:
    """Lecture booléenne tolérante d'un `supports_*` (ex. supports('supports_cloning'))."""
    return bool((caps or {}).get(flag))


def supports_timestamps_for(caps: Dict[str, Any], lang: str) -> bool:
    """
    Horodatage mot disponible POUR CETTE LANGUE.

    `supports_timestamps` seul ne suffit pas quand la capacité est bornée par
    `timestamp_languages` (cf. le vocabulaire ci-dessus, cas Kokoro). Les consommateurs
    passent par ici plutôt que de relire les deux clés — sinon la borne se perd au
    premier appelant qui l'ignore.

    Borne absente → la capacité vaut pour toutes les langues (cas général).
    """
    if not supports(caps, "supports_timestamps"):
        return False
    bornes = (caps or {}).get("timestamp_languages")
    if not isinstance(bornes, (list, tuple)) or not bornes:
        return True
    return ANY_LANGUAGE in bornes or (lang or "") in bornes


# ── AUTORITÉ du moteur sur les flags qu'il DÉCLARE ─────────────────────────────────────────
def declared_engine_flag(cls, flag: str):
    """Valeur d'un `supports_*` telle que la classe de moteur la DÉCLARE — ou `None`.

    ⚠ « Déclare » n'est pas « porte ». Le contrat commun (`backends/base.py`) pose tous les
    flags à False par défaut — *« un backend ne promet rien tant qu'il ne l'a pas déclaré »*.
    Ce défaut est un SILENCE, pas un fait : il ne doit jamais contredire ce qu'un manifeste a
    pu établir. On remonte donc la MRO jusqu'au contrat, et on ne rend une valeur que si une
    classe EN DESSOUS du contrat l'a écrite dans son propre corps.

    Ce qui a motivé cette distinction (2026-09-12, mesuré sur le catalogue) : `Audio8Backend`
    déclare `supports_cloning = False` avec sa raison (l'API exige le transcript de la
    référence, que le flux de voix WAMA ne porte pas — promettre le clonage serait mentir) ;
    la ligne de catalogue disait `True`, héritée d'un manifeste antérieur au backend. L'UI
    offrait les voix clonées, le moteur les ignorait en silence. `Qwen3TTSBackend` : même
    déclaration, catalogue muet — même effet.
    """
    from wama.common.backends.base import BaseModelBackend      # paresseux : utilitaire feuille
    for klass in getattr(cls, "__mro__", ()):
        if klass is BaseModelBackend:
            return None                       # atteint le contrat : rien de déclaré en dessous
        if flag in vars(klass):
            return bool(vars(klass)[flag])
    return None


def apply_engine_flags(caps: Dict[str, Any], cls) -> Dict[str, Any]:
    """Réaligne `caps` sur ce que la classe de moteur DÉCLARE — rend un NOUVEAU dict.

    Règle, dans le vocabulaire du dépôt (`merged_capabilities`, ex-`_capabilities_projectable`, 2026-08-31) : *« c'est la
    DÉCOUVERTE qui fait autorité — elle lit les flags sur les classes de backend ; on ne comble
    qu'un vide, on ne conteste jamais un fait »*. Le FAIT, quand il existe, est la déclaration
    du moteur ; le manifeste ne garde autorité que là où aucune classe ne se résout.

    Aujourd'hui la règle porte le CLONAGE, seul flag dont la contradiction avait une
    conséquence visible ; `inputs_optional` suit, parce que `reference_voice` n'est rien
    d'autre que « ce moteur accepte une voix à imiter » (INPUT_MODEL_MATCHING.md).
    Les autres flags (`supports_timestamps`…) restent posés « seulement s'ils sont vrais » par la
    découverte — sémantique différente, hors de cette règle.
    """
    caps = dict(caps or {})
    declare = declared_engine_flag(cls, "supports_cloning")
    if declare is None:
        return caps                           # défaut de base seulement : on ne conteste rien
    caps["supports_cloning"] = declare
    optionnels = [x for x in (caps.get("inputs_optional") or []) if x != "reference_voice"]
    if declare:
        optionnels.append("reference_voice")
    if optionnels or "inputs_optional" in caps:
        caps["inputs_optional"] = optionnels
    return caps


# ── NORMALISATION des dicts LEGACY vers le vocabulaire canonique ──────────────
def normalize_capabilities(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convertit un dict `capabilities` produit avec des clés legacy vers le vocabulaire canonique.

    - `native_diarization` → `supports_diarization`
    - `multilingual`(bool)/`languages_count`(int) → supprimées (mortes) ; si `languages` absent et
      `multilingual` True, on pose `languages=['*']` (agnostique) pour rester exploitable par lang_routing.
    - clés inconnues : conservées telles quelles (pas de perte — on ne « retire » rien silencieusement).
    """
    out: Dict[str, Any] = {}
    raw = raw or {}
    multilingual = bool(raw.get("multilingual"))
    for k, v in raw.items():
        if k in ("multilingual", "languages_count"):
            continue  # mortes — dérivées désormais depuis `languages`
        out[_LEGACY_KEYS.get(k, k)] = v
    if "languages" not in out and multilingual:
        out["languages"] = [ANY_LANGUAGE]
    return out


def is_canonical_key(key: str) -> bool:
    """Vrai si `key` fait partie du vocabulaire canonique (utilitaire d'audit/tests)."""
    return key in CANONICAL_CAPABILITIES


#: Jetons du raccourci `tasks` déclaré par app dans `model_config.py`. `style` a été ajouté le
#: 2026-09-11 (cf. `derive_inputs_from_tasks`).
TASK_TOKENS = ('t2i', 't2v', 'i2v', 'edit', 'i2i', 'style')

#: Les jetons qui décrivent une tâche de GÉNÉRATION. `style` n'en est pas une : un modèle à
#: transfert de style reste text-to-image, il accepte une entrée de conditionnement en plus.
GENERATIVE_TOKENS = ('t2i', 't2v', 'i2v', 'edit', 'i2i')


def derive_inputs_from_tasks(tasks: str, is_video: bool = False) -> Dict[str, Any]:
    """`tasks` (raccourci d'app) → vocabulaire CANONIQUE : task + entrées consommées.

    Extraite de `model_registry` le 2026-09-11, quand le jeton `style` y a été ajouté : la
    règle vivait au milieu d'une boucle de découverte de 400 lignes, donc la seule façon de la
    tester était d'en RECOPIER la logique — et une copie dérive de sa source sans rien dire.

    ⚠ `style` est le jeton qui MANQUAIT, et son absence était structurante. La dérivation ne
    savait produire que `work_image` : un modèle à transfert de style (IP-Adapter, ControlNet)
    aurait vu son image classée en fichier de TRAVAIL — « l'image qu'on édite » au lieu de
    « l'image qui guide ». Conséquence mesurée avant l'ajout : `reference_image` était déclaré
    par ZÉRO modèle du dépôt, non parce qu'aucun ne conditionne par une image, mais parce que
    le vocabulaire n'avait pas le mot pour le dire.
    (État de l'art, `INPUT_MODEL_MATCHING §6.2` : diffusers nomme ces rôles séparément —
    `image` l'init transformée, `ip_adapter_image` le style, `control_image` la structure.)

    Returns:
        {'task', 'inputs_required', 'inputs_optional', 'tokens'} — ids d'`INPUT_TYPES`, plus
        les JETONS reconnus dans `tasks` (triés), pour qui a besoin de TOUS les métiers déclarés.

    ⚠ `tokens` ajouté le 2026-09-12, et pas pour le confort : l'extraction du 11/09 a laissé
    dans `model_registry` (l. 584) une référence à `_tasks` — la variable locale qui portait ces
    jetons avant qu'ils ne soient calculés ici — sans plus rien qui la définisse. Mesuré dans le
    log Celery : **40 synchros du catalogue en échec sur la journée, toutes**
    (`name '_tasks' is not defined`), et le catalogue figé depuis le matin. Re-tokeniser dans la
    boucle aurait remis une seconde règle à côté de celle-ci ; la brique rend donc ce qu'elle
    calcule déjà, et la boucle le lit. *Une règle extraite doit rendre TOUT ce que son ancien
    domicile lisait — sinon l'extraction laisse une référence pendante que seul un RUN révèle.*
    """
    mode = (tasks or '').lower()
    for long, court in (('text-to-image', 't2i'), ('text-to-video', 't2v'),
                        ('image-to-video', 'i2v'), ('image-to-image', 'edit')):
        mode = mode.replace(long, court)
    jetons = {t for t in TASK_TOKENS if t in mode}
    if not jetons:                          # mode absent → déduit de la modalité
        jetons = {'t2v'} if is_video else {'t2i'}

    # `style` écarté du calcul de la tâche ET de l'obligation : sans ça,
    # `genere <= {'i2v','edit','i2i'}` deviendrait faux pour un `t2i+style`, et le modèle
    # exigerait une image de travail qu'il ne consomme pas.
    genere = jetons & set(GENERATIVE_TOKENS)
    if is_video:
        task = 'image-to-video' if genere == {'i2v'} else 'text-to-video'
    elif 'edit' in genere:
        task = 'image-to-image'
    else:
        task = 'text-to-image'

    requis, optionnels = ['prompt'], []
    if genere & {'i2v', 'edit', 'i2i'}:
        # L'image est OBLIGATOIRE si le modèle ne sait faire que ça, OPTIONNELLE s'il sait
        # aussi partir d'un simple prompt (LTX = t2v+i2v, SD = t2i+i2i).
        (requis if genere <= {'i2v', 'edit', 'i2i'} else optionnels).append('work_image')
    if 'style' in jetons:
        # TOUJOURS optionnelle : un modèle qui sait conditionner par une image sait aussi
        # générer sans elle. Un modèle qui l'exigerait le dirait en déclarant `style` SEUL —
        # cas inexistant aujourd'hui, à trancher s'il arrive.
        optionnels.append('reference_image')
    return {'task': task, 'inputs_required': requis, 'inputs_optional': optionnels,
            'tokens': sorted(jetons)}

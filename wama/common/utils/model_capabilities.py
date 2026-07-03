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

# ── Vocabulaire canonique : clé → description (documentation vivante) ──────────
# Les valeurs indiquent le TYPE attendu. Un modèle ne déclare que les clés pertinentes pour son type.
CANONICAL_CAPABILITIES: Dict[str, str] = {
    # Communes / structurelles
    "modalities":          "list[str] ⊂ {image,video,audio,document,text} — média(s) traité(s)",
    "task":                "str — identifiant de tâche façon HF (ex. 'text-to-image', 'segment')",
    "languages":           "list[str] — codes ISO gérés ; ['*'] = agnostique/toutes langues",
    "context_length":      "int — fenêtre de contexte (llm/vlm)",
    # Capacités booléennes (préfixe supports_ — ALIGNÉ sur les flags backend)
    "supports_diarization": "bool — diarisation locuteur native (⇐ ex-`native_diarization`)",
    "supports_timestamps":  "bool — horodatage mot/segment",
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
}

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

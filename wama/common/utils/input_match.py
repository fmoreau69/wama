"""Appariement card d'entrée ↔ modèles — côté SERVEUR de la brique commune.

Pendant Python de `static/common/js/wama-input-match.js` (doctrine INPUT_MODEL_MATCHING.md) :
fournit aux vues d'index le contexte `input_match_meta` / `input_labels` que le template passe
à `WamaInputMatch.init()`. SOURCE UNIQUE = le catalogue `AIModel.capabilities`
(`inputs_required` / `inputs_optional`, vocabulaire canonique de `model_capabilities.py`) ;
les libellés viennent d'`INPUT_TYPES` (`app_modes.py`). Zéro hardcode par app.

Historique : logique née dans le composer (1er adopteur, `views._input_match_meta`) puis
recopiée dans l'imager (inline depuis le registry) — extraite ici (2026-08-17) au moment de
l'adoption ×7 (règle /brique : le copier-coller imminent est LE signal d'extraction).

Les politiques d'app restent dans l'app : les pseudo-modèles « auto-* » du composer (union des
entrées de leur groupe) se déclarent en POST-TRAITEMENT du dict rendu, pas ici.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional


def input_match_meta(source: str,
                     key: Optional[Callable[[str], str]] = None,
                     extra_caps: tuple = ()) -> Dict[str, Dict[str, Any]]:
    """{model_id: {label, inputs_required, inputs_optional}} depuis le CATALOGUE — fail-safe {}.

    `source` = valeur d'`AIModel.source` (le lien app↔modèles, cf. feedback_find_accessor).
    `key` = mapping model_key → id d'option du <select> de l'app ; défaut = retrait du
    préfixe `source:` (``model_key.split(':', 1)[-1]``) — surcharger si le select de l'app
    emploie un autre identifiant (ex. anonymizer : clés `anonymizer:yolo:<poids>`).
    `extra_caps` = clés de capacités supplémentaires à joindre à chaque entrée (ex. `('task',)`
    pour le post-traitement auto-* du composer) — à retirer du payload avant sérialisation
    si elles ne servent qu'au serveur.
    """
    strip = key or (lambda mk: mk.split(':', 1)[-1])
    try:
        from wama.model_manager.models import AIModel
        meta: Dict[str, Dict[str, Any]] = {}
        for m in AIModel.objects.filter(source=source, is_proposed=False):
            caps = m.capabilities or {}
            entry: Dict[str, Any] = {
                'label': m.name or strip(m.model_key),
                'inputs_required': caps.get('inputs_required') or [],
                'inputs_optional': caps.get('inputs_optional') or [],
            }
            for k in extra_caps:
                entry[k] = caps.get(k)
            meta[strip(m.model_key)] = entry
        return meta
    except Exception:
        return {}


def auto_entry(meta: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Entrée du pseudo-modèle « auto » d'un select : intersection des requis, union du
    reste en optionnel (l'auto accepte ce qu'au moins UN candidat accepte). Extrait au 2ᵉ
    consommateur (transcriber puis reader, 2026-08-17) ; les politiques par GROUPE
    (auto-music/auto-sfx du composer) restent dans l'app."""
    if not meta:
        return {'inputs_required': [], 'inputs_optional': []}
    reqs = [set(e.get('inputs_required') or []) for e in meta.values()]
    alls = [set(e.get('inputs_required') or []) | set(e.get('inputs_optional') or [])
            for e in meta.values()]
    req = set.intersection(*reqs)
    return {'inputs_required': sorted(req),
            'inputs_optional': sorted(set().union(*alls) - req)}


def input_labels() -> Dict[str, str]:
    """{input_id: libellé} depuis INPUT_TYPES (source déclarée commune) — fail-safe {}."""
    try:
        from wama.common.utils.app_modes import INPUT_TYPES
        return {k: v.get('label', k) for k, v in INPUT_TYPES.items()}
    except Exception:
        return {}

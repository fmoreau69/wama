"""
Meta d'UI des moteurs TTS — brique COMMUNE aux apps qui exposent un select de moteur TTS.

Deux apps le font depuis le 2026-08-28 : le **synthesizer** (geste natif) et l'**avatarizer**
(pipeline dérivé texte→voix→avatar). Elles lisent le MÊME catalogue — `AIModel.source ==
'synthesizer'`, le lien app↔modèles étant `AIModel.source` — et affichent le même descriptif
de moteur. Extrait de `synthesizer/views.py` AU 2ᵉ CONSOMMATEUR : l'original a été remplacé
par un appel, jamais recopié (règle « zéro duplication », CLAUDE.md).

⚠ Ce module ne connaît AUCUNE de ses apps : la table valeur-d'option → suffixe-catalogue lui
est PASSÉE (`catalog_keys`), jamais importée. Même règle que le registre de fonctions — *le
substrat ne cite jamais ses producteurs*. Un `common/` qui importerait de `wama/<app>/`
inverserait la dépendance et rendrait la brique non réutilisable.

⚠⚠ `catalog_keys` est un jeu d'EXCEPTIONS, pas la liste des moteurs. La liste vient de
`TTS_MODEL_CHOICES` — c'est ce que le select propose RÉELLEMENT à l'utilisateur. La version
d'origine dérivait ses clés de `CATALOG_KEYS` (4 entrées) tout en peuplant le select depuis
`TTS_MODEL_CHOICES` (7) : `vits`, `tacotron2` et `speedy-speech` n'ont jamais reçu de
descriptif, et le commentaire qui l'expliquait (« pas d'entrée catalogue dédiée ») était
FAUX — mesuré le 2026-08-28, les 7 moteurs répondent en identité à `synthesizer:<valeur>`.
*Une table de correspondance prise pour un inventaire perd tout ce qui n'a pas d'exception.*

Django est importé PARESSEUSEMENT (dans les fonctions) : `common/tts/` est aussi consommé par
`tts_service.py`, service FastAPI qui n'a pas Django.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

#: Valeur d'`AIModel.source` sous laquelle vivent les moteurs TTS. Le préfixe est historique
#: (l'app synthesizer les a déclarés la première) ; il désigne le DOMAINE, pas l'app —
#: l'avatarizer lit le même jeu sans en posséder aucun.
TTS_CATALOG_SOURCE = 'synthesizer'


def _engines() -> list[str]:
    """Moteurs réellement proposés à l'utilisateur (valeurs d'option du select)."""
    from wama.common.tts.constants import TTS_MODEL_CHOICES
    return [value for value, _label in TTS_MODEL_CHOICES]


def _suffix_of(engine: str, catalog_keys: Optional[Mapping[str, str]]) -> str:
    """Suffixe catalogue d'un moteur — l'exception déclarée, sinon le moteur lui-même."""
    return (catalog_keys or {}).get(engine, engine)


def tts_input_match_meta(catalog_keys: Optional[Mapping[str, str]] = None
                         ) -> Dict[str, Dict[str, Any]]:
    """{valeur_option: {label, inputs_required, inputs_optional}} pour `WamaInputMatch`.

    Direction ENTRÉE→MODÈLE (une voix clonée désactive les moteurs sans clonage) ; la
    direction inverse est `WamaModelCaps`, qui va chercher ses capacités lui-même.
    Fail-safe {} hérité de `input_match_meta`.
    """
    inv = {suffix: engine for engine, suffix in (catalog_keys or {}).items()}
    from wama.common.utils.input_match import input_match_meta
    return input_match_meta(
        TTS_CATALOG_SOURCE,
        key=lambda mk: inv.get(mk.split(':', 1)[-1], mk.split(':', 1)[-1]))


def tts_model_help_meta(catalog_keys: Optional[Mapping[str, str]] = None
                        ) -> Dict[str, Dict[str, Any]]:
    """{valeur_option: {description, description_long, vram_gb}} pour `WamaModelHelp`.

    Lue du CATALOGUE `AIModel` (source unique). Fail-safe {} si le catalogue est
    indisponible : l'aide reste vide, la page ne tombe pas.

    ⚠ Une app dont le select est GÉNÉRÉ par `WamaParams` n'a pas besoin d'appeler ceci :
    `_bindModelHelp` auto-câble la brique et va chercher la meta via
    `WamaModelHelp.fetchCatalogMeta(help_source)`. Cette fonction sert aux selects écrits
    à la main (synthesizer), où la meta transite par le contexte de gabarit.
    """
    try:
        from wama.model_manager.models import AIModel
        keys = {f"{TTS_CATALOG_SOURCE}:{_suffix_of(e, catalog_keys)}": e for e in _engines()}
        meta: Dict[str, Dict[str, Any]] = {}
        for m in AIModel.objects.filter(model_key__in=keys):
            meta[keys[m.model_key]] = {
                'description': m.description_short or '',
                'description_long': m.description or '',
                'vram_gb': m.vram_gb,
            }
        return meta
    except Exception:
        return {}

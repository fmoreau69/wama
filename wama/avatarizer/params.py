"""
Schéma de paramètres Avatarizer — pour l'inspecteur contextuel du volet (compose-panel).

Comme Synthesizer : on GARDE les champs compose existants (id=/radios) et on câble l'inspecteur
contextuel dessus via WamaInspector.initFromSchema (panel read/apply dom_id-aware). dom_id du contexte
panel = id du champ (ou name du groupe radio). voice_preset hérite des voix centralisées
(options_source='voices' — utile si on rend la modale en WamaParams plus tard ; le compose garde ses
optgroups server-rendered pour l'instant). cardSettings (côté JS) lit les data-* du bouton ⚙ de la card.
"""
from wama.common.utils.param_schema import derive_from_model, schema_to_dicts
from wama.avatarizer.models import AvatarJob

PANEL = ("panel",)

PARAMS = derive_from_model(
    AvatarJob,
    include=["mode", "tts_model", "language", "voice_preset", "quality_mode", "use_enhancer", "bbox_shift"],
    overrides={
        "mode":         dict(type="radio", label="Mode", dom_id={"panel": "workflow_mode"}, contexts=PANEL),
        "tts_model":    dict(type="select", label="Modèle TTS", icon="fa-microchip", dom_id={"panel": "tts_model"}, contexts=PANEL),
        "language":     dict(type="select", label="Langue", icon="fa-language", dom_id={"panel": "language"}, contexts=PANEL),
        "voice_preset": dict(type="select", label="Voix", icon="fa-user", dom_id={"panel": "voice_preset"},
                             options_source="voices", contexts=PANEL),
        "quality_mode": dict(type="radio", label="Qualité", dom_id={"panel": "quality_mode"}, contexts=PANEL),
        "use_enhancer": dict(type="toggle", label="Enhancer IA", dom_id={"panel": "use_enhancer"}, contexts=PANEL),
        "bbox_shift":   dict(type="range", label="Bbox shift", dom_id={"panel": "bbox_shift"},
                             min=-9, max=9, step=1, contexts=PANEL),
    },
)

PARAMS_JSON = schema_to_dicts(PARAMS)

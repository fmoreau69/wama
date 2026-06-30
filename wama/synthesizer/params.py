"""
Schéma de paramètres Synthesizer — SOURCE UNIQUE pour la modale item, la modale batch et le volet
contextuel (inspecteur). Cartographie complète des 3 surfaces pour NE RIEN PERDRE.

⚠️ Spécificité Synthesizer : les options du select `voice_preset` (optgroups voix par défaut / groupes
dynamiques `voice_refs_groups` / héritage / « Mes voix » ua_ / Bark) sont SERVER-RENDERED et recopiées
par du JS maison (`cloneVoiceOptions`). On NE remplace donc PAS les champs par un rendu WamaParams (ce
qui perdrait les voix) : on garde les champs existants (mêmes `name=`) et on câble l'inspecteur
contextuel via `WamaInspector.initFromSchema` qui lit/écrit ces champs (file → défaut, batch, card).

`dom_id` par contexte = ponts vers les IDs existants de chaque surface (panel=compose, item=settings*,
batch=batchSettings*) → JS de voix/clone/submit inchangé. Gabarit : reader/describer params.py.
"""
from wama.common.utils.param_schema import derive_from_model, schema_to_dicts
from wama.common.utils.output_formats import output_format_params
from wama.synthesizer.models import VoiceSynthesis

PARAMS = derive_from_model(
    VoiceSynthesis,
    include=["tts_model", "language", "voice_preset", "speed", "pitch"],
    overrides={
        "tts_model": dict(
            type="select", label="Modèle TTS", icon="fa-microchip",
            dom_id={"panel": "tts_model", "item": "settingsTtsModel", "batch": "batchSettingsTtsModel"},
        ),
        "language": dict(
            type="select", label="Langue", icon="fa-language",
            dom_id={"panel": "language", "item": "settingsLanguage", "batch": "batchSettingsLanguage"},
        ),
        "voice_preset": dict(
            type="select", label="Voix", icon="fa-user",
            dom_id={"panel": "voice_preset", "item": "settingsVoicePreset", "batch": "batchSettingsVoicePreset"},
            options_source="voices",   # optgroups server-rendered + clonés par le JS existant — NON remplacés
        ),
        "speed": dict(
            type="range", label="Vitesse", icon="fa-gauge", min=0.5, max=2.0, step=0.1, default=1.0,
            dom_id={"panel": "speed", "item": "settingsSpeed", "batch": "batchSettingsSpeed"},
        ),
        "pitch": dict(
            type="range", label="Hauteur", icon="fa-music", min=0.5, max=2.0, step=0.1, default=1.0,
            dom_id={"panel": "pitch", "item": "settingsPitch", "batch": "batchSettingsPitch"},
        ),
    },
)

# Format + qualité de FICHIER de sortie : BRIQUE COMMUNE (output_format_params), domaine audio.
# early-binding (réglés avant génération) → contextes item+batch+panel ; dom_id = ids de chaque surface.
PARAMS += output_format_params(
    "audio",
    contexts=("item", "batch", "panel"),
    dom_id_format={"panel": "output_format", "item": "settingsOutputFormat"},
    dom_id_quality={"panel": "output_quality", "item": "settingsOutputQuality"},
)

PARAMS_JSON = schema_to_dicts(PARAMS)

"""
Schéma de paramètres Synthesizer — SOURCE UNIQUE pour la modale item, la modale batch et le volet
contextuel (inspecteur). Cartographie complète des 3 surfaces pour NE RIEN PERDRE.

Le champ `voice_preset` du VOLET est GÉNÉRÉ depuis le 2026-09-23 (gabarit : hôte `#voicePresetHost`
+ `WamaParams.render(context:'panel')`, groupes servis par `get_voice_groups` et rechargés par
`options_source='voices'`). ⚠ Ce bloc disait l'inverse jusque-là — « les options sont
SERVER-RENDERED, on NE remplace donc PAS les champs » — et cette phrase, recopiée dans deux briques
communes, a fait REFUSER pendant trois semaines de peupler le select du volet par la source commune.
Les quatre optgroups du gabarit redisaient à la main ce que la brique rend déjà pour la modale et
pour l'avatarizer, sans savoir dire les voix PARTAGÉES.

Les AUTRES champs du volet gardent leur markup écrit à la main : l'inspecteur contextuel
(`WamaInspector.initFromSchema`) les lit/écrit par `dom_id`, et il accepte les deux formes
d'identité (`name=` écrit à la main, `data-param=` généré).

`dom_id` par contexte = ponts vers les IDs existants de chaque surface (panel=compose, item=settings*,
batch=batchSettings*) → JS de voix/clone/submit inchangé. Gabarit : reader/describer params.py.
"""
from wama.common.utils.auto_model import intent_param
from wama.common.utils.param_schema import derive_from_model, schema_to_dicts
from wama.common.utils.output_formats import output_format_params_for_app
from wama.synthesizer.models import VoiceSynthesis

PARAMS = derive_from_model(
    VoiceSynthesis,
    include=["tts_model", "quality_intent", "language", "voice_preset", "speed", "pitch"],
    overrides={
        "tts_model": dict(
            type="select", label="Modèle TTS", icon="fa-microchip", chip=True,
            dom_id={"panel": "tts_model", "item": "settingsTtsModel", "batch": "batchSettingsTtsModel"},
            # Descriptif court + VRAM du catalogue — branchable depuis l'ALIGNEMENT 18/08
            # (valeurs du select = clés catalogue ; xtts_v2→coqui-xtts etc., rows migrées).
            help_source="synthesizer",
            # ── Route F4b, étape ② (2026-09-01) — le synthesizer est le PILOTE ────────────
            # Les options ne sont plus une liste écrite dans l'app : elles viennent du
            # CATALOGUE. Mesuré avant de câbler : le catalogue portait 7 moteurs TTS quand
            # l'app en proposait 4 — Kokoro-ONNX, installé la veille par la chaîne et 26×
            # plus rapide à charger que le .pt, était INCHOISISSABLE.
            #
            # `options_query` borne le DOMAINE, et rien d'autre. Pas de `source` : un moteur
            # TTS sert plusieurs surfaces (l'avatarizer emprunte ce parc, l'assistant
            # vocalise) — ancrer sur `AIModel.source` rebâtirait une cloison entre surfaces
            # qui partagent le même parc, et c'est précisément ce que le socle a écarté.
            # ⚠ Ce qui n'a PAS le droit d'y figurer : les entrées fournies et les capacités
            # requises. Celles-là GRISENT côté client (WamaInputMatch/WamaModelCaps) sur la
            # liste complète — lister n'est pas pouvoir choisir (INPUT_MODEL_MATCHING §2).
            options_source="catalog",
            options_query={"task": "text-to-speech"},
            # « auto » en 1ʳᵉ option + prévision sous le select (brique commune
            # auto_model, 2026-09-02) — le lancement résout dans workers.py.
            options_auto=True,
        ),
        # Curseur de QUALITÉ (échelle continue 0-100) — visible SEULEMENT quand le modèle
        # est « auto » (il pèse sur ce tirage-là et rien d'autre). Rendu/tricolore/
        # graduations : renderer commun `type='intent'` ; volet maison : partial
        # `common/_intent_slider.html`.
        "quality_intent": intent_param(
            dom_id={"panel": "quality_intent", "item": "settingsQualityIntent",
                    "batch": "batchSettingsQualityIntent"},
            show_if={"field": "tts_model", "equals": "auto"},
        ),
        "language": dict(
            type="select", label="Langue", icon="fa-language", chip=True,
            dom_id={"panel": "language", "item": "settingsLanguage", "batch": "batchSettingsLanguage"},
        ),
        "voice_preset": dict(
            type="select", label="Voix", icon="fa-user", chip=True,
            dom_id={"panel": "voice_preset", "item": "settingsVoicePreset", "batch": "batchSettingsVoicePreset"},
            # Source COMMUNE des voix (`get_voice_groups` → endpoint `/common/api/voices/`) :
            # elle sert les TROIS surfaces — volet généré, modale d'item, modale de lot.
            options_source="voices",
            # Aide RACCOURCIE : celle du modèle énumère la forme des valeurs entre accents
            # graves (« `default`, preset plat, `sa_<id>` (référence)… ») — lisible en base et
            # en admin, illisible sous un champ. Mesuré au rendu du volet généré : la ligne
            # d'identifiants s'affichait sous le select. Elle sert aussi de documentation à
            # `tool_api` : on garde donc les DEUX familles d'identifiants, en une phrase.
            help="Voix de référence (sa_…), voix clonée (ua_…) ou preset Bark",
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

# Format + qualité de FICHIER de sortie : BRIQUE COMMUNE auto depuis APP_CATALOG (domaine audio +
# early-binding déduits du catalogue). L'app ne fournit que les dom_id de ses surfaces.
# ⚠ Pas de contexte "batch" ici : `batch_update_settings` n'accepte que tts_model/language/
# voice_preset/speed/pitch — déclarer batch rendrait des champs MORTS dans la modale générée
# (mesuré 17/08). Réactiver quand l'endpoint portera le format/qualité de sortie.
PARAMS += output_format_params_for_app(
    "synthesizer",
    contexts=("item", "panel"),
    dom_id_format={"panel": "output_format", "item": "settingsOutputFormat"},
    dom_id_quality={"panel": "output_quality", "item": "settingsOutputQuality"},
)

PARAMS_JSON = schema_to_dicts(PARAMS)

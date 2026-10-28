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
from wama.common.tts.constants import VOICE_PAUSE_SETTINGS
from wama.common.utils.auto_model import intent_param
from wama.common.utils.param_schema import (derive_from_model, schema_to_dicts, seed_param,
                                            temperature_param, top_p_param, voices_of)
from wama.common.utils.output_formats import output_format_params_for_app
from wama.synthesizer.models import VoiceSynthesis

PARAMS = derive_from_model(
    VoiceSynthesis,
    include=["tts_model", "quality_intent", "language", "voice_preset", "speed", "pitch",
             "sentence_pause", "clause_pause", "temperature", "seed", "top_p"],
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
            # Les voix que le modèle choisi peut dire, sur les trois surfaces (2026-10-28) : la
            # page câblait le filtre au seul volet (`WamaModelCaps.init`), les modales en étaient
            # privées — une voix de Phonon y restait offerte sous Kokoro.
            cap_from=voices_of("tts_model"),
            # Aide RACCOURCIE : celle du modèle énumère la forme des valeurs entre accents
            # graves (« `default`, preset plat, `sa_<id>` (référence)… ») — lisible en base et
            # en admin, illisible sous un champ. Mesuré au rendu du volet généré : la ligne
            # d'identifiants s'affichait sous le select. Elle sert aussi de documentation à
            # `tool_api` : on garde donc les DEUX familles d'identifiants, en une phrase.
            help="Voix de référence (sa_…), voix clonée (ua_…) ou voix propre du moteur",
        ),
        "speed": dict(
            type="range", label="Vitesse", icon="fa-gauge", min=0.5, max=2.0, step=0.1, default=1.0,
            dom_id={"panel": "speed", "item": "settingsSpeed", "batch": "batchSettingsSpeed"},
        ),
        "pitch": dict(
            type="range", label="Hauteur", icon="fa-music", min=0.5, max=2.0, step=0.1, default=1.0,
            dom_id={"panel": "pitch", "item": "settingsPitch", "batch": "batchSettingsPitch"},
        ),
        # Les PAUSES (2026-10-18) — libellé, bornes et aide de la déclaration COMMUNE, celle de
        # l'assistant. Volet et modale d'élément : le front lit ses réglages par le schéma depuis
        # `188f732b` (création, inspecteur). ⚠ PAS `batch` : la modale de lot commune reposte toutes
        # ses valeurs, et des filles aux pauses différentes recevraient le défaut
        # (`MODES_QUEUE_UX §5ter`, chantier commun ouvert) — l'ajouter ici le jour où il est fait.
        "sentence_pause": dict(contexts=("item", "panel"),
                               dom_id={"panel": "sentence_pause", "item": "settingsSentencePause"},
                               **VOICE_PAUSE_SETTINGS["sentence_pause"]),
        "clause_pause": dict(contexts=("item", "panel"),
                             dom_id={"panel": "clause_pause", "item": "settingsClausePause"},
                             **VOICE_PAUSE_SETTINGS["clause_pause"]),
        # La TEMPÉRATURE du moteur (2026-10-21) : le réglage commun, lié au modèle — grisé sous un
        # moteur qui ne tire pas (Kokoro) ou dont WAMA ne la transmet pas, la valeur du moteur
        # rappelée (Higgs 0,7). Mêmes surfaces que les pauses, et pour la même raison (pas `batch`).
        "temperature": temperature_param(
            "tts_model", contexts=("item", "panel"),
            dom_id={"panel": "temperature", "item": "settingsTemperature"}),
        # Ses deux voisins (2026-10-22) : mêmes surfaces, même raison.
        "seed": seed_param(
            "tts_model", contexts=("item", "panel"),
            dom_id={"panel": "seed", "item": "settingsSeed"}),
        "top_p": top_p_param(
            "tts_model", contexts=("item", "panel"),
            dom_id={"panel": "top_p", "item": "settingsTopP"}),
    },
)

# Ce que chaque réglage PÉRIME (`Param.stales`, 2026-10-05) : tous les réglages de synthèse
# périment la synthèse — `ProcessSpec.watched` s'en dérive (function_specs.py n'y garde que les
# champs hors schéma). Posé AVANT les réglages de SORTIE, qui sont au process `output` commun.
for _param in PARAMS:
    _param.stales = ("generate",)
del _param

# Format + qualité de FICHIER de sortie : BRIQUE COMMUNE auto depuis APP_CATALOG (domaine audio +
# early-binding déduits du catalogue). L'app ne fournit que les dom_id de ses surfaces.
# ⚠ Pas de contexte "batch" ici — HISTORIQUE : la vue de lot n'acceptait que tts_model/language/
# voice_preset/speed/pitch, déclarer batch aurait rendu des champs MORTS (mesuré 17/08). Depuis
# le 2026-10-02 le lot passe par la fonction de la route d'élément, qui ÉCRIT format et qualité :
# la condition est levée. Reste à ouvrir le contexte (une ligne ici + les dom_id de lot) avec une
# vérification navigateur de la modale générée — pas fait à l'aveugle.
PARAMS += output_format_params_for_app(
    "synthesizer",
    contexts=("item", "panel"),
    dom_id_format={"panel": "output_format", "item": "settingsOutputFormat"},
    dom_id_quality={"panel": "output_quality", "item": "settingsOutputQuality"},
)

PARAMS_JSON = schema_to_dicts(PARAMS)

# ── Réglages UTILISATEUR — dérivés du schéma (contrat 3 de `WAMA_VERIFICATION §8`, 2026-10-18) ──
# La brique commune `user_settings` les garde, les relit et fait naître une synthèse avec eux
# (`new_element_settings`). Le synthesizer ne RETIENT que la voix — modèle, langue, voix —, sous
# ses clés historiques `preferred_*` (frontière des données) ; les autres réglages du volet partent
# de leur défaut du schéma. Cette déclaration vivait dans les vues (`_PANEL_PREF_KEYS`).
from wama.common.utils.param_schema import _pget, panel_defaults  # noqa: E402

STORED_UNDER = {'tts_model': 'preferred_tts_model', 'language': 'preferred_language',
                'voice_preset': 'preferred_voice_preset'}


def user_setting_key(p):
    """Clé de stockage d'un réglage RETENU, None s'il ne se retient pas."""
    return STORED_UNDER.get(_pget(p, 'name'))


USER_SETTINGS_DEFAULTS = panel_defaults(PARAMS, key=user_setting_key)

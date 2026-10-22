"""
Schéma de paramètres Describer — SOURCE UNIQUE pour les deux surfaces :
inspecteur (volet droit, context "panel") et modale item/batch (context "item"/"batch").

Dérivé du modèle `Description` (les choix de select viennent des `choices` du modèle) puis rendu
par `WamaParams.render(container, PARAMS_JSON, {context})`. Les `dom_id` reprennent les IDs LEGACY
de chaque surface → JS existant + apparence préservés (migration sans casse).

Voir le gabarit `transcriber/params.py` et `common/utils/param_schema.py`.

Depuis le 2026-10-13 la card porte un PIPELINE (`function_specs.PIPELINE`) : chaque réglage
déclare les process qu'il PÉRIME (`stales`) — changer le style ne réécoute pas l'audio, changer
le modèle de transcription ne réécrit que ce qui en dépend. Et le MODÈLE de chaque rôle se choisit
(décision de Fabien : « plusieurs modèles peuvent faire ces process ») : transcription, vision,
langage — trois selects tirés du CATALOGUE par capacité (route F4b, patron de l'avatarizer et de
ses deux selects), « auto » en tête.
"""
from wama.common.utils.auto_model import intent_param
from wama.common.utils.param_schema import (derive_from_model, schema_to_dicts, seed_param,
                                            temperature_param, top_p_param)
from wama.describer.models import Description

PANEL_ITEM_BATCH = ("panel", "item", "batch")

PARAMS = derive_from_model(
    Description,
    # ⚠ ORDRE : `asr_model` reste le PREMIER select `catalog` — `auto_model.catalog_field` rend le
    # premier, et le tirage « auto » du lancement (`workers.asr_key`) lit SON domaine et ses
    # affinages (`options_resolution`). Les deux autres « auto » sont propres au describer (la
    # cascade vision, les tiers du style) : leur select se tait plutôt que de prévoir faux.
    include=["output_style", "output_language", "max_length",
             "asr_model", "quality_intent", "vision_model", "vision_temperature",
             "vision_seed", "vision_top_p",
             "llm_model", "llm_temperature", "llm_seed", "llm_top_p",
             "generate_summary", "summary_type", "verify_coherence"],
    overrides={
        # dom_id "batch" (17/08) : modale batch DÉDIÉE générée (contrat reader) — remplace le
        # détournement de la modale item (_settingsBatchId + titre échangé) ; batch_update
        # accepte les champs de SETTINGS_FIELDS (views.py).
        "output_style": dict(
            type="select", label="Format de sortie", icon="fa-align-left",
            dom_id={"panel": "output_style", "item": "settingsOutputFormat",
                    "batch": "batchSettingsOutputStyle"},
            help="Niveau de détail de la description générée.",
            chip=True,
            stales=("describe",),
        ),
        "output_language": dict(
            type="select", label="Langue de sortie", icon="fa-language",
            dom_id={"panel": "output_language", "item": "settingsOutputLanguage",
                    "batch": "batchSettingsOutputLanguage"},
            chip=True,
            stales=("describe", "summarize", "coherence"),
        ),
        "max_length": dict(
            type="range", label="Longueur max", icon="fa-text-width",
            min=100, max=2000, step=50,
            dom_id={"panel": "max_length", "item": "settingsMaxLength",
                    "batch": "batchSettingsMaxLength"},
            help="Longueur maximale (caractères) de la description.",
            chip=True,
            stales=("describe",),
        ),
        # ── Le MODÈLE de chaque rôle (2026-10-13) ─────────────────────────────────────────────
        # Transcription : le domaine du transcriber, sa politique « Whisper d'abord » et l'entrée
        # que la card FOURNIT (un audio) — déclarées ici, lues par le lancement ET la prévision.
        # Pas de modèle distant (`options_cloud`) : le describer transcrivait en local, il le reste
        # tant que ce n'est pas décidé.
        "asr_model": dict(
            type="select", label="Modèle de transcription", icon="fa-microphone", chip=True,
            options_source="catalog",
            options_query={"task": "transcription"},
            options_auto=True,
            options_resolution={"priority": ["whisper", "vibevoice", "qwen"],
                                "available_inputs": ["work_audio"]},
            help_source="describer",
            help_fallback={"auto": "Choisi au lancement : Whisper d'abord, puis selon la mémoire "
                                   "GPU libre. Sert un audio et la piste son d'une vidéo."},
            dom_id={"panel": "asr_model", "item": "settingsAsrModel",
                    "batch": "batchSettingsAsrModel"},
            contexts=PANEL_ITEM_BATCH,
            stales=("transcribe",),
        ),
        # Curseur rapide/qualité : il arbitre le tirage « auto » de la transcription (les deux
        # autres « auto » suivent leur règle propre) — visible quand ce tirage a lieu.
        "quality_intent": intent_param(
            dom_id={"panel": "quality_intent", "item": "settingsQualityIntent",
                    "batch": "batchSettingsQualityIntent"},
            contexts=PANEL_ITEM_BATCH,
            show_if={"field": "asr_model", "equals": "auto"},
            stales=("transcribe",),
        ),
        # Vision : les modèles qui lisent une image — BLIP (légendage) et les modèles de
        # conversation qui acceptent une image (`llm` + `vision`, convention d'Ollama).
        # `options_auto="silent"` : « auto » est la cascade du describer (Ollama vision puis BLIP
        # pour une image, BLIP pour les images-clés), qu'une prévision du catalogue ne dirait pas.
        "vision_model": dict(
            type="select", label="Modèle de vision", icon="fa-eye", chip=True,
            options_source="catalog",
            options_query={"task": "captioning,text-generation", "modality": "image"},
            options_auto="silent",
            help_source="describer",
            help_fallback={"auto": "Une image : le meilleur modèle Ollama vision installé, BLIP "
                                   "à défaut. Les images-clés d'une vidéo : BLIP."},
            dom_id={"panel": "vision_model", "item": "settingsVisionModel",
                    "batch": "batchSettingsVisionModel"},
            contexts=PANEL_ITEM_BATCH,
            stales=("frames", "describe"),
        ),
        # La TEMPÉRATURE de chaque modèle qui tire (2026-10-21) : le réglage commun, lié au choix
        # du modèle — grisé sous BLIP (il ne tire pas), la valeur de l'éditeur rappelée.
        "vision_temperature": temperature_param(
            "vision_model",
            dom_id={"panel": "vision_temperature", "item": "settingsVisionTemperature",
                    "batch": "batchSettingsVisionTemperature"},
            contexts=PANEL_ITEM_BATCH,
            stales=("frames", "describe"),
        ),
        # Ses deux voisins (2026-10-22) : vides = un tirage neuf, celui du modèle.
        "vision_seed": seed_param(
            "vision_model",
            dom_id={"panel": "vision_seed", "item": "settingsVisionSeed",
                    "batch": "batchSettingsVisionSeed"},
            contexts=PANEL_ITEM_BATCH,
            stales=("frames", "describe"),
        ),
        "vision_top_p": top_p_param(
            "vision_model",
            dom_id={"panel": "vision_top_p", "item": "settingsVisionTopP",
                    "batch": "batchSettingsVisionTopP"},
            contexts=PANEL_ITEM_BATCH,
            stales=("frames", "describe"),
        ),
        # Langage : rédaction d'un document, d'un audio, d'une vidéo, puis résumé et cohérence.
        # « auto » = le gabarit du style (rapide pour un résumé court, lourd pour une synthèse
        # scientifique ou la cohérence), résolu au catalogue (`llm_utils.get_describer_model`).
        "llm_model": dict(
            type="select", label="Modèle de langage", icon="fa-brain", chip=True,
            options_source="catalog",
            options_query={"model_type": "llm"},
            options_auto="silent",
            help_source="describer",
            help_fallback={"auto": "Choisi au lancement selon le style : un modèle rapide pour "
                                   "un résumé court, le plus capable pour une synthèse "
                                   "scientifique ou la vérification de cohérence."},
            dom_id={"panel": "llm_model", "item": "settingsLlmModel",
                    "batch": "batchSettingsLlmModel"},
            contexts=PANEL_ITEM_BATCH,
            stales=("describe", "summarize", "coherence"),
        ),
        "llm_temperature": temperature_param(
            "llm_model",
            dom_id={"panel": "llm_temperature", "item": "settingsLlmTemperature",
                    "batch": "batchSettingsLlmTemperature"},
            contexts=PANEL_ITEM_BATCH,
            stales=("describe", "summarize", "coherence"),
        ),
        "llm_seed": seed_param(
            "llm_model",
            dom_id={"panel": "llm_seed", "item": "settingsLlmSeed",
                    "batch": "batchSettingsLlmSeed"},
            contexts=PANEL_ITEM_BATCH,
            stales=("describe", "summarize", "coherence"),
        ),
        "llm_top_p": top_p_param(
            "llm_model",
            dom_id={"panel": "llm_top_p", "item": "settingsLlmTopP",
                    "batch": "batchSettingsLlmTopP"},
            contexts=PANEL_ITEM_BATCH,
            stales=("describe", "summarize", "coherence"),
        ),
        # Les INTERRUPTEURS des process optionnels : ils sont le `toggle` de leur process, ils ne
        # périment rien.
        "generate_summary": dict(
            type="toggle", label="Générer un résumé LLM", icon="fa-file-lines",
            dom_id={"panel": "globalGenerateSummary", "item": "settingsGenerateSummary",
                    "batch": "batchSettingsGenerateSummary"},
        ),
        # Le TYPE de résumé (2026-10-13) — le compte-rendu de réunion en est un, comme au
        # transcriber (il était un style de description, migration 0016).
        "summary_type": dict(
            type="radio", label="", icon="fa-list", show_if="generate_summary", inline=True,
            choices=[("structured", "Structuré"), ("meeting", "Réunion")],
            stales=("summarize",),
        ),
        "verify_coherence": dict(
            type="toggle", label="Vérifier la cohérence", icon="fa-spell-check",
            dom_id={"panel": "globalVerifyCoherence", "item": "settingsVerifyCoherence",
                    "batch": "batchSettingsVerifyCoherence"},
        ),
    },
)

PARAMS_JSON = schema_to_dicts(PARAMS)

# ── Réglages UTILISATEUR — dérivés du schéma (contrat 3 de `WAMA_VERIFICATION §8`, 2026-10-18) ──
# Le volet est la surface des défauts de l'utilisateur ; la brique commune `user_settings` les
# garde, les relit et fait naître une description avec eux (`new_element_settings`). Ils se gardent
# sous le NOM du réglage : les trois préférences d'avant (style, langue, longueur, écrites par une
# liste à la main dans les vues) l'étaient déjà — frontière des données, rien à migrer.
from wama.common.utils.param_schema import panel_defaults, panel_name_key  # noqa: E402

user_setting_key = panel_name_key
USER_SETTINGS_DEFAULTS = panel_defaults(PARAMS, key=user_setting_key)

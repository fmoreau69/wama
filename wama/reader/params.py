"""
Schéma de paramètres Reader — SOURCE UNIQUE pour l'inspecteur (context "panel"), la modale BATCH
(context "batch") et la modale ⚙ d'ITEM (context "item" — rendue par le cycle commun
`WamaParams.settingsModal` depuis le 2026-09-24 ; « Reader n'a pas de modale item » était un
constat périmé).

Dérivé du modèle `ReadingItem` (mode = TextChoices du modèle ; le moteur, du CATALOGUE). Rendu par
`WamaParams.render(container, PARAMS_JSON, {context})`. Les `dom_id` reprennent les IDs LEGACY de
chaque surface → JS existant + apparence préservés. Gabarit : transcriber/params.py.

Depuis le 2026-10-13 la card porte un PIPELINE (`function_specs.PIPELINE` : lecture, mise en
forme, analyse) : chaque réglage déclare les process qu'il PÉRIME (`stales`) — changer de modèle
de langage ne relit pas le document. Les deux process optionnels ont leur interrupteur, et le
modèle de langage qu'ils emploient se choisit (`llm_model`).
"""
from wama.common.utils.auto_model import intent_param
from wama.common.utils.param_schema import (derive_from_model, schema_to_dicts, seed_param,
                                            temperature_param, top_p_param)
from wama.reader.models import ReadingItem
from wama.reader.utils.model_config import OCR_SPEC

PARAMS = derive_from_model(
    ReadingItem,
    # output_format ajouté 2026-08-01 : il était sur le modèle mais absent du schéma, donc
    # NI réglable dans l'inspecteur, NI affiché sur la card. C'est le champ qui décrit ce qui
    # va SORTIR — il alimente la section Sortie de la card v3 via section="output".
    # quality_intent (chantier C, 2026-09-20) : le curseur rapide/qualité commun. Hors modèle
    # (pas de colonne) : le reader n'a pas de choix par item, le curseur est un RÉGLAGE D'APP
    # de l'utilisateur (brique durable `user_settings`), lu au lancement par
    # `auto_model.quality_intent_of(item, 'reader')` quand le moteur est sur « auto ».
    include=["backend", "quality_intent", "mode", "language", "output_format",
             "llm_model", "llm_temperature", "llm_seed", "llm_top_p", "format_markdown",
             "generate_analysis"],
    overrides={
        "quality_intent": intent_param(
            dom_id={"panel": "qualityIntent"}, contexts=("panel",),
            show_if={"field": "backend", "equals": "auto"},
        ),
        "backend": dict(
            type="select", label="Moteur OCR", icon="fa-microchip", chip=True,
            dom_id={"panel": "backendSelect", "batch": "batchSettingsBackend", "item": "rSettings_backend"},
            # ── Route F4b, étape ⑤ (2026-10-07) — options par TÂCHE, clés ENTIÈRES ──────
            # Le domaine était `source='reader'` + `task` (2026-09-08), au motif que le reader
            # « possédait » ses moteurs OCR. Ce n'était plus vrai : GLM-OCR est servi par Ollama
            # (sa ligne `ollama:glm-ocr:latest`), et `reader:glm-ocr` n'en était qu'un DOUBLON,
            # retiré (« les modèles ne sont plus déclarés par application », Fabien). Domaine par
            # capacité, déclaré UNE fois (`utils/model_config.OCR_SPEC`, que le tirage « auto »
            # lit aussi) ; valeurs = clés de catalogue (migration 0012) ; lancement par la porte
            # commune (`backend_instance_for_key`, contrat OCR).
            options_source="catalog",
            options_query=OCR_SPEC,
            # « auto » en 1ʳᵉ option + prévision sous le select : le reader RÉSOUT réellement
            # « auto » au lancement (`_select_best_backend`), donc l'option a un sens.
            options_auto=True,
            # Descriptif du moteur sous le select (WamaParams → WamaModelHelp ; le script
            # wama-model-help.js doit être CHARGÉ par la page, sinon déclaration inerte).
            # help_source = catalogue, lu sur le DOMAINE du select (desc + VRAM) ; repli statique
            # indexé par CLÉ de catalogue (les valeurs d'option).
            help_source="reader",
            help_fallback={
                "auto": "Choisit automatiquement le meilleur moteur disponible selon le document et le GPU.",
                "reader:olmocr": "olmOCR-2 7B — OCR vision haute qualité (mise en page, tableaux, manuscrit). ~16 Go VRAM.",
                "reader:doctr": "docTR — pipeline détection + reconnaissance, tourne sur CPU. Idéal documents imprimés simples.",
                "ollama:glm-ocr:latest": "GLM-OCR 0.9B (via Ollama) — léger et rapide, bon compromis pour texte imprimé courant.",
            },
            stales=("read",),
        ),
        # Mode et langue : les réglages que le MOTEUR lit — sa capacité `params` (olmOCR les deux,
        # GLM-OCR la langue seule, docTR aucun ; `READER_MODELS[…]['params']` et `FAMILLES_OLLAMA`).
        # Un moteur qui ne les lit pas les GRISE, raison dite (`cap_from` « reads », 2026-10-13).
        # Ce grisage était câblé à la main dans `reader.js` (`wireEngineParams`, 29/09) et ne
        # grisait plus rien depuis les clés entières du 07/10 (`'reader:' + 'reader:olmocr'`).
        "mode": dict(
            type="select", label="Mode de lecture", icon="fa-pen-nib", chip=True,
            dom_id={"panel": "modeSelect", "batch": "batchSettingsMode", "item": "rSettings_mode"},
            cap_from={"field": "backend", "capability": "params", "mode": "reads",
                      "reason": "Ce moteur ne tient pas compte du mode de lecture."},
            stales=("read",),
        ),
        "language": dict(
            type="text", label="Langue", icon="fa-language", chip=True,
            dom_id={"panel": "languageInput", "batch": "batchSettingsLanguage", "item": "rSettings_language"},
            help="Optionnel (ex. fr, en). Auto-détection si vide.",
            cap_from={"field": "backend", "capability": "params", "mode": "reads",
                      "reason": "Ce moteur ne tient pas compte de la langue indiquée."},
            # La mise en forme la lit aussi (indice de langue donné au LLM).
            stales=("read", "format"),
        ),
        "output_format": dict(
            type="select", label="Format de sortie", icon="fa-file-lines", chip=True,
            # section="output" : ce chip décrit ce qui va SORTIR, pas comment on traite. La card
            # v3 le range donc en section Sortie sans que la vue ait à le savoir (§11).
            section="output",
            dom_id={"panel": "outputFormatSelect", "batch": "batchSettingsOutputFormat",
                    "item": "rSettings_output_format"},
            help="Format du texte produit. Les autres formats restent téléchargeables ensuite.",
        ),
        # ── Le modèle de LANGAGE et les deux process qui l'emploient (2026-10-13) ────────────
        # « auto » = leur comportement d'avant : le gabarit « par défaut » du describer pour la mise
        # en forme, le modèle par défaut de l'instance pour l'analyse. Une prévision du catalogue
        # ne dirait pas cette règle : le select se TAIT (`options_auto="silent"`, patron du
        # describer). Une clé désigne un modèle local, jamais remplacé en silence.
        "llm_model": dict(
            type="select", label="Modèle de langage", icon="fa-brain", chip=True,
            options_source="catalog",
            options_query={"model_type": "llm"},
            options_auto="silent",
            help_source="reader",
            help_fallback={"auto": "Choisi au lancement : le modèle de mise en forme habituel, "
                                   "le modèle par défaut de l'instance pour l'analyse."},
            dom_id={"panel": "llmModelSelect", "batch": "batchSettingsLlmModel",
                    "item": "rSettings_llm_model"},
            stales=("format", "analyze"),
        ),
        # Sa TEMPÉRATURE (2026-10-21) : le réglage commun, lié au choix du modèle de langage.
        "llm_temperature": temperature_param(
            "llm_model",
            dom_id={"panel": "llmTemperature", "batch": "batchSettingsLlmTemperature",
                    "item": "rSettings_llm_temperature"},
            stales=("format", "analyze"),
        ),
        # Ses deux voisins (2026-10-22) : vides = un tirage neuf, celui du modèle.
        "llm_seed": seed_param(
            "llm_model",
            dom_id={"panel": "llmSeed", "batch": "batchSettingsLlmSeed",
                    "item": "rSettings_llm_seed"},
            stales=("format", "analyze"),
        ),
        "llm_top_p": top_p_param(
            "llm_model",
            dom_id={"panel": "llmTopP", "batch": "batchSettingsLlmTopP",
                    "item": "rSettings_llm_top_p"},
            stales=("format", "analyze"),
        ),
        # Les INTERRUPTEURS des process optionnels : ils sont le `toggle` de leur process, ils ne
        # périment rien. La mise en forme est COCHÉE par défaut : elle avait toujours lieu.
        "format_markdown": dict(
            type="toggle", label="Mettre en forme (Markdown)", icon="fa-heading",
            dom_id={"panel": "formatMarkdownToggle", "batch": "batchSettingsFormatMarkdown",
                    "item": "rSettings_format_markdown"},
            help="Titres, listes et tableaux remis en Markdown par un LLM, sans rien retrancher. "
                 "Le texte natif d'un PDF reste tel quel.",
        ),
        "generate_analysis": dict(
            type="toggle", label="Analyser (résumé, points clés)", icon="fa-magnifying-glass-chart",
            dom_id={"panel": "generateAnalysisToggle", "batch": "batchSettingsGenerateAnalysis",
                    "item": "rSettings_generate_analysis"},
        ),
    },
)

PARAMS_JSON = schema_to_dicts(PARAMS)

# ── Réglages UTILISATEUR — dérivés du schéma (contrat 3 de `WAMA_VERIFICATION §8`, 2026-10-18) ──
# La brique commune `user_settings` les garde, les relit et fait naître une lecture avec eux
# (`new_element_settings`). Ils se gardent sous le NOM du réglage : c'était déjà le cas (moteur,
# mode, format, langue et curseur, écrits par une liste à la main dans les vues) — frontière des
# données, rien à migrer —, et c'est sous ce nom que `auto_model.quality_intent_of` relit le curseur.
from wama.common.utils.param_schema import panel_defaults, panel_name_key  # noqa: E402

user_setting_key = panel_name_key
USER_SETTINGS_DEFAULTS = panel_defaults(PARAMS, key=user_setting_key)

"""
Schéma de paramètres Reader — SOURCE UNIQUE pour l'inspecteur (context "panel"), la modale BATCH
(context "batch") et la modale ⚙ d'ITEM (context "item" — rendue par le cycle commun
`WamaParams.settingsModal` depuis le 2026-09-24 ; « Reader n'a pas de modale item » était un
constat périmé).

Dérivé du modèle `ReadingItem` (mode = TextChoices du modèle ; le moteur, du CATALOGUE). Rendu par
`WamaParams.render(container, PARAMS_JSON, {context})`. Les `dom_id` reprennent les IDs LEGACY de
chaque surface → JS existant + apparence préservés. Gabarit : transcriber/params.py.
"""
from wama.common.utils.auto_model import intent_param
from wama.common.utils.param_schema import derive_from_model, schema_to_dicts
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
    include=["backend", "quality_intent", "mode", "language", "output_format"],
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
        ),
        "mode": dict(
            type="select", label="Mode de lecture", icon="fa-pen-nib", chip=True,
            dom_id={"panel": "modeSelect", "batch": "batchSettingsMode", "item": "rSettings_mode"},
        ),
        "language": dict(
            type="text", label="Langue", icon="fa-language", chip=True,
            dom_id={"panel": "languageInput", "batch": "batchSettingsLanguage", "item": "rSettings_language"},
            help="Optionnel (ex. fr, en). Auto-détection si vide.",
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
    },
)

PARAMS_JSON = schema_to_dicts(PARAMS)

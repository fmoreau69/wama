"""
Schéma de paramètres Reader — SOURCE UNIQUE pour l'inspecteur (context "panel") et la modale BATCH
(context "batch"). Reader n'a pas de modale item → contexts = panel + batch.

Dérivé du modèle `ReadingItem` (backend/mode = TextChoices du modèle). Rendu par
`WamaParams.render(container, PARAMS_JSON, {context})`. Les `dom_id` reprennent les IDs LEGACY de
chaque surface → JS existant + apparence préservés. Gabarit : transcriber/params.py.
"""
from wama.common.utils.param_schema import derive_from_model, schema_to_dicts
from wama.reader.models import ReadingItem

PARAMS = derive_from_model(
    ReadingItem,
    # output_format ajouté 2026-08-01 : il était sur le modèle mais absent du schéma, donc
    # NI réglable dans l'inspecteur, NI affiché sur la card. C'est le champ qui décrit ce qui
    # va SORTIR — il alimente la section Sortie de la card v3 via section="output".
    include=["backend", "mode", "language", "output_format"],
    overrides={
        "backend": dict(
            type="select", label="Moteur OCR", icon="fa-microchip", chip=True,
            dom_id={"panel": "backendSelect", "batch": "batchSettingsBackend", "item": "rSettings_backend"},
            # ── Route F4b (2026-09-08) — les options viennent du CATALOGUE ────────────────
            # Les `choices` du modèle (TextChoices `Backend`) figeaient la liste : un moteur
            # OCR installé n'apparaissait jamais sans édition de code. Le domaine déclaré ici
            # est EXACTEMENT celui que `_select_best_backend` interroge déjà pour résoudre
            # « auto » (`select_model_id('reader', task='ocr')`, tasks.py) — un seul domaine,
            # deux usages : ce que le select PROPOSE et ce que « auto » TIRE ne peuvent plus
            # diverger (c'est la propriété que la brique `auto_model` cherche par
            # `catalog_domain`). `source` est légitime ICI, à l'inverse du parc TTS partagé :
            # les 3 moteurs OCR (olmocr/doctr/glm-ocr) sont possédés par le reader, et c'est
            # lui seul qui les exécute. Il maintient aussi l'ESPACE DE CLÉS de la colonne :
            # domaine avec `source` → identifiants nus ('olmocr'), ceux que `ReadingItem.backend`
            # porte déjà et que `backend_for_key('reader:' + …)` recompose.
            options_source="catalog",
            options_query={"source": "reader", "task": "ocr"},
            # « auto » en 1ʳᵉ option + prévision sous le select : le reader RÉSOUT réellement
            # « auto » au lancement (`_select_best_backend`), donc l'option a un sens.
            options_auto=True,
            # Descriptif du moteur sous le select (WamaParams → WamaModelHelp ; le script
            # wama-model-help.js doit être CHARGÉ par la page, sinon déclaration inerte).
            # help_source = catalogue (doctr/olmocr y sont : desc + VRAM) ; repli statique
            # pour les valeurs hors catalogue (auto, glm-ocr).
            help_source="reader",
            help_fallback={
                "auto": "Choisit automatiquement le meilleur moteur disponible selon le document et le GPU.",
                "olmocr": "olmOCR-2 7B — OCR vision haute qualité (mise en page, tableaux, manuscrit). ~16 Go VRAM.",
                "doctr": "docTR — pipeline détection + reconnaissance, tourne sur CPU. Idéal documents imprimés simples.",
                "glm-ocr": "GLM-OCR 0.9B (via Ollama) — léger et rapide, bon compromis pour texte imprimé courant.",
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

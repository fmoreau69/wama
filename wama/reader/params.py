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
            # Descriptif du moteur sous le select (systématique via WamaParams/WamaModelHelp).
            # Moteurs OCR maison → pas dans le catalogue model_manager : repli statique par valeur.
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

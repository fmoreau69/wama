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
    include=["backend", "mode", "language"],
    overrides={
        "backend": dict(
            type="select", label="Moteur OCR", icon="fa-microchip",
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
            type="select", label="Mode de lecture", icon="fa-pen-nib",
            dom_id={"panel": "modeSelect", "batch": "batchSettingsMode", "item": "rSettings_mode"},
        ),
        "language": dict(
            type="text", label="Langue", icon="fa-language",
            dom_id={"panel": "languageInput", "batch": "batchSettingsLanguage", "item": "rSettings_language"},
            help="Optionnel (ex. fr, en). Auto-détection si vide.",
        ),
    },
)

PARAMS_JSON = schema_to_dicts(PARAMS)

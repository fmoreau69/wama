"""
Emplacement canonique des modèles IA — dérivé de la CATÉGORIE (ModelType).

Règle unique : un modèle vit dans `AI-models/models/{category}/{family}/`, où `category`
est la valeur `ModelType` (minuscule) telle qu'estampillée dans le model_manager, et
`family` la sous-famille (whisper, kokoro, sam, blip, olmocr, yolo…).

Objectif : un seul endroit décide de l'emplacement → fin des dossiers ad-hoc (nom d'app
comme `reader`, nom long comme `vision-language`) et des mauvais emplacements.

NB : calcul PARESSEUX depuis `settings.AI_MODELS_DIR` (pas d'import au niveau settings →
évite l'import circulaire ; settings.py définit MODEL_PATHS en direct).
"""

from pathlib import Path
from django.conf import settings

# Alias historiques tolérés en entrée → catégorie canonique (le temps de la migration).
_CATEGORY_ALIASES = {
    'vision-language': 'vlm',
    'vision_language': 'vlm',
    'reader': 'ocr',          # 'reader' était un nom d'app, pas une catégorie
}


def canonical_category(category: str) -> str:
    """Normalise un nom de catégorie (gère les alias historiques) en valeur canonique."""
    c = str(category).strip().lower()
    return _CATEGORY_ALIASES.get(c, c)


def models_root() -> Path:
    return Path(settings.AI_MODELS_DIR) / "models"


def model_dir(category: str, family: str = None) -> Path:
    """
    Chemin canonique d'une catégorie (et famille) : `AI-models/models/{category}/{family}`.

    Args:
        category : valeur ModelType ('vlm', 'ocr', 'speech', 'vision', 'diffusion',
                   'music', 'upscaling', …). Les alias 'vision-language'/'reader' sont
                   normalisés.
        family   : sous-famille optionnelle (nom de dossier tel quel : 'whisper', 'blip'…).

    Returns:
        pathlib.Path (le dossier n'est PAS créé ici).
    """
    base = models_root() / canonical_category(category)
    return base / family if family else base

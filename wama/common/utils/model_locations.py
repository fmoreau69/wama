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
    # 2026-09-02 : `pull_model --category detect|enhance` (aide et table de l'installeur)
    # visait des dossiers inexistants — ce sont des TÂCHES, pas des catégories.
    'detect': 'vision',
    'enhance': 'upscaling',
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


# =============================================================================
# COMPOSANTS DÉCLARÉS D'UNE FAMILLE — lus par `manage.py check_model_layout`
# =============================================================================
# POURQUOI CETTE TABLE EXISTE. Un dossier de famille ne doit contenir QUE le(s) snapshot(s)
# du modèle qu'il nomme. Tout autre `models--org--nom` qu'on y trouve est, par défaut, un
# dépôt ACCIDENTEL — la signature du défaut `HF_HUB_CACHE` (cf. `CLAUDE.md §AJOUT D'UN
# NOUVEAU MODÈLE AI` et `ROADMAP §5b`) : la variable étant globale au processus, elle emporte
# les sous-dépendances dans le dossier du modèle principal.
#
# Mais certains modèles sont RÉELLEMENT faits de plusieurs dépôts HF (un pipeline pyannote,
# un tokenizer publié à part). Cette différence-là ne se DEVINE pas : elle se DÉCLARE. Sans
# déclaration, le contrôle crierait au loup sur des assemblages légitimes — et un contrôle
# qui crie au loup finit par être ignoré, donc par ne plus rien protéger.
#
# ⚠ AJOUTER UNE ENTRÉE ICI EST UNE DÉCISION, pas une formalité : on affirme que ce dépôt
# APPARTIENT à ce modèle. Si la réponse est « non, c'est une dépendance partagée » (t5, bert,
# un backbone timm), alors sa place est le CACHE PARTAGÉ et il ne faut PAS l'inscrire ici —
# il faut retirer la mutation d'environnement du backend qui l'a déposé là.
#
# Clé : `"<catégorie>/<famille>"`. Valeur : préfixes de snapshots attendus EN PLUS de ceux
# qui portent le nom de la famille.
COMPOSANTS_DECLARES = {
    # Pipeline pyannote : le diariseur charge segmentation + embedding + la pipeline elle-même,
    # trois dépôts du MÊME éditeur qui n'ont de sens qu'ensemble (déplacés là volontairement
    # depuis `speech/kokoro`, cf. ROADMAP §5b « 4 pyannote déplacés … là où le diariseur les
    # attend »).
    'speech/diarization': [
        'models--pyannote--segmentation-3.0',
        'models--pyannote--wespeaker-voxceleb-resnet34-LM',
    ],
    # Higgs Audio v2 : le générateur, son tokenizer audio et le HuBERT dont il dépend sont
    # publiés séparément par bosonai mais forment un seul moteur.
    'speech/higgs': [
        'models--bosonai--hubert_base',
    ],
}


def composants_declares(categorie: str, famille: str) -> list:
    """Snapshots légitimement attendus dans ce dossier, en plus de ceux de la famille."""
    return list(COMPOSANTS_DECLARES.get(f"{canonical_category(categorie)}/{famille}", []))

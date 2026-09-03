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

import logging
from pathlib import Path

logger = logging.getLogger(__name__)
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
# POURQUOI CE POINT EXISTE. Un dossier de famille ne doit contenir QUE le(s) snapshot(s) du
# modele qu'il nomme. Tout autre `models--org--nom` qu'on y trouve est, par defaut, un depot
# ACCIDENTEL — la signature du defaut `HF_HUB_CACHE` (`ROADMAP §5b`) : la variable etant
# globale au processus, elle emporte les sous-dependances dans le dossier du modele principal.
#
# Mais certains modeles sont REELLEMENT faits de plusieurs depots HF (un pipeline pyannote,
# un tokenizer publie a part). Cette difference-la ne se DEVINE pas : elle se DECLARE.
#
# ⚠⚠ LA TABLE EN DUR QUI VIVAIT ICI EST RETIREE (2026-09-04, demande de Fabien — l'auteur
# lui-meme avait signale l'entorse). Elle nommait 3 depots dans le SUBSTRAT. Le raisonnement
# etait juste, le LIEU etait faux : un modele porte son anatomie dans SON manifeste
# (`composition.components`, projete sur `AIModel.composition`) — c'est la qu'un composant se
# declare, avec sa cle `repo`. Une declaration ecrite dans `common/` est invisible du modele
# qu'elle decrit et oblige a editer le substrat pour ajouter un modele : les symptomes memes
# d'un nom en dur.
#
# ⚠ DECLARER RESTE UNE DECISION : on affirme que ce depot APPARTIENT au modele. Si la reponse
# est « non, c'est une dependance partagee » (t5, bert, un backbone timm), sa place est le
# CACHE PARTAGE — ne rien declarer, et retirer la mutation du backend qui l'a depose la.


def composants_declares(categorie: str, famille: str) -> list:
    """Snapshots légitimement attendus dans ce dossier — DÉRIVÉS du catalogue.

    Lit `AIModel.composition['components'][*]['repo']` des modèles qui vivent dans ce
    dossier : le modèle déclare son anatomie, le contrôle en dérive. Rien de déclaré →
    liste vide, donc le détecteur SIGNALE au lieu de masquer (« mieux vaut des cas à
    qualifier qu'une table inventée qui en masque »).

    Hors Django / base absente : liste vide — un contrôle de disposition doit rester
    utilisable sans base, quitte à être plus bavard.
    """
    cible = f"{canonical_category(categorie)}/{famille}".strip('/')
    prefixes = []
    try:
        from wama.model_manager.models import AIModel
        for m in AIModel.objects.exclude(composition={}).only('local_path', 'composition'):
            lieu = Path(m.local_path or '.').as_posix()
            if cible and cible not in lieu:
                continue
            for c in ((m.composition or {}).get('components') or []):
                repo = (c or {}).get('repo')
                if repo:
                    prefixes.append('models--' + str(repo).replace('/', '--'))
    except Exception as e:
        logger.debug('[model_locations] composants non dérivables : %s', e)
    return prefixes

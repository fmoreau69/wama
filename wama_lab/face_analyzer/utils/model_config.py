"""Modèles du Face Analyzer — DÉCLARATION (la seule autorité pour le catalogue).

⚠ **Modèle ≠ librairie**, et la confusion coûte cher ici (recadrage Fabien, 2026-09-05) :
  • `deepface`, `fer`, `mediapipe` sont des **LIBRAIRIES** → registre `Library`, semées par
    `manage.py manifest_export --kind library <clé>` depuis `venv_linux` ;
  • les fichiers `.h5` que DeepFace télécharge sont des **MODÈLES** → catalogue `AIModel`,
    découverts par `model_registry._discover_face_analyzer_models()`.
Une librairie n'a pas de VRAM ni de poids ; un modèle n'a pas de version pip. Les mélanger
rendrait les deux registres faux d'un coup.

**Pourquoi FER et MediaPipe n'ont AUCUNE entrée ici** : leurs poids sont **embarqués dans la
roue pip** (2,3 Mo pour `fer`, `.tflite` internes pour `mediapipe`). Il n'y a rien à télécharger,
rien à ranger, rien à mettre au catalogue — la librairie EST le modèle. Les cataloguer
inventerait un objet que personne ne peut installer ni supprimer séparément.

**Source des poids DeepFace** : GitHub Releases de `serengil/deepface_models` (source `github`
du registre des sources externes, famille « poids »). La lib n'expose **aucun** chemin
HuggingFace — vérifié le 2026-09-05 dans `weight_utils.py` : il n'y a donc pas de « mieux » à
faire côté source, contrairement au réflexe HF-d'abord.
"""
from pathlib import Path

from django.conf import settings

# ── ALIGNEMENT SUR LES MÉCANISMES WAMA (2026-09-05, cadrage Fabien) ──────────────────────
# L'app date d'avant les évolutions et n'est PAS portée (décision explicite : les apps Lab
# entreront au général plus tard). Ces déclarations sont néanmoins écrites AU FORMAT DE LA
# CIBLE, pour que le portage n'ait rien à refaire :
#
#   • `MODEL_PATHS['vision']['deepface']` (settings) — convention de chemin de toutes les apps ;
#   • ce `utils/model_config.py` — le domicile de déclaration que la checklist du CLAUDE.md
#     impose à chaque app ;
#   • `model_registry._discover_face_analyzer_models()` — le mécanisme documenté (« Découverte
#     unifiée des modèles », 13 consommateurs), et non un chemin parallèle ;
#   • `ModelSource.WAMA_FACE_ANALYZER` — l'énumération ne couvrait que le monde Médias ;
#   • `composition.runtime.engine` — la MOITIÉ MODÈLE du lien modèle↔moteur.
#
# ⚠⚠ CE QUI RESTE FAUX, ET QUE LE PORTAGE DEVRA COMBLER — à lire avant de croire le catalogue :
# `deepface` n'est PAS dans `known_engines()`, parce qu'aucun backend ne le DÉCLARE (l'app n'a
# pas de paquet `backends/`). Le verdict de disponibilité paraît bon uniquement parce que
# `backend_ref='face_analyzer'` court-circuite `backend_missing()` — c'est-à-dire par le champ
# que le dépôt veut RETIRER. Le jour où il tombe, ces 3 modèles seront grisés « moteur deepface
# sans backend installé », et ce sera JUSTE.
# Le portage doit donc créer `wama_lab/face_analyzer/backends/` avec une classe déclarant
# `ENGINE = 'deepface'` — même graphie qu'ici, sinon le lien ne se referme pas.
# *Un verdict sauvé par un champ condamné n'est pas un verdict.*

#: Racine où `DEEPFACE_HOME` (posé dans `settings.py`) fait atterrir les poids. La lib ajoute
#: elle-même `.deepface/weights` : cette convention est la SIENNE, on la lit, on ne la corrige pas.
DEEPFACE_DIR = Path(settings.MODEL_PATHS['vision']['deepface']) / '.deepface' / 'weights'

#: Dépôt GitHub d'où sortent les poids — nommé UNE fois (identifiant, pas une URL construite).
DEEPFACE_RELEASES = 'serengil/deepface_models'

#: Les poids réellement utilisés par l'app. `age`/`gender` ne servent QUE si `enable_age_gender`
#: est activé dans l'interface — d'où leur `optional`, qui explique pourquoi 1 Go peut manquer
#: sans que l'app soit cassée.
FACE_ANALYZER_MODELS = {
    'deepface-expression': {
        'fichier': 'facial_expression_model_weights.h5',
        'type': 'vision',
        'engine': 'deepface',
        'optional': False,
        'vram_gb': 0.3,
        'description': "Reconnaissance d'expressions faciales (7 émotions) — backend DeepFace",
    },
    'deepface-age': {
        'fichier': 'age_model_weights.h5',
        'type': 'vision',
        'engine': 'deepface',
        'optional': True,
        'vram_gb': 1.0,
        'description': "Estimation d'âge — chargé seulement si « Âge & Genre » est activé",
    },
    'deepface-gender': {
        'fichier': 'gender_model_weights.h5',
        'type': 'vision',
        'engine': 'deepface',
        'optional': True,
        'vram_gb': 1.0,
        'description': "Estimation de genre — chargé seulement si « Âge & Genre » est activé",
    },
}


def chemin_local(model_id: str) -> Path:
    """Chemin du fichier de poids — existe ou non, c'est l'appelant qui mesure."""
    return DEEPFACE_DIR / FACE_ANALYZER_MODELS[model_id]['fichier']

"""Les MAINS qui pilotent les scènes 3D (2026-10-22, demande de Fabien) — le modèle des gestes,
DÉCLARÉ à côté de son consommateur, la brique `common/js/wama-hands.js`.

Le geste se reconnaît DANS LE NAVIGATEUR (MediaPipe Tasks Vision, vendorisé sous
`static/vendors/mediapipe-tasks-vision-*`, section `mediapipe` de `tools/update_vendors.sh`) :
aucune image de la webcam ne part au serveur. Le serveur ne fait que SERVIR le modèle installé.

Le modèle est une ligne du catalogue comme une autre (`model_registry._discover_hand_gesture_models`),
installée et désinstallée par la route (pilote `files`, origine officielle `mediapipe_models` — la
même que le Face Landmarker du Face Analyzer, rangée dans le même dossier `vision/mediapipe`). Aucun
téléchargement « au premier usage » : absent, la scène le dit et renvoie à la gestion des modèles.
"""
from pathlib import Path

#: Clé de sa ligne au catalogue.
GESTURE_KEY = 'custom:mediapipe-gesture-recognizer'

#: `gesture_recognizer.task`, version `float16/1`, à son adresse OFFICIELLE. Taille et empreinte
#: MESURÉES le 2026-10-22 sur le fichier que sert Google.
GESTURE_FILES = [
    {'path': 'gesture_recognizer.task', 'size': 8373440,
     'sha256': '97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482',
     'origin': {'source': 'mediapipe_models',
                'file': 'gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task'}},
]

#: Le dossier vendorisé de MediaPipe Tasks Vision (sous `static/`) — le bundle ES et ses moteurs.
TASKS_VISION_VENDOR = 'vendors/mediapipe-tasks-vision-1.1.1'


def gesture_folder() -> Path:
    from django.conf import settings
    return Path(settings.MODEL_PATHS['vision']['mediapipe'])


def gesture_model_path() -> Path:
    """Chemin du modèle — existe ou non, c'est l'appelant qui mesure."""
    return gesture_folder() / GESTURE_FILES[0]['path']


def gesture_model_installed() -> bool:
    from wama.model_manager.services.model_installer import declared_files_present
    return declared_files_present(gesture_folder(), GESTURE_FILES)

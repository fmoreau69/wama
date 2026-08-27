# Face Analyzer — analyse faciale en vidéo expérimentale (WAMA Lab)

Application du monde **Lab** : extraction de variables comportementales et physiologiques depuis
des vidéos de visage (expérimentations en psychologie/ergonomie), croisables avec les autres
données du laboratoire.

**Accès** : `http://<serveur>/lab/face-analyzer/` (menu Applications → WAMA Lab). C'est une app
**Django** (`views.py`, `tasks.py`, `pipeline.py::FaceAnalysisPipeline`) — le `app.py` à la racine
n'est qu'un stub d'arguments, ne pas s'en servir.

## Ce que l'app analyse

| Module | Fichier | Sorties |
|---|---|---|
| Émotions | `emotions.py` | 2 backends au choix : **FER** (rapide, émotions seules) ou **DeepFace** (plus précis + âge/genre — `enable_age_gender` DeepFace-only) |
| rPPG | `rppg.py` | fréquence cardiaque estimée par photopléthysmographie à distance |
| Respiration | `respiration.py` | fréquence respiratoire |
| Regard | `eye_tracking.py` | indicateurs oculométriques |

Détection de visage : **MediaPipe**. Le backend émotions se choisit dans l'interface
(« Backend émotions : FER (rapide) / DeepFace (complet) », « Âge & Genre » activable en DeepFace).

## Installation

L'app utilise des **venvs isolés** (`venv_win/`, `venv_linux/`) :

```bash
cd wama_lab/face_analyzer
# Windows : venv_win\Scripts\activate     Linux : source venv_linux/bin/activate
pip install -r requirements/windows.txt   # ou requirements/linux.txt
```

Paquets clés : `opencv-python`, `numpy`, `scipy`, `mediapipe`, puis **au moins un** backend
émotions — `fer` (léger) et/ou `deepface` (complet ; les deux tirent TensorFlow, ~0,5-1 Go).

Migrations : `python manage.py makemigrations face_analyzer && python manage.py migrate face_analyzer`.

### Vérification

```bash
python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings'); django.setup()
from wama_lab.face_analyzer.pipeline import FaceAnalysisPipeline
print('Face Analyzer imports OK')
import mediapipe, cv2
print('MediaPipe', mediapipe.__version__, '/ OpenCV', cv2.__version__)
for mod, nom in (('fer', 'FER'), ('deepface', 'DeepFace')):
    try: __import__(mod); print(nom, 'backend: OK')
    except ImportError: print(nom, 'backend: NOT INSTALLED')
"
```

## Journalisation

Logger `wama_lab.face_analyzer` (console) — passer le niveau à `DEBUG` dans `LOGGING` des
settings pour le détail par frame.

## Dépannage

- **MediaPipe ne s'initialise pas** : réinstaller une version épinglée (`pip install mediapipe==0.10.9`).
- **Erreurs CUDA via TensorFlow (FER)** : `pip install tensorflow-cpu`.
- **Mémoire limitée** : décocher « Émotions » (le module le plus gourmand) avant de lancer.

---

*Ce README a absorbé l'ex-`INSTALLATION.md` le 2026-08-27 (archivé
`docs/archive/FACE_ANALYZER_INSTALLATION.md`) — un domaine = un fichier.*

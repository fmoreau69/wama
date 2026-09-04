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

⚠ **Cette section annonçait des « venvs isolés » (`venv_win/`, `venv_linux/`) — c'est PÉRIMÉ**
(corrigé le 2026-09-04 après vérification). L'app tourne dans le **venv principal**, comme toute
autre app WAMA : elle est en `INSTALLED_APPS`, sa tâche est routée vers la file `gpu`, et FER,
DeepFace, MediaPipe et TensorFlow s'importent réellement depuis `venv_linux` (mesuré, import réel
et non `find_spec`). Les deux dossiers de venv restés ici sont des **reliquats** de l'époque
autonome — `venv_linux/` n'a d'ailleurs jamais servi (créé sous Windows : arborescence
`Scripts/Lib`, 0 paquet installé).

Cette contradiction interne — le haut de ce même fichier disait déjà « c'est une app Django,
`app.py` n'est qu'un stub, ne pas s'en servir » — a réellement induit en erreur.
*Une doc qui se contredit coûte plus cher qu'une doc absente.*

```bash
# Depuis la racine du dépôt, dans le venv PRINCIPAL :
pip install -r wama_lab/face_analyzer/requirements/linux.txt
```

⚠ **Ne pas lancer cette commande telle quelle sur le venv principal.** Mesuré le 2026-09-04 par
simulation (`pip install --dry-run`, lecture seule) : elle rétrograderait **tensorflow 2.21.0 →
2.20.0** (pin `tf-keras` de ce fichier) et **nvidia-nccl-cu12 2.30.4 → 2.27.5**, qui est une
dépendance de **torch**. Les pins de ce fichier demandent une passe d'harmonisation avant d'être
raccordés à la chaîne d'installation racine — c'est pourquoi `requirements_linux.txt` le NOMME
sans l'inclure.

*C'est aussi la démonstration du critère : la simulation a vu la casse avant qu'elle arrive, là
où `pip check` — 46 conflits sur un venv qui marche — n'aurait rien dit d'utile.*

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

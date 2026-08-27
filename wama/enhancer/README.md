# Enhancer - AI Image/Video Upscaling

## 🎯 Vue d'ensemble

**Enhancer** est une application Django intégrée à WAMA qui permet d'améliorer la qualité des images et vidéos en utilisant l'intelligence artificielle.

Elle exploite la librairie **[QualityScaler](https://github.com/Djdefrag/QualityScaler)** pour fournir :
- Upscaling x2/x4 avec plusieurs modèles AI
- Débruitage intelligent
- Support GPU via DirectML (Windows)
- Traitement par lots

## ✨ Fonctionnalités

### Images
- ✅ **7 modèles AI** disponibles (RealESR, BSRGAN, IRCNN)
- ✅ **Upscaling** jusqu'à 4x la résolution originale
- ✅ **Débruitage** avec modèles spécialisés
- ✅ **Blending** pour mélanger avec l'original
- ✅ **Tiling automatique** pour grandes images
- ✅ **Multi-GPU** support

### Vidéos
- ✅ **Traitement frame par frame**
- ✅ **Extraction/encodage** avec FFmpeg
- ✅ **Préservation FPS** original
- ✅ **Encodage H.264** haute qualité

### Audio (branche dédiée)

L'app porte aussi une **amélioration audio** complète (modèle `AudioEnhancement`,
`utils/audio_enhancer.py`, ~20 routes `audio/*` dans `urls.py`) : débruitage DeepFilterNet et
resemble-enhance, avec sa propre file. Les batchs (import multi-fichiers, actions de lot) sont
câblés sur les deux branches.

### Formats Supportés

**Images** : `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, `.tiff`, `.webp`, `.heic`

**Vidéos** : `.mp4`, `.webm`, `.mkv`, `.flv`, `.gif`, `.avi`, `.mov`, `.mpg`, `.qt`, `.3gp`

## 📦 Installation

### Étape 1 : Dépendances Python

```bash
# Activer l'environnement virtuel
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows

# Installer les dépendances
pip install onnxruntime-directml  # Pour Windows avec GPU DirectML
# OU
pip install onnxruntime-gpu  # Pour Linux/Mac avec CUDA

# Autres dépendances (normalement déjà installées)
pip install opencv-python
pip install Pillow
```

### Étape 2 : Télécharger les Modèles AI

Les modèles ONNX ne sont **pas inclus** dans le repository (trop volumineux).

#### Option A : Téléchargement automatique (par défaut)

Les modèles essentiels se téléchargent **tout seuls au démarrage de l'app**
(`apps.py::ready()` → `check_and_download_essential_models()`, gardé par `RUN_MAIN` pour ne pas
doubler sous l'autoreloader). Source : **Hugging Face `svjack/AI-onnx`**
(`utils/model_downloader.py`), destination `AI-models/enhancer/onnx/`.

Commande manuelle (état, ou tout tirer) :

```bash
python manage.py download_enhancer_models --status   # état des modèles
python manage.py download_enhancer_models --all      # tout télécharger
```

#### Option B : Téléchargement manuel (repli)

Récupérer les `.onnx` depuis https://huggingface.co/svjack/AI-onnx/tree/main et les poser dans
`AI-models/enhancer/onnx/` (le downloader renomme certains fichiers — voir
`utils/model_downloader.py` pour la correspondance exacte).

#### Modèles Requis

Les fichiers suivants doivent être présents dans `AI-models/enhancer/onnx/` :

```
AI-models/enhancer/onnx/
├── RealESR_Gx4_fp16.onnx          (22 MB)  - Recommandé pour débuter
├── RealESR_Animex4_fp16.onnx      (22 MB)
├── BSRGANx2_fp16.onnx             (4 MB)
├── BSRGANx4_fp16.onnx             (4 MB)
├── RealESRGANx4_fp16.onnx         (22 MB)
├── IRCNN_Mx1_fp16.onnx            (30 MB)
└── IRCNN_Lx1_fp16.onnx            (30 MB)
```

**Note** : Vous pouvez commencer avec uniquement `RealESR_Gx4_fp16.onnx` pour tester.

### Étape 3 : Migrations Django

```bash
# Créer les migrations
python manage.py makemigrations enhancer

# Appliquer les migrations
python manage.py migrate enhancer
```

### Étape 4 : Collecter les fichiers statiques

```bash
python manage.py collectstatic --noinput
```

### Étape 5 : Vérification

L'application est déjà ajoutée aux settings et URLs. Vérifiez :

**`wama/settings.py`** :
```python
INSTALLED_APPS = [
    # ...
    'wama.enhancer',  # ✓ Déjà ajouté
]
```

**`wama/urls.py`** :
```python
urlpatterns = [
    # ...
    path('enhancer/', include(('wama.enhancer.urls', 'enhancer'), namespace='enhancer')),  # ✓ Déjà ajouté
]
```

## 🚀 Utilisation

### Démarrer les Services

```bash
# Terminal 1 : Django
python manage.py runserver

# Terminal 2 : Celery Worker
celery -A wama worker -l info
# Sur Windows :
celery -A wama worker -l info --pool=solo
```

### Accéder à l'Interface

1. Ouvrir le navigateur : `http://localhost:8000/enhancer/`
2. Glisser-déposer une image ou vidéo
3. Choisir les paramètres :
   - **Modèle AI** : RealESR_Gx4 (rapide) ou RealESRGANx4 (qualité max)
   - **Débruitage** : Activer pour réduire le bruit
   - **Blend Factor** : 0 = 100% AI, 1 = 100% Original
4. Cliquer sur **"Démarrer le traitement"**
5. Attendre la fin du traitement
6. Télécharger le résultat

## 🎨 Modèles AI Disponibles

| Modèle | Échelle | VRAM | Vitesse | Qualité | Usage |
|--------|---------|------|---------|---------|-------|
| **RealESR_Gx4** | 4x | 2.5GB | ⚡⚡⚡ | ⭐⭐⭐ | Photos générales |
| **RealESR_Animex4** | 4x | 2.5GB | ⚡⚡⚡ | ⭐⭐⭐ | Anime/Manga |
| **BSRGANx2** | 2x | 0.75GB | ⚡⚡ | ⭐⭐⭐⭐ | Haute qualité 2x |
| **BSRGANx4** | 4x | 0.75GB | ⚡⚡ | ⭐⭐⭐⭐ | Haute qualité 4x |
| **RealESRGANx4** | 4x | 2.5GB | ⚡ | ⭐⭐⭐⭐⭐ | Qualité maximale |
| **IRCNN_Mx1** | 1x | 4GB | ⚡⚡ | - | Débruitage moyen |
| **IRCNN_Lx1** | 1x | 4GB | ⚡ | - | Débruitage fort |

### Recommandations

- **Débutant** : `RealESR_Gx4` (rapide, bon compromis)
- **Anime** : `RealESR_Animex4`
- **Qualité Max** : `RealESRGANx4` (lent mais excellent)
- **Léger** : `BSRGANx2` ou `BSRGANx4`
- **Photos bruitées** : Activer le débruitage avec `IRCNN_Mx1`

## ⚙️ Configuration Avancée

### Tiling pour Grandes Images

Le système utilise automatiquement le tiling pour les grandes images :
- **Auto** : Taille calculée selon VRAM du modèle (512 ou 1024px)
- **Manuel** : Définir `tile_size` dans le modèle Enhancement

### Multi-GPU

Pour utiliser un GPU spécifique (si vous avez plusieurs GPUs) :

```python
# Dans ai_upscaler.py
upscaler = AIUpscaler(model_name='RealESR_Gx4', device_id=1)  # GPU #1
```

### Paramètres par Défaut

Les utilisateurs peuvent définir leurs paramètres par défaut via l'interface ou en base de données :
- `default_ai_model` : Modèle utilisé par défaut
- `default_denoise` : Activer/désactiver le débruitage
- `default_blend_factor` : Facteur de mélange par défaut

## 📊 Performances

### Images (GPU GTX 1660 Ti)

| Résolution | Modèle | Temps | Output |
|------------|--------|-------|--------|
| 512x512 | RealESR_Gx4 | ~2s | 2048x2048 |
| 1920x1080 | RealESR_Gx4 | ~8s | 7680x4320 |
| 1920x1080 | RealESRGANx4 | ~15s | 7680x4320 |
| 4096x4096 | BSRGANx2 | ~25s | 8192x8192 |

### Vidéos

| Vidéo | Frames | Modèle | Temps |
|-------|--------|--------|-------|
| 720p 30fps 10s | 300 | RealESR_Gx4 | ~5 min |
| 1080p 30fps 30s | 900 | BSRGANx2 | ~10 min |

**Note** : Performances dépendent de :
- Puissance GPU
- Résolution
- Modèle choisi
- VRAM disponible

## 🐛 Dépannage

### Problème : Modèle non trouvé

```
Model file not found: /path/to/RealESR_Gx4_fp16.onnx
```

**Solution** :
1. Vérifier que `AI-models/enhancer/onnx/` existe
2. Télécharger les modèles depuis QualityScaler
3. Vérifier les permissions de lecture

### Problème : ONNX Runtime Error

```
Failed to load model: DML execution provider not available
```

**Solution** :
```bash
pip uninstall onnxruntime onnxruntime-gpu
pip install onnxruntime-directml  # Windows
# OU
pip install onnxruntime-gpu  # Linux avec CUDA
```

### Problème : Out of Memory

```
CUDA out of memory
```

**Solution** :
1. Utiliser un modèle plus léger : `BSRGANx2` ou `BSRGANx4`
2. Réduire `tile_size` dans le code
3. Fermer d'autres applications utilisant le GPU
4. Traiter des images/vidéos plus petites

### Problème : FFmpeg non trouvé

```
[Errno 2] No such file or directory: 'ffmpeg'
```

**Solution** :
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg

# Windows
# Télécharger depuis https://ffmpeg.org/download.html
# Ajouter au PATH
```

### Problème : Traitement très lent

**Solutions** :
1. Vérifier que le GPU est utilisé (pas le CPU)
2. Utiliser un modèle plus rapide (`RealESR_Gx4`)
3. Réduire la résolution source
4. Vérifier que DirectML/CUDA est bien configuré

## 🔧 Développement

### Structure du Code

```
wama/enhancer/
├── models.py           # Enhancement, UserSettings
├── views.py            # 10 vues HTTP
├── urls.py             # Routing
├── tasks.py            # Celery tasks
├── utils/
│   ├── ai_upscaler.py      # Intégration QualityScaler
│   └── model_downloader.py # Téléchargement automatique
├── templates/
│   └── enhancer/
│       ├── base.html
│       └── index.html
└── static/
    └── enhancer/
        ├── css/style.css
        └── js/index.js

AI-models/enhancer/onnx/  # Modèles (centralisés)
```

### API Endpoints

```
POST /enhancer/upload/              # Upload fichier
POST /enhancer/start/<id>/          # Démarrer traitement
GET  /enhancer/progress/<id>/       # Obtenir progression
GET  /enhancer/download/<id>/       # Télécharger résultat
POST /enhancer/delete/<id>/         # Supprimer
POST /enhancer/update_settings/<id>/ # Modifier paramètres
POST /enhancer/start_all/           # Démarrer tous
POST /enhancer/clear_all/           # Tout effacer
GET  /enhancer/download_all/        # Télécharger tout (ZIP)
```

### Tests

```bash
# Test du worker
python manage.py shell
>>> from wama.enhancer.tasks import enhance_media
>>> enhance_media.delay(1)  # Enhancement ID 1

# Test de l'upscaler
python manage.py shell
>>> from wama.enhancer.utils.ai_upscaler import upscale_image_file
>>> upscale_image_file('input.jpg', 'output.jpg', model_name='RealESR_Gx4')
```

## 📝 TODO / Améliorations Futures

- [ ] Support CUDA natif pour Linux
- [ ] Batch processing optimisé
- [ ] Aperçu avant/après
- [ ] Crop & Enhance (améliorer une zone)
- [ ] Support H.265, VP9, AV1 pour vidéos
- [ ] Hardware encoding (NVENC, AMF, QSV)
- [ ] Modèles personnalisés
- [ ] API REST complète
- [ ] Webhook notifications

## 📚 Ressources

- **QualityScaler** : https://github.com/Djdefrag/QualityScaler
- **Real-ESRGAN** : https://github.com/xinntao/Real-ESRGAN
- **ONNX Runtime** : https://onnxruntime.ai/
- **DirectML** : https://github.com/microsoft/DirectML

## 📄 License

Cette application suit la même licence que WAMA.

QualityScaler est sous licence MIT.

## 🙏 Crédits

- **Djdefrag** pour [QualityScaler](https://github.com/Djdefrag/QualityScaler)
- **Tencent** pour Real-ESRGAN
- **cszn** pour BSRGAN
- **Microsoft** pour ONNX Runtime et DirectML

---

**Bon upscaling ! 🚀✨**

# Enhancer App - Documentation

## Vue d'ensemble

L'application **Enhancer** est une nouvelle application Django intégrée à WAMA qui permet d'améliorer la qualité des images et vidéos en utilisant l'intelligence artificielle.

Elle est basée sur la librairie **[QualityScaler](https://github.com/Djdefrag/QualityScaler)** par Djdefrag, qui utilise des modèles de deep learning (Real-ESRGAN, BSRGAN, IRCNN) pour l'upscaling et le débruitage.

## Fonctionnalités

### Images
- ✅ Upscaling x2 ou x4 avec différents modèles AI
- ✅ Débruitage avec modèles IRCNN
- ✅ Blending avec l'image originale
- ✅ Tiling automatique pour grandes images
- ✅ Support multi-GPU (DirectML)

### Vidéos
- ✅ Upscaling frame par frame
- ✅ Extraction/encodage avec FFmpeg
- ✅ Préservation du FPS original
- ✅ Encodage H.264 haute qualité

### Formats Supportés

**Images** : JPG, JPEG, PNG, BMP, TIF, TIFF, WebP, HEIC
**Vidéos** : MP4, WebM, MKV, FLV, GIF, AVI, MOV, MPG, QT, 3GP

## Modèles AI Disponibles

| Modèle | Échelle | VRAM | Description |
|--------|---------|------|-------------|
| RealESR_Gx4 | 4x | 2.5GB | Rapide, usage général |
| RealESR_Animex4 | 4x | 2.5GB | Optimisé anime/manga |
| BSRGANx2 | 2x | 0.75GB | Haute qualité, léger |
| BSRGANx4 | 4x | 0.75GB | Haute qualité |
| RealESRGANx4 | 4x | 2.5GB | Qualité maximale (lent) |
| IRCNN_Mx1 | 1x | 4GB | Débruitage moyen |
| IRCNN_Lx1 | 1x | 4GB | Débruitage fort |

## Architecture

```
wama/enhancer/
├── models.py           # Enhancement, UserSettings
├── views.py            # Upload, start, progress, download
├── urls.py             # URL routing
├── workers.py          # Celery tasks
├── utils/
│   ├── ai_upscaler.py  # Integration QualityScaler
│   └── __init__.py
├── templates/
│   └── enhancer/
│       ├── base.html
│       └── index.html
├── static/
│   └── enhancer/
│       ├── css/
│       └── js/
│           └── index.js
└── migrations/
```

## Installation

### 1. Dépendances

```bash
pip install onnxruntime-directml  # Pour Windows avec DirectML
pip install opencv-python
pip install Pillow
```

### 2. Télécharger les Modèles AI

1. Créer le répertoire : `wama/enhancer/AI-onnx/`
2. Télécharger les modèles depuis le repo QualityScaler
3. Placer les fichiers `.onnx` dans ce répertoire

Exemple de structure :
```
wama/enhancer/AI-onnx/
├── RealESR_Gx4_fp16.onnx
├── RealESR_Animex4_fp16.onnx
├── BSRGANx2_fp16.onnx
├── BSRGANx4_fp16.onnx
├── RealESRGANx4_fp16.onnx
├── IRCNN_Mx1_fp16.onnx
└── IRCNN_Lx1_fp16.onnx
```

### 3. Ajouter à Django Settings

Dans `wama/settings.py` :

```python
INSTALLED_APPS = [
    # ...
    'wama.enhancer',
    # ...
]
```

Dans `wama/urls.py` :

```python
urlpatterns = [
    # ...
    path('enhancer/', include('wama.enhancer.urls')),
    # ...
]
```

### 4. Migrations

```bash
python manage.py makemigrations enhancer
python manage.py migrate enhancer
```

### 5. Collecter les fichiers statiques

```bash
python manage.py collectstatic
```

## Utilisation

### Interface Web

1. Accéder à `/enhancer/`
2. Glisser-déposer une image ou vidéo
3. Choisir le modèle AI
4. (Optionnel) Activer le débruitage
5. (Optionnel) Ajuster le blend factor
6. Cliquer sur "Start Process"
7. Télécharger le résultat

### API

#### Upload
```javascript
POST /enhancer/upload/
FormData: {file: File}
→ {id, media_type, input_url, width, height, status}
```

#### Start Enhancement
```javascript
POST /enhancer/start/<id>/
FormData: {ai_model, denoise, blend_factor}
→ {task_id, status}
```

#### Check Progress
```javascript
GET /enhancer/progress/<id>/
→ {progress, status, error_message}
```

#### Download Result
```javascript
GET /enhancer/download/<id>/
→ Enhanced file
```

## Configuration Avancée

### Paramètres par Défaut

Les utilisateurs peuvent définir leurs paramètres par défaut dans `UserSettings` :
- `default_ai_model` : Modèle utilisé par défaut
- `default_denoise` : Activer le débruitage par défaut
- `default_blend_factor` : Facteur de mélange par défaut

### Tiling

Pour les grandes images, le système utilise automatiquement le tiling :
- **Auto** : Taille calculée selon VRAM du modèle
- **Manuel** : Spécifier `tile_size` dans Enhancement

### Multi-GPU

Pour utiliser un GPU spécifique :
```python
upscaler = AIUpscaler(model_name='RealESR_Gx4', device_id=1)  # GPU #1
```

## Performance

### Images
- **512x512 → 2048x2048** : ~2-5 secondes (RealESR_Gx4)
- **1920x1080 → 7680x4320** : ~10-30 secondes avec tiling

### Vidéos
- **720p → 2880p (30fps, 10sec)** : ~5-10 minutes
- Performance dépend de :
  - Nombre de frames
  - Résolution
  - Modèle choisi
  - Puissance GPU

## Limitations

1. **Modèles requis** : Les fichiers `.onnx` ne sont pas inclus (propriété de QualityScaler)
2. **VRAM** : Minimum 4GB recommandé pour les modèles légers
3. **Windows uniquement** : DirectML est spécifique à Windows (peut être adapté pour CUDA sur Linux)
4. **Vidéos longues** : Le traitement frame par frame peut être long pour vidéos > 1 min

## Améliorations Futures

1. **Batch Processing** : Traiter plusieurs fichiers en parallèle
2. **Video Codec Options** : Permettre H.265, VP9, AV1
3. **Hardware Encoding** : NVENC, AMF, QSV pour vidéos
4. **Preview** : Aperçu avant/après
5. **Crop & Enhance** : Améliorer seulement une zone
6. **Custom Models** : Support de modèles personnalisés

## Dépannage

### Modèle non trouvé
```
Model file not found: /path/to/RealESR_Gx4_fp16.onnx
```
→ Télécharger les modèles depuis QualityScaler

### Erreur ONNX Runtime
```
Failed to load model: DML execution provider not available
```
→ Installer `onnxruntime-directml`

### Out of Memory
```
CUDA out of memory
```
→ Utiliser un modèle plus léger (BSRGANx2) ou réduire `tile_size`

## Crédits

- **QualityScaler** par [Djdefrag](https://github.com/Djdefrag/QualityScaler) - MIT License
- **ONNX Runtime** par Microsoft
- **Real-ESRGAN** par Tencent
- **BSRGAN** par cszn

## License

Cette intégration suit la même licence que WAMA. QualityScaler est sous licence MIT.

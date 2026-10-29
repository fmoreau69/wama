# Enhancer - AI Image/Video Upscaling

## 🎯 Vue d'ensemble

**Enhancer** est une application Django intégrée à WAMA qui permet d'améliorer la qualité des images et vidéos en utilisant l'intelligence artificielle.

Elle exploite la librairie **[QualityScaler](https://github.com/Djdefrag/QualityScaler)** pour fournir :
- Upscaling x2/x4 avec plusieurs modèles AI
- Débruitage intelligent
- Support GPU via DirectML (Windows)
- Traitement par lots
- **Choix « Automatique » (2026-09-21)** : le modèle est tiré AU LANCEMENT par la brique commune
  d'auto-sélection (catalogue + VRAM libre), restreint au **facteur d'agrandissement** demandé
  (×2 / ×4) et pesé par le **curseur Rapide ↔ Qualité** ; côté audio, « Automatique » arbitre
  DeepFilterNet (rapide) ↔ Resemble (qualité) et décline le NFE du curseur. Un modèle désigné
  reste respecté tel quel. Déclarations de l'app : `utils/auto_model.py`.
- **Prévision et qualité MESURÉE (2026-10-14)** : le facteur est un BESOIN déclaré au schéma du
  select (`params.py`, `options_resolution.needs`) — le lancement le lit sur l'élément, la
  prévision « Prévu : … — réévalué au lancement » dans le formulaire ; elle s'affiche de nouveau
  et suit le facteur. ⚠ Jusqu'à ce jour, l'« auto » image rendait son REPLI (`RealESR_Gx4`) quel
  que soit le curseur : la liste « agrandir, débruiter » n'avait pas de catégorie au tirage
  (`ROUTE §F4b`, bloc du 14/10). Le curseur classe sur une mesure WAMA : le banc par construction
  `manage.py bench --task upscale --benchmark upscale_div2k_val_v1 --record` (DIV2K val, LPIPS —
  `WAMA_QUALITE §3`), relu au tri (étage 3) ; la vitesse mesurée y sert de coût. Un agrandisseur
  installé ensuite n'entre dans le classement qu'une fois passé au banc.

## ✨ Fonctionnalités

### Images
- ✅ **7 modèles AI** disponibles (RealESR, BSRGAN, IRCNN)
- ✅ **Upscaling** jusqu'à 4x la résolution originale
- ✅ **Débruitage** avec modèles spécialisés
- ✅ **Blending** pour mélanger avec l'original
- ✅ **Tiling automatique** pour grandes images
- ✅ **Multi-GPU** support

### Vidéos
- ✅ **Traitement image par image, par le rendu COMMUN** (`common/utils/video_render.render_video`,
  2026-10-29, décision de Fabien : « on porte l'upscale vidéo sur le rendu commun en conservant le
  son comme Anonymizer ») — le même que le floutage de l'Anonymizer :
  - **le son est gardé** : l'audio de la source est RECOPIÉ paquet par paquet, à ses propres temps
    (encodé au codec du conteneur seulement quand celui-ci ne l'accepte pas), jamais étiré ;
  - **chaque image agrandie à SON horodatage d'origine** (PyAV) : une cadence variable garde ses
    temps, rien ne s'étire ;
  - **le format d'origine, en un seul encodage**, aux codecs d'une conversion vers ce format
    (`converter.video_backend.rendering_encoding` : H.264 « visuellement sans perte » pour MP4/MOV/
    MKV) ; un conteneur hors de cette table sort en `.mp4`, et la card range ce fichier-là
    (`path` rendu par la route) ;
  - la taille de sortie est celle de l'image AGRANDIE ; « Garder la résolution d'origine » reste au
    process « Sortie » (ci-dessous).
  Jusque-là : extraction des images en PNG par ffmpeg, puis réencodage H.264 à la cadence NOMINALE
  — la vidéo sortait **muette** (constat de la revérification du 2026-10-29) et une cadence variable
  s'étirait. Gardes : `enhancer.tests.VideoRouteKeepsItsSoundTest` (vraie vidéo sonore, agrandisseur
  doublure), `enhancer.tests_task.VideoQueueTest` (le fichier rangé est celui écrit),
  `common.tests.tests_video_render` (taille changée, son, temps des images, interruption).

### Garder la résolution d'origine (images et vidéos, 2026-10-16)

Un réglage du volet et de la modale ⚙ (`output_keep_size`, chip « Résolution d'origine ») : la
qualité gagnée par l'amélioration, **sans le poids d'un fichier agrandi**. La sortie revient aux
dimensions de l'ENTRÉE (`width`/`height` de l'élément), par le **converter**, au process
**« Sortie »** de la card (`output_process.output_step(input_size=…)`, brique commune) — dans le
même passage que le format de sortie ; « Original » réencode dans le format du fichier. L'image
agrandie est gardée à côté (`native_outputs`) : cocher ou décocher ne relance que la Sortie, jamais
l'amélioration, et la card affiche les dimensions du fichier final. Une taille que le converter n'a
pas atteinte arrête la Sortie en le disant. Gardes : `tests_output_formats.KeepTheInputSizeTest`
(vrai converter, image et vidéo), `enhancer.tests.OutputKeepSizeTest`.

Format, qualité et résolution d'origine sont déclarés par la brique COMMUNE
(`output_formats.output_format_params(('image', 'video'), keep_size=True)`, 2026-10-28) : formats
groupés par nature, qualité affichée seulement quand le fichier est réencodé — un format choisi,
OU la résolution d'origine gardée (Fabien : « on peut vouloir garder la résolution d'origine et
changer le format et la qualité »). Le domaine audio a sa section Sortie au volet depuis le même
jour (ci-dessous).

### Audio (branche dédiée)

L'app porte aussi une **amélioration audio** complète (modèle `AudioEnhancement`,
`backends/audio_enhancer.py`, ~20 routes `audio/*` dans `urls.py`) : débruitage DeepFilterNet et
resemble-enhance, avec sa propre file. Les batchs (import multi-fichiers, actions de lot) sont
câblés sur les deux branches.

**Même modèle de réglages que l'image/vidéo (2026-10-28, porté d'un bloc)** : l'élément audio
NAÎT avec le volet — dépôt de card ou de lot, « Envoyer vers » du gestionnaire de fichiers, outil
`add_to_audio_enhancer` de l'assistant, tous par `views.new_audio_settings` (défauts du schéma ←
volet retenu de l'auteur ← ce qui est posté) ; ce qui est posté devient la mémoire du volet
(`save_panel_settings`), réaffichée à la page ; ▶ d'une card ou d'un lot lance avec les réglages
STOCKÉS de l'élément (avant : le volet était réappliqué en silence à chaque ▶) ; « Tout démarrer »
applique le volet entier, des deux domaines. Une seule fonction applique les réglages
(`_apply_audio_settings`, au lieu de quatre listes recopiées). Le réglage de force du débruitage
porte le nom de sa colonne (`denoising_strength`, ex-`strength` ; le catalogue de Resemble suit,
`model_registry`). La ⚙ de lot des deux domaines est remplie (contextes `panel`/`item`/`batch`) et
le lot audio a ses routes `audio/batch/<pk>/update|promote|realign` (fabrique commune
`make_batch_views`). L'outil de l'assistant lit moteurs et modes au catalogue et au schéma au lieu
de deux listes figées. Garde : `tests_panel_memory.AudioPanelMemoryTest`.
L'outil du domaine image/vidéo, `add_to_enhancer`, naît de même depuis le 2026-10-29
(`views.new_enhancement_settings`) : il créait l'élément sur des défauts écrits (`RealESR_Gx4`,
sans débruitage) quel que soit le volet, et ne refusait aucun modèle (un select de catalogue n'a
pas de `choices`). Garde : `PanelMemoryTest.test_the_assistant_tool_is_born_with_the_author_settings`.

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

#### Par la route d'installation (depuis le 2026-10-11)

Les sept modèles sont DÉCLARÉS par l'app (`utils/model_config.ENHANCER_MODELS`, champ `files` :
chemin, taille, empreinte et ORIGINE de chaque fichier). Leur ligne existe au catalogue même
absente, et s'installe comme tout modèle : bouton « Installer » du model manager,
`python manage.py pull_model enhancer:<id>`, ou `python manage.py install_requires enhancer` (la
même demande, `request_install` : garde d'espace disque, tâche suivie, journal ; pilote `files`).

**Origine** : le miroir du Hub `svjack/AI-onnx`, figé à son commit. Les versions GitHub de
QualityScaler (source « principale » de l'ancien téléchargeur) ne publient plus aucun fichier
(mesuré le 2026-10-11) ; le miroir sert des fichiers aux empreintes IDENTIQUES à ceux qui tournaient
ici. Il ne déclare pas de licence — accepté (décision de Fabien, 11/10) parce que l'empreinte
épinglée garantit les octets. L'Anime y porte un autre nom (`RealSRx4_Anime_fp16.onnx`) : la
déclaration le dit.

⚠ **Supprimés le 2026-10-11** (`docs/construction/suivi/REMOVAL_LEDGER.md`) : le téléchargement au
démarrage de `runserver` (`apps.py`), `utils/model_downloader.py` et la commande
`download_enhancer_models` — un second chemin d'installation, sans garde d'espace disque, sans
empreinte, sans journal.

```
AI-models/models/upscaling/onnx/      (MODEL_PATHS['upscaling']['onnx'])
├── RealESR_Gx4_fp16.onnx          (2,4 Mo)
├── RealESR_Animex4_fp16.onnx      (1,3 Mo)
├── BSRGANx2_fp16.onnx             (33,7 Mo)
├── BSRGANx4_fp16.onnx             (33,8 Mo)
├── RealESRGANx4_fp16.onnx         (33,7 Mo)
├── IRCNN_Mx1_fp16.onnx            (0,4 Mo)
└── IRCNN_Lx1_fp16.onnx            (0,4 Mo)
```

#### Agrandisseurs installés depuis le model manager (2026-10-06)

Le select « Modèle AI » liste le CATALOGUE par tâche (`upscale`, `denoise`) et stocke des clés de
catalogue (`enhancer:BSRGANx4`, `huggingface:org/depot`) — route F4b étape ⑤
(`WAMA_APP_GENERATION_ROUTE.md §F4b`). Un agrandisseur ONNX installé par la chaîne de prospection
y entre sans code : son manifeste porte `task: upscale`, `scale` et le moteur `onnxruntime`, et
`AIUpscaler` le sert dès que son entrée `SUPPORTED_MODELS` le NOMME (`model_key` seul — facteur,
VRAM et fichier sont lus au registre). Premier cas : **Swin2SR realworld ×4**
(`onnx-community/swin2SR-realworld-sr-x4-64-bsrgan-psnr-ONNX`, Apache-2.0), le plus FIDÈLE au banc
du 2026-10-06 (rendu doux, peu d'invention). Détail, banc et restes (SPAN, GaterV3 : poids publiés
hors HuggingFace) : `wama/model_manager/PROSPECTION_PIPELINE.md §Session du 2026-10-06`.
⚠ **Jusqu'au 2026-10-14, Swin2SR plantait** sur toute image dont un côté n'est pas multiple de 8
(`Reshape /swin2sr/patch_unembed`, onnxruntime) : ses fenêtres découpent l'image en carreaux de
8 px. Le modèle le DÉCLARE dans son `preprocessor_config.json` (`do_pad`, `pad_size: 8`) ;
`AIUpscaler` le lit, complète l'entrée en symétrique (image entière comme tuiles) et recadre la
sortie. Mesuré ensuite au banc DIV2K : LPIPS 0,326 en ×4, derrière SPAN, RealESRGAN, BSRGAN et
RealESR_G — fidèle mais doux, ce que LPIPS pénalise (`WAMA_QUALITE §3`, ligne `upscale`).

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
1. Le model manager dit-il le modèle installé ? Sinon : « Installer » (ou
   `python manage.py pull_model enhancer:<id>`)
2. Le dossier est `MODEL_PATHS['upscaling']['onnx']` (`AI-models/models/upscaling/onnx/`)
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
├── models.py           # Enhancement, AudioEnhancement, UserSettings, lots
├── params.py           # Schémas déclaratifs MEDIA / AUDIO (modales, volets, chips, curseur)
├── views.py            # Vues HTTP (image/vidéo + audio/*)
├── urls.py             # Routing
├── tasks.py            # GLU des tâches — squelette commun `task_skeleton.run_item_task`
├── backends/           # ROUTES nature → callable au contrat commun « fichier » (2026-09-21)
│   ├── media_backend.py    # enhance_image / enhance_video (moteur : common/backends/ai_upscaler ; vidéo : common/utils/video_render)
│   └── audio_backend.py    # enhance_audio (moteur : common/backends/audio_enhancer)
├── utils/
│   ├── auto_model.py       # Déclarations du tirage « auto » (domaines, facteur, NFE)
│   └── model_config.py     # ENHANCER_MODELS (descriptions, fichiers déclarés + origine)
├── tests.py            # Résolution auto, NFE, contrat des routes, glu, vues
├── templates/
│   └── enhancer/
│       ├── base.html
│       └── index.html
└── static/
    └── enhancer/
        └── js/index.js, audio-enhancer.js

AI-models/models/upscaling/onnx/  # Poids ONNX (`settings.MODEL_PATHS['upscaling']['onnx']`)
```

### API Endpoints

```
POST /enhancer/upload/              # Upload fichier
POST /enhancer/start/<id>/          # Démarrer traitement
GET  /enhancer/progress/<id>/       # Obtenir progression
GET  /enhancer/download/<id>/       # Télécharger résultat
POST /enhancer/delete/<id>/         # Supprimer
POST /enhancer/settings/<id>/ # Modifier paramètres
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

# Test de l'upscaler (moteur au substrat)
python manage.py shell
>>> from wama.common.backends.ai_upscaler import upscale_image_file
>>> upscale_image_file('input.jpg', 'output.jpg', model_name='RealESR_Gx4')

# Tests de l'app (CPU)
python manage.py test wama.enhancer --keepdb
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

# WAMA Imager - AI Image Generation

Application de génération d'images par intelligence artificielle intégrée à WAMA.

## Description

Imager utilise la bibliothèque [imaginAIry](https://github.com/brycedrennan/imaginAIry) pour générer des images à partir de descriptions textuelles (prompts). L'application supporte plusieurs modèles Stable Diffusion et offre de nombreuses options de personnalisation.

## Fonctionnalités

- **Génération d'images par IA** : Créez des images à partir de descriptions textuelles
- **Modèles multiples** : Support de OpenJourney v4, Dreamlike Art 2.0, Stable Diffusion 2.1 et 1.5
- **Paramètres personnalisables** :
  - Dimensions d'image (256px à 2048px)
  - Prompts négatifs pour exclure des éléments
  - Nombre de steps (qualité vs vitesse)
  - Guidance scale (adhérence au prompt)
  - Seed pour la reproductibilité
  - Upscaling optionnel
- **Génération par batch** : Jusqu'à 4 images à la fois
- **Suivi en temps réel** : Progression et statut de chaque génération
- **Support utilisateur anonyme** : Utilisable sans compte
- **Console de logs** : Monitoring détaillé des générations

## Installation

### 1. Installer imaginAIry

```bash
# Activer l'environnement virtuel
source venv_linux/bin/activate  # Linux/Mac
# ou
venv_win\Scripts\activate  # Windows

# Installer imaginAIry
pip install imaginairy

# Pour GPU (CUDA) - recommandé pour de meilleures performances
pip install imaginairy[cuda]

# Pour macOS avec M1/M2
pip install imaginairy[mps]
```

### 2. Télécharger les modèles

Les modèles seront téléchargés automatiquement lors de la première utilisation. Vous pouvez aussi les télécharger manuellement :

```bash
# Télécharger tous les modèles par défaut
imagine --download-models

# Télécharger un modèle spécifique
imagine --model openjourney-v4 --download-only
```

### 3. Configuration

Les modèles sont stockés dans `~/.cache/imaginairy/` par défaut.

Pour changer l'emplacement de stockage, définir la variable d'environnement :

```bash
export IMAGINAIRY_CACHE_DIR=/path/to/cache
```

## Utilisation

### Interface Web

1. Accédez à l'application Imager via le menu WAMA ou directement à `/imager/`
2. Entrez votre prompt (description de l'image souhaitée)
3. Optionnel : Ajustez les paramètres (modèle, dimensions, steps, etc.)
4. Cliquez sur "Add to Queue" puis "Start" pour générer
5. Téléchargez vos images une fois la génération terminée

### Exemples de Prompts

**Paysage :**
```
Prompt: "Majestic mountain range at golden hour, dramatic clouds, alpine meadow in foreground, photorealistic, highly detailed"
Negative: "blurry, low quality, cartoon, painting"
```

**Portrait :**
```
Prompt: "Portrait of a wise old wizard, long white beard, mystical robes, magical staff, fantasy art style, detailed"
Negative: "modern clothing, blurry, distorted face"
```

**Art abstrait :**
```
Prompt: "Abstract expressionist painting, vibrant colors, dynamic brush strokes, emotional, red and blue dominant, textured canvas"
Negative: "realistic, photographic, dull colors"
```

## Paramètres

### Prompt
Description principale de l'image à générer. Soyez descriptif et précis.

### Negative Prompt
Éléments à éviter dans l'image. Utile pour exclure : "blurry, low quality, distorted, ugly, watermark"

### Model
- **OpenJourney v4** : Style artistique, vibrant
- **Dreamlike Art 2.0** : Style onirique, surréaliste
- **Stable Diffusion 2.1** : Polyvalent, qualité équilibrée
- **Stable Diffusion 1.5** : Rapide, fiable

### Steps
Nombre d'étapes de diffusion. Plus = meilleure qualité mais plus lent.
- 20-30 : Rapide, bon pour tester
- 50-70 : Recommandé pour qualité
- 80-100 : Qualité maximale (très lent)

### Guidance Scale
Adhérence au prompt (1-20). Recommandé : 7-12

### Seed
Graine aléatoire pour reproductibilité. Même seed + même prompt = résultats similaires.

### Upscale
Augmente la résolution finale. Attention : augmente significativement le temps de génération.

## Performance

### Matériel recommandé

- **GPU avec CUDA** : Génération en 10-60 secondes
- **CPU uniquement** : Génération en 2-10 minutes
- **RAM** : 8 GB minimum, 16 GB recommandé
- **Stockage** : ~10 GB pour les modèles

### Optimisation

Pour de meilleures performances :
1. Utilisez un GPU avec CUDA si disponible
2. Réduisez les dimensions (512x512 est un bon compromis)
3. Diminuez le nombre de steps pour les tests
4. Désactivez l'upscaling sauf si nécessaire

## Tâches Celery

L'application utilise Celery pour les générations asynchrones. Assurez-vous que Celery est démarré :

```bash
# Démarrer le worker Celery
celery -A wama worker -l info

# Avec géolocalisation (optionnel)
celery -A wama worker -l info --pool=gevent
```

## Dépannage

### Erreur "imaginAIry not installed"
```bash
pip install imaginairy
```

### Génération lente
- Vérifiez que vous utilisez un GPU (CUDA)
- Réduisez les dimensions et le nombre de steps
- Désactivez l'upscaling

### Erreur de mémoire (OOM)
- Réduisez les dimensions de l'image
- Fermez les autres applications
- Ajoutez plus de RAM si possible

### Les images sont de mauvaise qualité
- Augmentez le nombre de steps (50-100)
- Ajustez guidance_scale (7-12 recommandé)
- Rendez le prompt plus descriptif
- Utilisez un negative prompt

## Architecture

```
wama/imager/
├── models.py           # Modèles Django (ImageGeneration, UserSettings)
├── views.py            # Vues et API endpoints
├── urls.py             # Routes URL
├── tasks.py            # Tâches Celery pour génération
├── admin.py            # Interface admin Django
├── templates/imager/   # Templates HTML
│   ├── base.html
│   ├── index.html
│   ├── console.html
│   ├── about.html
│   └── help.html
└── static/imager/      # Fichiers statiques
    ├── js/
    │   ├── index.js
    │   └── console.js
    └── css/
        └── imager.css
```

## API Endpoints

- `GET /imager/` : Page principale
- `POST /imager/create/` : Créer une nouvelle génération
- `POST /imager/start/<id>/` : Démarrer une génération
- `POST /imager/start-all/` : Démarrer toutes les générations en attente
- `GET /imager/progress/<id>/` : Obtenir la progression
- `GET /imager/global-progress/` : Progression globale
- `GET /imager/download/<id>/` : Télécharger les images
- `POST /imager/delete/<id>/` : Supprimer une génération
- `POST /imager/clear-all/` : Tout supprimer

## Licence

Vérifiez les licences des modèles que vous utilisez. La plupart des modèles Stable Diffusion permettent l'utilisation commerciale, mais vérifiez toujours avant.

## Support

Pour plus d'informations :
- [Documentation imaginAIry](https://github.com/brycedrennan/imaginAIry)
- [Stable Diffusion](https://stability.ai/)
- Page Help de l'application pour des guides détaillés

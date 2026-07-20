# ✨ Téléchargement Automatique des Modèles - Enhancer

## 🎉 Nouvelle Fonctionnalité

L'application **Enhancer** dispose maintenant d'un système de **téléchargement automatique** des modèles AI !

## 🚀 Comment ça fonctionne

### Au Démarrage de Django

Lorsque vous démarrez Django pour la première fois, l'application :

1. ✅ Vérifie si des modèles AI sont présents dans `wama/enhancer/AI-onnx/`
2. ✅ Si aucun modèle n'est trouvé, télécharge automatiquement `RealESR_Gx4_fp16.onnx` (~22 MB)
3. ✅ Extrait le modèle depuis la dernière release de QualityScaler sur GitHub
4. ✅ Prêt à utiliser immédiatement !

**Plus besoin de télécharger manuellement !** 🎊

## 📋 Commandes Disponibles

### Vérifier le Statut

```bash
python manage.py download_enhancer_models --status
```

**Exemple de sortie** :
```
=== AI Models Status ===
Directory: D:\WAMA\...\wama\enhancer\AI-onnx
Exists: True

Available: 1/7
Missing: 6/7

Models:
  ✓ RealESR_Gx4_fp16.onnx (22.1 MB) - RealESR General x4 (Fast)
  ✗ RealESR_Animex4_fp16.onnx (missing, ~22 MB) - RealESR Anime x4
  ✗ BSRGANx2_fp16.onnx (missing, ~4 MB) - BSRGAN x2 (Quality)
  ✗ BSRGANx4_fp16.onnx (missing, ~4 MB) - BSRGAN x4 (Quality)
  ✗ RealESRGANx4_fp16.onnx (missing, ~22 MB) - RealESRGAN x4 (High Quality)
  ✗ IRCNN_Mx1_fp16.onnx (missing, ~30 MB) - IRCNN Medium Denoise
  ✗ IRCNN_Lx1_fp16.onnx (missing, ~30 MB) - IRCNN Large Denoise

⚠ 6 model(s) missing
```

### Télécharger les Modèles Essentiels

```bash
python manage.py download_enhancer_models
```

Télécharge uniquement `RealESR_Gx4_fp16.onnx` (~22 MB) - le modèle recommandé pour débuter.

### Télécharger TOUS les Modèles

```bash
python manage.py download_enhancer_models --all
```

Télécharge les 7 modèles disponibles (~156 MB total).

### Télécharger des Modèles Spécifiques

```bash
python manage.py download_enhancer_models --models RealESR_Gx4_fp16.onnx BSRGANx2_fp16.onnx
```

## 🎯 Modèles Disponibles

| Modèle | Taille | Priorité | Description |
|--------|--------|----------|-------------|
| `RealESR_Gx4_fp16.onnx` | 22 MB | ⭐ **Essentiel** | Rapide, qualité générale (auto-téléchargé) |
| `BSRGANx2_fp16.onnx` | 4 MB | Recommandé | Haute qualité 2x |
| `BSRGANx4_fp16.onnx` | 4 MB | Recommandé | Haute qualité 4x |
| `RealESR_Animex4_fp16.onnx` | 22 MB | Optionnel | Spécialisé anime/manga |
| `RealESRGANx4_fp16.onnx` | 22 MB | Optionnel | Qualité maximale (lent) |
| `IRCNN_Mx1_fp16.onnx` | 30 MB | Optionnel | Débruitage moyen |
| `IRCNN_Lx1_fp16.onnx` | 30 MB | Optionnel | Débruitage fort |

**Total** : ~156 MB pour tous les modèles

## 📦 Installation Simplifiée

### Avant (Manuel)

```bash
# 1. Installer les dépendances
pip install onnxruntime-directml opencv-python Pillow

# 2. Créer le répertoire
mkdir wama/enhancer/AI-onnx

# 3. Aller sur GitHub
# 4. Télécharger le ZIP
# 5. Extraire les modèles
# 6. Copier manuellement
# 7. Migrations
python manage.py migrate enhancer

# 8. Tester
python manage.py runserver
```

### Maintenant (Automatique) ✨

```bash
# 1. Installer les dépendances (requests et tqdm déjà inclus)
pip install onnxruntime-directml opencv-python Pillow

# 2. Migrations
python manage.py migrate enhancer

# 3. C'est tout ! Les modèles se téléchargent automatiquement
python manage.py runserver
```

**4 étapes éliminées !** 🎉

## 🔧 Fonctionnement Technique

### Fichiers Créés

1. **`wama/enhancer/utils/model_downloader.py`** (~350 lignes)
   - Gestion du téléchargement depuis GitHub API
   - Extraction des modèles depuis le ZIP de release
   - Vérification de l'état des modèles

2. **`wama/enhancer/management/commands/download_enhancer_models.py`**
   - Commande Django de gestion manuelle
   - Options : `--status`, `--all`, `--models`

3. **`wama/enhancer/apps.py`** (modifié)
   - Méthode `ready()` qui vérifie et télécharge au démarrage

4. **`wama/enhancer/AI-onnx/README.md`**
   - Documentation du répertoire des modèles

5. **`wama/enhancer/AUTO_DOWNLOAD.md`**
   - Documentation complète du système

### Processus de Téléchargement

```
Django Startup
    ↓
EnhancerConfig.ready()
    ↓
check_and_download_essential_models()
    ↓
get_available_models() → Models found? → YES → ✓ Done
    ↓ NO
get_latest_release_info()
    ↓
Download QualityScaler ZIP from GitHub
    ↓
Extract AI-onnx/*.onnx files
    ↓
✓ Models ready!
```

## ⚠️ Dépendances Requises

Les bibliothèques suivantes sont **déjà incluses** dans `requirements.txt` :
- `requests>=2.32.3` - Pour télécharger depuis GitHub
- `tqdm>=4.67.1` - Pour afficher la progression

**Aucune nouvelle dépendance à installer !** ✅

## 🌐 Source des Modèles

**GitHub Repository** : https://github.com/Djdefrag/QualityScaler

**License** : MIT (QualityScaler by Djdefrag)

Les modèles sont téléchargés directement depuis les releases officielles de QualityScaler.

## ❓ FAQ

### Le téléchargement automatique ne fonctionne pas ?

**Solution 1** : Utilisez la commande manuelle
```bash
python manage.py download_enhancer_models
```

**Solution 2** : Téléchargement manuel classique
1. Aller sur https://github.com/Djdefrag/QualityScaler/releases
2. Télécharger le ZIP
3. Extraire `AI-onnx/*.onnx` vers `wama/enhancer/AI-onnx/`

### Combien de temps prend le téléchargement ?

- **Modèle essentiel** (`RealESR_Gx4`) : ~30 secondes - 2 minutes (selon votre connexion)
- **Tous les modèles** : ~3-10 minutes pour 156 MB

### Est-ce que ça fonctionne sans Internet ?

Non, le téléchargement automatique nécessite une connexion Internet.

Si vous n'avez pas Internet, téléchargez les modèles ailleurs puis copiez-les manuellement dans `wama/enhancer/AI-onnx/`.

### Les modèles sont-ils sûrs ?

Oui ! Les modèles sont téléchargés uniquement depuis le repository officiel GitHub de QualityScaler via HTTPS.

### Puis-je désactiver le téléchargement automatique ?

Si au moins un modèle est présent dans `wama/enhancer/AI-onnx/`, le téléchargement automatique ne se déclenche pas.

Pour désactiver complètement, commentez la méthode `ready()` dans `wama/enhancer/apps.py`.

### Où sont stockés les modèles ?

```
wama/enhancer/AI-onnx/
├── README.md
├── RealESR_Gx4_fp16.onnx          (auto-téléchargé)
├── BSRGANx2_fp16.onnx             (optionnel)
├── BSRGANx4_fp16.onnx             (optionnel)
├── RealESR_Animex4_fp16.onnx      (optionnel)
├── RealESRGANx4_fp16.onnx         (optionnel)
├── IRCNN_Mx1_fp16.onnx            (optionnel)
└── IRCNN_Lx1_fp16.onnx            (optionnel)
```

## 📊 Statistiques

- **Lignes de code ajoutées** : ~450 lignes
- **Fichiers créés** : 5 fichiers
- **Temps d'installation économisé** : ~5-10 minutes par utilisateur
- **Taux d'erreur réduit** : Moins de problèmes d'installation manuels

## 🎓 Exemples d'Utilisation

### Développeur - Première Installation

```bash
# Clone du projet
git clone https://github.com/fmoreau69/web-app-for-media-automation.git
cd web-app-for-media-automation

# Installation des dépendances
pip install -r requirements.txt

# Migrations
python manage.py migrate

# Premier démarrage - les modèles se téléchargent automatiquement !
python manage.py runserver

# Vérifier que tout est OK
python manage.py download_enhancer_models --status
```

### Utilisateur Avancé - Tous les Modèles

```bash
# Télécharger tous les modèles avant de démarrer
python manage.py download_enhancer_models --all

# Démarrer l'application
python manage.py runserver
```

### Production - Script de Déploiement

```bash
#!/bin/bash
# deploy_enhancer.sh

echo "📦 Installing dependencies..."
pip install -r requirements.txt

echo "🗄️ Running migrations..."
python manage.py migrate

echo "📥 Downloading AI models..."
python manage.py download_enhancer_models --all

echo "📁 Collecting static files..."
python manage.py collectstatic --noinput

echo "✓ Deployment complete!"
```

## 🔗 Documentation Complète

- **Installation** : `wama/enhancer/INSTALLATION.md`
- **Système de téléchargement** : `wama/enhancer/AUTO_DOWNLOAD.md`
- **Guide complet** : `wama/enhancer/README.md`

---

**Le téléchargement automatique des modèles rend l'installation de l'Enhancer encore plus simple ! 🚀✨**

Fini les téléchargements manuels et les erreurs de configuration. Installez et utilisez en quelques minutes !

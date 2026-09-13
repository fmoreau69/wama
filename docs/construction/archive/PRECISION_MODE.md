# Système de Précision et Sélection Automatique des Modèles

## Vue d'ensemble

Le système de précision permet aux utilisateurs de choisir entre un traitement **rapide** (Quick) et un traitement **précis** (Precise) via un slider intuitif. Ce réglage détermine automatiquement plusieurs paramètres pour optimiser soit la vitesse, soit la qualité du traitement.

## Interface Utilisateur

### Slider Quick <-> Precise

Le slider est situé dans les **Global Settings** et offre 5 niveaux de précision :

| Niveau | Valeur | Description | Taille du modèle | Segmentation |
|--------|--------|-------------|------------------|--------------|
| Quick | 0-20 | Ultra rapide, qualité de base | Nano (n) | Non |
| Balanced Quick | 21-40 | Rapide avec qualité correcte | Small (s) | Non |
| Balanced | 41-60 | Équilibre vitesse/qualité (défaut) | Medium (m) | Non |
| Balanced Precise | 61-80 | Précis avec temps raisonnable | Large (l) | Oui |
| Maximum Precision | 81-100 | Maximum de précision, plus lent | XLarge (x) | Oui |

### Fonctionnement

1. **Valeur par défaut** : 50 (Balanced)
2. **Le slider met à jour** :
   - La taille du modèle YOLO utilisé (n/s/m/l/x)
   - L'activation de la segmentation (>= 65)
   - Les paramètres de détection

3. **Sélection du modèle** :
   - Si l'utilisateur laisse "Auto (based on precision)", le système choisit automatiquement le meilleur modèle
   - Si l'utilisateur sélectionne un modèle spécifique, ce choix est prioritaire

## Architecture Technique

### 1. Modèles de données

#### UserSettings
```python
precision_level = models.IntegerField(
    default=50,
    verbose_name='Processing precision level',
    help_text='0=Quick (fast), 50=Balanced, 100=Precise (slow but accurate)'
)

use_segmentation = models.BooleanField(
    default=False,
    verbose_name='Use segmentation models',
    help_text='Automatically determined by precision level'
)
```

#### Media
Les mêmes champs existent dans le modèle Media pour permettre des réglages par média.

### 2. Logique de sélection automatique

#### Fichier : `wama/anonymizer/utils/model_selector.py`

**Fonction principale** : `select_model_by_precision(classes_to_blur, precision_level)`

Cette fonction :
1. Détermine la taille du modèle basée sur le niveau de précision
2. Détermine si la segmentation doit être utilisée
3. Recherche le modèle optimal installé
4. Vérifie que le modèle supporte les classes demandées

**Exemple** :
```python
from wama.anonymizer.utils.model_selector import select_model_by_precision

# Niveau 30 (Balanced Quick) avec classes face et plate
model = select_model_by_precision(['face', 'plate'], precision_level=30)
# Retourne : 'detect/yolo11s.pt' ou 'detect/yolov8s.pt'

# Niveau 75 (Balanced Precise) avec classes person et car
model = select_model_by_precision(['person', 'car'], precision_level=75)
# Retourne : 'segment/yolo11l-seg.pt' ou 'segment/yolov8l-seg.pt'
```

### 3. Intégration dans le traitement

#### Fichier : `wama/anonymizer/tasks.py`

Lors du traitement d'un média :
1. Le système récupère `precision_level` et `use_segmentation` depuis UserSettings ou Media
2. Si `model_to_use` est vide ou non spécifié, la fonction `select_model_by_precision()` est appelée
3. Le modèle sélectionné est chargé et utilisé pour le traitement

```python
# Dans process_single_media()
if model_to_use and model_to_use.strip():
    # Utiliser le modèle spécifié par l'utilisateur
    kwargs['model_path'] = get_model_path(model_to_use)
else:
    # Sélection automatique basée sur precision_level
    selected_model = select_model_by_precision(
        classes_to_blur=kwargs['classes2blur'],
        precision_level=precision_level
    )
    kwargs['model_path'] = get_model_path(selected_model)
```

## Algorithme de sélection

### Détermination de la taille du modèle

```python
def get_model_size_from_precision(precision_level: int) -> str:
    if precision_level <= 20:
        return 'n'  # Nano - fastest
    elif precision_level <= 40:
        return 's'  # Small
    elif precision_level <= 60:
        return 'm'  # Medium
    elif precision_level <= 80:
        return 'l'  # Large
    else:
        return 'x'  # XLarge - most accurate
```

### Détermination de la segmentation

```python
def should_use_segmentation(precision_level: int) -> bool:
    # Utilise la segmentation pour les niveaux > 65
    return precision_level >= 65
```

### Ordre de priorité pour la sélection

1. **YOLO11** est préféré à YOLOv8 (plus récent et plus performant)
2. Le système cherche : `{version}{size}{suffix}.pt`
   - Exemple : `yolo11m.pt` pour detect/Medium
   - Exemple : `yolo11l-seg.pt` pour segment/Large
3. Si le modèle YOLO11 n'existe pas, essaie YOLOv8
4. Si aucun modèle correspondant n'est trouvé, utilise `select_best_models()` comme fallback

## Paramètres futurs (à venir)

Le niveau de précision pourra également contrôler :

1. **Amélioration de qualité initiale** (QualityScaler)
   - Activé pour `precision_level >= 75`
   - Upscale l'image avant traitement pour améliorer la détection

2. **Grid Detection** (division en sous-images)
   - Activé pour `precision_level >= 80`
   - Divise les images en grille avec recouvrement pour améliorer la détection des petits objets

3. **Autres optimisations**
   - Ajustement automatique des seuils de détection
   - Amélioration de l'interpolation pour les vidéos

## Migration

Pour appliquer les changements de base de données :

```bash
python manage.py makemigrations anonymizer
python manage.py migrate anonymizer
```

## Tests

Pour tester le système :

```python
from wama.anonymizer.utils.model_selector import (
    get_model_size_from_precision,
    should_use_segmentation,
    select_model_by_precision
)

# Test 1 : Quick mode
assert get_model_size_from_precision(10) == 'n'
assert not should_use_segmentation(10)

# Test 2 : Balanced mode
assert get_model_size_from_precision(50) == 'm'
assert not should_use_segmentation(50)

# Test 3 : Precise mode
assert get_model_size_from_precision(90) == 'x'
assert should_use_segmentation(90)

# Test 4 : Auto-selection
model = select_model_by_precision(['person', 'car'], 30)
print(f"Selected model: {model}")  # Should be detect/yolo11s.pt or similar
```

## Avantages

1. **Simplicité pour l'utilisateur** : Un seul slider pour contrôler la qualité/vitesse
2. **Flexibilité** : L'utilisateur peut toujours spécifier un modèle manuellement
3. **Optimisation automatique** : Le système choisit les meilleurs paramètres
4. **Évolutivité** : Facile d'ajouter de nouveaux paramètres contrôlés par le niveau de précision

## Notes

- Le système télécharge automatiquement les modèles YOLO officiels s'ils ne sont pas présents
- La sélection automatique prend en compte les classes à flouter pour choisir le type de modèle (detect/segment)
- Pour les classes personnalisées (face, plate), le système utilise toujours les modèles personnalisés si disponibles

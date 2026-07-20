# Système de Sélection Automatique de Modèles YOLO

## Vue d'ensemble

Le système de sélection automatique de modèles permet à WAMA de choisir intelligemment le(s) meilleur(s) modèle(s) YOLO en fonction des classes d'objets que l'utilisateur souhaite flouter.

## Fonctionnalités

### 1. Scan Automatique des Classes

Le système scanne tous les modèles installés localement et extrait la liste des classes qu'ils peuvent détecter.

**Fichier**: `wama/anonymizer/utils/model_selector.py`

**Fonction principale**: `scan_installed_models()`

Exemple de sortie:
```python
{
    'detect/yolo11n.pt': {
        'path': '/path/to/model',
        'type': 'detect',
        'name': 'yolo11n.pt',
        'classes': {'0': 'person', '1': 'bicycle', '2': 'car', ...},
        'class_list': ['person', 'bicycle', 'car', ...],
        'official': True
    }
}
```

### 2. Sélection Automatique Intelligente

**Fonction**: `select_best_models(classes_to_blur)`

Le système:
1. Identifie les classes demandées par l'utilisateur
2. Trouve les modèles installés qui supportent ces classes
3. Sélectionne le minimum de modèles pour couvrir toutes les classes
4. Préfère les modèles officiels et de petite taille (nano/small) pour les performances

**Algorithme**:
- Stratégie greedy: Pour chaque classe non couverte, sélectionne le modèle qui couvre le plus de classes restantes
- Tie-breaker: Préfère modèles officiels > modèles nano/small

**Résultat**:
```python
{
    'models_to_use': [
        {
            'id': 'detect/yolo11n.pt',
            'path': '/full/path',
            'name': 'yolo11n.pt',
            'type': 'detect',
            'classes': ['person', 'car', 'bicycle']
        }
    ],
    'unsupported_classes': ['face'],  # Classes non supportées
    'recommendations': [...],  # Recommandations de téléchargement
    'coverage': 0.75,  # 75% des classes couvertes
    'total_classes': 4,
    'covered_classes': 3
}
```

### 3. Recommandations de Téléchargement

**Fonction**: `get_download_recommendations(classes_needed)`

Lorsque des classes ne sont pas supportées par les modèles installés, le système recommande des modèles officiels à télécharger.

**Classes COCO Standard** (80 classes):
- person, bicycle, car, motorcycle, airplane, bus, train, truck, boat, etc.
- Recommandé: `yolo11n.pt` (détection générale)

**Classes Spécialisées**:
- face, plate → Recommandation de modèles personnalisés

**Exemple de recommandation**:
```python
{
    'model_type': 'detect',
    'model_name': 'yolo11n.pt',
    'reason': 'YOLO11 Nano détecte les classes COCO standard: person, car, bicycle',
    'classes_covered': ['person', 'car', 'bicycle'],
    'download_command': 'python manage.py manage_models download detect yolo11n.pt'
}
```

### 4. API Endpoint

**URL**: `/anonymizer/model-recommendations/`

**Paramètres GET**:
- `classes`: Liste des classes séparées par des virgules (ex: "person,car,face")
- `current_model` (optionnel): Modèle actuellement sélectionné

**Exemples d'utilisation**:

```javascript
// Obtenir les recommandations pour person, car, face
fetch('/anonymizer/model-recommendations/?classes=person,car,face')
    .then(r => r.json())
    .then(data => console.log(data));
```

**Réponses possibles**:

1. **Sélection automatique complète** (coverage = 1.0):
```json
{
    "status": "auto_complete",
    "message": "1 modèle(s) sélectionné(s) automatiquement",
    "use_current": false,
    "models": [
        {
            "id": "detect/yolo11n.pt",
            "path": "/path/to/model",
            "name": "yolo11n.pt",
            "type": "detect",
            "classes": ["person", "car"]
        }
    ],
    "coverage": 1.0
}
```

2. **Couverture partielle**:
```json
{
    "status": "auto_partial",
    "message": "Couverture partielle: 2/3 classes",
    "use_current": false,
    "models": [...],
    "coverage": 0.66,
    "unsupported_classes": ["face"],
    "recommendations": [
        {
            "model_type": "custom",
            "model_name": "yolov8n_faces&plates",
            "reason": "Modèle spécialisé pour la détection de visages et plaques d'immatriculation",
            "classes_covered": ["face"],
            "download_command": "Téléchargement manuel requis - modèle personnalisé"
        }
    ]
}
```

3. **Modèle manuel OK**:
```json
{
    "status": "manual_ok",
    "message": "Le modèle sélectionné supporte toutes les classes demandées",
    "use_current": true,
    "current_model": "detect/yolo11s.pt",
    "supported_classes": ["person", "car"]
}
```

4. **Modèle manuel incomplet**:
```json
{
    "status": "manual_incomplete",
    "message": "Le modèle sélectionné ne supporte pas: face",
    "use_current": true,
    "current_model": "detect/yolo11n.pt",
    "unsupported_classes": ["face"],
    "suggestion": "Laissez le champ vide pour une sélection automatique"
}
```

5. **Aucun modèle disponible**:
```json
{
    "status": "no_models",
    "message": "Aucun modèle installé ne supporte ces classes",
    "use_current": false,
    "unsupported_classes": ["face", "person", "car"],
    "recommendations": [...]
}
```

## Utilisation Pratique

### Scenario 1: Utilisateur sélectionne des classes sans modèle

1. Utilisateur coche: `person`, `car`, `bicycle` dans l'interface
2. JavaScript appelle `/anonymizer/model-recommendations/?classes=person,car,bicycle`
3. Le système répond avec le meilleur modèle: `yolo11n.pt`
4. L'interface affiche: "Modèle sélectionné automatiquement: yolo11n.pt"

### Scenario 2: Classes partiellement supportées

1. Utilisateur coche: `person`, `car`, `face`
2. API répond: `yolo11n.pt` supporte `person` et `car`, mais pas `face`
3. L'interface affiche:
   - "Modèle auto: yolo11n.pt (person, car)"
   - "Non supporté: face"
   - "Recommandation: Télécharger yolov8n_faces&plates"

### Scenario 3: Aucun modèle installé

1. Utilisateur coche: `person`
2. API répond: Aucun modèle installé
3. L'interface affiche:
   - "Aucun modèle disponible"
   - "Télécharger: yolo11n.pt"
   - Bouton: "Télécharger automatiquement"

### Scenario 4: Modèle manuel sélectionné

1. Utilisateur sélectionne manuellement: `yolo11s.pt`
2. Utilisateur coche: `person`, `car`
3. API vérifie que `yolo11s.pt` supporte bien ces classes
4. L'interface confirme: "✓ Modèle compatible"

## Intégration Future: Multi-Modèles

Pour supporter l'utilisation simultanée de plusieurs modèles:

1. **Détection parallèle**: Lancer plusieurs tâches YOLO en parallèle
2. **Fusion des résultats**: Combiner les bounding boxes de tous les modèles
3. **Dé-duplication**: Éliminer les détections en double (IoU threshold)
4. **Floutage unifié**: Appliquer le flou sur toutes les détections combinées

**Exemple**:
```python
# Multi-model detection
results_model1 = yolo_model1.track(frame)  # person, car
results_model2 = yolo_model2.track(frame)  # face

# Combine detections
all_detections = combine_detections([results_model1, results_model2])

# Apply blur
blur_all_detections(frame, all_detections)
```

## Classes COCO Standard

Les 80 classes COCO supportées par les modèles YOLO11 et YOLOv8 de détection:

person, bicycle, car, motorcycle, airplane, bus, train, truck, boat, traffic light, fire hydrant, stop sign, parking meter, bench, bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe, backpack, umbrella, handbag, tie, suitcase, frisbee, skis, snowboard, sports ball, kite, baseball bat, baseball glove, skateboard, surfboard, tennis racket, bottle, wine glass, cup, fork, knife, spoon, bowl, banana, apple, sandwich, orange, broccoli, carrot, hot dog, pizza, donut, cake, chair, couch, potted plant, bed, dining table, toilet, tv, laptop, mouse, remote, keyboard, cell phone, microwave, oven, toaster, sink, refrigerator, book, clock, vase, scissors, teddy bear, hair drier, toothbrush

## Fichiers Concernés

- `wama/anonymizer/utils/model_selector.py` - Logique de sélection
- `wama/anonymizer/views.py` - API endpoint `get_model_recommendations`
- `wama/anonymizer/urls.py` - Route `/model-recommendations/`
- `wama/anonymizer/utils/model_manager.py` - Gestion des téléchargements

## Tests

### Test de l'API via console Python

```python
python manage.py shell

from wama.anonymizer.utils.model_selector import select_best_models, scan_installed_models

# Scan des modèles installés
models = scan_installed_models()
print(f"Modèles installés: {len(models)}")

# Test sélection automatique
result = select_best_models(['person', 'car', 'bicycle'])
print(f"Couverture: {result['coverage']}")
print(f"Modèles sélectionnés: {result['models_to_use']}")
```

### Test de l'API via curl

```bash
# Tester avec person et car
curl "http://localhost:8000/anonymizer/model-recommendations/?classes=person,car"

# Tester avec classe non supportée
curl "http://localhost:8000/anonymizer/model-recommendations/?classes=face,plate"

# Tester avec modèle manuel
curl "http://localhost:8000/anonymizer/model-recommendations/?classes=person&current_model=detect/yolo11n.pt"
```

## Avantages du Système

1. **Automatique**: L'utilisateur n'a plus besoin de connaître les modèles
2. **Intelligent**: Sélectionne le modèle optimal pour les classes demandées
3. **Transparent**: Affiche clairement ce qui est supporté ou non
4. **Guidé**: Propose des téléchargements pour les classes manquantes
5. **Flexible**: Permet toujours la sélection manuelle si désiré
6. **Évolutif**: Prêt pour le multi-modèle dans le futur

## Prochaines Étapes

1. ✅ Système de scan et sélection créé
2. ✅ API endpoint créé
3. ⏳ Interface utilisateur à créer
4. ⏳ Intégration dans le workflow de traitement
5. ⏳ Support multi-modèles (détection parallèle et fusion)

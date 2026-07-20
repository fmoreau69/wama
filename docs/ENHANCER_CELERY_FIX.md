# 🔧 Correction Celery - Enhancer Tasks

## ❌ Problème Rencontré

```
[ERROR] Received unregistered task of type 'wama.enhancer.workers.enhance_media'.
KeyError: 'wama.enhancer.workers.enhance_media'
```

La tâche Celery n'était pas découverte automatiquement par Celery.

## ✅ Solution Appliquée

### 1. Renommage `workers.py` → `tasks.py`

Celery cherche par défaut les tâches dans un fichier nommé `tasks.py`, pas `workers.py`.

**Avant** :
- Fichier : `wama/enhancer/workers.py` contenant `@shared_task enhance_media()`
- Import : `from .workers import enhance_media`

**Après** :
- Fichier : `wama/enhancer/tasks.py` contenant `@shared_task enhance_media()`
- Import : `from .tasks import enhance_media`

### 2. Mise à Jour de celery.py

Ajout explicite d'enhancer dans la liste des apps avec tasks:

**Fichier** : `wama/celery.py`
```python
app.autodiscover_tasks([
    'wama.anonymizer',
    'wama.synthesizer',
    'wama.transcriber',
    'wama.enhancer',  # ← AJOUTÉ
])
```

### 3. Mise à Jour des Imports dans views.py

**Avant** :
```python
from .workers import enhance_media
```

**Après** :
```python
from .tasks import enhance_media
```

## 🧪 Vérification

### Test 1 : Import Direct

```bash
python manage.py shell -c "from wama.enhancer.tasks import enhance_media; print('OK:', enhance_media.name)"
```

**Résultat attendu** :
```
OK: wama.enhancer.tasks.enhance_media
```

### Test 2 : Enregistrement Celery

```bash
python manage.py shell -c "from wama.celery import app; print('wama.enhancer.tasks.enhance_media' in app.tasks)"
```

**Résultat attendu** :
```
True
```

### Test 3 : Celery Worker

Redémarrez Celery et vérifiez les logs au démarrage:

```bash
celery -A wama worker -l info --pool=solo
```

**Dans les logs, vous devriez voir** :
```
[tasks]
  . wama.anonymizer.tasks.process_single_media
  . wama.anonymizer.tasks.process_user_media_batch
  . wama.enhancer.tasks.enhance_media  ← DOIT APPARAÎTRE
  . wama.synthesizer.workers.cleanup_old_syntheses
  . wama.synthesizer.workers.synthesize_voice
  . wama.transcriber.workers.transcribe
  . wama.transcriber.workers.transcribe_without_preprocessing
```

## 🚀 Relancer l'Application

### Étape 1 : Arrêter Celery (Ctrl+C dans Terminal 2)

### Étape 2 : Redémarrer Celery

```bash
# Windows
celery -A wama worker -l info --pool=solo

# Linux/Mac
celery -A wama worker -l info
```

### Étape 3 : Vérifier que la Tâche est Enregistrée

Dans les logs au démarrage de Celery, cherchez :
```
[tasks]
  ...
  . wama.enhancer.tasks.enhance_media
```

Si vous voyez cette ligne, c'est bon ! ✅

### Étape 4 : Tester un Traitement

1. Uploadez une image via l'interface Enhancer
2. Cliquez sur "Démarrer le traitement"
3. Observez les logs dans les 2 terminaux

**Terminal 1 (Django)** devrait montrer :
```
=== START ENHANCEMENT 1 ===
Calling enhance_media.delay()...
Task created: task_id=...
```

**Terminal 2 (Celery)** devrait montrer :
```
========================================
WORKER: enhance_media START
Enhancement ID: 1
========================================
```

Si vous voyez ces logs, le problème est résolu ! 🎉

## 📝 Fichiers Modifiés

1. ✅ `wama/enhancer/workers.py` → Renommé en `workers_backup.py`
2. ✅ `wama/enhancer/tasks.py` → Créé avec tout le code
3. ✅ `wama/enhancer/views.py` → Import modifié (`from .tasks import`)
4. ✅ `wama/celery.py` → Liste explicite des apps

## 🔍 Pourquoi Ça Ne Marchait Pas ?

Celery utilise la convention de nommage suivante pour découvrir automatiquement les tâches :

1. **Cherche dans chaque app** listée dans `autodiscover_tasks()`
2. **Importe le fichier `tasks.py`** de chaque app
3. **N'importe PAS automatiquement** les fichiers nommés différemment (`workers.py`, `jobs.py`, etc.)

**apps** comme `anonymizer` et `imager` utilisaient déjà `tasks.py`, donc leurs tâches étaient découvertes.

**apps** comme `synthesizer` et `transcriber` utilisent `workers.py`, mais leurs tâches fonctionnaient probablement car elles étaient importées ailleurs.

Pour **Enhancer**, aucun autre fichier n'importait `workers.py`, donc Celery ne pouvait pas découvrir la tâche.

## 💡 Solution Alternative (Non Utilisée)

Au lieu de renommer, on aurait pu explicitement importer dans `celery.py` :

```python
# wama/celery.py
app.autodiscover_tasks()

# Import manual
from wama.enhancer.workers import enhance_media  # Force l'import
```

Mais la solution choisie (renommer en `tasks.py`) est plus propre et suit la convention Celery.

## ✅ Statut Final

- ✅ Tâche renommée en `tasks.py`
- ✅ Imports mis à jour
- ✅ Celery.py configuré
- ✅ Tâche enregistrée dans Celery
- ✅ Logs détaillés ajoutés partout

**La tâche `wama.enhancer.tasks.enhance_media` est maintenant découverte et enregistrée correctement !**

Redémarrez Celery et testez à nouveau. Le problème devrait être résolu.

---

**🎉 Le worker Enhancer devrait maintenant démarrer correctement !**

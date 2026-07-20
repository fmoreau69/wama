# Live Transcription - Affichage de la File d'Attente

## Vue d'ensemble

La zone "Live transcription" affiche maintenant **automatiquement le texte de la première transcription en cours** dans la file d'attente. Cela permet de suivre en temps réel l'avancement de la transcription sans utiliser le mode Speak.

## Fonctionnement

### Mode File d'Attente (Queue Mode)

Lorsqu'une transcription est lancée via le bouton "Start Process" :
1. La zone "Live transcription" affiche automatiquement le texte de la **première transcription en cours** (statut RUNNING)
2. Le texte se met à jour progressivement au fur et à mesure du traitement
3. Le **dernier mot détecté** apparaît surligné en jaune (comme en mode Speak)
4. Une fois la transcription terminée, le texte reste affiché pendant 3 secondes avant de disparaître

### Priorité d'Affichage

Le système gère deux modes d'affichage :
- **Mode Speak** : Prioritaire - transcription vocale en direct
- **Mode Queue** : Affichage de la première transcription en cours de la file

Si le mode Speak est actif, il a la priorité et la zone ne sera pas modifiée par les transcriptions de la file.

### Indicateurs Visuels

**Zone de statut** (en haut à droite de la carte Live transcription) :
- `En attente...` : Aucune transcription en cours
- `Transcription #X en cours...` : Transcription active
- `Transcription #X terminée ✓` : Transcription réussie
- `Transcription #X échouée ✗` : Erreur de transcription

**Affichage du texte** :
- Messages de progression : 🎙️ 🔧 📥 🎯
- Texte transcrit avec dernier mot surligné en **jaune**
- Messages d'erreur : ❌

## Étapes de Transcription

### 1. Initialisation
```
🎙️ Transcription en cours...
```

### 2. Prétraitement (si activé)
```
🔧 Prétraitement audio...
```

### 3. Chargement du modèle
```
📥 Chargement du modèle Whisper...
```

### 4. Analyse
```
🎯 Analyse de l'audio en cours...
```

ou
```
🎯 Transcription en cours...

Cela peut prendre quelques instants selon la durée de l'audio.
```

### 5. Résultat
Le texte transcrit s'affiche mot par mot (simulé) ou en entier selon le moteur.

### 6. Erreur (si applicable)
```
❌ Erreur lors de la transcription:

[détails de l'erreur]
```

## Implémentation Technique

### 1. Backend - Worker (workers.py)

#### Nouvelle Fonction
```python
def _set_partial_text(transcript_id: int, text: str) -> None:
    """Store partial transcription text in cache for live display."""
    key = f"transcriber_partial_text_{transcript_id}"
    cache.set(key, text, timeout=3600)
```

#### Modifications dans `transcribe()` et `transcribe_without_preprocessing()`
- Ajout de `_set_partial_text()` aux étapes clés :
  - Initialisation
  - Prétraitement
  - Chargement du modèle
  - Transcription
  - Résultat final
  - Erreur

### 2. Backend - Views (views.py)

#### Modification de `progress()`
```python
def progress(request, pk: int):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    t = get_object_or_404(Transcript, pk=pk, user=user)
    p = int(cache.get(f"transcriber_progress_{t.id}", t.progress or 0))

    # Get partial text for live display
    partial_text = cache.get(f"transcriber_partial_text_{t.id}", '')

    return JsonResponse({
        'progress': p,
        'status': t.status,
        'partial_text': partial_text  # Nouveau champ
    })
```

### 3. Frontend - JavaScript (index.js)

#### Nouvelle Fonction : `updateLiveTranscriptionFromQueue()`
```javascript
function updateLiveTranscriptionFromQueue(transcriptId, status, partialText) {
  // Only update if not in speech mode and this is the first running transcript
  if (!liveOutput || !liveStatus) return;

  // Check if speak mode is active
  if (speakButton && speakButton.classList.contains('active')) {
    return; // Don't override speech mode
  }

  // Find the first RUNNING transcript
  const firstRunning = queueTable ? queueTable.querySelector('tbody tr[data-status="RUNNING"]') : null;

  if (!firstRunning) {
    // No running transcripts, show default message
    liveOutput.textContent = 'Aucune transcription en cours.';
    liveStatus.textContent = 'En attente...';
    return;
  }

  const firstRunningId = firstRunning.dataset.id;

  // Only update if this is the first running transcript
  if (firstRunningId !== String(transcriptId)) {
    return;
  }

  // Update status and display text
  // ...
}
```

#### Nouvelle Fonction : `displayTextWithHighlight()`
```javascript
function displayTextWithHighlight(text) {
  // Split text into words while keeping whitespace
  const words = text.split(/(\s+)/);

  // Find the last non-whitespace word
  let lastWordIndex = -1;
  for (let i = words.length - 1; i >= 0; i--) {
    if (words[i].trim().length > 0) {
      lastWordIndex = i;
      break;
    }
  }

  // Build HTML with highlighted last word
  const htmlParts = words.map((word, index) => {
    if (index === lastWordIndex) {
      return `<mark style="background-color: #ffc107; color: #000; padding: 2px 4px; border-radius: 3px;">${escapeHtml(word)}</mark>`;
    }
    return escapeHtml(word);
  });

  liveOutput.innerHTML = htmlParts.join('');
}
```

#### Modification de `updateRow()`
Ajout de l'appel à `updateLiveTranscriptionFromQueue()` :
```javascript
// Update live transcription display if this is the first running transcript
updateLiveTranscriptionFromQueue(id, status, data.partial_text);
```

## Architecture du Système

```
┌─────────────────────────────────────────────────────────────┐
│                     Worker (Celery)                         │
│                                                             │
│  1. _set_partial_text("🎙️ Transcription en cours...")      │
│  2. _set_partial_text("🔧 Prétraitement...")               │
│  3. _set_partial_text("📥 Chargement du modèle...")        │
│  4. _set_partial_text("🎯 Transcription...")               │
│  5. _set_partial_text(final_text)                          │
│                                                             │
│                         ↓                                   │
│                    Redis Cache                              │
│          transcriber_partial_text_{id}                      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                  Backend (Django Views)                     │
│                                                             │
│  GET /transcriber/progress/<id>/                           │
│  → Returns: {progress, status, partial_text}               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                Frontend (JavaScript Polling)                │
│                                                             │
│  setInterval(() => {                                        │
│    fetch('/progress/<id>/')                                │
│    .then(data => {                                          │
│      updateRow(id, data);                                   │
│      updateLiveTranscriptionFromQueue(id, status, text);   │
│    })                                                       │
│  }, 1200ms)                                                 │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    UI (Live Transcription)                  │
│                                                             │
│  ┌───────────────────────────────────────────────────┐    │
│  │ Live transcription    Transcription #1 en cours...│    │
│  ├───────────────────────────────────────────────────┤    │
│  │ Bonjour je suis en train de parler [maintenant]  │    │
│  │                                        ^^^^^^^^^^^     │
│  │                                      surligné jaune│    │
│  └───────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Comportement Détaillé

### Gestion des Priorités

1. **Mode Speak actif** → Live transcription affiche uniquement le mode Speak
2. **Mode Speak inactif + Transcription en cours** → Live transcription affiche la première transcription de la file
3. **Aucune activité** → Message par défaut "Aucune transcription en cours."

### Gestion des Transcriptions Multiples

Si plusieurs transcriptions sont lancées en même temps :
- Seule la **première** (ordre d'ID) avec statut RUNNING est affichée
- Les autres transcriptions continuent en arrière-plan
- Quand la première se termine, la suivante prend automatiquement sa place

### Nettoyage Automatique

- Le texte partiel reste affiché **3 secondes** après la fin de la transcription
- Ensuite, si aucune autre transcription n'est en cours, retour au message par défaut
- Le cache Redis expire automatiquement après 1 heure

## Limitations

1. **Pas de streaming réel** : Le texte n'apparaît pas mot par mot en temps réel car Whisper/CLI ne supportent pas le streaming. Le texte s'affiche par étapes (messages de progression, puis résultat final).

2. **Latence** : Le polling se fait toutes les 1.2 secondes, donc il peut y avoir un léger délai entre la génération du texte et son affichage.

3. **Une seule transcription visible** : Même si plusieurs transcriptions sont en cours, seule la première est affichée dans Live transcription.

## Améliorations Futures

### Possibles Améliorations

1. **Streaming réel** : Implémenter le découpage de l'audio en chunks et transcrire chunk par chunk pour afficher le texte progressivement

2. **WebSocket** : Remplacer le polling par des WebSockets pour une mise à jour instantanée

3. **Affichage multi-transcriptions** : Permettre de basculer entre les différentes transcriptions en cours

4. **Animation** : Ajouter des transitions CSS lors de l'apparition de nouveaux mots

5. **Progression visuelle** : Afficher une barre de progression intégrée dans la zone Live transcription

## Test

Pour tester la fonctionnalité :

1. Démarrez le serveur Django : `python manage.py runserver`
2. Démarrez Celery : `celery -A wama worker -l info`
3. Accédez à Transcriber : `http://localhost:8000/transcriber/`
4. Uploadez un ou plusieurs fichiers audio
5. Cliquez sur "Start Process"
6. Observez la zone "Live transcription" qui affiche automatiquement les messages de progression puis le texte transcrit avec le dernier mot surligné

## Déploiement

```bash
# Collecter les fichiers statiques
python manage.py collectstatic --noinput

# Redémarrer Celery
celery -A wama worker -l info --pool=solo  # Sur Windows

# Redémarrer le serveur Django (ou rafraîchir avec Ctrl+F5)
```

## Compatibilité

- ✅ **Tous les navigateurs** modernes supportant JavaScript ES6
- ✅ **Mode Speak** et **Mode Queue** sont totalement indépendants
- ✅ **Compatible** avec le prétraitement audio et sans prétraitement

## Notes Importantes

- La fonctionnalité n'interfère **jamais** avec le mode Speak (priorité absolue au mode vocal)
- Les emojis (🎙️ 🔧 📥 🎯 ❌) sont utilisés pour une meilleure lisibilité des étapes
- Le système utilise le cache Redis pour stocker temporairement le texte partiel
- Le surlignage du dernier mot fonctionne de la même manière en mode Speak et en mode Queue

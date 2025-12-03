# Nouvelles fonctionnalités du Transcriber

## Fonctionnalités ajoutées

### 1. Zone Drag & Drop
- Glissez-déposez vos fichiers audio/vidéo directement dans la zone prévue
- Support multi-fichiers (uploadez plusieurs fichiers à la fois)
- Apparence similaire au Synthesizer pour une expérience cohérente

### 2. Support vidéo
Le Transcriber accepte maintenant les fichiers vidéo :
- **Formats supportés** : MP4, AVI, MKV, MOV, WEBM, MPG, MPEG, 3GP, etc.
- **Extraction automatique** : L'audio est extrait automatiquement de la vidéo
- **Nettoyage** : La vidéo est supprimée après extraction (seul l'audio est conservé)
- **Format de sortie** : WAV 16kHz mono (optimal pour Whisper)

### 3. Transcription depuis YouTube
- Collez l'URL d'une vidéo YouTube
- L'audio est automatiquement téléchargé et converti
- Prêt pour la transcription immédiate

## Dépendances requises

### Pour l'extraction audio depuis vidéos
```bash
# FFmpeg doit être installé
# Windows
winget install FFmpeg

# Linux
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg
```

### Pour YouTube
```bash
# Installer yt-dlp
pip install yt-dlp

# OU via le système
# Windows
winget install yt-dlp.yt-dlp

# Linux
sudo curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp
sudo chmod a+rx /usr/local/bin/yt-dlp

# macOS
brew install yt-dlp
```

## Installation des dépendances Python

Ajoutez à votre requirements.txt ou installez directement :

```bash
pip install yt-dlp
```

## Utilisation

### Upload de vidéos
1. Cliquez sur la zone drag & drop ou utilisez le bouton "Parcourir"
2. Sélectionnez un ou plusieurs fichiers vidéo
3. L'audio sera automatiquement extrait
4. La transcription peut ensuite être lancée normalement

### YouTube
1. Copiez l'URL d'une vidéo YouTube
2. Collez-la dans le champ prévu
3. Cliquez sur "Télécharger & Transcrire"
4. Attendez le téléchargement (quelques secondes à minutes selon la vidéo)
5. Le fichier apparaît dans la file d'attente, prêt à transcrire

## Notes techniques

### Extraction audio
- Format de sortie : WAV PCM 16-bit
- Sample rate : 16kHz (optimal pour Whisper)
- Canaux : Mono
- Les fichiers temporaires sont nettoyés automatiquement

### YouTube
- Télécharge uniquement l'audio (pas la vidéo complète)
- Utilise le meilleur format audio disponible
- Convertit automatiquement en WAV
- Le titre de la vidéo est utilisé comme nom de fichier

### Sécurité
- Les vidéos ne sont jamais conservées sur le serveur
- Seul l'audio extrait est stocké
- Les fichiers temporaires sont supprimés après traitement
- Validation des URLs YouTube

## Troubleshooting

### Erreur "ffmpeg not found"
FFmpeg n'est pas installé ou pas dans le PATH. Installez-le selon votre OS (voir ci-dessus).

### Erreur "yt-dlp not found"
yt-dlp n'est pas installé. Installez-le avec pip ou via votre gestionnaire de paquets.

### Vidéo trop longue
Les très longues vidéos peuvent prendre du temps à traiter. Soyez patient.

### Erreur YouTube
- Vérifiez que l'URL est valide
- Certaines vidéos peuvent être protégées ou restreintes géographiquement
- Assurez-vous que yt-dlp est à jour : `pip install --upgrade yt-dlp`

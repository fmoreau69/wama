# Bark Models - Installation Guide

## Overview

Bark is a transformer-based text-to-audio model created by Suno AI. It can generate highly realistic, multilingual speech as well as other audio - including music, background noise and simple sound effects.

This directory stores Bark models locally in the centralized `AI-models/` structure.

## Features

- **Multilingual Support**: English, French, Spanish, German, Italian, Portuguese, Polish, Turkish, Russian, Dutch, Czech, Arabic, Chinese, Japanese, Korean
- **Natural Prosody**: Automatically generates natural intonation and rhythm
- **Emotional Expression**: Can convey emotions through voice
- **Sound Effects**: Can generate non-speech sounds like laughter, sighs, music
- **Multiple Speakers**: Pre-trained speaker voices available

## Model Download

Bark models are downloaded automatically on first use. The models are stored in:
```
AI-models/synthesizer/bark/
```

### Environment Configuration

Set the Bark cache directory in your code:
```python
import os
os.environ['SUNO_USE_SMALL_MODELS'] = 'False'  # Use full models for best quality
os.environ['XDG_CACHE_HOME'] = '/path/to/AI-models/synthesizer/bark'
```

## Available Speaker Presets

Bark includes pre-trained speaker voices:

### English Speakers
- `v2/en_speaker_0` to `v2/en_speaker_9` - Various English voices

### French Speakers
- `v2/fr_speaker_0` to `v2/fr_speaker_4` - Various French voices

### Spanish Speakers
- `v2/es_speaker_0` to `v2/es_speaker_3` - Various Spanish voices

### German Speakers
- `v2/de_speaker_0` to `v2/de_speaker_3` - Various German voices

### Other Languages
- Italian, Portuguese, Polish, Turkish, Russian, Dutch, Czech, Arabic, Chinese, Japanese, Korean, Hindi

## Model Sizes

Bark models consist of several components:
- **Text Encoder**: ~100MB
- **Coarse Model**: ~500MB
- **Fine Model**: ~500MB
- **Codec Model**: ~100MB

**Total**: ~1.2GB per language set

## Usage in WAMA Synthesizer

1. Select "Bark (Natural, Emotional, Sound Effects)" as the TTS model
2. Choose a Bark speaker preset (e.g., "Bark EN Speaker 0")
3. Select the appropriate language
4. Bark will automatically:
   - Generate natural prosody and emotion
   - Handle non-verbal sounds in square brackets: [laughs], [sighs], [clears throat]
   - Generate music when indicated with ♪

## Special Features

### Non-Verbal Sounds
Add sounds to your text:
```
Hello [laughs] this is amazing [clears throat] let me continue.
```

### Music Generation
Add music notes:
```
♪ La la la ♪
```

## References

- GitHub: https://github.com/suno-ai/bark
- Paper: https://arxiv.org/abs/2301.00000
- Demo: https://suno-ai.notion.site/

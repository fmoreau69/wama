# Default Voice References for XTTS v2

This directory contains default voice reference audio files used by the XTTS v2 TTS model for voice cloning.

## About XTTS v2

XTTS v2 is a voice cloning model that requires an audio reference sample (6-10 seconds) to generate speech. The system will automatically download a default sample if none exists, but you can add your own custom voice presets here.

## Adding Custom Voice Presets

To add custom voice presets, place WAV audio files in this directory with the following names:

- `default.wav` - Default voice (used when no preset is selected)
- `male_1.wav` - Male voice preset 1
- `male_2.wav` - Male voice preset 2
- `female_1.wav` - Female voice preset 1
- `female_2.wav` - Female voice preset 2

### Audio Requirements

- **Format**: WAV (recommended) or MP3
- **Duration**: 6-10 seconds
- **Quality**: Clear speech, minimal background noise
- **Content**: Natural speaking voice (not singing or whispering)
- **Sample Rate**: 16kHz or 22.05kHz recommended

### Example Sources

You can find suitable voice samples from:
- [OpenSLR](http://www.openslr.org/) - Free speech datasets
- [Common Voice](https://commonvoice.mozilla.org/) - Mozilla's voice dataset
- [LibriVox](https://librivox.org/) - Public domain audiobooks
- Record your own samples (6-10 seconds of clear speech)

## Automatic Download

If no `default.wav` file exists, the system will automatically download a sample from the Coqui TTS repository on first use.

## Usage

When users upload text files for synthesis without providing a voice reference file, the system will automatically use these default voices based on their selected voice preset.

## License

Any voice samples you add here must comply with applicable copyright and licensing terms. The automatically downloaded sample is from the LJSpeech dataset (public domain).

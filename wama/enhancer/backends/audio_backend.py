"""Route AUDIO de l'enhancer — contrat commun « fichier » (cf. `ROUTES`).

Le moteur reste au substrat (`wama/common/backends/audio_enhancer.run_audio_enhancement`,
que le converter appelle aussi en inline) ; ici seulement la lecture des options au
vocabulaire des colonnes d'`AudioEnhancement` (portage 2026-09-21).
"""
import os


def enhance_audio(input_path: str, output_path: str, output_format=None, options=None,
                  progress_callback=None) -> str:
    """Restauration de parole. Options : `engine` (résolu — 'resemble' | 'deepfilternet'),
    et pour Resemble `mode`, `denoising_strength`, `quality` (NFE). Écrit un WAV dans
    `output_path` ; rend ce chemin."""
    from wama.common.backends.audio_enhancer import run_audio_enhancement
    opts = dict(options or {})
    engine = str(opts.get('engine') or '')
    if not engine or engine == 'auto':
        raise ValueError("Aucun moteur audio dans les options (`engine`) — la glu résout "
                         "« auto » AVANT d'appeler la route.")
    run_audio_enhancement(
        input_path=input_path,
        output_path=output_path,
        engine=engine,
        mode=str(opts.get('mode') or 'both'),
        denoising_strength=float(opts.get('denoising_strength', 0.5) or 0.0),
        quality=int(opts.get('quality') or 64),
        progress_callback=progress_callback,
    )
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise FileNotFoundError(f"Output audio file not created at {output_path}")
    return output_path

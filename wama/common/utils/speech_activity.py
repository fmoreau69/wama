"""
Activité vocale d'un enregistrement — le filtre de parole (VAD) garde-t-il ce que le signal porte ?

Le VAD Silero que faster-whisper applique avant de transcrire saute les silences (moins
d'hallucinations, plus rapide), mais il rejette aussi la parole LOINTAINE ou étouffée. Mesuré
le 2026-09-25 sur deux entretiens : sur un enregistrement proche, le VAD garde 91-99 % de
l'audio pour 74-76 % d'actif à l'énergie ; sur un enregistrement en champ lointain, il garde
17-58 % pour 66-79 % d'actif — et Whisper y rendait 113 mots au lieu de 411 sur 3 minutes.

`vad_rejects_speech` confronte les deux mesures sur quelques fenêtres réparties dans le média
(coût : quelques secondes de CPU, sans charger le fichier entier) ; l'appelant décide quoi en
faire. Réutilisable par tout consommateur d'ASR (transcription, écriture au fil de la lecture).
"""
from __future__ import annotations

#: Le VAD « rejette la parole » quand il garde moins de cette part de ce que l'énergie dit actif.
#: Calé sur les deux mesures du module (0,43 en champ lointain, ≥ 1,2 en proche) : la marge est
#: large des deux côtés, la valeur n'est pas fine.
REJECT_FACTOR = 0.6
#: En dessous de cette part active à l'énergie, le média est surtout du silence : rien à trancher.
MIN_ACTIVE = 0.2
#: Une trame d'énergie est active quand elle dépasse le plancher de bruit (10ᵉ centile) de tant.
ACTIVE_MARGIN_DB = 10.0
FRAME_SECONDS = 0.1


def energy_active_ratio(wave, sr: int, margin_db: float = ACTIVE_MARGIN_DB) -> float:
    """Part des trames de 100 ms dont le niveau dépasse le plancher de bruit de `margin_db`."""
    import numpy as np
    n = int(sr * FRAME_SECONDS)
    if n <= 0 or len(wave) < n:
        return 0.0
    frames = np.asarray(wave[: len(wave) // n * n], dtype='float32').reshape(-1, n)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1) + 1e-12))
    return float((db > np.percentile(db, 10) + margin_db).mean())


def vad_speech_ratio(wave, sr: int) -> float:
    """Part de l'audio que le VAD de faster-whisper retient, avec ses réglages par défaut."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    if not len(wave):
        return 0.0
    spans = get_speech_timestamps(wave, VadOptions(), sampling_rate=sr)
    return sum(s['end'] - s['start'] for s in spans) / len(wave)


def vad_rejects_speech(path, duration_s: float = 0.0, windows: int = 3,
                       window_s: float = 120.0, decode=None) -> dict:
    """Sonde `windows` fenêtres de `window_s` réparties dans le média et rend
    `{'vad', 'energy', 'rejects'}` — `rejects` vrai quand le VAD garde moins de
    `REJECT_FACTOR` de l'actif à l'énergie. `decode(path, sr, start, duration)` est injectable
    (tests) ; par défaut, `audio_decode.decode_window`."""
    if decode is None:
        from wama.common.utils.audio_decode import decode_window as decode
    sr = 16000
    duration_s = float(duration_s or 0)
    if duration_s <= window_s:
        starts = [0.0]
    else:
        starts = [max(0.0, duration_s * (i + 1) / (windows + 1) - window_s / 2)
                  for i in range(windows)]
    vad = energy = 0.0
    for start in starts:
        wave, got_sr = decode(path, sr, start, window_s)
        vad += vad_speech_ratio(wave, got_sr)
        energy += energy_active_ratio(wave, got_sr)
    vad /= len(starts)
    energy /= len(starts)
    rejects = energy >= MIN_ACTIVE and vad < REJECT_FACTOR * energy
    return {'vad': round(vad, 3), 'energy': round(energy, 3), 'rejects': bool(rejects)}

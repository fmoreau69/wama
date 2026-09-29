"""
NIVELLEMENT DE LA PAROLE — une automation de niveau qui suit les mots (idée de Fabien, 2026-09-25).

Repérer où sont les mots (énergie au-dessus du plancher de bruit), mesurer le niveau de la parole
autour de chaque instant, amener ce niveau vers une CIBLE, garder dans les silences le gain des mots
voisins (le bruit n'est pas pompé), lisser l'automation, limiter les crêtes en douceur. Aucun
modèle : du traitement du signal, sur CPU.

HISTOIRE. Prototypé et mesuré le 2026-09-25 (session transcriber) sur deux fenêtres de 3 min —
nombres de MOTS rendus par Whisper, pas de taux d'erreur : neutre à légèrement négatif (voir
`TRANSCRIBER_CORRECTION §5bis`), donc pas intégré. Réintégré le 2026-09-29 (décision de Fabien) en
réglage OPTIONNEL du transcriber, pour être MESURÉ contre une référence dans les lots d'évaluation
(SUMM-RE, FLEURS-CS — `WAMA_QUALITE §9bis`). Paramètres = ceux du prototype, inchangés ; seule
la limitation des crêtes est corrigée (voir en fin de `level_speech`).

⚠ La cible est un niveau MOYEN de parole (−20 dBFS), pas une crête : viser 0 dB en moyenne
saturerait en permanence. La limitation douce garde les crêtes sous 0 dB — le nivellement fait
donc aussi ce que fait une normalisation de crête.
"""
from __future__ import annotations

import numpy as np

#: Trame d'analyse : 20 ms.
FRAME_SECONDS = 0.02


def level_speech(wave, sample_rate: int = 16000, *, target_db: float = -20.0,
                 window_s: float = 0.4, max_boost: float = 24.0, max_cut: float = 10.0,
                 gate_db: float = 8.0, smooth_s: float = 0.25):
    """Signal mono float → même signal, niveau de la parole amené vers `target_db` (dBFS, puissance
    moyenne des trames de parole), gain borné à +`max_boost` / −`max_cut` dB."""
    wave = np.asarray(wave, dtype=np.float32)
    hop = max(1, int(round(FRAME_SECONDS * sample_rate)))
    n = len(wave) // hop
    if n == 0:
        return wave.copy()
    frames = wave[: n * hop].reshape(n, hop)
    power = (frames.astype(np.float64) ** 2).mean(axis=1) + 1e-12
    db = 10 * np.log10(power)
    floor = np.percentile(db, 15)
    speech = db > floor + gate_db                            # « là où sont les mots »
    # Niveau de la PAROLE autour de chaque trame : puissance moyenne des trames de parole voisines.
    w = max(1, int(window_s / FRAME_SECONDS))
    kernel = np.ones(w)
    p_speech = np.convolve(np.where(speech, power, 0.0), kernel, 'same')
    n_speech = np.convolve(speech.astype(float), kernel, 'same')
    have = n_speech > 0
    local_db = np.full(n, np.nan)
    local_db[have] = 10 * np.log10(p_speech[have] / n_speech[have])
    gain_db = np.clip(target_db - local_db, -max_cut, max_boost)
    # Les silences gardent le gain des mots qui les entourent (interpolé) : pas de pompage du bruit.
    idx = np.arange(n)
    ok = ~np.isnan(gain_db)
    gain_db = np.interp(idx, idx[ok], gain_db[ok]) if ok.any() else np.zeros(n)
    s = max(1, int(smooth_s / FRAME_SECONDS))                # automation lissée
    gain_db = np.convolve(gain_db, np.ones(s) / s, 'same')
    gain = np.repeat(10 ** (gain_db / 20), hop).astype(np.float32)
    out = np.concatenate([wave[: n * hop] * gain, wave[n * hop:] * (gain[-1] if len(gain) else 1.0)])
    # Limitation douce des crêtes : ≈ linéaire aux bas niveaux, bornée à 0,98. ⚠ Le prototype du
    # 25/09 écrivait `tanh(x) / tanh(1) × 0,98`, qui DÉPASSE 1 dès que |x| > 1 (jusqu'à ×1,29) —
    # l'écriture en 16 bits aurait écrêté. Seule différence avec lui.
    if np.abs(out).max() > 0.98:
        out = 0.98 * np.tanh(out / 0.98)
    return out.astype(np.float32)


def level_file(in_path, out_path, sample_rate: int = 16000) -> str:
    """Nivelle un fichier audio (tout format lisible par le décodeur commun) → WAV mono 16 bits."""
    import soundfile as sf

    from wama.common.utils.audio_decode import decode_audio
    wave, sr = decode_audio(str(in_path), target_sr=sample_rate, mono=True)
    sf.write(str(out_path), level_speech(wave, sr), sr, subtype='PCM_16')
    return str(out_path)

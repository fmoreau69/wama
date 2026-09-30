"""
DÉGRADATION CONTRÔLÉE d'un enregistrement de parole — pour évaluer les prétraitements sur des
audios de qualité MOYENNE dont on connaît exactement la dégradation (demande de Fabien,
2026-09-30, `WAMA_QUALITE §9bis`).

Un corpus propre (SUMM-RE) garde sa référence horodatée ; on lui applique un PROFIL déclaré
(`PROFILES`) : bruit ajouté à un rapport signal/bruit donné, champ lointain (réverbération,
voix plus faible). Tout est DÉTERMINISTE (graine fixe) : le même profil sur le même audio rend
le même fichier — condition pour qu'une dégradation entre dans des tests d'évaluation
reproductibles, et pour qu'on puisse la confronter à un corpus RÉEL de qualité moyenne (CFPP2000)
avant de lui faire confiance.

CE QUE CE MODULE NE PRÉTEND PAS. Un bruit rose et une réverbération exponentielle ne sont pas une
salle réelle : ce sont des dégradations CONNUES, pas des dégradations réalistes. C'est la
comparaison avec le corpus réel qui dira si elles prédisent la même chose.

Traitement du signal seul, sur CPU (numpy, scipy). Aucun modèle, aucune donnée tierce.
"""
from __future__ import annotations

import numpy as np

#: Profils déclarés. Les CLÉS sont des données (elles nomment les variantes en médiathèque et se
#: lisent dans les rapports) ; les valeurs disent tout ce qui a été fait au signal.
#:   snr_db         : rapport entre la parole ACTIVE et le bruit ajouté (dB) ;
#:   rt60_s         : durée de réverbération (s) — absent = pas de réverbération ;
#:   attenuation_db : baisse du niveau global, bruit compris (voix lointaine, micro loin).
PROFILES = {
    'noise_snr15': {'label': 'bruit rose, 15 dB', 'snr_db': 15.0},
    'noise_snr5': {'label': 'bruit rose, 5 dB', 'snr_db': 5.0},
    'far_field': {'label': 'champ lointain (réverbération 0,7 s, −20 dB, bruit 15 dB)',
                  'rt60_s': 0.7, 'attenuation_db': 20.0, 'snr_db': 15.0},
}

#: Graine commune : une variante se refait à l'identique.
SEED = 20260930


def active_power(wave, sr: int, gate_db: float = 8.0) -> float:
    """Puissance moyenne des trames de 20 ms au-dessus du plancher (15ᵉ centile + `gate_db`) —
    le niveau de la PAROLE, pas celui des silences (même lecture que `speech_leveling`)."""
    hop = max(1, int(0.02 * sr))
    n = len(wave) // hop
    if n == 0:
        return float(np.mean(np.square(wave))) if len(wave) else 0.0
    power = (wave[: n * hop].astype(np.float64).reshape(n, hop) ** 2).mean(axis=1) + 1e-12
    db = 10 * np.log10(power)
    active = db > np.percentile(db, 15) + gate_db
    return float(power[active].mean() if active.any() else power.mean())


def pink_noise(length: int, rng) -> np.ndarray:
    """Bruit rose (densité en 1/f) de puissance unitaire, par mise en forme spectrale."""
    white = rng.standard_normal(length)
    spectrum = np.fft.rfft(white)
    freqs = np.arange(len(spectrum), dtype=np.float64)
    freqs[0] = 1.0
    pink = np.fft.irfft(spectrum / np.sqrt(freqs), n=length)
    return (pink / (np.sqrt(np.mean(pink ** 2)) + 1e-12)).astype(np.float32)


def add_noise(wave, sr: int, snr_db: float, rng) -> np.ndarray:
    """Ajoute un bruit rose tel que parole active / bruit = `snr_db`."""
    noise = pink_noise(len(wave), rng)
    gain = np.sqrt(active_power(wave, sr) / (10 ** (snr_db / 10)))
    return (wave + gain * noise).astype(np.float32)


def reverberate(wave, sr: int, rt60_s: float, rng) -> np.ndarray:
    """Réverbération synthétique : réponse impulsionnelle = trajet direct + queue de bruit à
    décroissance exponentielle (−60 dB en `rt60_s`, modèle de Polack). Niveau de parole conservé."""
    from scipy.signal import fftconvolve
    length = int(rt60_s * sr)
    t = np.arange(length) / sr
    tail = rng.standard_normal(length) * np.exp(-6.9078 * t / rt60_s)   # ln(1000) = 6.9078
    tail[: int(0.005 * sr)] = 0.0                                       # 5 ms avant les réflexions
    rir = tail * 0.5 / (np.sqrt(np.sum(tail ** 2)) + 1e-12)
    rir[0] = 1.0
    wet = fftconvolve(wave, rir)[: len(wave)]
    return (wet * np.sqrt(active_power(wave, sr) / (active_power(wet, sr) + 1e-12))).astype(np.float32)


def degrade(wave, sr: int, profile: str) -> np.ndarray:
    """Applique le profil déclaré `profile` : réverbération, puis bruit, puis atténuation ;
    les crêtes restent sous 0 dB (limitation douce, comme `speech_leveling`)."""
    spec = PROFILES[profile]
    rng = np.random.default_rng(SEED)
    out = np.asarray(wave, dtype=np.float32)
    if spec.get('rt60_s'):
        out = reverberate(out, sr, spec['rt60_s'], rng)
    if spec.get('snr_db') is not None:
        out = add_noise(out, sr, spec['snr_db'], rng)
    if spec.get('attenuation_db'):
        out = out * (10 ** (-spec['attenuation_db'] / 20))
    if np.abs(out).max() > 0.98:
        out = 0.98 * np.tanh(out / 0.98)
    return out.astype(np.float32)

"""
WAMA — Normalisation des libellés de locuteurs.

Chaque backend ASR produit ses propres identifiants de locuteur :
  - Whisper + pyannote  → "SPEAKER_00", "SPEAKER_01", …
  - VibeVoice (natif)   → "0", "1", … (ou "Speaker_1")

On unifie tout vers une forme canonique explicite « SPEAKER_NN » pour
l'affichage et l'export, tout en conservant intacts les noms personnalisés
(ex. « Fabien Moreau ») saisis par l'utilisateur.
"""
import re

_CANON_RE = re.compile(r'^\s*(?:speaker[\s_\-]*)?(\d+)\s*$', re.IGNORECASE)


def normalize_speaker_label(raw) -> str:
    """Ramène un id locuteur à la forme canonique « SPEAKER_NN ».

    - ""/None                → "" (segment sans locuteur)
    - "0", "1", "07"         → "SPEAKER_00", "SPEAKER_01", "SPEAKER_07"
    - "speaker 2", "Speaker_3" → "SPEAKER_02", "SPEAKER_03"
    - "SPEAKER_00"           → inchangé
    - "Fabien Moreau"        → inchangé (nom personnalisé)
    """
    if raw is None:
        return ''
    s = str(raw).strip()
    if not s:
        return ''
    m = _CANON_RE.match(s)
    if m:
        return f"SPEAKER_{int(m.group(1)):02d}"
    return s


def display_speaker(raw, speaker_map=None) -> str:
    """Libellé d'affichage final : nom personnalisé si présent dans speaker_map, sinon canonique.

    Ex. raw="0", speaker_map={"SPEAKER_00": "Fabien"} → "Fabien".
    """
    canon = normalize_speaker_label(raw)
    if speaker_map and canon in speaker_map and speaker_map[canon]:
        return speaker_map[canon]
    return canon


def normalize_segments_speakers(segments):
    """Normalise `speaker_id` sur une liste de dicts de segments (en place + retour)."""
    if not segments:
        return segments
    for seg in segments:
        if isinstance(seg, dict) and 'speaker_id' in seg:
            seg['speaker_id'] = normalize_speaker_label(seg.get('speaker_id'))
    return segments


def unique_speakers(segments):
    """Liste ordonnée et dédupliquée des locuteurs (canoniques) présents."""
    seen = []
    for seg in segments or []:
        spk = normalize_speaker_label(
            seg.get('speaker_id') if isinstance(seg, dict) else getattr(seg, 'speaker_id', '')
        )
        if spk and spk not in seen:
            seen.append(spk)
    # Tri naturel : SPEAKER_00 < SPEAKER_01 … ; noms personnalisés à la fin
    def _key(s):
        m = _CANON_RE.match(s)
        return (0, int(m.group(1))) if m else (1, 0)
    return sorted(seen, key=_key)

"""
WAMA Synthesizer - Batch File Parser

Parses pipe-separated batch synthesis files.
Format: nom_fichier|texte à synthétiser|voix|vitesse
Colonnes voix et vitesse sont optionnelles.
Lignes commençant par # = commentaires, lignes vides ignorées.

Formats de fichier supportés : TXT, MD, PDF, DOCX, CSV.

Text extraction is delegated to wama.common.utils.batch_parsers.
"""

import os
import logging
from typing import List, Tuple, Dict

from wama.common.utils.batch_parsers import extract_batch_file_text

logger = logging.getLogger(__name__)


def parse_batch_file(
    file_path: str,
    default_voice: str = 'default',
    default_speed: float = 1.0,
    source_name: str = None,
) -> Tuple[List[Dict], List[str]]:
    """
    Parse a batch synthesis file (pipe-separated).

    Args:
        file_path: Path to the batch file
        default_voice: Voice to use when column 3 is absent or empty
        default_speed: Speed to use when column 4 is absent or empty

    Le format à balises unifié (``-p "texte" [--voice …] [--speed …] [-o nom.wav]
    [-r ref_voix.wav]``) est détecté automatiquement ; sinon → format legacy
    pipe « nom|texte|voix|vitesse ».

    Returns:
        (tasks, warnings)
        Each task dict has keys: output_filename, text, voice, speed, line_num
        [+ voice_reference / language si fournis en format à balises]
    """
    raw_text = extract_batch_file_text(file_path)
    from wama.common.utils.batch_parsers import (
        is_structured_batch_text, apply_indexed_output_names,
    )
    if is_structured_batch_text(raw_text):
        tasks, warnings = _parse_unified_lines(raw_text, default_voice, default_speed)
        # Cas 2 : sorties sans nom → <nom_du_fichier_batch>_NN.wav
        apply_indexed_output_names(tasks, source_name or file_path, '.wav')
        return tasks, warnings
    return _parse_pipe_lines(raw_text, default_voice, default_speed)


def _parse_unified_lines(
    text: str,
    default_voice: str,
    default_speed: float,
) -> Tuple[List[Dict], List[str]]:
    """Batch structuré (CSV à en-têtes OU balises) pour la synthèse : ``prompt`` requis."""
    from wama.common.utils.batch_parsers import parse_structured_batch_text

    norm_items, warnings = parse_structured_batch_text(text)
    tasks: List[Dict] = []

    for parsed in norm_items:
        line_num = parsed.get('line_num')
        text_content = parsed.get('prompt')
        if not text_content:
            warnings.append(f"Ligne {line_num} : texte (prompt / -p) manquant, ignorée")
            continue

        opts = parsed.get('options') or {}
        # Nom de sortie : explicite (-o / colonne output) sinon laissé vide —
        # apply_indexed_output_names() le remplira via <fichier_batch>_NN.wav.
        filename = parsed.get('output') or ''
        if filename and not os.path.splitext(filename)[1]:
            filename += '.wav'

        voice = opts.get('voice') or default_voice

        speed = default_speed
        if 'speed' in opts:
            try:
                speed = float(opts['speed'])
                if not (0.5 <= speed <= 2.0):
                    warnings.append(
                        f"Ligne {line_num} : vitesse {speed} hors limites (0.5–2.0), ajustée"
                    )
                    speed = max(0.5, min(2.0, speed))
            except ValueError:
                warnings.append(
                    f"Ligne {line_num} : vitesse invalide '{opts['speed']}', "
                    f"utilisation de {default_speed}"
                )

        task: Dict = {
            'output_filename': filename,
            'text': text_content,
            'voice': voice,
            'speed': speed,
            'line_num': line_num,
        }
        if parsed.get('reference'):
            task['voice_reference'] = parsed['reference']
        if opts.get('language'):
            task['language'] = opts['language']
        tasks.append(task)

    if not tasks and not warnings:
        warnings.append("Aucune entrée valide (batch structuré)")

    return tasks, warnings


def _parse_pipe_lines(
    text: str,
    default_voice: str,
    default_speed: float,
) -> Tuple[List[Dict], List[str]]:
    """Parse pipe-separated lines into task dicts."""
    tasks: List[Dict] = []
    warnings: List[str] = []

    for line_num, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = [p.strip() for p in line.split('|')]

        if len(parts) < 2:
            warnings.append(f"Ligne {line_num} : format invalide (au moins 2 colonnes requises), ignorée")
            continue

        # Column 1 : output filename
        filename = parts[0]
        if not filename:
            warnings.append(f"Ligne {line_num} : nom de fichier vide, ignorée")
            continue
        # Add .wav extension if none present
        if not os.path.splitext(filename)[1]:
            filename += '.wav'

        # Column 2 : text to synthesize
        text_content = parts[1]
        if not text_content:
            warnings.append(f"Ligne {line_num} : texte vide, ignorée")
            continue

        # Column 3 : voice (optional)
        voice = default_voice
        if len(parts) > 2 and parts[2]:
            voice = parts[2]

        # Column 4 : speed (optional)
        speed = default_speed
        if len(parts) > 3 and parts[3]:
            try:
                speed = float(parts[3])
                if not (0.5 <= speed <= 2.0):
                    warnings.append(
                        f"Ligne {line_num} : vitesse {speed} hors limites (0.5–2.0), ajustée"
                    )
                    speed = max(0.5, min(2.0, speed))
            except ValueError:
                warnings.append(
                    f"Ligne {line_num} : vitesse invalide '{parts[3]}', "
                    f"utilisation de {default_speed}"
                )

        tasks.append({
            'output_filename': filename,
            'text': text_content,
            'voice': voice,
            'speed': speed,
            'line_num': line_num,
        })

    return tasks, warnings

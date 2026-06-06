"""
WAMA Composer - Batch File Parser

Parses pipe-separated batch generation files.
Format: nom_fichier|prompt|modèle|durée
Columns 3 and 4 are optional.
Lines starting with # = comments, blank lines ignored.

Supported file formats: TXT, MD, CSV, PDF, DOCX.

Text extraction is delegated to wama.common.utils.batch_parsers.
"""

from typing import List, Tuple, Dict

from wama.common.utils.batch_parsers import parse_composer_batch  # noqa: F401 (re-export)


def parse_batch_file(
    file_path: str,
    default_model: str = 'musicgen-small',
    default_duration: float = 10.0,
    source_name: str = None,
) -> Tuple[List[Dict], List[str]]:
    """
    Parse a Composer batch file.

    Args:
        file_path:        Path to the batch file
        default_model:    Model to use when column 3 is absent or empty
        default_duration: Duration (seconds) to use when column 4 is absent or empty

    Returns:
        (tasks, warnings)
        Each task dict has keys:
            output_filename, prompt, model, duration, generation_type, line_num
    """
    import os
    from wama.common.utils.batch_parsers import (
        extract_batch_file_text, is_structured_batch_text, parse_unified_batch,
    )
    from wama.composer.utils.model_config import COMPOSER_MODELS

    # Legacy pipe positionnel si pas de batch structuré → comportement inchangé.
    if not is_structured_batch_text(extract_batch_file_text(file_path)):
        return parse_composer_batch(file_path, default_model, default_duration)

    # Batch structuré (CSV à en-têtes OU balises : -p prompt, -r référence, -o sortie, --model, --duration)
    items, warnings = parse_unified_batch(file_path)
    tasks = []
    for it in items:
        prompt = (it.get('prompt') or '').strip()
        if not prompt:
            warnings.append(f"Ligne {it['line_num']} : prompt (-p) requis, ignorée")
            continue
        model = it['options'].get('model') or default_model
        if model not in COMPOSER_MODELS:
            model = default_model
        # Auto-modèle : si une référence audio (-r) est fournie → modèle melody.
        if it.get('reference') and 'musicgen-melody' in COMPOSER_MODELS:
            model = 'musicgen-melody'
        try:
            duration = float(it['options'].get('duration', default_duration))
        except (ValueError, TypeError):
            duration = default_duration
        duration = max(10.0, min(600.0, duration))
        # Nom de sortie : explicite (-o / colonne output) sinon laissé vide —
        # apply_indexed_output_names() le remplit via <fichier_batch>_NN.wav.
        output_filename = it.get('output') or ''
        if output_filename and not os.path.splitext(output_filename)[1]:
            output_filename += '.wav'
        tasks.append({
            'output_filename': output_filename,
            'prompt': prompt,
            'model': model,
            'duration': duration,
            'generation_type': COMPOSER_MODELS[model]['type'],
            'reference': it.get('reference'),
            'line_num': it['line_num'],
        })
    if not tasks:
        warnings.append("Aucune tâche valide (format à balises)")
    else:
        from wama.common.utils.batch_parsers import apply_indexed_output_names
        apply_indexed_output_names(tasks, source_name or file_path, '.wav')
    return tasks, warnings

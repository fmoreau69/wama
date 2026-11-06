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
    default_model: str,
    default_duration: float,
    source_name: str = None,
) -> Tuple[List[Dict], List[str]]:
    """
    Parse a Composer batch file.

    Args:
        file_path:        Path to the batch file
        default_model:    Model to use when column 3 is absent or empty
        default_duration: Duration (seconds) to use when column 4 is absent or empty
                          (both REQUIRED since 2026-10-04: the views pass the field's default,
                          3:30 — a default of 10 s written here had outlived it)

    Returns:
        (tasks, warnings)
        Each task dict has keys:
            output_filename, prompt, model, duration, generation_type, reference, given, line_num
        `given` : les réglages que la LIGNE porte elle-même (`--model`, `--duration`), sous leur
        nom de schéma — la création les POSTE comme un dépôt, la cascade commune fait le reste.
        `reference` (`-r`) : le morceau à reprendre (cover), un chemin désigné ou une URL.
    """
    import os
    from wama.common.utils.batch_parsers import (
        extract_batch_file_text, is_structured_batch_text, parse_unified_batch,
    )
    from wama.composer.utils.model_choice import generation_type, is_valid, normalize
    from wama.composer.utils.model_config import clamp_duration

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
        given = {}
        model = it['options'].get('model')
        if model and is_valid(model):
            given['model'] = normalize(model)
        elif model:
            warnings.append(f"Ligne {it['line_num']} : modèle inconnu « {model} », celui du lot")
        model = given.get('model') or normalize(default_model)
        # Une référence (-r) ne choisit plus de modèle ici : « basculer sur MusicGen Melody » était
        # un nom de modèle en dur (retiré le 2026-11-06). Le modèle qui la reprend se juge à la
        # création, sur ce que le catalogue déclare (`views.import_batch`, `accepts_input`).
        try:
            duration = float(it['options']['duration'])
            given['duration'] = duration
        except (KeyError, ValueError, TypeError):
            duration = default_duration
        duration = clamp_duration(duration)
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
            'generation_type': generation_type(model),
            'reference': it.get('reference'),
            'given': given,
            'line_num': it['line_num'],
        })
    if not tasks:
        warnings.append("Aucune tâche valide (format à balises)")
    else:
        from wama.common.utils.batch_parsers import apply_indexed_output_names
        apply_indexed_output_names(tasks, source_name or file_path, '.wav')
    return tasks, warnings

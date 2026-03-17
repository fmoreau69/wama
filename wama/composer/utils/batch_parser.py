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
    return parse_composer_batch(file_path, default_model, default_duration)

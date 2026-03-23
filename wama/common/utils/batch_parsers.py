"""
WAMA Common — Batch file parsers

Common infrastructure for parsing batch import files across apps.

Convention batch WAMA
---------------------
Séparateur : | (pipe).  Commentaires : # en début de ligne.  Encodage : UTF-8.

Type A — Media list (apps traitant des fichiers/URLs existants) :
    Col 1 (req) : chemin absolu/relatif ou URL
    Cols 2+ (opt) : overrides de paramètres spécifiques à l'app
    Apps : anonymizer, describer, enhancer, transcriber, reader
    → parse_media_list_batch()  ou  parse_pipe_batch(schema=TYPE_A_SCHEMA)

Type B — Content generation (apps créant de nouveaux fichiers) :
    Col 1 (req) : nom du fichier de sortie (extension auto si absente)
    Col 2 (req) : contenu principal (texte, prompt…)
    Cols 3+ (opt) : paramètres spécifiques à l'app (modèle, voix, durée…)
    Apps : synthesizer, composer, imager
    → parse_pipe_batch(schema=APP_BATCH_SCHEMA)

Schéma de colonne (pour parse_pipe_batch) :
    {'name': str, 'required': bool, 'default': any,
     'type': 'str'|'float'|'int', 'min': num, 'max': num,
     'choices': list|None, 'add_ext': str|None}
"""

import os
import tempfile
import logging
from typing import Callable, List, Optional, Tuple, Dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Low-level: text extraction from supported file formats
# ---------------------------------------------------------------------------

SUPPORTED_BATCH_EXTENSIONS = ('txt', 'md', 'csv', 'pdf', 'docx')


# ---------------------------------------------------------------------------
# Request-level helpers (shared by all app views)
# ---------------------------------------------------------------------------

def parse_batch_file_from_request(
    request,
    parser: Optional[Callable] = None,
) -> Tuple[List[Dict], List[str]]:
    """
    Extract batch_file from request.FILES, validate extension, parse it, clean up.

    Args:
        request : Django HTTP request containing FILES['batch_file']
        parser  : callable(tmp_path) -> (items, warnings).
                  Defaults to parse_media_list_batch (Type A apps).

    Returns:
        (items, warnings) — same contract as the underlying parser.

    Raises:
        ValueError : missing file, unsupported extension, or parse error.
    """
    if parser is None:
        parser = parse_media_list_batch

    batch_file = request.FILES.get('batch_file')
    if not batch_file:
        raise ValueError('Aucun fichier fourni')

    ext = os.path.splitext(batch_file.name)[1][1:].lower()
    if ext not in SUPPORTED_BATCH_EXTENSIONS:
        raise ValueError(f'Format non supporté : .{ext}')

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp:
            for chunk in batch_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        return parser(tmp_path)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def add_filename_to_items(items: List[Dict]) -> List[Dict]:
    """
    Add a 'filename' key to each item dict derived from item['path'].
    Mutates items in place and returns them for convenience.
    """
    for item in items:
        path = item['path']
        item.setdefault('filename', path.split('/')[-1].split('\\')[-1] or path)
    return items


def batch_media_list_preview_response(request, item_enricher: Optional[Callable] = None):
    """
    Standard batch_preview view helper for Type A apps (media_list).

    Parses the uploaded batch_file, adds 'filename' to each item, optionally
    calls item_enricher(item) for app-specific extra fields, and returns a
    JsonResponse.

    Usage in a view::

        from wama.common.utils.batch_parsers import batch_media_list_preview_response

        @require_POST
        def batch_preview(request):
            return batch_media_list_preview_response(request)

    With an enricher::

        def _enrich(item):
            item['detected_type'] = detect_type_from_extension(...)

        @require_POST
        def batch_preview(request):
            return batch_media_list_preview_response(request, item_enricher=_enrich)
    """
    from django.http import JsonResponse
    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    add_filename_to_items(items)
    if item_enricher is not None:
        for item in items:
            item_enricher(item)

    return JsonResponse({'items': items, 'warnings': warnings, 'count': len(items)})


def extract_batch_file_text(file_path: str) -> str:
    """
    Read and return the raw text from a batch file.

    Supports: .txt, .md, .csv (read as plain text), .pdf (PyPDF2), .docx (python-docx).

    Raises:
        ValueError: unsupported extension
        RuntimeError: missing optional dependency
    """
    ext = os.path.splitext(file_path)[1].lower().lstrip('.')

    if ext in ('txt', 'md', 'csv'):
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    if ext == 'pdf':
        try:
            import PyPDF2
            pages = []
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    t = page.extract_text()
                    if t:
                        pages.append(t)
            return '\n'.join(pages)
        except ImportError:
            raise RuntimeError("PyPDF2 non installé : pip install PyPDF2")

    if ext == 'docx':
        try:
            from docx import Document
            doc = Document(file_path)
            return '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            raise RuntimeError("python-docx non installé : pip install python-docx")

    raise ValueError(f"Format de fichier batch non supporté : .{ext}")


# ---------------------------------------------------------------------------
# URL / media path list parser
# (anonymizer, describer, enhancer, transcriber)
# ---------------------------------------------------------------------------

def parse_media_list_batch(
    file_path: str,
) -> Tuple[List[Dict], List[str]]:
    """
    Parse a batch file containing one media path or URL per line.

    Format:
        # commentaire (ignoré)
        /chemin/relatif/vers/media.mp4
        https://example.com/media.jpg
        ...

    Returns:
        (items, warnings)
        Each item dict has keys: path (str), line_num (int)
        warnings is a list of human-readable warning strings.
    """
    raw_text = extract_batch_file_text(file_path)
    return _parse_media_lines(raw_text)


def _parse_media_lines(text: str) -> Tuple[List[Dict], List[str]]:
    items: List[Dict] = []
    warnings: List[str] = []

    for line_num, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        items.append({'path': line, 'line_num': line_num})

    if not items:
        warnings.append("Aucune entrée valide trouvée dans le fichier batch")

    return items, warnings


# ---------------------------------------------------------------------------
# Composer batch parser (music / SFX generation)
# Format: nom_fichier|prompt|modèle|durée
# ---------------------------------------------------------------------------

def parse_composer_batch(
    file_path: str,
    default_model: str = 'musicgen-small',
    default_duration: float = 10.0,
) -> Tuple[List[Dict], List[str]]:
    """
    Parse a Composer batch file (pipe-separated).

    Format:
        # commentaire (ignoré)
        nom_fichier|prompt de génération|modèle|durée_en_secondes
        intro|upbeat jazz piano|musicgen-medium|20
        ambiance|dark drone|musicgen-small|15
        rain|heavy rain on tin roof|audiogen-medium|10

    Columns 3 (model) and 4 (duration in seconds) are optional.
    The model also determines the generation type (music vs sfx).

    Returns:
        (tasks, warnings)
        Each task dict has keys:
            output_filename, prompt, model, duration, generation_type, line_num
    """
    raw_text = extract_batch_file_text(file_path)
    return _parse_composer_lines(raw_text, default_model, default_duration)


def _parse_composer_lines(
    text: str,
    default_model: str,
    default_duration: float,
) -> Tuple[List[Dict], List[str]]:
    """Parse pipe-separated Composer batch lines into task dicts."""
    from wama.composer.utils.model_config import COMPOSER_MODELS

    tasks: List[Dict] = []
    warnings: List[str] = []
    valid_models = set(COMPOSER_MODELS.keys())

    for line_num, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = [p.strip() for p in line.split('|')]

        if len(parts) < 2:
            warnings.append(
                f"Ligne {line_num} : format invalide (au moins 2 colonnes requises), ignorée"
            )
            continue

        # Column 1: output filename
        filename = parts[0]
        if not filename:
            warnings.append(f"Ligne {line_num} : nom de fichier vide, ignorée")
            continue
        if not os.path.splitext(filename)[1]:
            filename += '.wav'

        # Column 2: prompt
        prompt = parts[1]
        if not prompt:
            warnings.append(f"Ligne {line_num} : prompt vide, ignorée")
            continue

        # Column 3: model (optional)
        model = default_model
        if len(parts) > 2 and parts[2]:
            m = parts[2]
            if m in valid_models:
                model = m
            else:
                warnings.append(
                    f"Ligne {line_num} : modèle '{m}' inconnu, utilisation de '{default_model}'"
                )

        # Column 4: duration in seconds (optional)
        duration = default_duration
        if len(parts) > 3 and parts[3]:
            try:
                duration = float(parts[3])
                if not (1.0 <= duration <= 30.0):
                    warnings.append(
                        f"Ligne {line_num} : durée {duration}s hors limites (1–30s), ajustée"
                    )
                    duration = max(1.0, min(30.0, duration))
            except ValueError:
                warnings.append(
                    f"Ligne {line_num} : durée invalide '{parts[3]}', "
                    f"utilisation de {default_duration}s"
                )

        generation_type = COMPOSER_MODELS.get(model, {}).get('type', 'music')

        tasks.append({
            'output_filename': filename,
            'prompt': prompt,
            'model': model,
            'duration': duration,
            'generation_type': generation_type,
            'line_num': line_num,
        })

    return tasks, warnings


# ---------------------------------------------------------------------------
# Generic pipe-separated batch parser (all apps, schema-driven)
# ---------------------------------------------------------------------------

def parse_pipe_batch(
    file_path: str,
    schema: List[Dict],
) -> Tuple[List[Dict], List[str]]:
    """
    Generic parser for pipe-separated batch files.

    Each app defines its own schema — a list of column descriptors:

        schema = [
            {'name': 'output_filename', 'required': True,  'type': 'str',   'add_ext': '.wav'},
            {'name': 'text',            'required': True,  'type': 'str'},
            {'name': 'voice',           'required': False, 'type': 'str',   'default': None},
            {'name': 'speed',           'required': False, 'type': 'float', 'default': 1.0,
             'min': 0.5, 'max': 2.0},
            {'name': 'language',        'required': False, 'type': 'str',   'default': ''},
        ]

    Column descriptor keys:
        name      (str)  : key in the output dict
        required  (bool) : if True, empty value → row is skipped with a warning
        type      (str)  : 'str' | 'float' | 'int'  — coercion applied
        default   (any)  : value used when column is absent or empty
        min / max (num)  : optional range clamp + warning for numeric types
        choices   (list) : optional allowed values; unknown value → warning, use default
        add_ext   (str)  : if set and the value has no extension, this extension is appended

    Returns:
        (tasks, warnings)
        Each task dict has all 'name' keys from the schema + 'line_num'.
    """
    raw_text = extract_batch_file_text(file_path)
    return _parse_pipe_with_schema(raw_text, schema)


def _parse_pipe_with_schema(
    text: str,
    schema: List[Dict],
) -> Tuple[List[Dict], List[str]]:
    tasks: List[Dict] = []
    warnings: List[str] = []

    for line_num, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = [p.strip() for p in line.split('|')]
        task: Dict = {'line_num': line_num}
        skip = False

        for col_idx, col in enumerate(schema):
            name     = col['name']
            required = col.get('required', False)
            default  = col.get('default', None)
            col_type = col.get('type', 'str')
            choices  = col.get('choices')
            add_ext  = col.get('add_ext')

            # Raw value from parts or absent
            raw = parts[col_idx].strip() if col_idx < len(parts) else ''

            if not raw:
                if required:
                    warnings.append(f"Ligne {line_num} : colonne '{name}' requise mais vide — ligne ignorée")
                    skip = True
                    break
                task[name] = default
                continue

            # Type coercion
            if col_type in ('float', 'int'):
                try:
                    value = float(raw) if col_type == 'float' else int(raw)
                    lo, hi = col.get('min'), col.get('max')
                    if lo is not None and value < lo:
                        warnings.append(f"Ligne {line_num} : '{name}' = {value} < min {lo}, ajusté")
                        value = lo
                    if hi is not None and value > hi:
                        warnings.append(f"Ligne {line_num} : '{name}' = {value} > max {hi}, ajusté")
                        value = hi
                    task[name] = value
                except ValueError:
                    warnings.append(
                        f"Ligne {line_num} : '{name}' = '{raw}' invalide pour type {col_type}, "
                        f"utilisation de la valeur par défaut ({default})"
                    )
                    task[name] = default
            else:
                value = raw
                if choices and value not in choices:
                    warnings.append(
                        f"Ligne {line_num} : '{name}' = '{value}' non reconnu "
                        f"(valeurs: {choices}), utilisation de la valeur par défaut ({default})"
                    )
                    value = default
                if add_ext and value and not os.path.splitext(value)[1]:
                    value = value + add_ext
                task[name] = value

        if not skip:
            tasks.append(task)

    if not tasks:
        warnings.append("Aucune entrée valide trouvée dans le fichier batch")

    return tasks, warnings

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
import shlex
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

    Le format à balises unifié (``-i <fichier> [-o …] [--clé …]``) est détecté
    automatiquement (cf. Phase B) : la balise ``-i`` alimente ``path`` et les
    autres balises (``-o``, ``-p``, ``--option``) sont transportées telles quelles
    pour les apps qui les consomment. Sinon → format legacy « 1 chemin/URL par ligne ».

    Returns:
        (items, warnings)
        Each item dict has keys: path (str), line_num (int)
        [+ output / prompt / reference / options si fournis en format à balises]
        warnings is a list of human-readable warning strings.
    """
    raw_text = extract_batch_file_text(file_path)
    if is_structured_batch_text(raw_text):
        return _structured_items_to_media(raw_text)
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


def _structured_items_to_media(text: str) -> Tuple[List[Dict], List[str]]:
    """Apps Type A : items structurés (CSV/balises) → liste média (``input`` → ``path``).

    Les champs ``output`` / ``prompt`` / ``reference`` / ``options`` sont
    transportés s'ils sont présents (consommés par l'app si pertinent).
    """
    norm_items, warnings = parse_structured_batch_text(text)
    items: List[Dict] = []
    for parsed in norm_items:
        path = parsed.get('input')
        if not path:
            warnings.append(
                f"Ligne {parsed.get('line_num')} : entrée (input / -i) manquante, ignorée"
            )
            continue
        item: Dict = {'path': path, 'line_num': parsed.get('line_num')}
        for key in ('output', 'prompt', 'reference'):
            if parsed.get(key):
                item[key] = parsed[key]
        if parsed.get('options'):
            item['options'] = parsed['options']
        items.append(item)

    if not items and not warnings:
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


# ---------------------------------------------------------------------------
# Phase B — Format batch UNIFIÉ à balises (ffmpeg-style, ordre libre)
# ---------------------------------------------------------------------------
# Un seul format pour toutes les apps. Une URL/un fichier de travail et un
# prompt ne sont que des CHAMPS — l'app consomme ceux qui la concernent.
#
#   -i / --input      fichier ou URL de travail (entrée à traiter)
#   -p / --prompt     texte (génération, TTS, guidage…)
#   -r / --reference  référence (voix de clonage, mélodie, image avatar…)
#   -o / --output     nom/chemin de sortie (optionnel)
#   --clé valeur      option propre à l'app (voice, speed, model, language…)
#   -x valeur         option courte → options['x']
#
# Exemples (une ligne = un item) :
#   -i "https://…/clip.mp4" -o "résumé_1.txt"
#   -p "upbeat jazz piano" -r "melody.wav" --duration 30 -o "track_1.wav"
#
# Voir BATCH_FORMAT.md pour la matrice des champs par app.

_UNIFIED_FLAG_MAP = {
    '-i': 'input', '--input': 'input',
    '-p': 'prompt', '--prompt': 'prompt',
    '-r': 'reference', '--reference': 'reference',
    '-o': 'output', '--output': 'output',
}


def parse_unified_batch_line(line: str) -> Optional[Dict]:
    """Parse une ligne à balises → ``{input, prompt, reference, output, options{}}``.

    Renvoie ``None`` si la ligne ne contient AUCUNE balise reconnue (permet à
    l'appelant de retomber sur un parseur legacy positionnel).
    """
    try:
        tokens = shlex.split(line, comments=False, posix=True)
    except ValueError:
        tokens = line.split()

    item: Dict = {'input': None, 'prompt': None, 'reference': None, 'output': None, 'options': {}}
    found = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ''
        if tok in _UNIFIED_FLAG_MAP:
            item[_UNIFIED_FLAG_MAP[tok]] = nxt
            found = True
            i += 2
        elif tok.startswith('--') and len(tok) > 2:
            item['options'][tok[2:]] = nxt
            found = True
            i += 2
        elif tok.startswith('-') and len(tok) > 1:
            item['options'][tok[1:]] = nxt
            found = True
            i += 2
        else:
            i += 1
    return item if found else None


def is_unified_batch_text(text: str) -> bool:
    """True si le fichier utilise le format à balises (1ʳᵉ ligne utile commence par une balise)."""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        first = s.split(None, 1)[0]
        return first in _UNIFIED_FLAG_MAP or (first.startswith('-') and len(first) > 1)
    return False


def _parse_balise_text(text: str) -> Tuple[List[Dict], List[str]]:
    """Parse le format à balises (ffmpeg-style) → items normalisés."""
    items: List[Dict] = []
    warnings: List[str] = []
    for line_num, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        parsed = parse_unified_batch_line(s)
        if parsed is None:
            warnings.append(f"Ligne {line_num} : aucune balise reconnue (-i/-p/-r/-o), ignorée")
            continue
        parsed['line_num'] = line_num
        items.append(parsed)
    if not items:
        warnings.append("Aucune entrée valide (format à balises)")
    return items, warnings


def parse_structured_batch_text(text: str) -> Tuple[List[Dict], List[str]]:
    """Parse un batch STRUCTURÉ (CSV à en-têtes OU balises) → items normalisés.

    Chaque item : ``{input, prompt, reference, output, options{}, line_num}``.
    Dispatche automatiquement : CSV à en-têtes si la 1ʳᵉ ligne utile contient des
    colonnes reconnues, sinon format à balises.
    """
    if is_csv_header_batch(text):
        return parse_csv_header_batch(text)
    return _parse_balise_text(text)


def parse_unified_batch(file_path: str) -> Tuple[List[Dict], List[str]]:
    """Parse un fichier batch structuré → liste d'items normalisés.

    Accepte le **CSV à en-têtes** (tableur) et le **format à balises**.
    Chaque item : ``{input, prompt, reference, output, options{}, line_num}``.
    L'app valide ensuite les champs requis (ex. ``input`` pour les apps média,
    ``prompt`` pour les apps génératives).
    """
    return parse_structured_batch_text(extract_batch_file_text(file_path))


# ---------------------------------------------------------------------------
# Phase B (suite) — Variante CSV à en-têtes (« tableur »)
# ---------------------------------------------------------------------------
# Même item normalisé que le format à balises, mais construit depuis un CSV où
# la 1ʳᵉ ligne nomme les colonnes. Le module csv gère les virgules dans une
# cellule entre guillemets (`"Bonjour, le monde"`) — donc un prompt avec des
# virgules ne casse pas la structure.
#
# En-têtes reconnus (insensibles casse/accents) → champ canonique ; toute autre
# colonne devient une option (``options[nom_colonne]``).

_CSV_HEADER_ALIASES = {
    'input': 'input', 'file': 'input', 'fichier': 'input', 'url': 'input',
    'media': 'input', 'path': 'input', 'chemin': 'input', 'entree': 'input', 'source': 'input',
    'prompt': 'prompt', 'text': 'prompt', 'texte': 'prompt', 'description': 'prompt', 'contenu': 'prompt',
    # NB : `voice`/`voix` ne sont PAS la référence — ce sont des OPTIONS (preset TTS),
    # cohérent avec le format à balises (`--voice` = option, `-r` = référence clonage).
    'reference': 'reference', 'ref': 'reference',
    'avatar': 'reference', 'melody': 'reference', 'melodie': 'reference',
    'output': 'output', 'sortie': 'output', 'name': 'output', 'nom': 'output', 'filename': 'output',
}


def _normalize_header(h: str) -> str:
    """minuscule + suppression des accents pour le matching d'en-tête."""
    import unicodedata
    h = (h or '').strip().lower()
    return ''.join(c for c in unicodedata.normalize('NFD', h)
                   if unicodedata.category(c) != 'Mn')


#: Alias FR→canonique des noms d'OPTIONS (colonnes non-cœur du mode en-têtes). Sans eux,
#: « modele » / « duree » étaient silencieusement perdus alors que --model/--duration (balises)
#: marchaient — découvert au test du sniffer (2026-07-05).
_OPTION_HEADER_ALIASES = {
    'modele': 'model',
    'duree': 'duration',
    'voix': 'voice',
    'vitesse': 'speed',
    'langue': 'language',
    'format': 'output_format',
    'qualite': 'output_quality',
}

#: Délimiteurs acceptés par le mode « en-têtes » (tableur). Le pipe permet la variante
#: « fichier|prompt|modèle|durée » AVEC ligne d'en-tête (idée Fabien 2026-07-05) : l'ordre
#: des colonnes devient libre, pour TOUTES les apps, sans nouveau format.
_CSV_DELIMITERS = [',', ';', '|', '\t']


def _sniff_csv_delimiter(header_line: str) -> str:
    """Délimiteur qui découpe le PLUS de colonnes sur la ligne d'en-tête."""
    import csv
    best, best_n = ',', 1
    for d in _CSV_DELIMITERS:
        try:
            n = len(next(csv.reader([header_line], delimiter=d)))
        except Exception:
            continue
        if n > best_n:
            best, best_n = d, n
    return best


def is_csv_header_batch(text: str) -> bool:
    """True si la 1ʳᵉ ligne utile est un en-tête tableur (délimiteur , ; | ou tab)
    avec ≥1 colonne reconnue."""
    import csv
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        try:
            row = next(csv.reader([s], delimiter=_sniff_csv_delimiter(s)))
        except Exception:
            return False
        if len(row) < 2:
            return False
        canon = {_CSV_HEADER_ALIASES.get(_normalize_header(c)) for c in row}
        return bool(canon & {'input', 'prompt', 'reference'})
    return False


def parse_csv_header_batch(text: str) -> Tuple[List[Dict], List[str]]:
    """Parse un tableur à en-têtes (délimiteur sniffé) → items normalisés (clés des balises)."""
    import csv
    import io
    items: List[Dict] = []
    warnings: List[str] = []

    # On retire les lignes de commentaire AVANT l'en-tête / entre les lignes.
    kept = [l for l in text.splitlines() if not l.strip().startswith('#')]
    delim = _sniff_csv_delimiter(kept[0]) if kept else ','
    reader = csv.DictReader(io.StringIO('\n'.join(kept)), delimiter=delim)

    # En-tête → ligne 1 ; les données commencent en ligne 2.
    for idx, row in enumerate(reader, start=2):
        item: Dict = {'input': None, 'prompt': None, 'reference': None,
                      'output': None, 'options': {}, 'line_num': idx}
        for header, val in row.items():
            if header is None or val is None:
                continue
            val = val.strip()
            if not val:
                continue
            canon = _CSV_HEADER_ALIASES.get(_normalize_header(header))
            if canon:
                item[canon] = val
            else:
                key = _normalize_header(header)
                item['options'][_OPTION_HEADER_ALIASES.get(key, key)] = val
        if not any([item['input'], item['prompt'], item['reference']]):
            warnings.append(f"Ligne {idx} : aucune colonne utile (input/prompt/reference), ignorée")
            continue
        items.append(item)

    if not items:
        warnings.append("Aucune ligne valide (CSV à en-têtes)")
    return items, warnings


def is_structured_batch_text(text: str) -> bool:
    """True si le texte est un batch structuré (CSV à en-têtes OU balises)."""
    return is_csv_header_batch(text) or is_unified_batch_text(text)


def build_batch_template(fields, example, *, app_label=''):
    """Génère le TEMPLATE batch d'une app depuis sa DÉCLARATION de champs (A5-23).

    Une seule source pour le fichier téléchargeable : documente les 3 syntaxes
    auto-détectées et fournit la ligne d'en-têtes + une ligne d'exemple.
    `fields` = noms de colonnes (alias FR acceptés), `example` = {champ: valeur}."""
    lines = [
        f"# Template batch {app_label} — 3 syntaxes acceptées (détection automatique) :",
        "#  1) TABLEUR à ligne d'en-têtes — délimiteur , ; | ou tabulation ; ordre des colonnes LIBRE",
        "#  2) BALISES style CLI : -i entrée · -p \"prompt\" · -r référence · -o sortie · --option valeur",
        "#  3) POSITIONNEL hérité : valeurs séparées par | dans l'ordre ci-dessous, SANS en-tête",
        "# Les lignes commençant par # sont des commentaires.",
        '|'.join(fields),
        '|'.join(str(example.get(f, '')) for f in fields),
    ]
    return '\n'.join(lines) + '\n'


def apply_indexed_output_names(tasks, source_name, default_ext, *, key='output_filename'):
    """Nomme les sorties manquantes : ``<stem_du_fichier_batch>_<NN>.<ext>``.

    **Décision projet (Cas 2)** : un fichier batch de N prompts SANS nom de sortie
    par ligne → noms dérivés du **nom du fichier batch**, indexés 01, 02, 03…
    (ex. ``poems.csv`` → ``poems_01.wav``, ``poems_02.wav``).

    - N'écrase **jamais** un nom explicite (``-o`` / colonne ``output``) ; lui ajoute
      seulement l'extension si absente.
    - L'index est la position (1-based) de la tâche dans la liste.
    """
    import os
    stem = os.path.splitext(os.path.basename(source_name or 'batch'))[0] or 'batch'
    ext = (default_ext or 'out').lstrip('.')
    for i, t in enumerate(tasks, start=1):
        cur = (t.get(key) or '').strip()
        if not cur:
            t[key] = f"{stem}_{i:02d}.{ext}"
        elif not os.path.splitext(cur)[1]:
            t[key] = f"{cur}.{ext}"
    return tasks

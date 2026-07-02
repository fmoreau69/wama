"""
WAMA Common — Application Registry

Single source of truth for all app specifications:
  - accepted input extensions (used by upload validation, FileManager send-to)
  - batch type and support
  - import capabilities (URL, YouTube)
  - output types
  - conventions conformity status

Re-exports CONVERTER_OUTPUT_FORMATS from converter.utils.format_router so that
other apps and templates can reference it via a single import from app_registry.

Usage:
    from wama.common.app_registry import APP_CATALOG, AUDIO_EXTENSIONS, IMAGE_EXTENSIONS
    from wama.common.app_registry import get_app_extensions_for_filemanager
    from wama.common.app_registry import CONVERTER_OUTPUT_FORMATS
"""

# ---------------------------------------------------------------------------
# Centralized extension constants
# ---------------------------------------------------------------------------

AUDIO_EXTENSIONS = ('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.opus', '.wma')

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.heic', '.gif')

VIDEO_EXTENSIONS = ('.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv', '.mpg', '.qt', '.3gp')

# OCR-readable inputs (PDF + scanned images) — used by Reader.
OCR_INPUT_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp', '.bmp')

TEXT_EXTENSIONS = ('.txt', '.md', '.csv', '.pdf', '.docx')  # batch file formats (= SUPPORTED_BATCH_EXTENSIONS)

# Rich text-document + ebook formats (Pandoc + PyMuPDF + Calibre) — generic.
# Mirrors SUPPORTED_CONVERSIONS['document']['input'] in converter/utils/format_router.py.
DOCUMENT_EXTENSIONS = ('.pdf', '.docx', '.md', '.markdown', '.html',
                       '.htm', '.txt', '.rtf', '.odt', '.epub', '.fb2',
                       '.tex', '.latex', '.mobi', '.azw3', '.azw')

# Archive formats (Converter archive backend — stdlib + optional py7zr/rarfile).
ARCHIVE_EXTENSIONS = ('.zip', '.tar', '.gz', '.tgz', '.bz2', '.tbz2',
                      '.xz', '.txz', '.7z', '.rar')


# ---------------------------------------------------------------------------
# Normalisation type → CATÉGORIE média (vocabulaire unifié pour la méta-app studio).
# input_types/output_types d'APP_CATALOG sont hétérogènes (parfois catégories : 'image',
# parfois extensions : 'wav'/'srt'). On ramène tout à un jeu fini de catégories pour que le
# « typage par connexion » du studio soit cohérent (sortie ∩ entrée sur des catégories).
# ---------------------------------------------------------------------------
MEDIA_CATEGORIES = ('image', 'video', 'audio', 'document', 'archive', 'text')

def _build_cat_of():
    m = {}
    for cat, exts in (('image', IMAGE_EXTENSIONS), ('video', VIDEO_EXTENSIONS),
                      ('audio', AUDIO_EXTENSIONS), ('archive', ARCHIVE_EXTENSIONS),
                      ('document', DOCUMENT_EXTENSIONS)):
        for e in exts:
            m.setdefault(e.lstrip('.').lower(), cat)
    # Sous-titres / texte / données → 'text' (prime sur 'document' pour ces extensions).
    for e in ('txt', 'srt', 'vtt', 'json', 'md', 'markdown', 'csv'):
        m[e] = 'text'
    return m

_CAT_OF = _build_cat_of()

def normalize_types(types):
    """['wav','image','srt'] → ['audio','image','text'] (catégories média, dédupliquées, ordre stable)."""
    out = []
    for t in types or []:
        t = str(t).lstrip('.').lower()
        cat = t if t in MEDIA_CATEGORIES else _CAT_OF.get(t)
        if cat and cat not in out:
            out.append(cat)
    return out


def studio_node_ports(app_id):
    """
    Dérive les PORTS d'un nœud studio pour une app, métadonnée-driven :
      - port « travail » média (entrée) : catégories de input_types (hors 'text'), multi.
      - port « prompt » : si 'text' en entrée (imager/composer…).
      - ports « référence » : depuis app_modes (reference_image→image, reference_voice→audio).
      - sortie : catégories de output_types.
    Retourne {'inputs': [...], 'output': {...}} ou None si app inconnue.
    """
    cat = APP_CATALOG.get(app_id)
    if not cat:
        return None
    in_cats = normalize_types(cat.get('input_types', []))
    out_cats = normalize_types(cat.get('output_types', []))
    media_in = [c for c in in_cats if c != 'text']

    inputs = []
    if media_in:
        inputs.append({'id': 'work', 'label': 'Entrée', 'group': 'travail',
                       'types': media_in, 'multi': True})
    if 'text' in in_cats:
        inputs.append({'id': 'prompt', 'label': 'Prompt', 'group': 'prompt',
                       'types': ['prompt'], 'multi': False})

    # Ports de référence déclarés dans le schéma modes (si l'app y figure).
    try:
        from wama.common.utils.app_modes import APP_MODES, INPUT_TYPES
    except Exception:
        APP_MODES, INPUT_TYPES = {}, {}
    schema = APP_MODES.get(app_id) or {}
    seen = set()
    for dom in schema.get('domains', []):
        for mode in dom.get('modes', []):
            for kind in mode.get('inputs', []):
                spec = INPUT_TYPES.get(kind) or {}
                if spec.get('port') != 'reference' or kind in seen:
                    continue
                seen.add(kind)
                acc = spec.get('accept')
                types = normalize_types([acc]) if acc else (media_in or ['image'])
                inputs.append({'id': kind, 'label': spec.get('label', kind),
                               'group': 'reference', 'types': types or ['image'], 'multi': bool(spec.get('multi'))})

    return {'inputs': inputs, 'output': {'label': 'Sortie', 'types': out_cats}}


# ---------------------------------------------------------------------------
# Convention conformity flags
# Meanings:
#   True  = implemented and conformant
#   False = missing / non-conformant (should be fixed)
#   None  = not applicable for this app
# ---------------------------------------------------------------------------

def _conv(
    # Boutons & queue de base (existants)
    settings=True, start=True, download=True, duplicate=True, delete=True,
    start_all=True, clear_all=True, download_all=True, drag_drop=True, batch=True,
    # Features transversales — défauts False = non implémenté par défaut, à overrider
    # quand l'app est conforme. Mettre à None pour signaler N/A (ex: eta_batch sur
    # une app sans système batch).
    settings_modal_item=False,    # §10 — modale d'édition par item
    save_profile=None,             # §7 — profils sauvegardables (par défaut N/A)
    eta_individual=False,          # §7.2 — ETA par item
    eta_batch=False,               # §7.2 — ETA par batch
    eta_queue=False,               # §7.2 — ETA queue globale
    multi_format_download=False,   # §6.3 — split-button download multi-format
    export_binding='early',        # §6.4 — 'early' (format réglé AVANT génération, render-based) |
                                   #        'late' (format choisi AU TÉLÉCHARGEMENT, master-based)
    filemanager_import=False,      # §8.3 — "Envoyer vers app" + dispatch wama:fileimported
    recursive_import=False,        # §8.4 — import dossier récursif
    tool_api=False,                # §17 — fonctions exposées dans tool_api.py
    cross_app_options=None,        # post-traitement cross-app (upscale, audio enhance) — N/A par défaut
    # Homogénéisation (chantier d'uniformisation 2026-06) — défauts False, override quand conforme.
    inspector=False,               # volet droit CONTEXTUEL complet (card/batch/file) via WamaInspector
    modes=False,                   # switch de MODE généré par WamaModes (+ schéma app_modes)
    layout=False,                  # affichage Ligne / Mosaïque (toggle commun + card_layout)
    model_help=False,              # descriptif modèle sous le select (courte + ⓘ longue) via
                                   # WamaModelHelp commun — audit 2026-07-02, cf. REMOVAL_LEDGER
):
    return {
        # Buttons & queue
        'settings_btn':           settings,
        'start_btn':              start,
        'download_btn':           download,
        'duplicate_btn':          duplicate,
        'delete_btn':             delete,
        'start_all':              start_all,
        'clear_all':              clear_all,
        'download_all':           download_all,
        'drag_drop':              drag_drop,
        'batch':                  batch,
        # Cross-cutting features
        'settings_modal_item':    settings_modal_item,
        'save_profile':           save_profile,
        'eta_individual':         eta_individual,
        'eta_batch':              eta_batch,
        'eta_queue':              eta_queue,
        'multi_format_download':  multi_format_download,
        'export_binding':         export_binding,
        'filemanager_import':     filemanager_import,
        'recursive_import':       recursive_import,
        'tool_api':               tool_api,
        'cross_app_options':      cross_app_options,
        'inspector':              inspector,
        'modes':                  modes,
        'layout':                 layout,
        'model_help':             model_help,
    }


# ---------------------------------------------------------------------------
# App Catalog
# ---------------------------------------------------------------------------

APP_CATALOG = {

    'anonymizer': {
        'label':       'Anonymizer',
        'icon':        'fas fa-user-secret',
        'color':       '#dc3545',
        'url_name':    'anonymizer:index',
        'description': 'Floutage automatique de visages et plaques sur images et vidéos.',
        'input_extensions': IMAGE_EXTENSIONS + VIDEO_EXTENSIONS,
        'input_types': ('image', 'video'),
        'batch_type':  'media_list',  # Type A: one URL/path per line
        'has_batch':   True,
        'has_url_import': True,
        'has_youtube': True,
        'output_types': ('image', 'video'),
        'conventions': _conv(
            settings_modal_item=True,
            tool_api=True,
            model_help=True,     # WamaModelHelp (select YOLO #user_setting_model_to_use, meta catalogue)
        ),
    },

    'avatarizer': {
        'label':       'Avatarizer',
        'icon':        'fas fa-user-circle',
        'color':       '#0dcaf0',
        'url_name':    'avatarizer:index',
        'description': 'Génération de vidéos d\'avatars lip-sync animés par IA (MuseTalk + CodeFormer).',
        'input_extensions': AUDIO_EXTENSIONS + IMAGE_EXTENSIONS,  # audio (standalone) + image (avatar)
        'input_types': ('audio', 'image', 'text'),  # text en mode pipeline TTS
        'batch_type':  None,
        'has_batch':   False,
        'has_url_import': False,
        'has_youtube': False,
        'output_types': ('video',),
        'conventions': _conv(
            settings=True,
            duplicate=False,
            start_all=False,
            clear_all=False,
            download_all=False,
            batch=False,
            settings_modal_item=True,
            inspector=True,      # volet contextuel via WamaInspector.initFromSchema (clic card → réglages #N)
            eta_batch=None,      # N/A — pas de batch
            eta_queue=None,      # N/A — pas de queue multi-item significative
            model_help=None,     # N/A — MuseTalk fixe (v1.5), aucun select de modèle exposé
        ),
    },

    'composer': {
        'label':       'Composer',
        'icon':        'fas fa-music',
        'color':       '#198754',
        'url_name':    'composer:index',
        'description': 'Génération de musique et effets sonores par IA.',
        'input_extensions': TEXT_EXTENSIONS,
        'input_types': ('text',),
        'batch_type':  'pipe',   # Type B: filename|prompt|model|duration
        'has_batch':   True,
        'has_url_import': False,
        'has_youtube': False,
        'output_types': ('wav', 'mp3'),
        'conventions': _conv(
            start=None,  # auto-start on generate, no per-item start button needed
            settings_modal_item=True,
            inspector=True,      # volet contextuel via WamaInspector.initFromSchema
            model_help=True,     # WamaModelHelp (descriptif sous le select modèle)
        ),
    },

    'converter': {
        'label':       'Converter',
        'icon':        'fas fa-exchange-alt',
        'color':       '#20c997',
        'url_name':    'converter:index',
        'description': 'Conversion de formats : image, vidéo, audio, documents, archives (Pillow + FFmpeg + Pandoc).',
        'input_extensions': (IMAGE_EXTENSIONS + VIDEO_EXTENSIONS + AUDIO_EXTENSIONS
                             + DOCUMENT_EXTENSIONS + ARCHIVE_EXTENSIONS),
        'input_types': ('image', 'video', 'audio', 'document', 'archive'),
        'batch_type':  'media_list',   # multi-fichiers (par nature) + fichier d'URLs
        'has_batch':   True,
        'has_url_import': True,         # fichier batch d'URLs locales/distantes
        'has_youtube': False,
        'output_types': ('image', 'video', 'audio', 'document', 'archive'),
        'conventions': _conv(
            batch=True,              # ConversionBatch (multi-fichiers groupé par nature + fichier d'URLs) — 2026-06
            download_all=False,      # P2
            settings_modal_item=True, # Phase 0 (2026-05-16)
            save_profile=True,       # Phase 1 (2026-05-16)
            filemanager_import=True, # quick-action + dispatch wama:fileimported (2026-05-16)
            tool_api=True,           # convert_file + get_converter_status (2026-06-02)
            cross_app_options=False, # Phase 2 à implémenter (upscale + audio enhance)
            inspector=True,          # volet contextuel via WamaInspector.init (variante : sélection + bandeau, édition en modale)
            model_help=None,         # N/A — pas de modèles IA (ffmpeg/pandoc/Pillow)
        ),
    },

    'describer': {
        'label':       'Describer',
        'icon':        'fas fa-search-plus',
        'color':       '#0dcaf0',
        'url_name':    'describer:index',
        'description': 'Description automatique d\'images, vidéos, fichiers audio et documents par LLM.',
        'input_extensions': IMAGE_EXTENSIONS + VIDEO_EXTENSIONS + AUDIO_EXTENSIONS + TEXT_EXTENSIONS,
        'input_types': ('image', 'video', 'audio', 'text'),
        'batch_type':  'media_list',  # Type A: one URL/path per line
        'has_batch':   True,
        'has_url_import': True,
        'has_youtube': True,
        'output_types': ('txt',),
        'conventions': _conv(
            settings_modal_item=True,
            multi_format_download=True,
            export_binding='late',
            tool_api=True,
            inspector=True,      # volet contextuel via WamaInspector.initFromSchema
            model_help=None,     # N/A — sélection de modèle INTERNE (auto par type de média), aucun select
        ),
    },

    'enhancer': {
        'label':       'Enhancer',
        'icon':        'fas fa-magic',
        'color':       '#6f42c1',
        'url_name':    'enhancer:index',
        'description': 'Upscaling IA d\'images/vidéos et amélioration audio (Resemble, DeepFilterNet).',
        'input_extensions': IMAGE_EXTENSIONS + VIDEO_EXTENSIONS + AUDIO_EXTENSIONS,
        'input_types': ('image', 'video', 'audio'),
        'batch_type':  'media_list',
        'has_batch':   True,
        'has_url_import': True,
        'has_youtube': False,
        'output_types': ('image', 'video', 'audio'),
        'conventions': _conv(
            settings_modal_item=True,
            tool_api=True,
            inspector=True,      # volet contextuel via WamaInspector.initFromSchema (image/vidéo/audio)
            modes=True,          # onglets domaine image/vidéo/audio générés (WamaModes.fetch/create)
            model_help=True,     # WamaModelHelp (help_fallback moteurs, cf. enhancer/params.py)
        ),
    },

    'imager': {
        'label':       'Imager',
        'icon':        'fas fa-image',
        'color':       '#fd7e14',
        'url_name':    'imager:index',
        'description': 'Génération d\'images et vidéos par IA (Stable Diffusion, Hunyuan, Mochi…).',
        'input_extensions': TEXT_EXTENSIONS + IMAGE_EXTENSIONS,  # text prompt + image reference
        'input_types': ('text', 'image'),
        'batch_type':  None,   # to be redesigned
        'has_batch':   False,
        'has_url_import': False,
        'has_youtube': False,
        'output_types': ('image', 'video'),
        'conventions': _conv(
            settings=False,
            duplicate=False,
            start_all=False,
            drag_drop=False,
            batch=False,
            tool_api=True,
            settings_modal_item=True,  # modales par-item #generationSettingsModal / #videoSettingsModal
            eta_batch=None,    # N/A — pas de batch
            modes=True,        # barres de mode image/vidéo générées (WamaModes)
            model_help=True,   # WamaModelHelp (descriptif sous les selects modèle image/vidéo)
        ),
    },

    'reader': {
        'label':       'Reader (OCR)',
        'icon':        'fas fa-book-open',
        'color':       '#0dcaf0',
        'url_name':    'reader:index',
        'description': 'Extraction de texte par OCR (Tesseract, PaddleOCR, EasyOCR).',
        'input_extensions': OCR_INPUT_EXTENSIONS,
        'input_types': ('document', 'image'),
        'batch_type':  'media_list',
        'has_batch':   True,
        'has_url_import': False,
        'has_youtube': False,
        'output_types': ('txt', 'markdown'),
        'conventions': _conv(
            settings_modal_item=True,
            multi_format_download=True,
            export_binding='late',
            tool_api=True,
            inspector=True,      # volet contextuel via WamaInspector.initFromSchema
            model_help=True,     # WamaModelHelp (help_fallback moteurs OCR, cf. reader/params.py)
        ),
    },

    'synthesizer': {
        'label':       'Synthesizer',
        'icon':        'fas fa-microphone',
        'color':       '#0d6efd',
        'url_name':    'synthesizer:index',
        'description': 'Synthèse vocale TTS (XTTS, Higgs Audio, Kokoro…).',
        'input_extensions': TEXT_EXTENSIONS,
        'input_types': ('text',),
        'batch_type':  'pipe',   # Type B: filename|text|voice|speed
        'has_batch':   True,
        'has_url_import': False,
        'has_youtube': False,
        'output_types': ('mp3', 'wav'),
        'conventions': _conv(
            start=None,
            settings_modal_item=True,
            tool_api=True,
            inspector=True,      # volet contextuel via WamaInspector.initFromSchema (volet = zone compose, à séparer)
            model_help=True,     # WamaModelHelp (select #tts_model, meta catalogue via _tts_model_help_meta)
        ),
    },

    'transcriber': {
        'label':       'Transcriber',
        'icon':        'fas fa-file-alt',
        'color':       '#ffc107',
        'url_name':    'transcriber:index',
        'description': 'Transcription audio/vidéo en texte (Whisper).',
        'input_extensions': AUDIO_EXTENSIONS + VIDEO_EXTENSIONS,
        'input_types': ('audio', 'video'),
        'batch_type':  'media_list',
        'has_batch':   True,
        'has_url_import': True,
        'has_youtube': True,
        'output_types': ('txt', 'srt', 'vtt', 'json'),
        'conventions': _conv(
            settings_modal_item=True,
            multi_format_download=True,
            export_binding='late',
            tool_api=True,
            inspector=True,   # référence : volet contextuel card/batch/file ET modale item/batch
                              # GÉNÉRÉS depuis le schéma unique (transcriber/params.py + WamaParams)
            modes=None,       # N/A — Speak (temps réel) = AFFORDANCE de la card (show_live,
                              # _new_item_card), PAS un switch WamaModes (design card-centric
                              # intentionnel, cf. transcriber/index.html:321,352). À repasser à True
                              # SI le temps réel devient un vrai mode WamaModes (vision « realtime=mode »).
            layout=True,      # ligne / mosaïque
            model_help=True,  # WamaModelHelp (meta backends via get_backends_info, index.js:1580)
        ),
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Re-export CONVERTER_OUTPUT_FORMATS for convenience
try:
    from wama.converter.utils.format_router import CONVERTER_OUTPUT_FORMATS
except ImportError:
    CONVERTER_OUTPUT_FORMATS = {}


def get_app_extensions_for_filemanager() -> dict:
    """
    Returns a dict suitable for FileManager JS APP_EXTENSIONS:
        { 'reader': ['pdf', 'jpg', ...], 'transcriber': [...], ... }

    Extensions are returned without leading dot, lowercased.
    """
    return {
        app_name: sorted({ext.lstrip('.') for ext in spec['input_extensions']})
        for app_name, spec in APP_CATALOG.items()
    }


def get_conformity_summary() -> dict:
    """
    Returns per-app conformity score:
        { 'reader': {'score': 10, 'total': 10, 'pct': 100, 'issues': []}, ... }
    """
    summary = {}
    for app_name, spec in APP_CATALOG.items():
        conv = spec.get('conventions', {})
        issues = []
        total = 0
        ok = 0
        for key, val in conv.items():
            if val is None:
                continue  # N/A
            total += 1
            if val:
                ok += 1
            else:
                issues.append(key)
        pct = int(ok / total * 100) if total > 0 else 100
        summary[app_name] = {
            'score': ok,
            'total': total,
            'pct':   pct,
            'issues': issues,
        }
    return summary


# ── Descriptions longues (inspecteur volet droit `/apps/`, cf. PROJECT_STATUS §2bis) ──────────
# Source unique des descriptions détaillées, plus riches que le one-liner `description` des cards.
# Fusionnées dans APP_CATALOG à l'import ; consommées par l'inspecteur d'app (WamaInspector).
_DESCRIPTION_LONG = {
    'anonymizer': "Détection puis floutage automatique de visages et de plaques d'immatriculation sur images et vidéos. Modèles YOLO de détection/segmentation, suivi inter-frames avec interpolation pour combler les trous entre détections, et floutage progressif. Un chemin parallèle (détection → cache → floutage fusionné) gère les requêtes multi-modèles. Généralisation multimodale (documents, audio, texte via Presidio) prévue.",
    'avatarizer': "Génère une vidéo d'avatar parlant lip-sync à partir d'une image de visage et d'un audio — ou directement d'un texte synthétisé en voix (mode pipeline TTS). Pipeline MuseTalk (synchronisation labiale) + CodeFormer (restauration faciale).",
    'composer': "Génération de musique et d'effets sonores à partir de prompts texte (Meta AudioCraft — MusicGen pour la musique, AudioGen pour les SFX). Référence de mélodie optionnelle (MusicGen Melody). Import batch et conversion du format de sortie inline via le Converter. Prompts traduits si besoin (MusicGen entraîné en anglais).",
    'converter': "Conversion de formats sur cinq modalités — images, vidéo, audio, documents et archives (Pillow, FFmpeg, Pandoc, py7zr/rarfile) — avec presets de qualité. Sert aussi de couche de conversion partagée : les autres apps importent ses formats de sortie et réutilisent apply_inline_conversion pour convertir leurs résultats sans dupliquer la logique.",
    'describer': "Description et résumé automatiques d'images, vidéos, audio et documents par modèles multimodaux (Ollama local — gemma/qwen-vl — ou cloud). Le prompt de vision est émis dans la langue de sortie choisie ; plusieurs formats de rendu (résumé, points clés, description structurée). Sous-page de compréhension de documents scientifiques (OpenScholar) prévue.",
    'enhancer': "Amélioration de la qualité média. Image/vidéo : upscaling et restauration IA. Audio : amélioration et débruitage (Resemble Enhance génératif, DeepFilterNet discriminatif). Le préprocessing DeepFilterNet est mutualisé avec le Transcriber (singleton keep_loaded).",
    'imager': "Génération et édition d'images et de vidéos par IA depuis des prompts texte : diffusion (Stable Diffusion XL, Hunyuan, Qwen-Image), logos (FLUX LoRA), vidéo (Mochi, LTX, CogVideoX). Modes img2img / style / describe2img via image de référence. Prompts traduits et enrichis par la PromptPipeline commune.",
    'reader': "Extraction de texte par OCR (Tesseract, PaddleOCR, EasyOCR) depuis images, scans et documents. Brique d'extraction réutilisable par d'autres traitements (compréhension de fichiers de référence, RAG à venir).",
    'synthesizer': "Synthèse vocale (TTS) multi-moteurs : XTTS, Higgs Audio, Kokoro… Voix prédéfinies, voix personnalisées et clonage à partir d'un échantillon. Toute synthèse est encapsulée dans un batch (upload simple = batch de 1, fichier = batch de N). Le texte est dit tel quel — jamais traduit.",
    'transcriber': "Transcription audio/vidéo en texte (Whisper large-v3 et autres moteurs). Diarisation des locuteurs, horodatage par mot, résumé et contrôle de cohérence. Éditeur de correction manuelle assistée (onde + heatmap, navigation clavier, timecode « aller à », auto-save) — voir wama/transcriber/TRANSCRIBER_CORRECTION.md.",
}

for _app_id, _long in _DESCRIPTION_LONG.items():
    if _app_id in APP_CATALOG:
        APP_CATALOG[_app_id]['description_long'] = _long

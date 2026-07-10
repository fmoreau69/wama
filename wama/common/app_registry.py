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

AUDIO_EXTENSIONS = ('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.opus', '.wma',
                    '.aiff', '.aif')

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.heic', '.gif',
                    '.heif', '.avif')

VIDEO_EXTENSIONS = ('.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv', '.mpg', '.mpeg', '.qt',
                    '.3gp', '.wmv', '.ts', '.m4v')

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


# ─── CATÉGORIES d'applications (déclaratif, ÉVOLUTIF — décision Fabien 2026-07-05) ────────────
# Axe de classement = NATURE de l'opération (le domaine média est un ATTRIBUT de l'app, pas un
# groupe — piège de l'Enhancer coupé en deux). Les 3 premières catégories sont DÉRIVABLES des
# types déclarés (derive_category) ; les suivantes accueillent les surfaces hors-catalogue via
# extra_links en attendant leur entrée au catalogue (Data = apps à venir : LSL, segmentation…).
APP_CATEGORIES = {
    'understand': {
        'label': 'Comprendre', 'icon': '🧠', 'order': 1,
        'tagline': 'Média → texte : transcrire, décrire, océriser',
    },
    'create': {
        'label': 'Créer', 'icon': '✨', 'order': 2,
        'tagline': 'Texte → média : images & vidéos, musique/SFX, voix, avatars',
    },
    'transform': {
        'label': 'Transformer', 'icon': '🔧', 'order': 3,
        'tagline': 'Média → média : anonymiser, améliorer, convertir',
    },
    'data': {
        'label': 'Données', 'icon': '📊', 'order': 4,
        'tagline': 'Acquisition (LSL), segmentation, visualisation, traitement — à venir',
        'extra_links': [],
    },
    'lab': {
        'label': 'WAMA Lab', 'icon': '🔬', 'order': 5,
        'tagline': 'Applications métier recherche',
        'extra_links': [
            # Routes namespacées wama_lab (le premier jet 'face_analyzer:index' était silencieusement
            # omis par le garde NoReverseMatch). gate = clé accessible_apps pour le menu nav.
            {'label': 'Face Analyzer', 'url_name': 'wama_lab:face_analyzer:index', 'icon': 'fa-face-smile', 'color': '#0dcaf0', 'gate': 'face_analyzer'},
            {'label': 'Cam Analyzer', 'url_name': 'wama_lab:cam_analyzer:index', 'icon': 'fa-video', 'color': '#ffc107', 'gate': 'cam_analyzer'},
        ],
    },
    'platform': {
        'label': 'Transversal', 'icon': '🧩', 'order': 6,
        'tagline': 'Briques de la plateforme, au service de toutes les apps',
        'extra_links': [
            # nav_hide = présent au catalogue (/apps/) mais pas au menu Applications
            # (le model_manager a déjà son entrée dans la section Administration du header).
            {'label': 'Studio', 'url_name': 'studio:index', 'icon': 'fa-diagram-project', 'color': '#fb923c', 'gate': 'studio'},
            {'label': 'Médiathèque', 'url_name': 'media_library:index', 'icon': 'fa-photo-film', 'color': '#a78bfa', 'gate': 'media_library'},
            {'label': 'Gestion des modèles', 'url_name': 'model_manager:index', 'icon': 'fa-microchip', 'nav_hide': True},
        ],
    },
}

#: Sorties « texte » (pour la dérivation de catégorie).
_TEXT_OUTPUTS = {'txt', 'text', 'markdown', 'md', 'srt', 'vtt', 'json', 'docx', 'pdf'}


def derive_category(entry) -> str:
    """Catégorie DÉRIVÉE des types déclarés — la déclaration explicite prime, la dérivation
    sert de défaut ET de garde-fou manifeste (une app qui sort du texte = Comprendre ;
    qui prend du texte en entrée = Créer ; média→média = Transformer)."""
    outs = {str(t).lower() for t in (entry.get('output_types') or ())}
    ins = {str(t).lower() for t in (entry.get('input_types') or ())}
    if outs and outs <= _TEXT_OUTPUTS:
        return 'understand'
    if 'text' in ins:
        return 'create'
    return 'transform'


def get_apps_by_category():
    """Catalogue groupé, ordonné par APP_CATEGORIES[order] — source des surfaces groupées
    (/apps/, nav, assistant). Renvoie [(cat_id, cat_meta, [(app_name, entry), …]), …] ;
    les catégories sans app mais avec extra_links sont incluses (Data/Lab/Transversal)."""
    groups = {cid: [] for cid in APP_CATEGORIES}
    for name, entry in APP_CATALOG.items():
        cid = entry.get('category') or derive_category(entry)
        groups.setdefault(cid, []).append((name, entry))
    out = []
    for cid, meta in sorted(APP_CATEGORIES.items(), key=lambda kv: kv[1].get('order', 99)):
        apps = groups.get(cid, [])
        if apps or meta.get('extra_links'):
            out.append((cid, meta, apps))
    return out


APP_CATALOG = {

    'anonymizer': {
        'label':       'Anonymizer',
        'category': 'transform',  # cf. APP_CATEGORIES (dérivable de input/output_types)
        'icon':        'fas fa-user-secret',
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
        'category': 'create',  # cf. APP_CATEGORIES (dérivable de input/output_types)
        'icon':        'fas fa-user-circle',
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
            # Corrigé 2026-07-10 (grille périmée) : duplicate/batch/clear_all vérifiés présents
            # (btn-duplicate-job, BatchAvatarJob(BatchMixin), btn-clear-all — index.html:337/442/217).
            duplicate=True,
            start_all=False,     # pas de bouton « Démarrer tout » global (vérifié absent)
            clear_all=True,
            download_all=False,  # pas de bouton « Télécharger tout » global (vérifié absent)
            batch=True,
            settings_modal_item=True,
            inspector=True,      # volet contextuel via WamaInspector.initFromSchema (clic card → réglages #N)
            eta_batch=True,      # wama-eta câblé sur les batchs (index.html:332)
            eta_queue=None,      # N/A — pas de queue multi-item significative
            model_help=None,     # N/A — MuseTalk fixe (v1.5), aucun select de modèle exposé
        ),
    },

    'composer': {
        'label':       'Composer',
        'category': 'create',  # cf. APP_CATEGORIES (dérivable de input/output_types)
        'icon':        'fas fa-music',
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
            tool_api=True,       # compose_music + get_composer_status (tool_api.py central, VÉRIFIÉ
                                 # registre l.2002 — le flag False était PÉRIMÉ, audit 2026-07-03)
            batch=True,          # batch unifié _wrap_generation_in_batch + _auto_wrap_orphans (vérifié)
            eta_individual=True,   # .wama-eta par card (_generation_card l.65) — flag périmé corrigé
            eta_batch=True,        # data-eta-ids en-tête de batch (index l.154)
            eta_queue=True,        # barre globale (brique _global_progress + endpoint au contrat, 2026-07-04)
            layout=True,           # Ligne/Mosaïque commun (wama-queue.js + wama-card, 2026-07-03)
            multi_format_download=None,  # N/A — EARLY binding (format/qualité réglés AVANT génération)
            modes=None,          # N/A — plus de mode (switch retiré, type dérivé du modèle)
            filemanager_import=None,     # N/A — app à entrée TEXTE (prompt), pas de médias à recevoir
        ),
    },

    'converter': {
        'label':       'Converter',
        'category': 'transform',  # cf. APP_CATEGORIES (dérivable de input/output_types)
        'icon':        'fas fa-exchange-alt',
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
            download_all=False,      # P2 — pas de bouton « Télécharger tout » global (vérifié absent)
            settings_modal_item=True, # Phase 0 (2026-05-16)
            save_profile=True,       # Phase 1 (2026-05-16)
            filemanager_import=True, # quick-action + dispatch wama:fileimported (2026-05-16)
            tool_api=True,           # convert_file + get_converter_status (2026-06-02)
            cross_app_options=False, # Phase 2 à implémenter (upscale + audio enhance)
            # Porté 2026-07-10 (grille périmée, corrigée) : inspecteur via initFromSchema
            # (détail/chips build_detail, cloneActions item+batch), card « Nouvel élément » en
            # tête de file (import sans passer par le filemanager), ETA individuel/batch/queue
            # câblés (_job_card.html wama-eta, _batch_card.html eta_ids, _global_progress.html).
            inspector=True,
            eta_individual=True,
            eta_batch=True,
            eta_queue=True,
            model_help=None,         # N/A — pas de modèles IA (ffmpeg/pandoc/Pillow)
        ),
    },

    'describer': {
        'label':       'Describer',
        'category': 'understand',  # cf. APP_CATEGORIES (dérivable de input/output_types)
        'icon':        'fas fa-search-plus',
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
            layout=True,         # Ligne/Mosaïque commun (toolbar + wama-card, 2026-07-05)
        ),
    },

    'enhancer': {
        'label':       'Enhancer',
        'category': 'transform',  # cf. APP_CATEGORIES (dérivable de input/output_types)
        'icon':        'fas fa-magic',
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
        'category': 'create',  # cf. APP_CATEGORIES (dérivable de input/output_types)
        'icon':        'fas fa-image',
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
            # Corrigé 2026-07-10 (grille périmée, snapshot manifestement très ancien) : settings/
            # duplicate/start_all/drag_drop vérifiés présents (index.html:532 settings-btn,
            # :562 duplicate-btn, startAllBtn, plusieurs .drop-zone). `batch` LAISSÉ tel quel
            # (False) malgré `parent_generation` (self-FK) : `has_batch=False`/`batch_type=None
            # « to be redesigned » ci-dessus suggèrent une nuance volontaire (pas un vrai batch
            # unifié à la ConversionBatch) — à trancher par Fabien, pas réinterprété ici.
            settings=True,
            duplicate=True,
            start_all=True,
            drag_drop=True,
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
        'category': 'understand',  # cf. APP_CATEGORIES (dérivable de input/output_types)
        'icon':        'fas fa-book-open',
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
            # ETA vérifié 2026-07-10 (grille de conformité périmée, corrigée) : individuel
            # (_item_card.html wama-eta), batch (_batch_card.html eta_ids) et queue
            # (_global_progress.html) tous câblés.
            eta_individual=True,
            eta_batch=True,
            eta_queue=True,
        ),
    },

    'synthesizer': {
        'label':       'Synthesizer',
        'category': 'create',  # cf. APP_CATEGORIES (dérivable de input/output_types)
        'icon':        'fas fa-microphone',
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
        'category': 'understand',  # cf. APP_CATEGORIES (dérivable de input/output_types)
        'icon':        'fas fa-file-alt',
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
            # Corrigé 2026-07-10 (grille périmée) : individuel + queue vérifiés câblés
            # (wama-eta.js chargé, WamaEta.render sur la card index.js:279, _global_progress.html
            # inclus). eta_batch=False confirmé encore non fait (pas de eta_ids batch en JS).
            eta_individual=True,
            eta_queue=True,
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



# ─── Couleurs d'IDENTITÉ dérivées par catégorie (CARD_DESIGN §9 — validé 2026-07-05) ─────────
# UNE teinte (hue HSL) par catégorie ; la nuance de chaque app est DÉRIVÉE de son rang
# alphabétique dans la catégorie (luminosité étagée 46→66 % : distinguable, daltonisme-friendly,
# contraste OK sur #212529). Identité ≠ état : ces couleurs ne vont JAMAIS sur les barres de
# progression, badges de statut ou boutons d'action. Override : poser 'color' sur l'entrée.
_CATEGORY_HUES = {
    'understand': 200,  # cyan-bleu (analyse)
    'create': 282,      # violet (génération)
    'transform': 160,   # vert-teal (traitement)
    'data': 40,         # ambre
    'lab': 25,          # orange
    'platform': 215,    # gris-bleu
}


def _hsl_hex(h, s, l):
    import colorsys
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, l / 100.0, s / 100.0)
    return '#%02x%02x%02x' % (round(r * 255), round(g * 255), round(b * 255))


def category_color(cid: str) -> str:
    """Couleur de RÉFÉRENCE d'une catégorie (en-têtes de section, dossiers…)."""
    return _hsl_hex(_CATEGORY_HUES.get(cid, 215), 70, 55)


def _assign_derived_colors():
    groups = {}
    for _name, _spec in APP_CATALOG.items():
        _cid = _spec.get('category') or derive_category(_spec)
        groups.setdefault(_cid, []).append(_name)
    for _cid, _names in groups.items():
        hue = _CATEGORY_HUES.get(_cid, 215)
        n = len(_names)
        for i, _name in enumerate(sorted(_names)):
            if 'color' in APP_CATALOG[_name]:
                continue  # override déclaré : on respecte
            light = 46 + (20.0 * i / max(n - 1, 1))
            APP_CATALOG[_name]['color'] = _hsl_hex(hue, 65, light)


_assign_derived_colors()


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

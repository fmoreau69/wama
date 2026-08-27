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

# Échantillons de VOIX (clonage/consigne) : politique d'acceptation partagée
# synthesizer/avatarizer — le même quadruplet était recopié 5 fois. SANS points
# (format attendu par FileExtensionValidator).
VOICE_SAMPLE_EXTENSIONS = ['wav', 'mp3', 'flac', 'ogg']

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

# 3D object formats (chaîne objets 3D — ROADMAP §17ter, consigné 2026-08-18).
# Pivot d'interéchange = GLB ; FBX/USD visés côté passerelle Unreal/virtualib.
# Déclaré UNE fois ici : catégorie '3d' — normalize_types / category_of_path /
# typage des ports studio / TYPE_GROUPS médiathèque en DÉRIVENT (zéro code par consommateur).
OBJECT3D_EXTENSIONS = ('.glb', '.gltf', '.obj', '.fbx', '.stl', '.ply',
                       '.usd', '.usdz', '.dae')


# ---------------------------------------------------------------------------
# Normalisation type → CATÉGORIE média (vocabulaire unifié pour la méta-app studio).
# input_types/output_types d'APP_CATALOG sont hétérogènes (parfois catégories : 'image',
# parfois extensions : 'wav'/'srt'). On ramène tout à un jeu fini de catégories pour que le
# « typage par connexion » du studio soit cohérent (sortie ∩ entrée sur des catégories).
# ---------------------------------------------------------------------------
MEDIA_CATEGORIES = ('image', 'video', 'audio', 'document', 'archive', 'text', '3d')

def _build_cat_of():
    m = {}
    for cat, exts in (('image', IMAGE_EXTENSIONS), ('video', VIDEO_EXTENSIONS),
                      ('audio', AUDIO_EXTENSIONS), ('archive', ARCHIVE_EXTENSIONS),
                      ('document', DOCUMENT_EXTENSIONS), ('3d', OBJECT3D_EXTENSIONS)):
        for e in exts:
            m.setdefault(e.lstrip('.').lower(), cat)
    # Sous-titres / texte / données → 'text' (prime sur 'document' pour ces extensions).
    for e in ('txt', 'srt', 'vtt', 'json', 'md', 'markdown', 'csv'):
        m[e] = 'text'
    return m

_CAT_OF = _build_cat_of()


def category_of_path(path):
    """Catégorie média ('image'|'video'|'audio'|'document'|'archive'|'text'|'3d') d'un chemin
    d'après son extension. Source UNIQUE (studio, previews, etc.) — défaut 'document'."""
    import os
    ext = os.path.splitext(str(path or ''))[1].lstrip('.').lower()
    return _CAT_OF.get(ext, 'document')


def normalize_types(types):
    """['wav','image','srt'] → ['audio','image','text'] (catégories média, dédupliquées, ordre stable)."""
    out = []
    for t in types or []:
        t = str(t).lstrip('.').lower()
        cat = t if t in MEDIA_CATEGORIES else _CAT_OF.get(t)
        if cat and cat not in out:
            out.append(cat)
    return out


def app_capabilities(app_id):
    """Capacités déclarées d'une app = les drapeaux `conventions` d'APP_CATALOG, retournés à plat.

    Accesseur UNIQUE des capacités (analogue de `studio_node_ports` pour les ports) — contrat de
    jonction manifeste : le mécanisme de preview « pendant » lit `during_preview`/`streaming` ICI,
    jamais en tapant dans les conventions ailleurs. Quand le manifeste deviendra autoritaire, ceci
    en sera la projection et les consommateurs (preview, etc.) hériteront sans changer.
    """
    meta = APP_CATALOG.get(app_id) or {}
    conv = meta.get('conventions')
    if conv is None:
        return {}
    if isinstance(conv, dict):
        return dict(conv)
    try:
        return dict(conv._asdict())            # namedtuple
    except Exception:
        pass
    try:
        import dataclasses
        if dataclasses.is_dataclass(conv):
            return dataclasses.asdict(conv)    # dataclass
    except Exception:
        pass
    return {k: getattr(conv, k) for k in dir(conv)
            if not k.startswith('_') and not callable(getattr(conv, k, None))}


def app_supports_during_preview(app_id):
    """True si l'app déclare la capacité de preview « pendant » (progressive/temporaire pendant le
    traitement, streaming « à la Suno »). Lit `during_preview` OU `streaming` via `app_capabilities`.
    """
    caps = app_capabilities(app_id)
    return bool(caps.get('during_preview') or caps.get('streaming'))


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

    # `id` sur la sortie comme sur les entrées : un port sans identifiant n'est pas câblable
    # (le schéma de manifeste l'exige, et la génération d'un nœud studio en aura besoin pour
    # relier les liens). Ajout ADDITIF — les consommateurs existants lisent label/types.
    return {'inputs': inputs, 'output': {'id': 'out', 'label': 'Sortie', 'types': out_cats}}


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
    # §6.3 — formats offerts par le split-button, DÉCLARÉS (2026-08-23). Liste de valeurs de
    # `?format=` ; le libellé et l'icône sont dérivés par `common/utils/export_formats.py`.
    # ⚠ NE PAS confondre avec `output_types` (au niveau de l'app, pas des conventions) : celui-ci
    # décrit les TYPES DE DONNÉE produits, pas les formats de FICHIER téléchargeables. Les deux
    # divergent légitimement — le transcriber produit `txt/srt/vtt/json` et propose au
    # téléchargement `txt/srt/pdf/docx`. Les confondre, c'est ce qui a laissé le bouton ⬇ être
    # le seul des six à n'avoir ni brique ni déclaration.
    export_formats=(),             # ex. ('txt', 'srt', 'pdf', 'docx') — vide = format unique (lien)
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
    # Briques d'uniformisation (audit empirique 2026-07-10) — défauts False, override quand adopté.
    new_item_card=False,           # card « Nouvel élément » commune (_new_item_card.html) en TÊTE de file
    queue_toolbar=False,           # tri/filtre/disposition (_queue_toolbar.html + apply_queue_sort_filter)
    queue_manipulation=False,      # fabrique make_queue_manipulation_views (reorder/move/remove/consolidate)
    anti_race=False,               # démarrage verrouillé (begin_processing OU atomic+select_for_update+revoke)
    cycle_button=False,            # bouton cycle ▶/⏳/↻ commun (_cycle_button.html)
    processing_time=False,         # ProcessingTimeMixin + affichage du temps de traitement sur la card
    status_vocab=False,            # vocabulaire de statut SUCCESS/FAILURE en base (pas DONE/ERROR)
    toast=False,                   # notifications WamaApp.toast — zéro alert() bloquant restant
    during_preview=False,          # §preview — aperçu « PENDANT » (partiel/progressif) : le mécanisme
    streaming=False,               #   commun (preview_utils / app_capabilities) lit ce flag. streaming =
                                   #   émission progressive de l'onde/média (effet « Suno »). Cf. WAMA_MANIFEST_SPEC.
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
        'export_formats':         tuple(export_formats or ()),
        'filemanager_import':     filemanager_import,
        'recursive_import':       recursive_import,
        'tool_api':               tool_api,
        'cross_app_options':      cross_app_options,
        'inspector':              inspector,
        'modes':                  modes,
        'layout':                 layout,
        'model_help':             model_help,
        # Briques d'uniformisation (audit 2026-07-10)
        'new_item_card':          new_item_card,
        'queue_toolbar':          queue_toolbar,
        'queue_manipulation':     queue_manipulation,
        'anti_race':              anti_race,
        'cycle_button':           cycle_button,
        'processing_time':        processing_time,
        'status_vocab':           status_vocab,
        'toast':                  toast,
        'during_preview':         during_preview,
        'streaming':              streaming,
    }


# ---------------------------------------------------------------------------
# App Catalog
# ---------------------------------------------------------------------------


# ─── CATÉGORIES d'applications (déclaratif, ÉVOLUTIF — décision Fabien 2026-07-05) ────────────
# Axe de classement = NATURE de l'opération (le domaine média est un ATTRIBUT de l'app, pas un
# groupe — piège de l'Enhancer coupé en deux). Les 3 premières catégories sont DÉRIVABLES des
# types déclarés (derive_category) ; les suivantes accueillent les surfaces hors-catalogue via
# extra_links en attendant leur entrée au catalogue (Data = apps à venir : LSL, segmentation…).
#
# ⚠ `gate` N'EST PAS un détail de menu : c'est l'app_id de la surface, donc LA clé unique par
# laquelle `accessible()` décide du droit ET par laquelle l'abonnement (PROFILES_PERMISSIONS §8)
# décide de l'affichage. Une surface transversale (studio, médiathèque, model_manager) ou Lab est
# déclarée ICI et pas dans APP_CATALOG parce qu'APP_CATALOG n'est pas « la liste des apps » mais le
# CONTRAT d'une app générique de traitement de fichiers (input_types, batch_type, grille
# `conventions` mesurée par check_app_conformity). Y faire entrer une brique transversale la ferait
# entrer dans le dénominateur de conformité avec un contrat presque entièrement N/A.
# Corollaire : tout ce qui est gardé porte un `gate` — un extra_link sans `gate` n'est ni gardable
# ni masquable, et se lit comme « surface publique ».
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
            # `gate` ajouté le 27/08 : le model_manager EST sous contrôle d'accès
            # (DEFAULT_APP_ACCESS, min_tier développeur) mais son lien s'affichait au catalogue
            # pour tout le monde — le middleware refusait ensuite la page. Un lien gardé ailleurs
            # et pas ici, c'est la promesse d'un 403.
            {'label': 'Gestion des modèles', 'url_name': 'model_manager:index', 'icon': 'fa-microchip', 'nav_hide': True, 'gate': 'model_manager'},
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
            settings_modal_item=True,  # ⚠ modale hand-built (settings_modal.js innerHTML l.287) ;
                                       # params.py existe mais ORPHELIN (aucun consommateur WamaParams)
            tool_api=True,
            model_help=True,     # WamaModelHelp (select YOLO #user_setting_model_to_use, meta catalogue)
            during_preview=True,  # frame floutée COURANTE (~2 s) publiée pendant les vidéos
                                  # (hook on_frame de la boucle de floutage → publish_partial,
                                  # tasks.py 18/08 ; images = une seule frame, pas de pendant)
            # Audit empirique 2026-07-10 :
            eta_individual=True,       # .wama-eta card (_media_card.html:107) + WamaEta.update (process.js:49)
            eta_batch=True,            # data-eta-ids (media_table.html:21)
            eta_queue=True,            # _global_progress.html (content.html:10)
            filemanager_import=True,   # wama:fileimported écouté (right_panel.js:581)
            cross_app_options=True,    # select output_format + apply_inline_conversion (tasks.py:81)
            multi_format_download=None,  # N/A — format réglé en amont (early binding via output_format)
            # Portage 2026-07-11 (suite audit §31) — le PRÉREQUIS le plus profond est tombé :
            status_vocab=True,         # champ `status` PENDING/RUNNING/SUCCESS/FAILURE (migration 0021
                                       # avec conversion des données AVANT drop de `processed` ;
                                       # `processed` survit en property dérivée pour les lecteurs)
            processing_time=True,      # ProcessingTimeMixin + worker (`processing_seconds` au SUCCESS)
                                       # + task_id/error_message ajoutés (FAILURE consigné sur exception)
            layout=True,               # wama-queue-{{ card_layout }} sur #medias
            toast=True,                # 23 alert() → WamaApp.toast typés (5 fichiers JS) ; couleurs
                                       # boutons card alignées (⚙ outline-secondary, ⧉ outline-warning)
            # KO restants : inspector=False (detail FAIT 2026-07-11 + preview OK, mais initFromSchema
            # + _inspector_actions absents — volet droit hand-built right_panel.js) ; modes déclaré
            # APP_MODES:129 mais non câblé ; anti_race partiel (RUNNING posé par le worker + lock
            # cache, pas de begin_processing — pas de vue start par item) ; _new_item_card/
            # _batch_card/_queue_toolbar/_cycle_button absents ; modale hand-built (params.py
            # partiellement orphelin : consommé par le detail adapter désormais).
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
            start_all=True,      # vue start_all + bouton #btn-start-all (audit 2026-07-11)
            clear_all=True,      # vue serveur clear_all (remplace la boucle DELETE client, 2026-07-11)
            download_all=True,   # vue download_all (ZIP) + bouton #btn-download-all (2026-07-11)
            batch=True,
            settings_modal_item=True,
            inspector=True,      # volet contextuel via WamaInspector.initFromSchema (clic card → réglages #N)
                                 # register_app_detail + register_app_preview FAITS 2026-07-11
                                 # (labels params.py, aperçu = avatar_upload) ; reste _inspector_actions
            eta_batch=True,      # wama-eta câblé sur les batchs (index.html:332)
            eta_individual=True, # .wama-eta sur la card (index.html:413) + eta_estimator (views.py:206)
            eta_queue=True,      # _global_progress.html inclus (index.html:319) — N/A périmé (audit 2026-07-10)
            tool_api=True,       # add_to/start/get_status au registre CENTRAL wama/tool_api.py
                                 # (flag False périmé, audit 2026-07-10)
            status_vocab=True,   # SUCCESS/FAILURE (models.py:19)
            multi_format_download=None,  # N/A — sortie vidéo MP4 unique (conversion = rôle converter)
            model_help=None,     # N/A — MuseTalk fixe (v1.5), aucun select de modèle exposé
            # Passe conservatrice 2026-07-11 (suite audit §31) :
            anti_race=True,      # begin_processing sur start + start_all (verrou + revoke)
            toast=True,          # 21 alert() → WamaApp.toast typés ; ordre boutons card corrigé
                                 # (⚙ avant ↻) + couleurs outline (template + buildCard JS)
            new_item_card=True,  # _new_item_card COMMUNE en tête de file (2026-07-11) : dropzone=
                                 # audio (voix de l'avatar) + galerie avatars via slot déclaré
                                 # extra_zone_template. STANDALONE-ONLY depuis 2026-07-11 (décision
                                 # Fabien) : le pipeline texte→TTS→avatar = composition STUDIO
                                 # synthesizer→avatarizer ; backend mode/tts intact (historique,
                                 # batch, tool_api), seule la création UI est standalone.
            # KO restants : _batch_card mère (inline)/_queue_toolbar/_cycle_button/layout/
            # ProcessingTimeMixin absents ; absent d'APP_MODES ; filemanager_import partiel
            # (quick-drop filemanager:filedrop OK, listener wama:fileimported absent).
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
            start=True,  # bouton de cycle commun ▶/⏹/↻ par card (WamaCycleButton, composer/js/index.js:559
                         #   + endpoint composer:start) — l'ancien N/A « auto-start on generate » était
                         #   périmé depuis le portage du bouton de cycle (re-vérifié 2026-08-18)
            during_preview=True,  # aperçu « pendant » activé : le worker publie l'audio via on_audio
                                  #   (composer/tasks.py) → face ?side=during (mécanisme commun)
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
            # Audit empirique 2026-07-10 :
            cross_app_options=True,    # format/qualité converter inline (output_format_params_for_app, params.py:39)
            new_item_card=True,        # _new_item_card.html en tête de file (index.html:78)
            queue_toolbar=True,        # _queue_toolbar + apply_queue_sort_filter (views.py:101)
            queue_manipulation=True,   # make_queue_manipulation_views (views.py:76)
            anti_race=True,            # begin_processing ×4 (views.py:259/367/464/819)
            cycle_button=True,         # _cycle_button.html (_generation_card.html:96)
            processing_time=True,      # ProcessingTimeMixin + _processing_time.html (card:68)
            status_vocab=True,         # SUCCESS/FAILURE (models.py:18)
            toast=True,                # 4 alert() → WamaApp.toast (2026-07-11) ; couleurs boutons card
                                       # alignées outline + ⚙ visible pendant RUNNING (_generation_card)
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
            download_all=True,       # vue download_all (ZIP global) + slot toolbar (2026-07-11, §31.5)
            settings_modal_item=True, # Phase 0 (2026-05-16)
            save_profile=True,       # Phase 1 (2026-05-16)
            filemanager_import=True, # quick-action + dispatch wama:fileimported (2026-05-16)
            tool_api=True,           # convert_file + get_converter_status (2026-06-02)
            during_preview=True,     # audio hors in-place : la sortie ffmpeg s'écrit sous MEDIA
                                     #   → URL partielle écoutable pendant la conversion (13/08)
            streaming=True,          # émission PROGRESSIVE du média réel (pas un aperçu) : la sortie
                                     #   ffmpeg est lisible PENDANT la conversion — audio intégral,
                                     #   vidéo en conteneur streamable webm/mkv/ts (tasks.py:89-100 ;
                                     #   mp4/mov partiel structurellement illisible, moov en fin)
            cross_app_options=True,  # Phase 2 CÂBLÉE (18/08) : schéma dérivé de CROSS_APP_OPTIONS
                                     #   (params.py), split options↔cross_app_options (views.update_job),
                                     #   application inline enhancer (utils/cross_app.py — image
                                     #   upscale/denoise, audio enhance, vidéo enhance de piste audio ;
                                     #   upscale vidéo DIFFÉRÉ, cf. format_router)
            # Porté 2026-07-10 (grille périmée, corrigée) : inspecteur via initFromSchema
            # (détail/chips build_detail, cloneActions item+batch), card « Nouvel élément » en
            # tête de file (import sans passer par le filemanager), ETA individuel/batch/queue
            # câblés (_job_card.html wama-eta, _batch_card.html eta_ids, _global_progress.html).
            inspector=True,
            eta_individual=True,
            eta_batch=True,
            eta_queue=True,
            model_help=None,         # N/A — pas de modèles IA (ffmpeg/pandoc/Pillow)
            # Audit empirique 2026-07-10 :
            multi_format_download=None,  # N/A — le format de sortie EST le paramètre central du job
            layout=True,               # wama-queue-{{ card_layout }} (index.html:381)
            new_item_card=True,        # _new_item_card.html en tête de file (index.html:375)
            queue_toolbar=True,        # _queue_toolbar + apply_queue_sort_filter (views.py:148)
            anti_race=True,            # pattern local atomic+select_for_update (views.py:242/496/667)
            cycle_button=True,         # _cycle_button.html (_job_card.html:49)
            processing_time=True,      # ProcessingTimeMixin + _processing_time.html (_job_card.html:85)
            status_vocab=True,         # migré SUCCESS/FAILURE (migration 0005, 2026-07-11 — pattern reader.0008)
            toast=True,                # 21 alert() → WamaApp.toast (2026-07-11)
            # queue_manipulation=False : consolidate artisanal (urls.py:22) — la fabrique commune
            # exige l'architecture batch unifiée (liaison + BatchMixin) que ConversionBatch n'a pas ;
            # batch léger = choix documenté (note d'intention CONV §15), à trancher AVANT d'adopter.
            # Non déclaré dans APP_MODES malgré 4 domaines (audit 2026-07-10).
        ),
    },

    'describer': {
        'label':       'Describer',
        'category': 'understand',  # cf. APP_CATEGORIES (dérivable de input/output_types)
        'icon':        'fas fa-search-plus',
        'url_name':    'describer:index',
        'description': 'Description automatique d\'images, vidéos, fichiers audio et documents par LLM.',
        'input_extensions': IMAGE_EXTENSIONS + VIDEO_EXTENSIONS + AUDIO_EXTENSIONS + TEXT_EXTENSIONS,
        # `document`, pas `text` (correctif route §10.1, 2026-08-11) : les fichiers texte/PDF
        # que le describer DÉCRIT sont des documents de TRAVAIL — `text` fabriquait un port
        # prompt fantôme et le port travail perdait `document` (les extensions, elles, étaient
        # déjà là). L'ordre = priorité de résolution du nœud studio, préservé de l'historique.
        'input_types': ('image', 'video', 'audio', 'document'),
        'batch_type':  'media_list',  # Type A: one URL/path per line
        'has_batch':   True,
        'has_url_import': True,
        'has_youtube': True,
        'output_types': ('txt',),
        'conventions': _conv(
            settings_modal_item=True,
            multi_format_download=True,
            export_binding='late',
            export_formats=('txt', 'pdf', 'docx'),  # §6.3 — mesurés sur `_description_card.html`
            tool_api=True,
            during_preview=True,  # texte partiel qui se construit (workers._set_partial →
                                  #   brique publish_partial_text → face ?side=during, 2026-08-13)
            inspector=True,      # volet contextuel via WamaInspector.initFromSchema
            model_help=None,     # N/A — sélection de modèle INTERNE (auto par type de média), aucun select
            layout=True,         # Ligne/Mosaïque commun (toolbar + wama-card, 2026-07-05)
            # Audit empirique 2026-07-10 : ETA 3 niveaux câblés (index.js:633 WamaEta.render ;
            # eta_ids batch views.py:233 ; _global_progress index.html:39) — flags False périmés.
            eta_individual=True,
            eta_batch=True,
            eta_queue=True,
            filemanager_import=True,   # wama:fileimported écouté (index.js:1019)
            new_item_card=True,        # _new_item_card.html en tête de file (index.html:37)
            queue_toolbar=True,        # _queue_toolbar + apply_queue_sort_filter (views.py:242)
            queue_manipulation=True,   # make_queue_manipulation_views (views.py:203)
            anti_race=True,            # begin_processing (views.py:547)
            cycle_button=True,         # _cycle_button.html (_description_card.html:71)
            processing_time=True,      # ProcessingTimeMixin + _processing_time.html (card:56)
            status_vocab=True,         # SUCCESS/FAILURE (models.py:19)
            toast=True,                # WamaApp.toast, 0 alert() réel (index.js:957)
            # Reste audité KO 2026-07-10 : couleurs boutons card (⚙ plein, ⧉ info, 🗑 plein —
            # _description_card.html:61/95/100) ; card v2 chips non propagée.
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
            during_preview=True,  # frame UPSCALÉE courante (~2 s) pendant les vidéos
                                  # (tasks.py 18/08) ; reste = domaine AUDIO (callback à
                                  # câbler dans audio_enhancer) et image unitaire (une frame)
            inspector=True,      # volet contextuel via WamaInspector.initFromSchema (image/vidéo/audio)
                                 # register_app_detail FAIT 2026-07-11 (enhancer + audio_enhancer,
                                 # labels params.py) ; reste _inspector_actions (avec cloneActions,
                                 # à câbler au port complet de la file)
            modes=True,          # onglets domaine image/vidéo/audio générés (WamaModes.fetch/create)
            model_help=True,     # WamaModelHelp (help_fallback moteurs, cf. enhancer/params.py)
            # Audit empirique 2026-07-10 :
            eta_individual=True,       # WamaEta.render sur card (index.js:314)
            eta_batch=True,            # data-eta-ids entête batch (index.html:379/602)
            eta_queue=True,            # _global_progress.html (index.html:271)
            filemanager_import=True,   # wama:fileimported écouté (index.js:958)
            cross_app_options=True,    # select output_format converter inline (index.html:205)
            multi_format_download=None,  # N/A — format réglé en amont (early binding output_format)
            status_vocab=True,         # SUCCESS/FAILURE (models.py:15/123)
            # Portage 2026-07-11 (suite audit §31) :
            anti_race=True,            # begin_processing sur start + audio_start (verrou + revoke)
            processing_time=True,      # ProcessingTimeMixin ×2 (migrations 0010/0011 — champ legacy
                                       # processing_time supprimé, doublon sans lecteur) + _processing_time.html
            layout=True,               # wama-queue-{{ card_layout }} sur #enhancer-queue
            toast=True,                # 13 alert() → WamaApp.toast typés ; couleurs boutons alignées
                                       # outline (template + buildCard JS synchronisés)
            # KO restants : _new_item_card, _batch_card mère (hand-built index.html:367),
            # _queue_toolbar, _cycle_button — port complet de la file à faire (PROJECT_STATUS §30/§32).
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
        # Batch LIVRÉ le 2026-08-06 (`9922f65`) : GenerationBatch(BatchMixin, ScopedVisibility)
        # + GenerationBatchItem, migration 0013, contrat commun `build_batches_list` — c'est un
        # vrai batch unifié, au même titre que ConversionBatch. Le « to be redesigned » et le
        # `has_batch=False` qui l'accompagnaient sont donc PÉRIMÉS.
        # `media_list` = vocabulaire EXISTANT pour « un item par ligne » (Type A,
        # parse_media_list_batch). Ici les lignes sont des PROMPTS, pas des médias : le nom de
        # la brique commune porte un type de média à tort (cf. règle de vocabulaire), mais on
        # réutilise la valeur en place plutôt que d'en inventer une.
        'batch_type':  'media_list',
        'has_batch':   True,
        'has_url_import': False,
        'has_youtube': False,
        'output_types': ('image', 'video'),
        'conventions': _conv(
            # Corrigé 2026-07-10 : settings/duplicate/start_all/drag_drop vérifiés présents.
            # `batch` était laissé à False dans l'attente d'un arbitrage sur `parent_generation`
            # (self-FK) : TRANCHÉ PAR LE CODE le 2026-08-06 — `9922f65` a livré un vrai batch
            # unifié (GenerationBatch/GenerationBatchItem) et le self-FK, qui n'avait JAMAIS
            # servi (0 batch en base), est remplacé.
            settings=True,
            duplicate=True,
            start_all=True,
            drag_drop=True,
            batch=True,
            tool_api=True,
            settings_modal_item=True,  # modales par-item, GÉNÉRÉES par WamaParams depuis params.py
                                       # (`f37b705`) — le « hand-built / params.py ORPHELIN »
                                       # noté ici était périmé.
            modes=True,        # barres de mode image/vidéo générées (WamaModes)
            model_help=True,   # WamaModelHelp (descriptif sous les selects modèle image/vidéo)
            # Audit empirique 2026-07-10 :
            eta_individual=True,       # .wama-eta (index.html:526/889) + WamaEta.render (index.js:1267)
            eta_queue=True,            # _global_progress.html (index.html:482)
            cross_app_options=True,    # output_format/quality (models.py:307) + apply_inline_conversion (tasks.py:284)
            multi_format_download=None,  # N/A — format choisi à la GÉNÉRATION (early binding)
            status_vocab=True,         # PENDING/RUNNING/SUCCESS/FAILURE (models.py:165)
            # Passe conservatrice 2026-07-11 (suite audit §31) :
            anti_race=True,            # begin_processing sur start_generation (verrou + revoke)
            toast=True,                # showNotification délègue à WamaApp.toast (doublon Bootstrap
                                       # retiré) + 3 alert() purgés
            # KO restants : inspector=False — detail FAIT (register_app_detail, labels params.py)
            # mais preview VOLONTAIREMENT différé (`generated_images` = JSON multi-images, choix de
            # design au port complet) + initFromSchema/_inspector_actions absents ;
            # filemanager_import partiel (data-wama-app sans listener) ; double markup card
            # image/vidéo (index.html:533 vs 896) ; layout NON posé (cards Bootstrap larges,
            # rendu mosaïque incertain — décision différée) ; _new_item_card/_queue_toolbar/
            # _cycle_button/ProcessingTimeMixin absents.
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
            export_formats=('txt', 'md', 'pdf', 'docx', 'json'),  # §6.3 — `json` n'est offert que si `item.raw_result` — le gabarit garde ce conditionnel
            tool_api=True,
            inspector=True,      # volet contextuel via WamaInspector.initFromSchema
            model_help=True,     # WamaModelHelp (help_fallback moteurs OCR, cf. reader/params.py)
            during_preview=True,  # texte OCR qui se CONSTRUIT page à page (on_partial des 3
                                  # backends → publish_partial_text, tasks._read 18/08) + brut
                                  # affiché pendant la mise en forme LLM (98 %)
            # ETA vérifié 2026-07-10 (grille de conformité périmée, corrigée) : individuel
            # (_item_card.html wama-eta), batch (_batch_card.html eta_ids) et queue
            # (_global_progress.html) tous câblés.
            eta_individual=True,
            eta_batch=True,
            eta_queue=True,
            # Audit empirique 2026-07-10 :
            layout=True,               # wama-queue-{{ card_layout }} (index.html:181) — flag False périmé
            filemanager_import=True,   # wama:fileimported écouté (reader.js:764)
            new_item_card=True,        # _new_item_card.html en tête de file (index.html:171)
            queue_toolbar=True,        # _queue_toolbar + apply_queue_sort_filter (views.py:156)
            queue_manipulation=True,   # make_queue_manipulation_views (views.py:632)
            anti_race=True,            # begin_processing + stop_instance (views.py:264/248)
            cycle_button=True,         # _cycle_button.html (_item_card.html:55)
            processing_time=True,      # ProcessingTimeMixin + _processing_time.html (card:43)
            status_vocab=True,         # SUCCESS/FAILURE (models.py:12, migration 0008)
            # PILOTE card v2 : _card_chips.html + chips_for() (_item_card.html:33, views.py:125).
            toast=True,                # 2 alert() → WamaApp.toast (2026-07-11)
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
            start=True,  # bouton de cycle commun ▶/⏹/↻ par card (clics délégués, synthesizer/js/index.js:13
                         #   + endpoint synthesizer:start) — l'ancien N/A datait d'avant le portage du
                         #   bouton de cycle (re-vérifié 2026-08-18)
            settings_modal_item=True,  # ⚠ modale = HTML hand-built (index.html:472), params.py existe
                                       # mais ponte seulement les dom_id — à migrer vers WamaParams.render
            tool_api=True,
            inspector=True,      # volet contextuel via WamaInspector.initFromSchema (volet = zone compose, à séparer)
                                 # register_app_detail FAIT 2026-07-11 (labels params.py) +
                                 # data-preview-url posé sur la card ; reste _inspector_actions
            model_help=True,     # WamaModelHelp (select #tts_model, meta catalogue via _tts_model_help_meta)
            # Audit empirique 2026-07-10 :
            eta_individual=True,       # .wama-eta card (_synthesis_card.html:57) + eta_estimator (views.py:623)
            eta_batch=True,            # data-eta-ids entête batch (index.html:346)
            eta_queue=True,            # _global_progress.html (index.html:311)
            filemanager_import=True,   # wama:fileimported écouté (index.js:1401)
            cross_app_options=True,    # output_format_params_for_app (params.py:48)
            multi_format_download=None,  # N/A — early binding per-item (output_format/output_quality)
            cycle_button=True,         # _cycle_button.html (_synthesis_card.html:76)
            status_vocab=True,         # SUCCESS/FAILURE (models.py:20/150)
            modes=False,               # déclaré APP_MODES (normal/realtime) mais WamaModes non câblé côté UI
            # Portage 2026-07-11 (suite audit §31) :
            anti_race=True,            # begin_processing sur start (verrou + revoke + reset audio_output)
            processing_time=True,      # ProcessingTimeMixin (migration 0013) + _processing_time.html + worker
            layout=True,               # wama-queue-{{ card_layout }} sur #synthesisQueue
            toast=True,                # 42 alert() (JS + template) → WamaApp.toast typés ; couleurs
                                       # boutons card alignées outline
            # KO restants : modales hand-built (params.py ne ponte que les dom_id — P1 BLOCKER),
            # _new_item_card/_batch_card/_queue_toolbar — port complet de la file à faire.
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
            export_formats=('txt', 'srt', 'pdf', 'docx'),  # §6.3 — ⚠ diffère d'`output_types` ('txt','srt','vtt','json') : ce sont deux choses
            tool_api=True,
            during_preview=True,  # texte partiel qui se construit (workers._set_partial_text →
                                  #   brique publish_partial_text → face ?side=during, 2026-08-13)
            inspector=True,   # référence : volet contextuel card/batch/file ET modale item/batch
                              # GÉNÉRÉS depuis le schéma unique (transcriber/params.py + WamaParams)
            modes=None,       # N/A — Speak (temps réel) = AFFORDANCE de la card (show_live,
                              # _new_item_card), PAS un switch WamaModes (design card-centric
                              # intentionnel, cf. transcriber/index.html:321,352). À repasser à True
                              # SI le temps réel devient un vrai mode WamaModes (vision « realtime=mode »).
            layout=True,      # ligne / mosaïque
            model_help=True,  # WamaModelHelp (meta backends via get_backends_info, index.js:1580)
            # Audit empirique 2026-07-10 : ETA 3 niveaux câblés (WamaEta.render index.js:279 ;
            # eta_ids batch views.py:141 → _batch_card data-eta-ids ; _global_progress.html:183).
            eta_individual=True,
            eta_batch=True,
            eta_queue=True,
            filemanager_import=True,   # wama:fileimported écouté (index.js:1430)
            new_item_card=True,        # _new_item_card.html en tête de file (index.html:164)
            queue_toolbar=True,        # _queue_toolbar + apply_queue_sort_filter (views.py:152)
            queue_manipulation=True,   # make_queue_manipulation_views (views.py:68)
            anti_race=True,            # begin_processing (views.py:433, start_all, batch)
            cycle_button=True,         # _cycle_button.html (_transcript_card.html:91)
            processing_time=True,      # ProcessingTimeMixin + _card_progress elapsed (card:66)
            status_vocab=True,         # SUCCESS/FAILURE (models.py:28)
            toast=True,                # 0 alert() (edit.js purgé 2026-07-11 ; confirm() conservé = décision user)
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


# ── Conformité MESURÉE (check_app_conformity) ────────────────────────────────────
# Le rapport JSON produit par `manage.py check_app_conformity` (analyse statique du
# code réel, cf. common/services/conformity_checker.py) ÉCRASE les booléens déclarés
# de `_conv(...)` — les valeurs saisies à la main ne servent plus que de repli pour
# les critères non mesurés. Cache par mtime (pas de re-parse à chaque requête).
_CONFORMITY_REPORT = {'mtime': None, 'data': None}


def _measured_conformity(app_name: str) -> tuple[dict, str | None]:
    """(valeurs mesurées {clé: True|'partial'|False}, date du rapport) — ({}, None) sans rapport."""
    import json as _json
    from pathlib import Path as _Path
    try:
        from django.conf import settings as _settings
        path = _Path(_settings.BASE_DIR) / 'logs' / 'conformity_report.json'
        mtime = path.stat().st_mtime
    except Exception:
        return {}, None
    if _CONFORMITY_REPORT['mtime'] != mtime:
        try:
            _CONFORMITY_REPORT['data'] = _json.loads(path.read_text(encoding='utf-8'))
            _CONFORMITY_REPORT['mtime'] = mtime
        except Exception:
            return {}, None
    data = _CONFORMITY_REPORT['data'] or {}
    app = data.get('apps', {}).get(app_name, {})
    return app.get('conv', {}), data.get('generated_at')


def measure_and_write_conformity() -> dict:
    """Mesure les 10 apps (conformity_checker.run_checks) et ÉCRIT le rapport JSON.

    Domicile UNIQUE de la mesure-écriture — consommé par la commande
    `check_app_conformity` (CLI/skill /conformite) ET par le bouton « Re-mesurer »
    de la page /apps/ (2026-08-04). Le cache mtime de `_measured_conformity` voit
    le nouveau fichier au prochain accès (pas d'invalidation à faire ici).
    """
    import json as _json
    from datetime import datetime, timezone
    from pathlib import Path as _Path
    from django.conf import settings as _settings
    from wama.common.services.conformity_checker import run_checks

    # Les jumelles bac à sable sont EXCLUES : on ne MESURE pas un bac à sable, on le
    # COMPARE à sa source (route §10.3 marche S).
    from wama.common.sandbox import non_sandbox_apps
    report = run_checks(non_sandbox_apps(APP_CATALOG))
    report['generated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    path = _Path(_settings.BASE_DIR) / 'logs' / 'conformity_report.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    return report


def get_conformity_summary() -> dict:
    """
    Returns per-app conformity score:
        { 'reader': {'score': 10, 'total': 10, 'pct': 100, 'issues': [], 'measured': True}, ... }
    Les critères MESURÉS (rapport check_app_conformity) priment sur les déclarés ;
    'partial' compte pour 0.5 et apparaît dans issues avec le suffixe « (partiel) ».
    """
    summary = {}
    for app_name, spec in APP_CATALOG.items():
        if (spec or {}).get('sandbox'):
            continue   # jumelle bac à sable : comparée à sa source, jamais notée
        conv = dict(spec.get('conventions', {}))
        measured, measured_at = _measured_conformity(app_name)
        conv.update(measured)  # le réel écrase le déclaré
        issues = []
        total = 0
        ok = 0.0
        for key, val in conv.items():
            if val is None:
                continue  # N/A
            if val == 'partial':
                total += 1
                ok += 0.5
                issues.append(f"{key} (partiel)")
                continue
            if not isinstance(val, bool):
                continue  # taxonomie (ex. export_binding 'early'/'late') — pas un critère notable
            total += 1
            if val:
                ok += 1
            else:
                issues.append(key)
        pct = int(ok / total * 100) if total > 0 else 100
        summary[app_name] = {
            'score': int(ok),
            'total': total,
            'pct':   pct,
            'issues': issues,
            'measured': bool(measured),
            'measured_at': measured_at,
        }
    return summary


# ── Descriptions longues (inspecteur volet droit `/apps/`, cf. PROJECT_STATUS §2bis) ──────────
# Source unique des descriptions détaillées, plus riches que le one-liner `description` des cards.
# Fusionnées dans APP_CATALOG à l'import ; consommées par l'inspecteur d'app (WamaInspector).
_DESCRIPTION_LONG = {
    'anonymizer': "Détection puis floutage automatique de visages et de plaques d'immatriculation sur images et vidéos. Modèles YOLO de détection/segmentation, suivi inter-frames avec interpolation pour combler les trous entre détections, et floutage progressif. Un chemin parallèle (détection → cache → floutage fusionné) gère les requêtes multi-modèles. Généralisation multimodale (documents, audio, texte via Presidio) prévue.",
    'avatarizer': "Génère une vidéo d'avatar parlant lip-sync à partir d'une image de visage et d'un audio — ou directement d'un texte synthétisé en voix (mode pipeline TTS). Pipeline MuseTalk (synchronisation labiale) + CodeFormer (restauration faciale).",
    'composer': "Génération de musique et d'effets sonores à partir de prompts texte : chansons complètes avec paroles chantées (MiniMax-Music3, sections [verse]/[chorus], jusqu'à 5 min, moteur audio.cpp), pistes instrumentales (Meta AudioCraft — MusicGen), bruitages (AudioGen). Référence de mélodie optionnelle (MusicGen Melody uniquement — Music3 est conditionné par le texte seul). Import batch et conversion du format de sortie inline via le Converter. Prompts traduits si besoin, et enrichis selon le contrat déclaré du modèle cible (prompt_contract).",
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


# ── Bac à sable (route §10.3 marche S) : entrées APP_CATALOG des jumelles ────────────────
# APRÈS la fusion des descriptions longues (le clone les emporte). Badge « BAC À SABLE »,
# marqueurs sandbox/generated_from ; EXCLUES de la grille (cf. measure_and_write_conformity).
try:
    from wama.common.sandbox import inject_sandbox_catalog
    inject_sandbox_catalog(APP_CATALOG)
except Exception:
    pass

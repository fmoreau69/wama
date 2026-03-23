import os, logging, socket
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Fonctionnalités conditionnelles
ENABLE_CELERY = True
APPEND_SLASH = True
ENABLE_LDAP = True
DEBUG = True

# Répertoires de base
BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# =============================================================================
# CENTRALIZED AI MODELS CONFIGURATION
# =============================================================================
# All AI models are stored in AI-models/ at project root, organized by type/task
# This allows multiple applications to share the same models

AI_MODELS_DIR = BASE_DIR / "AI-models"
AI_MODELS_DIR.mkdir(parents=True, exist_ok=True)

# New centralized model paths (organized by domain, then by model family)
# Structure: models/<domain>/<model_family>/
MODEL_PATHS = {
    # Vision models (detection, segmentation, pose, classification)
    'vision': {
        'root': AI_MODELS_DIR / "models" / "vision",
        # YOLO models (all types: detect, segment, pose, classify, obb)
        'yolo': AI_MODELS_DIR / "models" / "vision" / "yolo",
        # SAM models (Segment Anything Model)
        'sam': AI_MODELS_DIR / "models" / "vision" / "sam",
    },
    # Upscaling/Enhancement models (ONNX)
    'upscaling': {
        'root': AI_MODELS_DIR / "models" / "upscaling",
        'onnx': AI_MODELS_DIR / "models" / "upscaling" / "onnx",
    },
    # Speech models (ASR, TTS)
    'speech': {
        'root': AI_MODELS_DIR / "models" / "speech",
        'whisper': AI_MODELS_DIR / "models" / "speech" / "whisper",
        'coqui': AI_MODELS_DIR / "models" / "speech" / "coqui",
        'bark': AI_MODELS_DIR / "models" / "speech" / "bark",
        'higgs': AI_MODELS_DIR / "models" / "speech" / "higgs",
        'vibevoice': AI_MODELS_DIR / "models" / "speech" / "vibevoice",
        'qwen_asr': AI_MODELS_DIR / "models" / "speech" / "qwen_asr",
        'diarization': AI_MODELS_DIR / "models" / "speech" / "diarization",
        'resemble_enhance': AI_MODELS_DIR / "models" / "speech" / "resemble-enhance",
        'deepfilternet': AI_MODELS_DIR / "models" / "speech" / "deepfilternet",
        'kokoro': AI_MODELS_DIR / "models" / "speech" / "kokoro",
    },
    # Diffusion models (image/video generation)
    'diffusion': {
        'root': AI_MODELS_DIR / "models" / "diffusion",
        'hunyuan': AI_MODELS_DIR / "models" / "diffusion" / "hunyuan",
        'stable_diffusion': AI_MODELS_DIR / "models" / "diffusion" / "stable-diffusion",
        'cogvideox': AI_MODELS_DIR / "models" / "diffusion" / "cogvideox",
        'ltx': AI_MODELS_DIR / "models" / "diffusion" / "ltx",
        'mochi': AI_MODELS_DIR / "models" / "diffusion" / "mochi",
        'flux': AI_MODELS_DIR / "models" / "diffusion" / "flux",
        'logo': AI_MODELS_DIR / "models" / "diffusion" / "logo",
        'qwen_image': AI_MODELS_DIR / "models" / "diffusion" / "qwen-image",
        'flux2_klein': AI_MODELS_DIR / "models" / "diffusion" / "flux2-klein",
    },
    # Vision-Language models (BLIP, LLaVA, etc.)
    'vision_language': {
        'root': AI_MODELS_DIR / "models" / "vision-language",
        'blip': AI_MODELS_DIR / "models" / "vision-language" / "blip",
        'bart': AI_MODELS_DIR / "models" / "vision-language" / "bart",
    },
    # Reader — OCR models (olmOCR-2, docTR)
    'reader': {
        'root':    AI_MODELS_DIR / "models" / "reader",
        'olmocr':  AI_MODELS_DIR / "models" / "reader" / "olmocr",
        'doctr':   AI_MODELS_DIR / "models" / "reader" / "doctr",
    },
    # Music generation models (AudioCraft: MusicGen + AudioGen)
    'music': {
        'root': AI_MODELS_DIR / "models" / "music",
        'musicgen': AI_MODELS_DIR / "models" / "music" / "musicgen",
        'audiogen': AI_MODELS_DIR / "models" / "music" / "audiogen",
    },
    # LLM models (reference to Ollama)
    'llm': {
        'root': AI_MODELS_DIR / "models" / "llm",
    },
    # HuggingFace cache (shared)
    'cache': {
        'huggingface': AI_MODELS_DIR / "cache" / "huggingface",
    },
}

# Create all model directories
for category in MODEL_PATHS.values():
    for path in category.values():
        path.mkdir(parents=True, exist_ok=True)

# =============================================================================
# LEGACY PATHS (for backward compatibility during migration)
# =============================================================================
# These will be removed after full migration to MODEL_PATHS

# Legacy MODELS_ROOT (deprecated - use MODEL_PATHS['detection']['yolo'])
MODELS_ROOT = AI_MODELS_DIR / "anonymizer" / "models--ultralytics--yolo"

# Legacy per-app paths (deprecated)
LEGACY_MODEL_PATHS = {
    'anonymizer_yolo': AI_MODELS_DIR / "anonymizer" / "models--ultralytics--yolo",
    'anonymizer_sam': AI_MODELS_DIR / "anonymizer" / "models--facebook--sam3",
    'enhancer_onnx': AI_MODELS_DIR / "enhancer" / "onnx",
    'imager_wan': AI_MODELS_DIR / "imager" / "wan",
    'imager_hunyuan': AI_MODELS_DIR / "imager" / "hunyuan",
    'synthesizer_tts': AI_MODELS_DIR / "synthesizer" / "tts",
    'synthesizer_bark': AI_MODELS_DIR / "synthesizer" / "bark",
}

# =============================================================================
# HUGGINGFACE CONFIGURATION
# =============================================================================
# HuggingFace cache - MUST be set before any HF imports

HF_DEFAULT_CACHE = MODEL_PATHS['cache']['huggingface']
os.environ.setdefault('HF_HOME', str(HF_DEFAULT_CACHE))
os.environ.setdefault('HF_HUB_CACHE', str(HF_DEFAULT_CACHE))
os.environ.setdefault('HUGGINGFACE_HUB_CACHE', str(HF_DEFAULT_CACHE))

# HuggingFace access token — required for gated models (pyannote/speaker-diarization-3.1).
# Generate at https://huggingface.co/settings/tokens (read access).
# You must also accept the model terms at https://huggingface.co/pyannote/speaker-diarization-3.1
# If set to None, falls back to HF_TOKEN env var or ~/.cache/huggingface/token (huggingface-cli login).
HUGGINGFACE_TOKEN = os.environ.get('HF_TOKEN', None)

# Anonymizer media paths
MEDIA_INPUT_URL = '/media/anonymizer/input'
MEDIA_INPUT_ROOT = MEDIA_ROOT / 'anonymizer' / 'input'
MEDIA_OUTPUT_URL = '/media/anonymizer/output'
MEDIA_OUTPUT_ROOT = MEDIA_ROOT / 'anonymizer' / 'output'

# Clé secrète & débogage
SECRET_KEY = 'REDACTED_SECRET_KEY'
ALLOWED_HOSTS = ['*']

# Allow same-origin framing (needed for PDF embed preview in Chrome)
# DENY (Django default) blocks even same-origin iframes/embed used by Chrome's PDF viewer
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Nom d'hôte machine
try:
    HOSTNAME = socket.gethostname()
except:
    HOSTNAME = 'localhost'

# Base de données
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "wama_db",
        "USER": "wama_user",
        "PASSWORD": "REDACTED_DB_PASSWORD",
        "HOST": "127.0.0.1",
        "PORT": "5432",
    }
}

# Configuration du cache (Redis partagé entre workers Gunicorn)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'db': 1,  # DB1 pour le cache (DB0 pour Celery)
        }
    }
}

# Configuration LDAP
if ENABLE_LDAP:
    import ldap
    from django_auth_ldap.config import LDAPSearch

    AUTH_LDAP_SERVER_URI = 'ldap://ldap-eiffel.ifsttar.fr'
    AUTH_LDAP_USER_SEARCH = LDAPSearch(
        'ou=people,dc=univ-eiffel,dc=fr',
        ldap.SCOPE_SUBTREE,
        '(uid=%(user)s)',
    )
    AUTH_LDAP_USER_ATTR_MAP = {
        "first_name": "givenName",
        "last_name": "sn",
        "email": "mail",
    }
    AUTH_LDAP_ALWAYS_UPDATE_USER = True
    AUTHENTICATION_BACKENDS = [
        'django_auth_ldap.backend.LDAPBackend',
        'django.contrib.auth.backends.ModelBackend',
    ]
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'handlers': {
            'console': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
            },
        },
        'loggers': {
            'django_auth_ldap': {
                'level': 'DEBUG',
                'handlers': ['console'],
                'propagate': True,
            },
        },
    }
else:
    AUTHENTICATION_BACKENDS = [
        'django_auth_ldap.backend.LDAPBackend',
        'django.contrib.auth.backends.ModelBackend',
    ]

# Applications
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    "django_celery_results",
    "django_celery_beat",
    'django_wysiwyg',
    'wama.common',       # Composants communs à toutes les apps
    'wama.accounts',
    'wama.anonymizer',
    'wama.describer',    # AI Content Description
    'wama.enhancer',     # AI Image/Video Upscaling
    'wama.filemanager',  # File browser sidebar
    'wama.imager',
    'wama.synthesizer',
    'wama.transcriber',
    'wama.avatarizer',
    'wama.model_manager',  # AI Models Manager
    'wama.media_library',  # Médiathèque centralisée
    'wama.composer',       # Music & SFX generation (AudioCraft)
    'wama.reader',         # OCR Document — imprimé + manuscrit
    # WAMA Lab - Experimental/Research applications
    'wama_lab.face_analyzer',
    'wama_lab.cam_analyzer',
    # REST API
    'rest_framework',
    'rest_framework.authtoken',
]

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

# Middleware
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'wama.urls'

# Templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR / 'wama' / 'templates',
            BASE_DIR / 'wama' / 'anonymizer' / 'templates',
            BASE_DIR / 'wama' / 'accounts' / 'templates',
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'wama.accounts.views.login_form',
                'wama.accounts.context_processors.user_role',
            ],
        },
    },
]

WSGI_APPLICATION = 'wama.wsgi.application'

# Validation des mots de passe
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalisation
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Europe/Paris'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Authentication
LOGIN_URL = '/'  # Rediriger vers la page d'accueil au lieu de /accounts/login/
LOGIN_REDIRECT_URL = '/anonymizer/'  # Après login, aller vers Anonymizer

# Session configuration
SESSION_COOKIE_AGE = 86400 * 7  # 7 jours (en secondes)
# SESSION_SAVE_EVERY_REQUEST = True  # Renouveler la session à chaque requête
SESSION_EXPIRE_AT_BROWSER_CLOSE = False  # La session persiste même après fermeture du navigateur
SESSION_COOKIE_HTTPONLY = True  # Protection contre XSS
SESSION_COOKIE_SAMESITE = 'Lax'  # Protection CSRF
SESSION_COOKIE_NAME = 'wama_sessionid'  # Nom personnalisé pour éviter les conflits

# Fichiers statiques et médias
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'wama' / 'static',
    BASE_DIR / 'wama' / 'common' / 'static',
    BASE_DIR / 'wama' / 'anonymizer' / 'static',
    BASE_DIR / 'wama' / 'synthesizer' / 'static',
    BASE_DIR / 'wama' / 'transcriber' / 'static',
]

# Configuration Celery (optionnelle)
if ENABLE_CELERY:
    CELERY_TIMEZONE = "Europe/Paris"
    CELERY_TASK_TRACK_STARTED = True
    CELERY_BROKER_URL = "redis://127.0.0.1:6379/0"
    CELERY_RESULT_BACKEND = "redis://127.0.0.1:6379/1"
    CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}  # 1h
    CELERY_ACCEPT_CONTENT = ['application/json']
    CELERY_TASK_SERIALIZER = 'json'
    CELERY_RESULT_SERIALIZER = 'json'

    # Queue routing: GPU-heavy tasks → 'gpu' queue, light tasks → 'default'
    CELERY_TASK_ROUTES = {
        'wama.anonymizer.tasks.*': {'queue': 'gpu'},
        'wama.imager.tasks.*': {'queue': 'gpu'},
        'wama.enhancer.tasks.*': {'queue': 'gpu'},
        'wama.synthesizer.workers.*': {'queue': 'gpu'},
        'wama.transcriber.workers.*': {'queue': 'gpu'},
        'wama.describer.workers.*': {'queue': 'gpu'},
        'wama.avatarizer.workers.*': {'queue': 'gpu'},
        'wama.reader.tasks.*': {'queue': 'gpu'},
        'wama.composer.tasks.*': {'queue': 'gpu'},
        'wama_lab.face_analyzer.tasks.*': {'queue': 'gpu'},
        'wama_lab.cam_analyzer.tasks.*': {'queue': 'gpu'},
        'wama.model_manager.tasks.*': {'queue': 'default'},
    }
    CELERY_TASK_DEFAULT_QUEUE = 'default'

    # Logging : les loggers wama.* propagent vers le handler Celery (logfile)
    # worker_hijack_root_logger=True (défaut) → Celery prend en charge le root logger
    # On s'assure que les loggers WAMA ne désactivent pas la propagation
    CELERY_WORKER_HIJACK_ROOT_LOGGER = True
    CELERY_WORKER_REDIRECT_STDOUTS = True
    CELERY_WORKER_REDIRECT_STDOUTS_LEVEL = 'INFO'

# =============================================================================
# DESCRIBER — Intelligent LLM model selection
# =============================================================================
# Models are chosen per tier based on content type and output format.
# Tier routing (see llm_utils.get_describer_model):
#   image   → multimodal vision model (used directly by Ollama /api/generate)
#   heavy   → meeting notes, scientific analysis, coherence verification
#   default → standard descriptions (detailed, audio, video)
#   fast    → quick summary, bullet_points
#
# Override any tier here; all fallback to 'default' if the key is absent.
DESCRIBER_LLM_MODELS = {
    'image':   os.environ.get('DESCRIBER_MODEL_IMAGE',   'moondream'),
    'heavy':   os.environ.get('DESCRIBER_MODEL_HEAVY',   'qwen3.5:9b'),
    'default': os.environ.get('DESCRIBER_MODEL_DEFAULT', 'qwen3.5:9b'),
    'fast':    os.environ.get('DESCRIBER_MODEL_FAST',    'qwen3.5:4b'),
}

# TTS Microservice URL (FastAPI service for preloaded TTS models)
TTS_SERVICE_URL = os.environ.get('TTS_SERVICE_URL', 'http://localhost:8001')

# Ollama host (AI Assistant on the home page)
# If WAMA runs in WSL2 and Ollama runs on Windows, point this to the Windows IP:
#   export OLLAMA_HOST=http://REDACTED_HOST_IP:11434
OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')

# Anthropic API Configuration (for AI Chat feature)
# Set your API key here or use ANTHROPIC_API_KEY environment variable
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', None)

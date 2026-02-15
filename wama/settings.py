import os, logging, socket
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Fonctionnalités conditionnelles
ENABLE_CELERY = True
APPEND_SLASH = True
ENABLE_LDAP = False
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
    },
    # Diffusion models (image/video generation)
    'diffusion': {
        'root': AI_MODELS_DIR / "models" / "diffusion",
        'wan': AI_MODELS_DIR / "models" / "diffusion" / "wan",
        'hunyuan': AI_MODELS_DIR / "models" / "diffusion" / "hunyuan",
        'stable_diffusion': AI_MODELS_DIR / "models" / "diffusion" / "stable-diffusion",
    },
    # Vision-Language models (BLIP, LLaVA, etc.)
    'vision_language': {
        'root': AI_MODELS_DIR / "models" / "vision-language",
        'blip': AI_MODELS_DIR / "models" / "vision-language" / "blip",
        'bart': AI_MODELS_DIR / "models" / "vision-language" / "bart",
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

# Anonymizer media paths
MEDIA_INPUT_URL = '/media/anonymizer/input'
MEDIA_INPUT_ROOT = MEDIA_ROOT / 'anonymizer' / 'input'
MEDIA_OUTPUT_URL = '/media/anonymizer/output'
MEDIA_OUTPUT_ROOT = MEDIA_ROOT / 'anonymizer' / 'output'

# Clé secrète & débogage
SECRET_KEY = 'REDACTED_SECRET_KEY'
ALLOWED_HOSTS = ['*']

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
    'wama.model_manager',  # AI Models Manager
    # WAMA Lab - Experimental/Research applications
    'wama_lab.face_analyzer',
    'wama_lab.cam_analyzer',
]

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
TIME_ZONE = 'UTC'
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
    CELERY_TIMEZONE = "UTC"
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
        'wama_lab.face_analyzer.tasks.*': {'queue': 'gpu'},
        'wama_lab.cam_analyzer.tasks.*': {'queue': 'gpu'},
        'wama.model_manager.tasks.*': {'queue': 'default'},
    }
    CELERY_TASK_DEFAULT_QUEUE = 'default'

# TTS Microservice URL (FastAPI service for preloaded TTS models)
TTS_SERVICE_URL = os.environ.get('TTS_SERVICE_URL', 'http://localhost:8001')

# Anthropic API Configuration (for AI Chat feature)
# Set your API key here or use ANTHROPIC_API_KEY environment variable
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', None)

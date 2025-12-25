import os, logging, socket
from pathlib import Path


# Fonctionnalités conditionnelles
ENABLE_CELERY = True
APPEND_SLASH = True
ENABLE_LDAP = True
DEBUG = True

# Répertoires de base
BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_ROOT = BASE_DIR / "anonymizer" / "models"
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Anonymizer media paths
MEDIA_INPUT_URL = '/media/anonymizer/inputs'
MEDIA_INPUT_ROOT = MEDIA_ROOT / 'anonymizer' / 'inputs'
MEDIA_OUTPUT_URL = '/media/anonymizer/outputs'
MEDIA_OUTPUT_ROOT = MEDIA_ROOT / 'anonymizer' / 'outputs'

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
    'wama.synthesizer',
    'wama.transcriber',
    'wama.imager',
    'wama.enhancer',     # AI Image/Video Upscaling
    'wama.filemanager',  # File browser sidebar
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

from pathlib import Path
import logging
import socket


# Fonctionnalités conditionnelles
ENABLE_LDAP = True
ENABLE_CELERY = False

# Répertoires de base
BASE_DIR = Path(__file__).resolve().parent.parent

# Clé secrète & débogage
SECRET_KEY = 'REDACTED_SECRET_KEY'
DEBUG = True
ALLOWED_HOSTS = ['*']

# Nom d'hôte machine
try:
    HOSTNAME = socket.gethostname()
except:
    HOSTNAME = 'localhost'

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
    'django_wysiwyg',
    'wama.accounts',
    'wama.medias',
    'anonymizer',
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
            BASE_DIR / 'wama' / 'medias' / 'templates',
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

# Base de données
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

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

# Fichiers statiques et médias
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'wama' / 'static',
    BASE_DIR / 'wama' / 'medias' / 'static',
]

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_INPUT_URL = '/media/input_media'
MEDIA_INPUT_ROOT = MEDIA_ROOT / 'input_media'
MEDIA_OUTPUT_URL = '/media/output_media'
MEDIA_OUTPUT_ROOT = MEDIA_ROOT / 'output_media'

# Configuration Celery (optionnelle)
if ENABLE_CELERY:
    CELERY_TIMEZONE = "UTC"
    CELERY_TASK_TRACK_STARTED = True
    CELERY_RESULT_BACKEND = 'django-db'
    CELERY_BROKER_URL = 'redis://127.0.0.1:6379'
    CELERY_ACCEPT_CONTENT = ['application/json']
    CELERY_TASK_SERIALIZER = 'json'
    CELERY_RESULT_SERIALIZER = 'json'

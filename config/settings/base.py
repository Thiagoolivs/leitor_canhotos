"""
Base Django settings for leitor_canhotos project.

Architecture decisions:
- python-decouple is used for all environment variable access, keeping
  secrets out of version control.
- Service Layer + Repository patterns are used; models only contain data
  structure, business logic lives in services/, database access in repositories/.
- Celery handles asynchronous OCR processing so web requests are not blocked.
- Watchdog (in monitoring/) monitors the scanner input folder for new PDFs.
- WhiteNoise serves static files efficiently without a separate nginx in development.
"""
import json
import os
from pathlib import Path

from decouple import config, Csv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ==============================================================================
# CORE DJANGO SETTINGS
# ==============================================================================

SECRET_KEY = config('SECRET_KEY', default='django-insecure-dev-key-change-in-production')

DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

# ==============================================================================
# INSTALLED APPS
# ==============================================================================

DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'django_filters',
]

LOCAL_APPS = [
    'apps.notas.apps.NotasConfig',
    'apps.canhotos.apps.CanhotosConfig',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ==============================================================================
# MIDDLEWARE
# ==============================================================================

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Serve static files efficiently
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

# ==============================================================================
# TEMPLATES
# ==============================================================================

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ==============================================================================
# DATABASE
# ==============================================================================

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='leitor_canhotos'),
        'USER': config('DB_USER', default='leitor_canhotos'),
        'PASSWORD': config('DB_PASSWORD', default='leitor2024'),
        'HOST': config('DB_HOST', default='db'),
        'PORT': config('DB_PORT', default='5432'),
        'CONN_MAX_AGE': 60,
        'OPTIONS': {
            'connect_timeout': 10,
        },
    }
}

# ==============================================================================
# CACHE (Redis)
# ==============================================================================

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': config('REDIS_URL', default='redis://redis:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'SOCKET_CONNECT_TIMEOUT': 5,
            'SOCKET_TIMEOUT': 5,
        }
    }
}

SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# ==============================================================================
# CELERY
# ==============================================================================

CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://redis:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://redis:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'America/Sao_Paulo'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300  # 5 minutes max per OCR task
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # One task at a time per worker
CELERY_ACKS_LATE = True  # Acknowledge task only after completion

# ==============================================================================
# PASSWORD VALIDATION
# ==============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ==============================================================================
# INTERNATIONALIZATION
# ==============================================================================

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

# ==============================================================================
# STATIC FILES (CSS, JavaScript, Images)
# WhiteNoise is used to serve static files without nginx in development.
# ==============================================================================

STATIC_URL = '/static/'
STATIC_ROOT = config('STATIC_ROOT', default=str(BASE_DIR / 'staticfiles'))
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ==============================================================================
# MEDIA FILES (Uploaded canhotos PDFs/images)
# ==============================================================================

MEDIA_URL = '/media/'
MEDIA_ROOT = config('MEDIA_ROOT', default=str(BASE_DIR / 'media'))

# ==============================================================================
# DEFAULT PRIMARY KEY
# ==============================================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ==============================================================================
# SCANNER CONFIGURATION
# Directories used by the watchdog monitor and OCR tasks.
# ==============================================================================

def _parse_scanner_dirs(value: str) -> list:
    """Parse SCANNER_INPUT_DIRS: comma-separated string or JSON array."""
    if not value:
        return ['/entrada_canhotos']
    value = value.strip()
    if value.startswith('['):
        return json.loads(value)
    return [d.strip() for d in value.split(',') if d.strip()]


SCANNER_INPUT_DIRS = _parse_scanner_dirs(
    config('SCANNER_INPUT_DIRS', default='/entrada_canhotos')
)
SCANNER_PROCESSED_DIR = config('SCANNER_PROCESSED_DIR', default='/processados')
SCANNER_ERROR_DIR = config('SCANNER_ERROR_DIR', default='/erro')

# Tesseract executable path (overridable via env for Windows)
import pytesseract as _pytesseract
_tesseract_cmd = config('TESSERACT_CMD', default='tesseract')
_pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd

# Poppler path for pdf2image (needed on Windows)
POPPLER_PATH = config('POPPLER_PATH', default=None) or None

# Regex patterns for extracting Brazilian invoice (Nota Fiscal) numbers from OCR text.
# Ordered from most specific to least specific to minimize false positives.
NOTA_NUMBER_PATTERNS = [
    r'NOTA\s+FISCAL\s+(?:ELETR[OÔ]NICA\s+)?N[Oo°\.º]?\s*:?\s*(\d{1,6})',
    r'N[Oo°\.º]\s*:?\s*(\d{1,6})',
    r'NF\s*[-:]\s*(\d{1,6})',
    r'N[ÚúUu]MERO\s*(?:DA\s+NOTA)?\s*:?\s*(\d{1,6})',
    r'(?:^|\s)(\d{6})(?:\s|$)',
]

# ==============================================================================
# LOGGING
# Structured log format: timestamp | level | module | message
# Handlers: rotating file in logs/ and console output.
# ==============================================================================

# Ensure log directory exists before Django tries to open log files
_LOGS_DIR = Path(config('LOGS_DIR', default=str(BASE_DIR / 'logs')))
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'structured': {
            'format': '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'simple': {
            'format': '%(levelname)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'structured',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(config('LOGS_DIR', default=str(BASE_DIR / 'logs')), 'leitor_canhotos.log'),
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 5,
            'formatter': 'structured',
        },
        'error_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(config('LOGS_DIR', default=str(BASE_DIR / 'logs')), 'errors.log'),
            'maxBytes': 10 * 1024 * 1024,  # 10 MB
            'backupCount': 5,
            'formatter': 'structured',
            'level': 'ERROR',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'file', 'error_file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console', 'file', 'error_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'services': {
            'handlers': ['console', 'file', 'error_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'tasks': {
            'handlers': ['console', 'file', 'error_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'monitoring': {
            'handlers': ['console', 'file', 'error_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'repositories': {
            'handlers': ['console', 'file', 'error_file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'celery': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

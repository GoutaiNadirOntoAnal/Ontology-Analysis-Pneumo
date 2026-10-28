"""
Django settings for mypfe project.
Production/cPanel safe version.
"""

from pathlib import Path
import os
import logging

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret.
# Valeur reprise depuis ton settings.py actuel.
SECRET_KEY = 'django-insecure-)oe0+u180ve%rp4u8b6-zoq3s!_3l-1@dj*0-z^m-mw(0d7+=2'

DEBUG = False

ALLOWED_HOSTS = [
    "ontologyanalysis.com",
    "www.ontologyanalysis.com",
    "localhost",
    "127.0.0.1",
]

# Reduce noisy logs in cPanel stderr.log
logging.getLogger("PyRuSH").setLevel(logging.ERROR)
logging.getLogger("medspacy").setLevel(logging.ERROR)
logging.getLogger("spacy").setLevel(logging.ERROR)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'hopital',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'mypfe.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'hopital.context_processors.medecin_context',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'mypfe.wsgi.application'

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(BASE_DIR / "mydatabase"),
        "OPTIONS": {
            "timeout": 20,
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Africa/Algiers'

USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = "/home/ontolo54/public_html/static"

STATICFILES_DIRS = [
    "/home/ontolo54/mypfe1/static",
]

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/login/'

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ontology-analysis-cache",
        "TIMEOUT": 3600,
        "OPTIONS": {
            "MAX_ENTRIES": 300,
        },
    }
}

CSRF_TRUSTED_ORIGINS = [
    "https://ontologyanalysis.com",
    "https://www.ontologyanalysis.com",
]

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
X_FRAME_OPTIONS = "DENY"

# Si ton site marche bien en HTTPS, tu peux activer ces 2 lignes.
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True

"""Projet master de mehalli chourouk"""

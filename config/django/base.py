import os

from decimal import Decimal
from config.env import BASE_DIR, env

env.read_env(os.path.join(BASE_DIR, '.env'))

# Django 4.x required setting
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY', default='test-secret-key')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool('DEBUG', False)

ALLOWED_HOSTS = ['*']

# Application definition

DJANGO_APPS = [
    'daphne',
    'whitenoise.runserver_nostatic',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.admin',
    'django.contrib.humanize',
]

THRID_PARTY_APPS = [
    'corsheaders',
    'django_filters',
    'django_celery_beat',
    'django_redis',
    'channels',
]

LOCAL_APPS = [
    'users',
    'common',
    'app'
]

INSTALLED_APPS = DJANGO_APPS + THRID_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'compression_middleware.middleware.CompressionMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': False,
        'OPTIONS': {
            'loaders': [
                (
                    'django.template.loaders.cached.Loader',
                    [
                        'django.template.loaders.filesystem.Loader',
                        'django.template.loaders.app_directories.Loader',
                    ],
                )
            ],
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.i18n',
                'django.template.context_processors.static',
                'django.template.context_processors.tz',
            ]
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'


PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 8,
        }
    },
]

AUTH_USER_MODEL = 'users.User'

# Login/Logout URLs
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

CORS_URLS_REGEX = r'^/api/.*$'

# Allow CORS from local Next.js dev servers
try:
    from config.env import env as _env
except Exception:  # pragma: no cover
    _env = None  # type: ignore

CORS_ALLOWED_ORIGINS = (
    _env.list('CORS_ALLOWED_ORIGINS', default=[
        'http://localhost:3000',
        'http://127.0.0.1:3000',
        'http://localhost:3001',
        'http://127.0.0.1:3001',
    ]) if _env else [
        'http://localhost:3000',
        'http://127.0.0.1:3000',
        'http://localhost:3001',
        'http://127.0.0.1:3001',
    ]
)

# If you rely on cookies or Authorization header across origins
CORS_ALLOW_CREDENTIALS = True

# Trusted origins for CSRF (required by Django 4+ when using cookies on cross-origin)
CSRF_TRUSTED_ORIGINS = (
    _env.list('CSRF_TRUSTED_ORIGINS', default=[
        'http://localhost:3000',
        'http://127.0.0.1:3000',
        'http://localhost:3001',
        'http://127.0.0.1:3001',
    ]) if _env else [
        'http://localhost:3000',
        'http://127.0.0.1:3000',
        'http://localhost:3001',
        'http://127.0.0.1:3001',
    ]
)
LANGUAGE_CODE = 'id-id'

TIME_ZONE = 'Asia/Jakarta'

USE_I18N = True

USE_L10N = True

USE_TZ = True  # Changed to True for Django 4.x best practices

ADMIN_URL = "admin/"

ADMINS = [("""Admin Dashboard""", "m.hdafi89@gmail.com")]

MANAGERS = ADMINS

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = str(BASE_DIR / 'staticfiles')
# STATICFILES_DIRS = [str(BASE_DIR / 'assets')]

STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]

MEDIA_URL = '/media/'
MEDIA_ROOT = str(BASE_DIR / 'media_cdn')

# STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

import re

# http://whitenoise.evans.io/en/stable/django.html#WHITENOISE_IMMUTABLE_FILE_TEST

def immutable_file_test(path, url): # type: ignore
    # Match vite (rollup)-generated hashes, à la, `some_file-CSliV9zW.js`
    return re.match(r"^.+[.-][0-9a-zA-Z_-]{8,12}\..+$", url)

WHITENOISE_IMMUTABLE_FILE_TEST = immutable_file_test

from config.settings.celery import *
from config.settings.cache import *
# from config.settings.drf import *
from config.settings.logging import *
from config.settings.s3 import *
from config.settings.email import *

# Provide safe defaults for API keys and external services to avoid ImproperlyConfigured during tests
OPENAI_API_KEY = env('OPENAI_API_KEY', default='')
AIMLAPI_KEY = env('AIMLAPI_KEY', default='')
ANTHROPIC_API_KEY = env('ANTHROPIC_API', default='')
MINIMAX_API_KEY = env('MINIMAX_API_KEY', default='')
DEEPSEEK_API_KEY = env('DEEPSEEK_API_KEY', default='')
GOOGLE_API_KEY = env('GOOGLE_API_KEY', default='')
APIFY_API_KEY = env('APIFY_API_KEY', default='')
REPLICATE_API_KEY = env('REPLICATE_API_KEY', default='')
SERPER_API_KEY = env('SERPER_API_KEY', default='')
BRAVE_API_KEY = env('BRAVE_API_KEY', default='')
LARASANA_API_BASE = env('LARASANA_API_BASE', default='')
LARASANA_API_KEY = env('LARASANA_API_KEY', default='')
DAYTONA_API_KEY = env('DAYTONA_API_KEY', default='')
DAYTONA_API_URL = env('DAYTONA_API_URL', default='')
CLERK_JWKS_URL = env('CLERK_JWKS_URL', default=None)
CLERK_ISSUER = env('CLERK_ISSUER', default=None)
CLERK_AUDIENCE = env('CLERK_AUDIENCE', default=None)
CLERK_WEBHOOK_SECRET = env('CLERK_WEBHOOK_SECRET', default=None)

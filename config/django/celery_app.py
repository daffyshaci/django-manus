import os
from config.env import BASE_DIR, env

env.read_env(os.path.join(BASE_DIR, '.env'))

# Django 4.x required setting
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool('DEBUG', False)

# Minimal hosts for Celery (tidak perlu expose web)
ALLOWED_HOSTS = [env("HOST")]

# Application definition - MINIMAL untuk Celery
# Hanya apps yang diperlukan untuk Celery tasks
DJANGO_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
]

THRID_PARTY_APPS = [
    'django_celery_beat',  # Untuk scheduled tasks
    'django_redis',        # Untuk cache/broker
    'channels',
]

from .base import LOCAL_APPS

INSTALLED_APPS = DJANGO_APPS + THRID_PARTY_APPS + LOCAL_APPS

# MIDDLEWARE - MINIMAL untuk Celery (tidak ada web requests)
# Celery tidak memerlukan middleware karena tidak handle HTTP requests
MIDDLEWARE = []

# Password hashers tetap diperlukan jika Celery tasks menggunakan User authentication
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

# Authentication backends mungkin diperlukan jika tasks menggunakan User models
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]

# User model tetap diperlukan
AUTH_USER_MODEL = 'users.User'

# Localization settings
LANGUAGE_CODE = 'id-id'
TIME_ZONE = 'Asia/Jakarta'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Database tetap diperlukan untuk Celery tasks
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': env('DB_NAME'),
        'USER': env('DB_USERNAME'),
        'PASSWORD': env('DB_PASSWORD'),
        'HOST': env('DB_HOST'),
        'PORT': env('DB_PORT')
    }
}

# Import setting yang diperlukan untuk Celery
from config.settings.celery import *
from config.settings.cache import *

# API Keys tetap diperlukan jika Celery tasks menggunakan external APIs
OPENAI_API_KEY = env('OPENAI_API_KEY')
AIMLAPI_KEY = env('AIMLAPI_KEY')
ANTHROPIC_API_KEY = env('ANTHROPIC_API')
MINIMAX_API_KEY = env('MINIMAX_API_KEY')
DEEPSEEK_API_KEY = env('DEEPSEEK_API_KEY')
GOOGLE_API_KEY = env('GOOGLE_API_KEY')
APIFY_API_KEY = env('APIFY_API_KEY')
REPLICATE_API_KEY = env('REPLICATE_API_KEY')
SERPER_API_KEY = env('SERPER_API_KEY')
BRAVE_API_KEY = env('BRAVE_API_KEY')
LARASANA_API_BASE = env('LARASANA_API_BASE')
LARASANA_API_KEY = env('LARASANA_API_KEY')

# Business logic constants tetap diperlukan jika digunakan dalam tasks
from decimal import Decimal
VALUE_PER_CREDIT_USD = Decimal('0.001')
USD_TO_IDR_RATE = Decimal('17000')
CREDIT_CONVERSION_FACTOR = 1000000
MARKUP_PERCENTAGE = Decimal('1.20')

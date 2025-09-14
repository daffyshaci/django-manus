from .base import *
from config.env import env

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool('DEBUG', False)

ALLOWED_HOSTS = [env("HOST")]
# CSRF settings for production deployment
CSRF_TRUSTED_ORIGINS = [
    f"https://{env('HOST')}",
    f"http://{env('HOST')}",
]
# PREPEND_WWW = True
# DEBUG_PROPAGATE_EXCEPTIONS = False

SESSION_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_SECONDS = 31536000
# SECURE_REDIRECT_EXEMPT = []
# SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_COOKIE_SECURE = True
MIDTRANS_SNAP_URL = env('MIDTRANS_SNAP_URL')
MIDTRANS_SERVER_URL = env('MIDTRANS_SERVER_URL')
MIDTRANS_SERVER_KEY = env('MIDTRANS_SERVER_KEY')
MIDTRANS_CLIENT_KEY = env('MIDTRANS_CLIENT_KEY')
MIDTRANS_IS_PRODUCTION = True

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


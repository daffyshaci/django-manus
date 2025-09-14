from datetime import timedelta
from config.env import env

REST_FRAMEWORK = {
    'EXCEPTION_HANDLER': 'core.common.exceptions.common_exception_handler',
    'NON_FIELD_ERROR_KEY': 'error',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        # 'core.common.authentication.HybridAuthentication',  # Support both API keys and existing auth
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',

    ],
    'DEFAULT_THROTTLE_RATES': {
        'unauthenticated': '1/minute',
        'authenticated': '100/minute',
        'api_key': '1000/hour'  # Higher rate limit for API key users
    },
    # Ensure drf-spectacular is used for schema generation
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SIMPLE_JWT = {
    'AUTH_HEADER_TYPES': (
        'Bearer',
        'JWT'
    ),
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'SIGNING_KEY': env('SIGNING_KEY'),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
}

DJOSER = {
    "LOGIN_FIELD": "email",
    "USER_CREATE_PASSWORD_RETYPE": True,
    "USERNAME_CHANGED_EMAIL_CONFIMATION": False,
    "PASSWORD_CHANGED_EMAIL_CONFIRMATION": False,
    "SEND_CONFIRMATION_EMAIL": False,
    "PASSWORD_RESET_CONFIRM_URL": "password/reset/confirm/{uid}/{token}",
    "SET_PASSWORD_RETYPE": True,
    "SET_EMAIL_RETYPE": True,
    "PASSWORD_RESET_CONFIRM_RETYPE": True,
    "USERNAME_RESET_CONFIRM_URL": "email/reset/confirm/{uid}/{token}",
    "ACTIVATION_URL": "activate/{uid}/{token}",
    "SEND_ACTIVATION_EMAIL": False,
    "SERIALIZERS": {
        "user_create": "core.users.serializers.CreateUserSerializer",
        "user": "core.users.serializers.UserSerializer",
        "current_user": "core.users.serializers.UserSerializer",
        "user_delete": "djoser.serializers.UserDeleteSerializer",
    },
    # 'EMAIL': {
    #     'activation': 'core.users.emails.CustomActivationEmail',
    #     'confirmation': 'core.users.emails.CustomConfirmationEmail',
    #     'password_reset': 'core.users.emails.CustomAPasswordResetEmail',
    #     'password_changed_confirmation': 'core.users.emails.CustomPasswordChangedConfirmationEmail',
    #     # 'username_changed_confirmation': 'path.to.your.custom.UsernameChangedConfirmationEmail',
    #     # 'username_reset': 'path.to.your.custom.UsernameResetEmail',
    # },
}

# DRF Spectacular settings (replacement for drf-yasg)
SPECTACULAR_SETTINGS = {
    'TITLE': 'Larasana API',
    'DESCRIPTION': 'API documentation for Larasana APP',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SCHEMA_PATH_PREFIX': r'/api/v[0-9]',
}

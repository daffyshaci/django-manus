from config.env import env

CHANNEL_LAYERS = {
    'default' : {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [env('CELERY_BROKER_URL')],
            'symmetric_encryption_keys': [env('SECRET_KEY')],
            'capacity': 1500,  # Default: 100
            'expiry': 60,  # Default: 60 seconds
        },
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': str(env('CELERY_BROKER_URL')),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 50,
                'socket_keepalive': True,
                'socket_keepalive_options': {},
            },
        },
    }
}

CACHE_TTL = 60 * 15

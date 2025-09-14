from config.env import env


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,

    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
        # 'request_data_filter': {
        #     # Filter ini akan menambahkan informasi request ke log record
        #     '()': 'core.common.log_filters.RequestDataFilter',
        # }
    },

    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}\n'
                      'Path: {path}\nMethod: {method}\nUser: {user}\n\n',
            'style': '{',
        },
        'automation_formatter': {
            'format': '{levelname} {asctime} {name} {message}',
            'style': '{',
        },
    },

    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
        },
        # 'db_log': {
        #     'level': 'WARNING',
        #     'class': 'core.common.db_log_handler.DatabaseLogHandler',
        #     'filters': ['request_data_filter'],
        # }
    },

    'loggers': {
        'django.request': {
            'handlers': [],  # Tidak ada handler
            'level': 'ERROR', # Hanya proses jika ada error fatal (yang jarang terjadi)
            'propagate': False, # Pastikan tidak merambat ke mana-mana
        },
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
}

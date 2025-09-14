from config.env import env


EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp-pulse.com' #env('EMAIL_HOST')
EMAIL_PORT = 587 #env('EMAIL_PORT')
DEFAULT_FROM_EMAIL = 'support@kontenai.com'
EMAIL_USE_SSL = False
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'novitayudar89@gmail.com' #env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = 'P5fM5gjrcat6sK'

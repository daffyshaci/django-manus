from config.env import env
from celery.schedules import crontab

CELERY_BROKER_URL = env('CELERY_BROKER_URL')
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TIMEZONE = 'Asia/Jakarta'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_DEFAULT_QUEUE = 'default'
CELERY_WORKER_CONCURRENCY = 1000
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ACKS_LATE = False
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1000
CELERY_TASK_SOFT_TIME_LIMIT = 300
CELERY_TASK_TIME_LIMIT = 360

CELERY_BEAT_SCHEDULE = {
    # 'cleanup-anonymous-conversations-every-night': {
    #     'task': 'core.generation.tasks.cleanup_anonymous_conversations',
    #     # Jalankan setiap hari pada jam 2 pagi
    #     'schedule': crontab(minute=0, hour=2),
    # },
    # 'cleanup-unsaved-conversations-daily': {
    #     'task': 'core.generation.tasks_cleanup.cleanup_unsaved_conversations',
    #     # Jalankan setiap hari pada jam 3 pagi
    #     'schedule': crontab(minute=0, hour=3),
    # },
    # 'cleanup-marked-conversations-daily': {
    #     'task': 'core.generation.tasks_cleanup.cleanup_marked_conversations',
    #     # Jalankan setiap hari pada jam 4 pagi
    #     'schedule': crontab(minute=0, hour=4),
    # },
    # 'cleanup-orphaned-messages-weekly': {
    #     'task': 'core.generation.tasks_cleanup.cleanup_orphaned_messages',
    #     # Jalankan setiap minggu pada hari Senin jam 5 pagi
    #     'schedule': crontab(minute=0, hour=5, day_of_week=1),
    # },
}

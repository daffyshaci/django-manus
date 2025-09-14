from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


class StaticStorage(S3Boto3Storage):
    location = 'static'
    file_overwrite = True

class PublicMediaStorage(S3Boto3Storage):
    location = 'media'
    file_overwrite = True
    # default_acl = 'public-read'
    # custom_domain = f"settings.AWS_S3_ENDPOINT_URL.split('://')[-1]"
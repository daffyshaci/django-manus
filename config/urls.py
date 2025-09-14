
from django.contrib import admin
from django.urls import path, include, URLPattern, URLResolver
from django.conf import settings
from django.conf.urls.static import static
from .api import api
from typing import List, Union


urlpatterns: List[Union[URLPattern, URLResolver]] = [
    path('admin/', admin.site.urls),

    path("", include("users.urls")),
    path("", include("app.urls")),
    path("api/", api.urls)
]

if settings.DEBUG:
    urlpatterns.extend(static(settings.STATIC_URL,
                             document_root=settings.STATIC_ROOT))
    urlpatterns.extend(static(settings.MEDIA_URL,
                             document_root=settings.MEDIA_ROOT))

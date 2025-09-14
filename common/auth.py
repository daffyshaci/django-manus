from ninja.security import APIKeyCookie
from django.http import HttpRequest
from typing import Optional, Any
from django.contrib.auth import get_user as django_get_user
from asgiref.sync import sync_to_async


class AsyncSessionAuth(APIKeyCookie):
    param_name = "sessionid"

    async def __call__(self, request: HttpRequest) -> Optional[Any]:
        user = await sync_to_async(django_get_user)(request)
        if user and user.is_authenticated:
            return user
        return None

    def authenticate(self, request: HttpRequest, key: str) -> Optional[Any]:
        pass
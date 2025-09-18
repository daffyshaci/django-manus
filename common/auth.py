from ninja.security import APIKeyCookie
from django.http import HttpRequest
from typing import Optional, Any
from django.contrib.auth import get_user as django_get_user
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
import jwt
from jwt import PyJWKClient
from common.models import ClerkIdentity
import logging

logger = logging.getLogger(__name__)


class AsyncSessionAuth(APIKeyCookie):
    param_name = "sessionid"

    async def __call__(self, request: HttpRequest) -> Optional[Any]:
        user = await sync_to_async(django_get_user)(request)
        if user and user.is_authenticated:
            return user
        return None

    def authenticate(self, request: HttpRequest, key: str) -> Optional[Any]:
        pass


# Helper (sync) to ensure user exists based on Clerk claims

def _ensure_user_from_clerk_claims(claims):
    User = get_user_model()
    clerk_user_id = claims.get("sub")
    if not clerk_user_id:
        return None

    email = claims.get("email")
    first_name = claims.get("given_name") or claims.get("first_name")
    last_name = claims.get("family_name") or claims.get("last_name")

    # Derive username (users.User requires unique username)
    base_username = None
    if email:
        base_username = email.split("@")[0]
    else:
        base_username = f"clerk_{clerk_user_id[:12]}"

    with transaction.atomic():
        identity = ClerkIdentity.objects.select_related("user").filter(
            clerk_user_id=clerk_user_id
        ).first()
        if identity:
            user = identity.user
            # Optional: keep profile in sync
            updated = False
            if email and user.email != email:
                user.email = email
                updated = True
            if first_name and user.first_name != first_name:
                user.first_name = first_name
                updated = True
            if last_name and user.last_name != last_name:
                user.last_name = last_name
                updated = True
            if updated:
                user.save(update_fields=["email", "first_name", "last_name"])  # type: ignore
            return user

        # Create user if identity not found
        # Ensure unique username
        username = base_username
        suffix = 0
        while User.objects.filter(username=username).exists():
            suffix += 1
            username = f"{base_username}{suffix}"

        # Ensure email exists (fallback placeholder if missing)
        if not email:
            email = f"{username}@example.invalid"

        user = User.objects.create(
            email=email,
            username=username,
            is_active=True,
        )
        try:
            user.set_unusable_password()
            user.first_name = first_name or ""
            user.last_name = last_name or ""
            user.save()
        except Exception:
            # In case set_unusable_password not available or custom manager logic differs
            pass

        ClerkIdentity.objects.create(
            user=user,
            clerk_user_id=clerk_user_id,
            email=email,
            first_name=first_name or "",
            last_name=last_name or "",
        )
        return user


class AsyncClerkJWTAuth:
    async def __call__(self, request: HttpRequest) -> Optional[Any]:
        try:
            auth_header = request.headers.get("Authorization") or ""
            if not auth_header:
                logger.debug("[ClerkJWTAuth] Missing Authorization header")
            if not auth_header.lower().startswith("bearer "):
                return None

            token = auth_header.split(" ", 1)[1].strip()
            jwks_url = getattr(settings, "CLERK_JWKS_URL", None)
            issuer = getattr(settings, "CLERK_ISSUER", None)
            audience = getattr(settings, "CLERK_AUDIENCE", None)
            if not (jwks_url and issuer and audience):
                logger.error(
                    "[ClerkJWTAuth] Missing config: jwks_url=%s issuer=%s audience=%s",
                    bool(jwks_url), bool(issuer), bool(audience)
                )
                return None

            jwks_client = PyJWKClient(jwks_url)
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=audience,
                issuer=issuer,
            )
            user = await sync_to_async(_ensure_user_from_clerk_claims)(claims)
            return user
        except Exception as e:
            # Try decode unverified to help diagnose mismatched iss/aud
            try:
                unverified = jwt.decode(token, options={"verify_signature": False, "verify_aud": False, "verify_iss": False})
            except Exception:
                unverified = {}
            iss_tok = unverified.get("iss") if isinstance(unverified, dict) else None
            aud_tok = unverified.get("aud") if isinstance(unverified, dict) else None
            logger.exception(
                "[ClerkJWTAuth] Failed to verify token: %s | expected iss=%s aud=%s | token iss=%s aud=%s",
                e, getattr(settings, "CLERK_ISSUER", None), getattr(settings, "CLERK_AUDIENCE", None), iss_tok, aud_tok
            )
            return None


class CombinedAuth:
    def __init__(self) -> None:
        self.clerk = AsyncClerkJWTAuth()
        self.session = AsyncSessionAuth()

    async def __call__(self, request: HttpRequest) -> Optional[Any]:
        user = await self.clerk(request)
        if user:
            return user
        return await self.session(request)
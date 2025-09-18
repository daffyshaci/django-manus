from urllib.parse import parse_qs
from typing import Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from asgiref.sync import sync_to_async
from common.models import ClerkIdentity
import jwt
from jwt import PyJWKClient


async def _get_or_create_user_from_claims(claims):
    User = get_user_model()
    clerk_user_id = claims.get("sub")
    if not clerk_user_id:
        return None

    email = claims.get("email")
    first_name = claims.get("given_name") or claims.get("first_name")
    last_name = claims.get("family_name") or claims.get("last_name")

    def _sync_op():
        from django.db import transaction
        with transaction.atomic():
            identity = ClerkIdentity.objects.select_related("user").filter(
                clerk_user_id=clerk_user_id
            ).first()
            if identity:
                user = identity.user
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

            base_username = email.split("@")[0] if email else f"clerk_{clerk_user_id[:12]}"
            username = base_username
            suffix = 0
            while User.objects.filter(username=username).exists():
                suffix += 1
                username = f"{base_username}{suffix}"
            if not email:
                email_local = f"{username}@example.invalid"
            else:
                email_local = email
            user = User.objects.create(email=email_local, username=username, is_active=True)
            try:
                user.set_unusable_password()
                user.first_name = first_name or ""
                user.last_name = last_name or ""
                user.save()
            except Exception:
                pass
            ClerkIdentity.objects.create(
                user=user,
                clerk_user_id=clerk_user_id,
                email=email_local,
                first_name=first_name or "",
                last_name=last_name or "",
            )
            return user

    return await sync_to_async(_sync_op)()


class ClerkJWTAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "websocket":
            return await self.inner(scope, receive, send)

        token: Optional[str] = None
        # Try query string first
        try:
            query = parse_qs(scope.get("query_string", b"").decode())
            t = query.get("token")
            if t:
                token = t[0]
        except Exception:
            token = None

        # Fallback to Authorization header if present
        if not token:
            for (name, value) in scope.get("headers", []):
                if name.lower() == b"authorization":
                    try:
                        v = value.decode()
                        if v.lower().startswith("bearer "):
                            token = v.split(" ", 1)[1].strip()
                    except Exception:
                        pass

        user = AnonymousUser()
        try:
            jwks_url = getattr(settings, "CLERK_JWKS_URL", None)
            issuer = getattr(settings, "CLERK_ISSUER", None)
            audience = getattr(settings, "CLERK_AUDIENCE", None)
            if token and jwks_url and issuer and audience:
                jwks_client = PyJWKClient(jwks_url)
                signing_key = jwks_client.get_signing_key_from_jwt(token)
                claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    audience=audience,
                    issuer=issuer,
                )
                u = await _get_or_create_user_from_claims(claims)
                if u:
                    user = u
        except Exception:
            # Leave as AnonymousUser on failure
            pass

        scope = dict(scope)
        scope["user"] = user
        return await self.inner(scope, receive, send)
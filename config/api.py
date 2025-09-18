from ninja import NinjaAPI
# from core.chat.api import router as chat_router
# from core.ai.api import router as ai_router
from app.api import router as app_router
from django.http import JsonResponse
from django.conf import settings
from django.contrib.auth import get_user_model
from common.models import ClerkIdentity
import base64, hmac, hashlib, time, json


# Initialize main API instance
api = NinjaAPI(
    title="Larasana v3 API",
    version="1.0.0",
    description="Comprehensive API for Larasana v3 platform including chat, AI, billing, and user management",
    docs_url="/docs/",
    openapi_url="/openapi.json"
)

# # Add chat router with versioning
api.add_router("/v1/chat", app_router, tags=["chat"])
# # Add AI router with versioning
# api.add_router("/v1/ai", ai_router, tags=["ai"])


@api.post("/clerk/webhooks")
def clerk_webhooks(request):
    secret = getattr(settings, "CLERK_WEBHOOK_SECRET", None)
    if not secret:
        return JsonResponse({"error": "Webhook secret not configured"}, status=400)

    try:
        raw_body = request.body  # bytes
        svix_id = request.headers.get("svix-id")
        svix_timestamp = request.headers.get("svix-timestamp")
        svix_signature = request.headers.get("svix-signature")
        if not (svix_id and svix_timestamp and svix_signature):
            return JsonResponse({"error": "Missing Svix headers"}, status=400)

        # Reject stale timestamps (>5 minutes)
        if abs(int(time.time()) - int(svix_timestamp)) > 60 * 5:
            return JsonResponse({"error": "Stale timestamp"}, status=400)

        # Signature verification (HMAC-SHA256 over f"{timestamp}.{body}")
        key_b64 = secret.split("whsec_")[-1]
        key = base64.b64decode(key_b64)
        to_sign = f"{svix_timestamp}.".encode() + raw_body
        calc_sig = base64.b64encode(hmac.new(key, to_sign, hashlib.sha256).digest()).decode()

        # Header might contain multiple signatures like "v1=...,v2=..."; accept if any matches
        provided_sigs = []
        for part in svix_signature.split(","):
            part = part.strip()
            if "=" in part:
                _, val = part.split("=", 1)
                provided_sigs.append(val)

        if calc_sig not in provided_sigs:
            return JsonResponse({"error": "Invalid signature"}, status=400)

        body = json.loads(raw_body.decode("utf-8"))
        event_type = body.get("type")
        data = body.get("data", {})
        clerk_user_id = data.get("id")
        if not clerk_user_id:
            return JsonResponse({"status": "ignored"}, status=200)

        # Extract primary email
        email = data.get("email")
        if not email:
            emails = data.get("email_addresses") or []
            primary_id = data.get("primary_email_address_id")
            primary_obj = None
            if primary_id and isinstance(emails, list):
                for e in emails:
                    if e.get("id") == primary_id:
                        primary_obj = e
                        break
            if not primary_obj and emails:
                primary_obj = emails[0]
            if primary_obj:
                email = primary_obj.get("email_address")

        first_name = data.get("first_name") or data.get("given_name")
        last_name = data.get("last_name") or data.get("family_name")

        User = get_user_model()
        if event_type in ("user.created", "user.updated"):
            identity = ClerkIdentity.objects.select_related("user").filter(
                clerk_user_id=clerk_user_id
            ).first()
            if identity:
                user = identity.user
                changed_fields = []
                if email and getattr(user, "email", None) != email:
                    user.email = email
                    changed_fields.append("email")
                if first_name is not None and hasattr(user, "first_name") and getattr(user, "first_name", None) != first_name:
                    user.first_name = first_name
                    changed_fields.append("first_name")
                if last_name is not None and hasattr(user, "last_name") and getattr(user, "last_name", None) != last_name:
                    user.last_name = last_name
                    changed_fields.append("last_name")
                if changed_fields:
                    user.save(update_fields=changed_fields)  # type: ignore
            else:
                base_username = email.split("@")[0] if email else f"clerk_{clerk_user_id[:12]}"
                username = base_username
                suffix = 0
                while User.objects.filter(username=username).exists():
                    suffix += 1
                    username = f"{base_username}{suffix}"
                email_local = email or f"{username}@example.invalid"
                user = User.objects.create(email=email_local, username=username, is_active=True)
                try:
                    if hasattr(user, "set_unusable_password"):
                        user.set_unusable_password()
                    if first_name is not None and hasattr(user, "first_name"):
                        user.first_name = first_name
                    if last_name is not None and hasattr(user, "last_name"):
                        user.last_name = last_name
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
        elif event_type in ("user.deleted", "user.blocked"):
            identity = ClerkIdentity.objects.select_related("user").filter(
                clerk_user_id=clerk_user_id
            ).first()
            if identity:
                user = identity.user
                if hasattr(user, "is_active"):
                    user.is_active = False
                    user.save(update_fields=["is_active"])  # type: ignore

        return JsonResponse({"status": "ok"}, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)

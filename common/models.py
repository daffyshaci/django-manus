import uuid
from django.db import models



class TimeStampedUUIDModel(models.Model):
    pkid = models.BigAutoField(primary_key=True, editable=False)
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at", "-updated_at"]


class ClerkIdentity(TimeStampedUUIDModel):
    user = models.OneToOneField(
        "users.User", on_delete=models.CASCADE, related_name="clerk_identity"
    )
    clerk_user_id = models.CharField(max_length=128, unique=True, db_index=True)
    email = models.EmailField(null=True, blank=True)
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.clerk_user_id} -> {self.user_id}"

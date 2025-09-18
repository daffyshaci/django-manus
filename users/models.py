import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .managers import CustomUserManager
 
class User(AbstractBaseUser, PermissionsMixin):
    pkid = models.BigAutoField(primary_key=True, editable=False)
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    username = models.CharField(verbose_name=_("username"), db_index=True, max_length=255, unique=True)
    first_name = models.CharField(verbose_name=_("first name"), max_length=50, null=True, blank=True)
    last_name = models.CharField(verbose_name=_("last name"), max_length=50, null=True, blank=True)
    email = models.EmailField(verbose_name=_("email address"), db_index=True, unique=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = CustomUserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        return f"{self.username} - {self.email}"

    @property
    def get_full_name(self):
        return f"{(self.first_name or '').title()} {(self.last_name or '').title()}".strip()

    def get_short_name(self):
        return self.first_name

    # Ensure username and email are unique and populated when missing
    def save(self, *args, **kwargs):
        # Ensure unique username on create if duplicate exists
        if not self.pk and self.username:
            base = self.username.strip()
            candidate = base
            suffix = 0
            # Exclude current pk to avoid false positives on updates
            while self.__class__.objects.filter(username=candidate).exists():
                suffix += 1
                candidate = f"{base}{suffix}"
            self.username = candidate

        # Ensure email is always populated and unique, even when missing
        if not self.email or not str(self.email).strip():
            base = (self.username or f"user_{uuid.uuid4().hex[:8]}").strip()
            base = base.replace("@", "_at_")
            candidate = f"{base}@example.invalid"
            suffix = 0
            while self.__class__.objects.filter(email=candidate).exclude(pk=self.pk).exists():
                suffix += 1
                candidate = f"{base}{suffix}@example.invalid"
            self.email = candidate.lower()
        super().save(*args, **kwargs)
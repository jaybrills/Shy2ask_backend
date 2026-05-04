from django.contrib.auth.base_user import BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def verified(self):
        return self.filter(is_verified=True)

    def unverified(self):
        return self.filter(is_verified=False)

    def staff(self):
        return self.filter(is_staff=True)

    def search(self, term: str | None):
        term = (term or "").strip()
        if not term:
            return self
        return self.filter(
            models.Q(email__icontains=term)
            | models.Q(first_name__icontains=term)
            | models.Q(last_name__icontains=term)
            | models.Q(alias_name__icontains=term)
        )

    def for_directory(self):
        return self.order_by("-date_joined")

    def by_email(self, email: str | None):
        normalized = UserManager.normalize_email(email or "").lower()
        return self.filter(email__iexact=normalized) if normalized else self.none()


class UserManager(BaseUserManager.from_queryset(UserQuerySet)):
    """
    Custom user manager where email is the unique identifier
    instead of username.
    """

    def create_user(self, email, password=None, **extra_fields):
        """
        Create and save a regular user with the given email and password.
        """
        if not email:
            raise ValueError(_('The Email field must be set'))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """
        Create and save a superuser with the given email and password.
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))

        return self.create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        return self.get_queryset().by_email(username).get()

    def find_by_email(self, email: str | None):
        return self.get_queryset().by_email(email).first()


class OTPQuerySet(models.QuerySet):
    def valid(self, now):
        return self.filter(expires_at__gt=now)

    def latest_first(self):
        return self.order_by("-created_at")


class OTPManager(models.Manager.from_queryset(OTPQuerySet)):
    pass


class UserDeviceQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def inactive(self):
        return self.filter(is_active=False)

    def for_user(self, user):
        return self.filter(user=user)

    def active_for_user(self, user):
        return self.active().for_user(user)

    def active_tokens_for_user(self, user) -> list[str]:
        return list(self.active_for_user(user).values_list("fcm_token", flat=True))


class UserDeviceManager(models.Manager.from_queryset(UserDeviceQuerySet)):
    def register(self, *, user, fcm_token: str, device_type: str = "android", device_name: str = "") -> "models.Model":
        """
        Upsert a device by token. If the token already exists under a different
        user (e.g. after account switch or re-install), ownership is transferred.
        Always reactivates the token so re-installs are handled transparently.
        """
        device, _ = self.update_or_create(
            fcm_token=fcm_token,
            defaults={
                "user": user,
                "device_type": device_type,
                "device_name": device_name,
                "is_active": True,
            },
        )
        return device

    def deactivate_token(self, fcm_token: str) -> None:
        """Mark a single token as invalid. Called when FCM returns UnregisteredError."""
        self.filter(fcm_token=fcm_token).update(is_active=False)

    def deactivate_tokens(self, token_ids: list[int]) -> None:
        """Bulk-deactivate stale tokens by primary key after a batch send."""
        if token_ids:
            self.filter(id__in=token_ids).update(is_active=False)

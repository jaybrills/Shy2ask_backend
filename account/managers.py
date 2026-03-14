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

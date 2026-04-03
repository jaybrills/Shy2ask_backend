import re
from difflib import SequenceMatcher

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .managers import OTPManager, UserManager
from .validators import validate_phone_number, validate_disposable_email


class CreatedAtModel(models.Model):
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        abstract = True


class TimeStampedModel(CreatedAtModel):
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        abstract = True


class UpdatedAtModel(models.Model):
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        abstract = True


class User(AbstractBaseUser, PermissionsMixin, UpdatedAtModel):
    """
    Custom User model that uses email as the unique identifier
    instead of username.
    """
    username = None
    email = models.EmailField(
        _('email address'),
        unique=True,
        db_index=True,
        validators=[validate_disposable_email],
        help_text=_('Required. Enter a valid email address.')
    )
    
    first_name = models.CharField(_('first name'), max_length=150, blank=True)
    last_name = models.CharField(_('last name'), max_length=150, blank=True)
    alias_name = models.CharField(_('alias name'), max_length=150, blank=True, help_text=_('Optional display name or nickname.'))
    phone_number = models.CharField(
        _('phone number'),
        max_length=20,
        blank=True,
        validators=[validate_phone_number],  # Use function, not class instance
        help_text=_('Phone number in international format (e.g., +41 79 123 4567). Must start with + and country code.')
    )
    profile_picture = models.ImageField(_('profile picture'), upload_to='profile_pictures/', blank=True, null=True)
    
    is_staff = models.BooleanField(
        _('staff status'),
        default=False,
        help_text=_('Designates whether the user can log into this admin site.'),
    )
    is_active = models.BooleanField(
        _('active'),
        default=True,
        help_text=_(
            'Designates whether this user should be treated as active. '
            'Unselect this instead of deleting accounts.'
        ),
    )
    is_verified = models.BooleanField(
        _('verified'),
        default=False,
        help_text=_('Designates whether this user has verified their email with OTP.'),
    )
    date_joined = models.DateTimeField(_('date joined'), auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')
        db_table = 'account_user'
        ordering = ['-date_joined']

    @staticmethod
    def _normalize_name_for_comparison(value):
        return re.sub(r'[^a-z0-9]+', '', (value or '').lower())

    def _alias_matches_real_name(self):
        alias = self._normalize_name_for_comparison(self.alias_name)
        if not alias:
            return False

        candidates = {
            self._normalize_name_for_comparison(self.first_name),
            self._normalize_name_for_comparison(self.last_name),
            self._normalize_name_for_comparison(f"{self.first_name} {self.last_name}"),
        }
        candidates.discard("")

        for candidate in candidates:
            if alias == candidate:
                return True
            if SequenceMatcher(None, alias, candidate).ratio() >= 0.85:
                return True
        return False

    def __str__(self):
        if self.alias_name:
            return f"{self.alias_name} ({self.email})"
        if self.get_full_name():
            return f"{self.get_full_name()} ({self.email})"
        return self.email

    def get_full_name(self):
        """
        Return the first_name plus the last_name, with a space in between.
        """
        full_name = f'{self.first_name} {self.last_name}'.strip()
        return full_name if full_name else self.email

    def get_short_name(self):
        """Return the short name for the user."""
        return self.first_name if self.first_name else self.email.split('@')[0]

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email).lower()

        if self._alias_matches_real_name():
            raise ValidationError(
                {"alias_name": _("Alias name cannot closely match your first or last name.")}
            )
        
        # Normalize phone number format (validator already checked validity)
        if self.phone_number:
            # Remove extra whitespace but keep single spaces for readability
            # Format: +[country code] [rest of number with spaces]
            cleaned = re.sub(r'\s+', ' ', self.phone_number.strip())
            # Ensure + is directly followed by digits (no space after +)
            cleaned = re.sub(r'\+\s+', '+', cleaned)
            self.phone_number = cleaned

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class OTPBase(CreatedAtModel):
    otp_code = models.CharField(_("OTP code"), max_length=8)
    expires_at = models.DateTimeField(_("expires at"))

    objects = OTPManager()

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    @property
    def is_expired(self):
        from django.utils import timezone
        return self.expires_at <= timezone.now()


class PasswordResetOTP(OTPBase):
    """One-time code for password reset; sent by email."""
    email = models.EmailField(_("email address"), db_index=True)

    class Meta:
        verbose_name = _("password reset OTP")
        verbose_name_plural = _("password reset OTPs")
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.email = User.objects.normalize_email(self.email).lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"OTP for {self.email}"


class EmailVerificationOTP(OTPBase):
    """One-time code for email verification after signup."""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="email_verification_otps",
    )

    class Meta:
        verbose_name = _("email verification OTP")
        verbose_name_plural = _("email verification OTPs")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Verification OTP for {self.user.email}"


class CeleryTaskError(models.Model):
    task_name = models.CharField(max_length=255)
    args = models.TextField()
    kwargs = models.TextField()
    exception = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.task_name


class ActiveUser(User):
    class Meta:
        proxy = True
        verbose_name = _("active user")
        verbose_name_plural = _("active users")


class PendingVerificationUser(User):
    class Meta:
        proxy = True
        verbose_name = _("pending verification user")
        verbose_name_plural = _("pending verification users")

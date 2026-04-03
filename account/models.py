import re

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from fuzzywuzzy import fuzz

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

    @staticmethod
    def _tokenize_name(value):
        return [part for part in re.split(r'[^a-z0-9]+', (value or '').lower()) if part]

    @staticmethod
    def _is_strict_name_match(alias, candidate):
        if not alias or not candidate:
            return False

        if alias == candidate:
            return True

        # Reject strong partial matches like "khaj" vs "khajan".
        if len(alias) >= 4 and alias in candidate:
            return True
        if len(candidate) >= 4 and candidate in alias:
            return True

        return (
            fuzz.ratio(alias, candidate) >= 80
            or fuzz.partial_ratio(alias, candidate) >= 90
            or fuzz.token_sort_ratio(alias, candidate) >= 85
        )

    @classmethod
    def _tokens_match_real_name(cls, alias_tokens, name_tokens):
        if not alias_tokens or not name_tokens or len(alias_tokens) > len(name_tokens):
            return False

        matched = 0
        for alias_token, name_token in zip(alias_tokens, name_tokens):
            if alias_token == name_token:
                matched += 1
                continue
            if len(alias_token) >= 3 and name_token.startswith(alias_token):
                matched += 1
                continue
            if cls._is_strict_name_match(alias_token, name_token):
                matched += 1

        return matched == len(alias_tokens)

    @classmethod
    def _compact_alias_matches_name_tokens(cls, alias, name_tokens):
        if not alias or len(name_tokens) < 2:
            return False

        normalized_tokens = [cls._normalize_name_for_comparison(token) for token in name_tokens if token]
        if len(normalized_tokens) < 2:
            return False

        min_prefix_len = 3
        split_count = len(normalized_tokens) - 1

        def search(start_index, token_index):
            current_token = normalized_tokens[token_index]
            remaining_tokens = len(normalized_tokens) - token_index - 1

            min_end = start_index + min_prefix_len
            max_end = len(alias) - (remaining_tokens * min_prefix_len)
            if token_index == len(normalized_tokens) - 1:
                piece = alias[start_index:]
                return bool(piece) and (
                    current_token.startswith(piece) or cls._is_strict_name_match(piece, current_token)
                )

            for end_index in range(min_end, max_end + 1):
                piece = alias[start_index:end_index]
                if current_token.startswith(piece) or cls._is_strict_name_match(piece, current_token):
                    if search(end_index, token_index + 1):
                        return True
            return False

        return len(alias) >= (len(normalized_tokens) * min_prefix_len) and search(0, 0)

    def _alias_matches_real_name(self):
        raw_alias = (self.alias_name or "").strip()
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
            if self._is_strict_name_match(alias, candidate):
                return True

        alias_tokens = self._tokenize_name(raw_alias)
        token_candidates = [
            self._tokenize_name(self.first_name),
            self._tokenize_name(self.last_name),
            self._tokenize_name(f"{self.first_name} {self.last_name}"),
        ]
        return any(
            self._tokens_match_real_name(alias_tokens, tokens)
            or self._compact_alias_matches_name_tokens(alias, tokens)
            for tokens in token_candidates
        )

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

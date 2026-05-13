import re
from difflib import SequenceMatcher

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from .alias_utils import generate_alias_suggestions, generate_unique_alias_name, normalize_alias_name
from .managers import OTPManager, UserDeviceManager, UserManager
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
    alias_name = models.CharField(
        _('alias name'),
        max_length=150,
        help_text=_('Unique display name or nickname. Auto-generated when omitted.'),
    )
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
        constraints = [
            models.UniqueConstraint(Lower("alias_name"), name="account_user_alias_name_ci_unique"),
        ]

    @staticmethod
    def _normalize_name_for_comparison(value):
        return re.sub(r'[^a-z0-9]+', '', (value or '').lower())

    @staticmethod
    def _tokenize_name(value):
        return [part for part in re.split(r'[^a-z0-9]+', (value or '').lower()) if part]

    @staticmethod
    def _ratio(left, right):
        return int(SequenceMatcher(None, left, right).ratio() * 100)

    @classmethod
    def _partial_ratio(cls, left, right):
        if not left or not right:
            return 0

        shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
        if shorter == longer:
            return 100

        window = len(shorter)
        best = 0
        for start in range(0, len(longer) - window + 1):
            best = max(best, cls._ratio(shorter, longer[start : start + window]))
            if best == 100:
                return best
        return best

    @classmethod
    def _token_sort_ratio(cls, left, right):
        left_tokens = " ".join(sorted(cls._tokenize_name(left)))
        right_tokens = " ".join(sorted(cls._tokenize_name(right)))
        return cls._ratio(left_tokens, right_tokens)

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
            User._ratio(alias, candidate) >= 80
            or User._partial_ratio(alias, candidate) >= 90
            or User._token_sort_ratio(alias, candidate) >= 85
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
            if len(alias_token) == 1 and name_token.startswith(alias_token):
                matched += 1
                continue
            if len(alias_token) >= 3 and name_token.startswith(alias_token):
                matched += 1
                continue
            if cls._is_strict_name_match(alias_token, name_token):
                matched += 1

        return matched == len(alias_tokens)

    @classmethod
    def _compact_alias_matches_token_sequence(cls, alias, name_tokens):
        if not alias or len(name_tokens) < 2:
            return False

        normalized_tokens = [cls._normalize_name_for_comparison(token) for token in name_tokens if token]
        if len(normalized_tokens) < 2:
            return False

        min_prefix_len = 3

        def search(start_index, token_index, has_substantial_piece):
            current_token = normalized_tokens[token_index]
            remaining_tokens = len(normalized_tokens) - token_index - 1

            if start_index >= len(alias):
                return False

            max_end = len(alias) - remaining_tokens
            piece_lengths = []
            if alias[start_index] == current_token[0]:
                piece_lengths.append(1)

            min_end = start_index + min_prefix_len
            for end_index in range(min_end, max_end + 1):
                piece = alias[start_index:end_index]
                if current_token.startswith(piece) or cls._is_strict_name_match(piece, current_token):
                    piece_lengths.append(len(piece))

            for piece_length in sorted(set(piece_lengths)):
                next_index = start_index + piece_length
                next_has_substantial_piece = has_substantial_piece or piece_length >= min_prefix_len
                if token_index == len(normalized_tokens) - 1:
                    if next_index == len(alias) and next_has_substantial_piece:
                        return True
                    continue
                if search(next_index, token_index + 1, next_has_substantial_piece):
                    return True
            return False

        return search(0, 0, False)

    @classmethod
    def _compact_alias_matches_name_tokens(cls, alias, name_tokens):
        if not alias or len(name_tokens) < 2:
            return False

        sequences = [name_tokens]
        reversed_tokens = list(reversed(name_tokens))
        if reversed_tokens != list(name_tokens):
            sequences.append(reversed_tokens)
        return any(cls._compact_alias_matches_token_sequence(alias, sequence) for sequence in sequences)

    def _alias_matches_real_name(self):
        raw_alias = normalize_alias_name(self.alias_name)
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

    @classmethod
    def alias_exists(cls, alias_name, exclude_pk=None):
        alias_name = normalize_alias_name(alias_name)
        if not alias_name:
            return False

        queryset = cls.objects.filter(alias_name__iexact=alias_name)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        return queryset.exists()

    @classmethod
    def is_alias_invalid_for_name(cls, alias_name, first_name="", last_name=""):
        candidate = normalize_alias_name(alias_name)
        if not candidate:
            return False
        return cls(first_name=first_name, last_name=last_name, alias_name=candidate)._alias_matches_real_name()

    @classmethod
    def generate_unique_alias(cls, first_name="", last_name="", exclude_pk=None, reserved_aliases=None):
        return generate_unique_alias_name(
            alias_exists=lambda alias: cls.alias_exists(alias, exclude_pk=exclude_pk),
            is_invalid_alias=lambda alias: cls.is_alias_invalid_for_name(
                alias,
                first_name=first_name,
                last_name=last_name,
            ),
            reserved_aliases=reserved_aliases,
        )

    @classmethod
    def alias_suggestions(cls, first_name="", last_name="", exclude_pk=None, count=3):
        return generate_alias_suggestions(
            count=count,
            alias_exists=lambda alias: cls.alias_exists(alias, exclude_pk=exclude_pk),
            is_invalid_alias=lambda alias: cls.is_alias_invalid_for_name(
                alias,
                first_name=first_name,
                last_name=last_name,
            ),
        )

    @classmethod
    def get_alias_availability(cls, alias_name, first_name="", last_name="", exclude_pk=None):
        normalized_alias = normalize_alias_name(alias_name)
        if not normalized_alias:
            return False, _("Alias name is required.")
        if cls.is_alias_invalid_for_name(normalized_alias, first_name=first_name, last_name=last_name):
            return False, _("Alias name cannot closely match your first or last name.")
        if cls.alias_exists(normalized_alias, exclude_pk=exclude_pk):
            return False, _("This alias name is already taken.")
        return True, _("Alias name is available.")

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
        self.alias_name = normalize_alias_name(self.alias_name)

        if self._alias_matches_real_name():
            raise ValidationError(
                {"alias_name": _("Alias name cannot closely match your first or last name.")}
            )
        if self.alias_exists(self.alias_name, exclude_pk=self.pk):
            raise ValidationError(
                {"alias_name": _("This alias name is already taken.")}
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
        generated_alias = False
        self.alias_name = normalize_alias_name(self.alias_name)
        if not self.alias_name:
            self.alias_name = self.__class__.generate_unique_alias(
                first_name=self.first_name,
                last_name=self.last_name,
                exclude_pk=self.pk,
            )
            generated_alias = True
        if generated_alias and kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"alias_name"}
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


class UserDevice(CreatedAtModel):
    """
    One row per physical app install.
    A single user can have many devices (phone, tablet, second phone etc.).
    FCM tokens are globally unique — they identify a specific app installation,
    not a user — so the token is the natural upsert key.
    """

    ANDROID = "android"
    IOS = "ios"
    WEB = "web"
    DEVICE_TYPE_CHOICES = [
        (ANDROID, _("Android")),
        (IOS, _("iOS")),
        (WEB, _("Web")),
    ]

    user = models.ForeignKey(
        "account.User",
        on_delete=models.CASCADE,
        related_name="devices",
        verbose_name=_("user"),
    )
    fcm_token = models.TextField(
        _("FCM token"),
        unique=True,
        help_text=_("Firebase Cloud Messaging registration token for this device."),
    )
    device_type = models.CharField(
        _("device type"),
        max_length=10,
        choices=DEVICE_TYPE_CHOICES,
        default=ANDROID,
    )
    device_name = models.CharField(
        _("device name"),
        max_length=100,
        blank=True,
        default="",
        help_text=_("Optional human-readable label, e.g. 'iPhone 15 Pro'."),
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Unset automatically when FCM reports the token as unregistered."),
    )
    last_used_at = models.DateTimeField(
        _("last used at"),
        auto_now=True,
    )

    objects = UserDeviceManager()

    class Meta:
        verbose_name = _("user device")
        verbose_name_plural = _("user devices")
        db_table = "account_user_device"
        indexes = [
            models.Index(fields=["user", "is_active"], name="account_device_user_active_idx"),
        ]

    def __str__(self):
        label = self.device_name or self.get_device_type_display()
        return f"{self.user.email} — {label}"


class UserNotification(models.Model):
    """
    Persistent log of every push notification sent to a user.
    Written by send_push_notification_task before FCM delivery so that
    the history is complete even if the device was offline or the token stale.
    """

    class Priority(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        IGNORABLE = "ignorable", "Ignorable"
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("user"),
    )
    title = models.CharField(_("title"), max_length=255)
    body = models.TextField(_("body"))
    notification_type = models.CharField(
        _("notification type"),
        max_length=100,
        db_index=True,
        help_text=_("Key from PushTemplate (e.g. subscription_activated, payment_failed)."),
    )
    priority = models.CharField(
        _("priority"),
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    data = models.JSONField(
        _("extra data"),
        default=dict,
        blank=True,
        help_text=_("Full data payload delivered with the notification."),
    )
    is_read = models.BooleanField(
        _("read"),
        default=False,
        db_index=True,
    )
    created_at = models.DateTimeField(_("sent at"), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("user notification")
        verbose_name_plural = _("user notifications")
        db_table = "account_user_notification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                name="account_notif_user_date_idx",
            ),
            models.Index(
                fields=["user", "is_read"],
                name="account_notif_user_read_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.priority.upper()}] {self.user.email} — {self.title}"


class SocialAccount(CreatedAtModel):
    """Links a Firebase social provider (Google / Apple) to a local User account."""

    PROVIDER_GOOGLE = "google"
    PROVIDER_APPLE = "apple"
    PROVIDER_CHOICES = [
        (PROVIDER_GOOGLE, "Google"),
        (PROVIDER_APPLE, "Apple"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="social_accounts",
        verbose_name=_("user"),
    )
    provider = models.CharField(_("provider"), max_length=20, choices=PROVIDER_CHOICES)
    provider_uid = models.CharField(
        _("provider UID"),
        max_length=255,
        help_text=_("Firebase UID from the decoded ID token."),
    )
    email = models.EmailField(
        _("provider email"),
        blank=True,
        help_text=_("Email reported by the provider at the time of linking."),
    )

    class Meta:
        verbose_name = _("social account")
        verbose_name_plural = _("social accounts")
        db_table = "account_social_account"
        unique_together = [("provider", "provider_uid")]
        indexes = [
            models.Index(fields=["provider", "provider_uid"], name="account_social_provider_uid_idx"),
        ]

    def __str__(self):
        return f"{self.user.email} via {self.get_provider_display()}"


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

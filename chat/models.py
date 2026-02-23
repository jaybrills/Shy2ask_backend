import secrets
import string
from decimal import Decimal

from django.conf import settings
from django.db import models


def generate_tracking_code(length: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class ShyRequest(models.Model):
    class ServiceChannel(models.TextChoices):
        EMAIL = ("email", "E-mail")
        LETTER = ("letter", "Letter")
        CALL = ("call", "Phone call")

    class Status(models.TextChoices):
        DRAFT = ("draft", "Draft")
        SUBMITTED = ("submitted", "Submitted")
        IN_PROGRESS = ("in_progress", "In progress")
        COMPLETED = ("completed", "Completed")
        REJECTED = ("rejected", "Rejected")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    
    tracking_code = models.CharField(max_length=12, unique=True, blank=True)
    requester_name = models.CharField(max_length=120)
    requester_email = models.EmailField()
    requester_phone = models.CharField(max_length=50, blank=True)
    requester_alias = models.CharField(
        max_length=120,
        blank=True,
        help_text="Display name for this request (e.g. in chat). If blank, profile alias or requester_name is used.",
    )


    target_name = models.CharField(max_length=120, blank=True)
    target_email = models.EmailField(blank=True)
    target_phone = models.CharField(max_length=50, blank=True)
    target_address = models.CharField(max_length=255, blank=True)

    description = models.TextField()
    service_channel = models.CharField(
        max_length=20, choices=ServiceChannel.choices, default=ServiceChannel.EMAIL
    )
    call_minutes = models.PositiveIntegerField(
        default=0, help_text="Estimated minutes if we call."
    )
    quoted_price_chf = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    country_code = models.CharField(max_length=8, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def calculate_price(self) -> Decimal:
        """Apply simple pricing rules from the SRS."""
        if self.service_channel == self.ServiceChannel.EMAIL:
            return Decimal("1.00")
        if self.service_channel == self.ServiceChannel.LETTER:
            return Decimal("10.00")
        minutes = Decimal(self.call_minutes or 0)
        return Decimal("20.00") + minutes

    def change_status(self, new_status: str):
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])

    def save(self, *args, **kwargs):
        if not self.tracking_code:
            self.tracking_code = generate_tracking_code()
        self.quoted_price_chf = self.calculate_price()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Request by {self.requester_name} ({self.service_channel})"


class Attachment(models.Model):
    request = models.ForeignKey(
        ShyRequest, related_name="attachments", on_delete=models.CASCADE
    )
    file = models.FileField(upload_to="attachments/%Y/%m/%d")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.file.name


class Conversation(models.Model):
    request = models.OneToOneField(
        ShyRequest, related_name="conversation", on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Conversation for {self.request}"


class Message(models.Model):
    class Sender(models.TextChoices):
        REQUESTER = ("requester", "Requester")
        STAFF = ("staff", "Staff")
        RESPONDER = ("responder", "Responder")  # reply via tracking code (no login)

    conversation = models.ForeignKey(
        Conversation, related_name="messages", on_delete=models.CASCADE
    )
    sender = models.CharField(max_length=20, choices=Sender.choices)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    sender_display_name = models.CharField(
        max_length=120,
        blank=True,
        help_text="Display name for this message (e.g. alias). If blank, derived from request/profile.",
    )
    body = models.TextField()
    clean_body = models.TextField(blank=True)
    is_blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_sender_display()}: {self.body[:40]}"

    def save(self, *args, **kwargs):
        if not self.clean_body:
            from .utils import censor_text

            clean_body, blocked = censor_text(self.body)
            self.clean_body = clean_body
            self.is_blocked = blocked
        super().save(*args, **kwargs)


class Notification(models.Model):
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=200)
    body = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    related_request = models.ForeignKey(
        ShyRequest, on_delete=models.CASCADE, null=True, blank=True
    )

    def save(self, *args, **kwargs):
        if not self.created_at:
            from django.utils import timezone
            self.created_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Notification to {self.recipient_email}"


class Deal(models.Model):
    class Status(models.TextChoices):
        PROPOSED = ("proposed", "Proposed")
        AGREED = ("agreed", "Agreed")
        PAYMENT_DUE = ("payment_due", "Payment due")
        PAID = ("paid", "Paid")
        COMPLETED = ("completed", "Completed")
        CANCELLED = ("cancelled", "Cancelled")

    class Payer(models.TextChoices):
        REQUESTER = ("requester", "Requester")
        RECIPIENT = ("recipient", "Recipient")
        SPLIT = ("split", "Split")

    request = models.OneToOneField(
        ShyRequest, related_name="deal", on_delete=models.CASCADE
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=8, default="INR")
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payer = models.CharField(max_length=20, choices=Payer.choices, default=Payer.REQUESTER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROPOSED)
    payment_reference = models.CharField(max_length=120, blank=True)
    invoice_number = models.CharField(max_length=40, blank=True)
    ai_detected = models.BooleanField(default=False, help_text="True if deal was detected by AI from conversation.")
    ai_summary = models.TextField(blank=True, help_text="AI-generated summary of the deal.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def calculate_fee(self) -> Decimal:
        return (self.amount or Decimal("0")) * Decimal("0.03")

    def save(self, *args, **kwargs):
        self.platform_fee = self.calculate_fee()
        if not self.invoice_number:
            self.invoice_number = f"INV-{self.request.tracking_code}-{self.pk or ''}".strip("-")
        super().save(*args, **kwargs)

    def mark_paid(self, reference: str):
        self.payment_reference = reference
        self.status = self.Status.PAID
        self.save(update_fields=["payment_reference", "status", "updated_at", "platform_fee"])


class Subscription(models.Model):
    """User subscriptions: request updates, deal alerts, optional daily digest (all AI-enhanced)."""
    class Type(models.TextChoices):
        REQUEST_UPDATES = ("request_updates", "Request updates (new messages)")
        DEAL_ALERTS = ("deal_alerts", "Deal alerts (AI-detected deals)")
        DAILY_DIGEST = ("daily_digest", "Daily digest (AI summary)")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions"
    )
    request = models.ForeignKey(
        ShyRequest, on_delete=models.CASCADE, null=True, blank=True, related_name="subscriptions"
    )
    subscription_type = models.CharField(max_length=30, choices=Type.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [["user", "request", "subscription_type"]]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} {self.get_subscription_type_display()} ({self.request_id or 'all'})"


# ----- Censor engine: store offensive terms in DB (any language) -----
class CensorCategory(models.Model):
    """Category for offensive terms (abusive, illegal, drugs, etc.)."""
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=50, unique=True, help_text="e.g. abusive, illegal, human_trafficking")
    description = models.CharField(max_length=255, blank=True)
    is_blocking = models.BooleanField(
        default=True,
        help_text="If True, matching content is blocked (rejected).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Censor category"
        verbose_name_plural = "Censor categories"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.slug})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            from .censor_loader import invalidate_censor_cache
            invalidate_censor_cache()
        except Exception:
            pass


class OffensiveTerm(models.Model):
    """Single offensive word or phrase, any language. Loaded by censor engine."""
    class TermType(models.TextChoices):
        WORD = ("word", "Word")
        PHRASE = ("phrase", "Phrase")

    category = models.ForeignKey(
        CensorCategory,
        on_delete=models.CASCADE,
        related_name="terms",
    )
    term = models.CharField(max_length=255, help_text="Word or phrase to detect (case-insensitive).")
    term_type = models.CharField(
        max_length=10,
        choices=TermType.choices,
        default=TermType.WORD,
    )
    language_code = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="ISO 639-1 e.g. en, ar, hi. Empty = any language.",
    )
    is_blocking = models.BooleanField(
        default=True,
        help_text="If True, content containing this term is blocked.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Offensive term"
        verbose_name_plural = "Offensive terms"
        ordering = ["category", "term_type", "-term"]
        indexes = [
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["language_code", "is_active"]),
        ]

    def __str__(self):
        return f"{self.term} ({self.category.slug})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            from .censor_loader import invalidate_censor_cache
            invalidate_censor_cache()
        except Exception:
            pass


class CensorLog(models.Model):
    """Log when content was blocked by censor (for safety and tuning)."""
    source = models.CharField(max_length=32, blank=True, help_text="e.g. api, chat, upload")
    categories = models.JSONField(default=list, help_text="List of category slugs that triggered.")
    detected_terms = models.JSONField(default=list, help_text="List of detected term strings.")
    blocked = models.BooleanField(default=True)
    text_preview = models.CharField(max_length=500, blank=True, help_text="First 500 chars of input (redacted).")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Censor log"
        verbose_name_plural = "Censor logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"CensorLog {self.id} blocked={self.blocked} {self.created_at}"


class CensorTrainingExample(models.Model):
    """
    Training data for our own AI model.
    When Google API detects toxic content (and our model missed it), we save here.
    Then we retrain our model on this data so it learns over time.
    """
    class Source(models.TextChoices):
        GOOGLE_API = ("google_api", "Google API (fallback detected)")
        OUR_MODEL = ("our_model", "Our model detected")
        MANUAL = ("manual", "Manual label")

    text = models.TextField(help_text="Input text (truncated for storage).")
    is_toxic = models.BooleanField(help_text="True = offensive/toxic, False = safe.")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.GOOGLE_API)
    score = models.FloatField(null=True, blank=True, help_text="Toxicity score from API or model.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Censor training example"
        verbose_name_plural = "Censor training examples"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["source", "is_toxic"])]

    def __str__(self):
        return f"{'toxic' if self.is_toxic else 'safe'} ({self.source})"

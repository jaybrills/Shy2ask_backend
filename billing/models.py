from django.conf import settings
from django.db import models
from django.utils import timezone


class StripeCustomer(models.Model):
    """
    Maps each Django user to their Stripe Customer ID.
    One-to-one: a user has exactly one Stripe customer record.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="stripe_customer",
    )
    stripe_customer_id = models.CharField(max_length=255, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Stripe Customer"
        verbose_name_plural = "Stripe Customers"

    def __str__(self):
        return f"{self.user} → {self.stripe_customer_id}"


class StripePlan(models.Model):
    """
    Represents a Stripe Price (plan). Seed these via the admin or a management
    command — they mirror what you've configured in your Stripe dashboard.
    """

    class Interval(models.TextChoices):
        MONTH = "month", "Monthly"
        YEAR = "year", "Yearly"

    name = models.CharField(max_length=255)
    # Blank/null for free plans — they don't exist in Stripe
    stripe_price_id = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)
    stripe_product_id = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Price in smallest currency units (e.g. cents). 0 for free plans.")
    currency = models.CharField(max_length=10, default="chf")
    interval = models.CharField(max_length=10, choices=Interval.choices, default=Interval.MONTH)
    is_free = models.BooleanField(default=False, help_text="Free plans bypass Stripe checkout entirely.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Stripe Plan"
        verbose_name_plural = "Stripe Plans"
        ordering = ["amount"]

    def __str__(self):
        return f"{self.name} ({self.interval}) — {self.currency.upper()} {self.amount}"


class StripeSubscription(models.Model):
    """
    Mirrors a Stripe Subscription object. Created/updated via webhooks.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CANCELED = "canceled", "Canceled"
        INCOMPLETE = "incomplete", "Incomplete"
        INCOMPLETE_EXPIRED = "incomplete_expired", "Incomplete Expired"
        PAST_DUE = "past_due", "Past Due"
        PAUSED = "paused", "Paused"
        TRIALING = "trialing", "Trialing"
        UNPAID = "unpaid", "Unpaid"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="stripe_subscriptions",
    )
    plan = models.ForeignKey(
        StripePlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscriptions",
    )
    # Null for free-plan subscriptions (no Stripe objects involved)
    stripe_subscription_id = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True)
    stripe_customer_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.INCOMPLETE)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(null=True, blank=True)
    trial_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Stripe Subscription"
        verbose_name_plural = "Stripe Subscriptions"
        ordering = ["-created_at"]

    def __str__(self):
        sub_id = self.stripe_subscription_id or "free"
        return f"{self.user} — {sub_id} ({self.status})"

    @property
    def is_active(self) -> bool:
        return self.status in (self.Status.ACTIVE, self.Status.TRIALING)

    @property
    def is_past_due(self) -> bool:
        return self.status == self.Status.PAST_DUE


class StripeEvent(models.Model):
    """
    Idempotency log of every webhook event received from Stripe.
    Prevents double-processing when Stripe retries delivery.
    """
    stripe_event_id = models.CharField(max_length=255, unique=True, db_index=True)
    event_type = models.CharField(max_length=255)
    payload = models.JSONField()
    processed_at = models.DateTimeField(default=timezone.now)
    processing_error = models.TextField(blank=True)

    class Meta:
        verbose_name = "Stripe Webhook Event"
        verbose_name_plural = "Stripe Webhook Events"
        ordering = ["-processed_at"]

    def __str__(self):
        return f"{self.event_type} — {self.stripe_event_id}"

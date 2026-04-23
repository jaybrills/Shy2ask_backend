from rest_framework import serializers

from .models import StripePlan, StripeSubscription


class StripePlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = StripePlan
        fields = [
            "id",
            "name",
            "stripe_price_id",
            "amount",
            "currency",
            "interval",
            "is_free",
            "is_active",
        ]


class StripeSubscriptionSerializer(serializers.ModelSerializer):
    plan = StripePlanSerializer(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_past_due = serializers.BooleanField(read_only=True)

    class Meta:
        model = StripeSubscription
        fields = [
            "id",
            "stripe_subscription_id",
            "status",
            "plan",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
            "canceled_at",
            "trial_end",
            "is_active",
            "is_past_due",
            "created_at",
            "updated_at",
        ]


class CreateCheckoutSessionSerializer(serializers.Serializer):
    price_id = serializers.CharField(
        help_text="Stripe Price ID (e.g. price_xxxxxxxxxxxxxxxx). "
                  "Leave blank to use the default plan from settings.",
        required=False,
        allow_blank=True,
    )
    success_url = serializers.URLField(
        help_text="URL Stripe redirects to after a successful payment."
    )
    cancel_url = serializers.URLField(
        help_text="URL Stripe redirects to if the user cancels checkout."
    )


class CheckoutSessionResponseSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    url = serializers.URLField()


class CustomerPortalSerializer(serializers.Serializer):
    return_url = serializers.URLField(
        help_text="URL Stripe redirects to after the portal session ends."
    )


class CustomerPortalResponseSerializer(serializers.Serializer):
    url = serializers.URLField()


class EnrollFreePlanSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="ID of the free StripePlan to enroll in. "
                  "Omit to auto-select the only active free plan.",
    )


# ── React Native / Mobile SDK serializers ────────────────────────────────────

class BillingConfigSerializer(serializers.Serializer):
    publishable_key = serializers.CharField(
        help_text="Stripe publishable key to initialize the mobile SDK."
    )


class PaymentSheetResponseSerializer(serializers.Serializer):
    customer_id = serializers.CharField()
    ephemeral_key_secret = serializers.CharField(
        help_text="Short-lived EphemeralKey secret — pass to initPaymentSheet."
    )
    setup_intent_client_secret = serializers.CharField(
        help_text="SetupIntent client_secret — pass to initPaymentSheet for saving a card."
    )
    publishable_key = serializers.CharField()


class MobileSubscribeSerializer(serializers.Serializer):
    price_id = serializers.CharField(
        help_text="Stripe Price ID (e.g. price_xxxx) for the plan to subscribe to."
    )


class MobileSubscribeResponseSerializer(serializers.Serializer):
    subscription_id = serializers.CharField()
    client_secret = serializers.CharField(
        allow_null=True,
        help_text=(
            "client_secret for the Payment Sheet. "
            "Null when no payment is needed (trial, $0 plan, or full credit coverage)."
        ),
    )
    intent_type = serializers.ChoiceField(
        choices=["payment", "setup"],
        allow_null=True,
        help_text=(
            "Tells the frontend which field to use in initPaymentSheet:\n"
            "  'payment' → paymentIntentClientSecret\n"
            "  'setup'   → setupIntentClientSecret (card saved, will auto-charge later)\n"
            "  null      → no Payment Sheet needed, subscription already active"
        ),
    )
    status = serializers.CharField(
        help_text="Stripe subscription status (e.g. incomplete, active, trialing)."
    )
    detail = serializers.CharField(
        required=False,
        help_text="Human-readable note when client_secret is null.",
    )


class CancelSubscriptionSerializer(serializers.Serializer):
    immediately = serializers.BooleanField(
        default=False,
        required=False,
        help_text="True to cancel now; False (default) to cancel at period end.",
    )


class PaymentMethodCardSerializer(serializers.Serializer):
    brand = serializers.CharField()
    last4 = serializers.CharField()
    exp_month = serializers.IntegerField()
    exp_year = serializers.IntegerField()


class PaymentMethodSerializer(serializers.Serializer):
    id = serializers.CharField()
    type = serializers.CharField()
    card = PaymentMethodCardSerializer(required=False, allow_null=True)
    is_default = serializers.BooleanField()
    created = serializers.IntegerField(help_text="Unix timestamp.")


class InvoiceSerializer(serializers.Serializer):
    id = serializers.CharField()
    amount_due = serializers.IntegerField(help_text="In smallest currency units (e.g. cents).")
    amount_paid = serializers.IntegerField()
    currency = serializers.CharField()
    status = serializers.CharField()
    created = serializers.IntegerField(help_text="Unix timestamp.")
    invoice_pdf = serializers.URLField(allow_null=True, required=False)
    hosted_invoice_url = serializers.URLField(allow_null=True, required=False)
    period_start = serializers.IntegerField(help_text="Unix timestamp.")
    period_end = serializers.IntegerField(help_text="Unix timestamp.")

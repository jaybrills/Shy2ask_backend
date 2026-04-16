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

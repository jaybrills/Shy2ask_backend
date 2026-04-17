from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import StripeCustomer, StripeEvent, StripePlan, StripeSubscription


@admin.register(StripePlan)
class StripePlanAdmin(ModelAdmin):
    list_display = ["name", "stripe_price_id", "amount", "currency", "interval", "is_active", "created_at"]
    list_filter = ["interval", "is_active", "currency"]
    search_fields = ["name", "stripe_price_id", "stripe_product_id"]
    list_editable = ["is_active"]
    ordering = ["amount"]


@admin.register(StripeCustomer)
class StripeCustomerAdmin(ModelAdmin):
    list_display = ["user", "stripe_customer_id", "created_at"]
    search_fields = ["user__email", "stripe_customer_id"]
    raw_id_fields = ["user"]
    readonly_fields = ["stripe_customer_id", "created_at", "updated_at"]


@admin.register(StripeSubscription)
class StripeSubscriptionAdmin(ModelAdmin):
    list_display = [
        "user",
        "stripe_subscription_id",
        "status",
        "plan",
        "current_period_end",
        "cancel_at_period_end",
        "created_at",
    ]
    list_filter = ["status", "cancel_at_period_end", "plan"]
    search_fields = [
        "user__email",
        "stripe_subscription_id",
        "stripe_customer_id",
    ]
    raw_id_fields = ["user", "plan"]
    readonly_fields = [
        "stripe_subscription_id",
        "stripe_customer_id",
        "current_period_start",
        "current_period_end",
        "canceled_at",
        "trial_end",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]


@admin.register(StripeEvent)
class StripeEventAdmin(ModelAdmin):
    list_display = ["stripe_event_id", "event_type", "processed_at", "has_error"]
    list_filter = ["event_type"]
    search_fields = ["stripe_event_id", "event_type"]
    readonly_fields = ["stripe_event_id", "event_type", "payload", "processed_at", "processing_error"]
    ordering = ["-processed_at"]

    @admin.display(boolean=True, description="Error?")
    def has_error(self, obj):
        return bool(obj.processing_error)

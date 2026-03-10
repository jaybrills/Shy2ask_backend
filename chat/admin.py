from django.contrib import admin

from .models import (
    Attachment,
    CensorCategory,
    CensorLog,
    CensorTrainingExample,
    Deal,
    Message,
    Notification,
    OffensiveTerm,
    ShyRequest,
    Subscription,
)


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    readonly_fields = ("uploaded_at",)


@admin.register(ShyRequest)
class ShyRequestAdmin(admin.ModelAdmin):
    list_display = (
        "requester_name",
        "tracking_code",
        "service_channel",
        "status",
        "quoted_price_chf",
        "country_code",
        "created_at",
    )
    list_filter = ("service_channel", "status", "country_code")
    search_fields = (
        "requester_name",
        "requester_email",
        "target_name",
        "target_email",
    )
    inlines = [AttachmentInline]


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ("request", "file", "uploaded_at")
    search_fields = ("file",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("request", "sender", "is_blocked", "created_at")
    list_filter = ("sender", "is_blocked")
    search_fields = ("body", "clean_body")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient_email", "subject", "sent_at", "related_request")


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = ("request", "amount", "currency", "platform_fee", "status", "payer", "ai_detected")
    list_filter = ("status", "currency", "ai_detected")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "request", "subscription_type", "is_active", "created_at")
    list_filter = ("subscription_type", "is_active")
    search_fields = ("user__email",)
    raw_id_fields = ("user", "request")


# ----- Censor engine (DB terms + logs) -----
class OffensiveTermInline(admin.TabularInline):
    model = OffensiveTerm
    extra = 0
    fields = ("term", "term_type", "language_code", "is_blocking", "is_active")


@admin.register(CensorCategory)
class CensorCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_blocking", "created_at")
    list_filter = ("is_blocking",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [OffensiveTermInline]


@admin.register(OffensiveTerm)
class OffensiveTermAdmin(admin.ModelAdmin):
    list_display = ("term", "category", "term_type", "language_code", "is_blocking", "is_active", "created_at")
    list_filter = ("category", "term_type", "is_blocking", "is_active", "language_code")
    search_fields = ("term",)
    raw_id_fields = ("category",)
    actions = ["mark_active", "mark_inactive"]

    def mark_active(self, request, queryset):
        queryset.update(is_active=True)
    mark_active.short_description = "Mark selected as active"

    def mark_inactive(self, request, queryset):
        queryset.update(is_active=False)
    mark_inactive.short_description = "Mark selected as inactive"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        try:
            from .censor_loader import invalidate_censor_cache
            invalidate_censor_cache()
        except Exception:
            pass


@admin.register(CensorLog)
class CensorLogAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "blocked", "categories_display", "created_at")
    list_filter = ("source", "blocked", "created_at")
    search_fields = ("text_preview", "detected_terms")
    readonly_fields = ("source", "categories", "detected_terms", "blocked", "text_preview", "created_at")

    def categories_display(self, obj):
        return ", ".join(obj.categories or []) if obj.categories else "-"
    categories_display.short_description = "Categories"


@admin.register(CensorTrainingExample)
class CensorTrainingExampleAdmin(admin.ModelAdmin):
    list_display = ("id", "is_toxic", "source", "score", "text_preview", "created_at")
    list_filter = ("is_toxic", "source", "created_at")
    search_fields = ("text",)
    readonly_fields = ("text", "is_toxic", "source", "score", "created_at")

    def text_preview(self, obj):
        return (obj.text or "")[:80] + "..." if len(obj.text or "") > 80 else (obj.text or "")
    text_preview.short_description = "Text"

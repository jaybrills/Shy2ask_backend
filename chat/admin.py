from django.contrib import admin

from .models import (
    Attachment,
    Conversation,
    Deal,
    Message,
    Notification,
    ShyRequest,
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


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("request", "created_at")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "sender", "is_blocked", "created_at")
    list_filter = ("sender", "is_blocked")
    search_fields = ("body", "clean_body")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient_email", "subject", "sent_at", "related_request")


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = ("request", "amount", "currency", "platform_fee", "status", "payer")
    list_filter = ("status", "currency")

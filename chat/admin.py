from django.contrib import admin
from django.utils.html import format_html
from django.utils.timesince import timesince
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    ActiveShyRequest,
    Attachment,
    CensorCategory,
    CensorLog,
    CensorTrainingExample,
    ConversationMessage,
    Deal,
    FAQ,
    FAQVideo,
    Message,
    Notification,
    OffensiveTerm,
    ShyRequest,
    Subscription,
    SupportTicket,
    SupportTicketReply,
)


def badge(label: str, tone: str) -> str:
    return format_html(
        '<span style="display:inline-flex;align-items:center;padding:0.2rem 0.65rem;'
        'border-radius:999px;background:{};color:white;font-weight:600;font-size:0.75rem;">{}</span>',
        tone,
        label,
    )


class AttachmentInline(TabularInline):
    model = Attachment
    extra = 0
    readonly_fields = ("uploaded_at",)


class FAQVideoInline(TabularInline):
    model = FAQVideo
    extra = 0
    fields = ("title", "video_url", "sort_order", "is_active")


class SupportTicketReplyInline(TabularInline):
    model = SupportTicketReply
    extra = 0
    fields = ("sender_type", "author", "email", "body", "created_at")
    readonly_fields = ("created_at",)


class MessageInline(TabularInline):
    model = Message
    extra = 0
    fk_name = "request"
    fields = (
        "message_kind",
        "sender",
        "recipient",
        "sender_display_name",
        "body_preview",
        "is_blocked",
        "created_at",
    )
    readonly_fields = fields
    show_change_link = True

    @admin.display(description="Preview")
    def body_preview(self, obj):
        text = obj.clean_body or obj.body or ""
        return text[:80] + ("..." if len(text) > 80 else "")


@admin.register(ShyRequest)
class ShyRequestAdmin(ModelAdmin):
    list_fullwidth = True
    compressed_fields = True
    warn_unsaved_form = True
    list_filter_submit = True
    search_help_text = "Search by tracking code, requester, target, or participant email."
    list_display = (
        "tracking_code",
        "participant_snapshot",
        "service_channel",
        "status_badge",
        "quoted_price_chf",
        "country_code",
        "created_at",
    )
    list_filter = ("service_channel", "status", "country_code", "created_at")
    search_fields = (
        "tracking_code",
        "requester_name",
        "requester_email",
        "target_name",
        "target_email",
        "description",
    )
    inlines = [AttachmentInline, MessageInline]
    readonly_fields = ("tracking_code", "quoted_price_chf", "created_at", "updated_at")
    fieldsets = (
        (
            "Request flow",
            {
                "fields": (
                    "tracking_code",
                    "status",
                    "service_channel",
                    "quoted_price_chf",
                    "call_minutes",
                    "country_code",
                )
            },
        ),
        (
            "Requester",
            {
                "fields": (
                    "user",
                    "requester_user",
                    "requester_name",
                    "requester_alias",
                    "requester_email",
                    "requester_phone",
                )
            },
        ),
        (
            "Target",
            {
                "fields": (
                    "target_user",
                    "target_name",
                    "target_email",
                    "target_phone",
                    "target_address",
                )
            },
        ),
        ("Content", {"fields": ("description",)}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Participants")
    def participant_snapshot(self, obj):
        return format_html(
            "<strong>{}</strong><br><span style='color:#667085'>{} -> {}</span>",
            obj.requester_display_name,
            obj.requester_email,
            obj.target_email or obj.target_display_name,
        )

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            ShyRequest.Status.DRAFT: "#667085",
            ShyRequest.Status.SUBMITTED: "#1d4ed8",
            ShyRequest.Status.IN_PROGRESS: "#b45309",
            ShyRequest.Status.COMPLETED: "#15803d",
            ShyRequest.Status.REJECTED: "#b42318",
        }
        return badge(obj.get_status_display(), colors.get(obj.status, "#475467"))


@admin.register(ActiveShyRequest)
class ActiveShyRequestAdmin(ShyRequestAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).open()


@admin.register(Attachment)
class AttachmentAdmin(ModelAdmin):
    list_display = ("request", "file", "uploaded_at")
    search_fields = ("file", "request__tracking_code")
    readonly_fields = ("uploaded_at",)


@admin.register(Message)
class MessageAdmin(ModelAdmin):
    list_fullwidth = True
    list_filter_submit = True
    list_display = (
        "request",
        "message_kind",
        "sender",
        "recipient",
        "moderation_state",
        "created_at",
    )
    list_filter = ("message_kind", "sender", "recipient", "is_blocked", "created_at")
    search_fields = ("body", "clean_body", "sender_email", "recipient_email", "request__tracking_code")
    readonly_fields = ("clean_body", "is_blocked", "created_at")
    raw_id_fields = ("request", "author", "sender_user", "recipient_user")

    @admin.display(description="Moderation")
    def moderation_state(self, obj):
        return badge("Blocked" if obj.is_blocked else "Clean", "#b42318" if obj.is_blocked else "#119279")


@admin.register(ConversationMessage)
class ConversationMessageAdmin(MessageAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).conversation()


@admin.register(FAQ)
class FAQAdmin(ModelAdmin):
    list_display = ("question", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active", "created_at", "updated_at")
    search_fields = ("question", "answer")
    list_editable = ("is_active", "sort_order")
    inlines = [FAQVideoInline]


@admin.register(FAQVideo)
class FAQVideoAdmin(ModelAdmin):
    list_display = ("title", "faq", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active", "created_at", "updated_at")
    search_fields = ("title", "video_url", "faq__question")
    raw_id_fields = ("faq",)


@admin.register(Notification)
class NotificationAdmin(ModelAdmin):
    list_fullwidth = True
    list_display = ("subject", "recipient_email", "read_state", "related_request", "sent_at")
    list_filter = ("is_read", "sent_at", "created_at")
    search_fields = ("subject", "body", "recipient_email", "related_request__tracking_code")
    readonly_fields = ("created_at", "sent_at")
    raw_id_fields = ("recipient_user", "related_request")

    @admin.display(description="Read")
    def read_state(self, obj):
        return badge("Read" if obj.is_read else "Unread", "#15803d" if obj.is_read else "#1d4ed8")


@admin.register(Deal)
class DealAdmin(ModelAdmin):
    list_fullwidth = True
    list_display = ("request", "amount", "currency", "fee_snapshot", "status_badge", "payer", "ai_detected")
    list_filter = ("status", "currency", "payer", "ai_detected")
    search_fields = ("invoice_number", "payment_reference", "request__tracking_code")
    readonly_fields = ("platform_fee", "invoice_number", "created_at", "updated_at")
    raw_id_fields = ("request", "requester_user", "target_user")

    @admin.display(description="Fee")
    def fee_snapshot(self, obj):
        return f"{obj.platform_fee} {obj.currency}"

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            Deal.Status.PROPOSED: "#667085",
            Deal.Status.AGREED: "#1d4ed8",
            Deal.Status.PAYMENT_DUE: "#b45309",
            Deal.Status.PAID: "#15803d",
            Deal.Status.COMPLETED: "#0f766e",
            Deal.Status.CANCELLED: "#b42318",
        }
        return badge(obj.get_status_display(), colors.get(obj.status, "#475467"))


@admin.register(Subscription)
class SubscriptionAdmin(ModelAdmin):
    list_display = ("user", "request", "subscription_type", "is_active", "created_at")
    list_filter = ("subscription_type", "is_active", "created_at")
    search_fields = ("user__email", "request__tracking_code")
    raw_id_fields = ("user", "request")


@admin.register(SupportTicket)
class SupportTicketAdmin(ModelAdmin):
    list_fullwidth = True
    list_filter_submit = True
    list_display = (
        "tracking_code",
        "subject",
        "user",
        "status_badge",
        "priority",
        "assigned_to",
        "last_reply_at",
        "created_at",
    )
    list_filter = ("status", "priority", "created_at", "last_reply_at")
    search_fields = ("tracking_code", "subject", "message", "email", "user__email")
    raw_id_fields = ("user", "assigned_to")
    readonly_fields = ("tracking_code", "created_at", "updated_at", "last_reply_at")
    inlines = [SupportTicketReplyInline]
    fieldsets = (
        (
            "Ticket",
            {
                "fields": (
                    "tracking_code",
                    "user",
                    "email",
                    "subject",
                    "message",
                    "status",
                    "priority",
                    "assigned_to",
                )
            },
        ),
        ("Audit", {"fields": ("last_reply_at", "created_at", "updated_at")}),
    )

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            SupportTicket.Status.OPEN: "#1d4ed8",
            SupportTicket.Status.IN_PROGRESS: "#b45309",
            SupportTicket.Status.RESOLVED: "#15803d",
            SupportTicket.Status.CLOSED: "#667085",
        }
        return badge(obj.get_status_display(), colors.get(obj.status, "#475467"))

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in instances:
            if isinstance(obj, SupportTicketReply) and not obj.author_id:
                obj.author = request.user
                obj.email = getattr(request.user, "email", "") or obj.email
                if not obj.sender_type:
                    obj.sender_type = (
                        SupportTicketReply.SenderType.ADMIN
                        if request.user.is_superuser
                        else SupportTicketReply.SenderType.STAFF
                    )
            obj.save()
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()


@admin.register(SupportTicketReply)
class SupportTicketReplyAdmin(ModelAdmin):
    list_display = ("ticket", "sender_type", "author", "email", "created_at")
    list_filter = ("sender_type", "created_at")
    search_fields = ("ticket__tracking_code", "ticket__subject", "body", "email", "author__email")
    raw_id_fields = ("ticket", "author")
    readonly_fields = ("created_at",)


class OffensiveTermInline(TabularInline):
    model = OffensiveTerm
    extra = 0
    fields = ("term", "term_type", "language_code", "is_blocking", "is_active")


@admin.register(CensorCategory)
class CensorCategoryAdmin(ModelAdmin):
    list_display = ("name", "slug", "is_blocking", "created_at")
    list_filter = ("is_blocking", "created_at")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [OffensiveTermInline]


@admin.register(OffensiveTerm)
class OffensiveTermAdmin(ModelAdmin):
    list_fullwidth = True
    list_display = ("term", "category", "term_type", "language_code", "blocking_state", "created_at")
    list_filter = ("category", "term_type", "is_blocking", "is_active", "language_code")
    search_fields = ("term", "category__name")
    raw_id_fields = ("category",)
    actions = ["mark_active", "mark_inactive"]

    @admin.display(description="State")
    def blocking_state(self, obj):
        if not obj.is_active:
            return badge("Inactive", "#667085")
        return badge("Blocking" if obj.is_blocking else "Warning", "#b42318" if obj.is_blocking else "#b45309")

    @admin.action(description="Mark selected as active")
    def mark_active(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="Mark selected as inactive")
    def mark_inactive(self, request, queryset):
        queryset.update(is_active=False)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        try:
            from .censor_loader import invalidate_censor_cache

            invalidate_censor_cache()
        except Exception:
            pass


@admin.register(CensorLog)
class CensorLogAdmin(ModelAdmin):
    list_fullwidth = True
    list_display = ("id", "source", "blocked", "categories_display", "created_at")
    list_filter = ("source", "blocked", "created_at")
    search_fields = ("text_preview", "detected_terms")
    readonly_fields = ("source", "categories", "detected_terms", "blocked", "text_preview", "created_at")

    @admin.display(description="Categories")
    def categories_display(self, obj):
        return ", ".join(obj.categories or []) if obj.categories else "-"


@admin.register(CensorTrainingExample)
class CensorTrainingExampleAdmin(ModelAdmin):
    list_display = ("id", "is_toxic", "source", "score", "text_preview", "age")
    list_filter = ("is_toxic", "source", "created_at")
    search_fields = ("text",)
    readonly_fields = ("text", "is_toxic", "source", "score", "created_at")

    @admin.display(description="Text")
    def text_preview(self, obj):
        return (obj.text or "")[:80] + ("..." if len(obj.text or "") > 80 else "")

    @admin.display(description="Logged")
    def age(self, obj):
        return f"{timesince(obj.created_at)} ago"

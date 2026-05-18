from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from django.utils.timesince import timesince
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    ActiveUser,
    CeleryTaskError,
    EmailVerificationOTP,
    PasswordResetOTP,
    PendingVerificationUser,
    User,
    UserDevice,
)


def status_badge(label: str, *, tone: str) -> str:
    return format_html(
        '<span style="display:inline-flex;align-items:center;padding:0.2rem 0.65rem;'
        'border-radius:999px;background:{};color:white;font-weight:600;font-size:0.75rem;">{}</span>',
        tone,
        label,
    )


class UserDeviceInline(TabularInline):
    model = UserDevice
    extra = 0
    fields = ("device_type", "device_name", "active_state", "last_used_at", "token_preview")
    readonly_fields = ("active_state", "last_used_at", "token_preview")
    show_change_link = False

    @admin.display(description="Status")
    def active_state(self, obj):
        return status_badge("Active" if obj.is_active else "Stale", tone="#0f766e" if obj.is_active else "#b42318")

    @admin.display(description="FCM Token")
    def token_preview(self, obj):
        return f"{obj.fcm_token[:28]}…" if len(obj.fcm_token) > 28 else obj.fcm_token


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    list_fullwidth = True
    compressed_fields = True
    warn_unsaved_form = True
    list_filter_submit = True
    search_help_text = "Search by email, alias, first name, last name, or phone number."
    inlines = [UserDeviceInline]
    list_display = (
        "email",
        "identity_snapshot",
        "verification_state",
        "staff_state",
        "activity_state",
        "date_joined",
    )
    list_filter = ("is_email_verified", "is_phone_verified", "is_staff", "is_superuser", "is_active", "date_joined")
    search_fields = ("email", "alias_name", "first_name", "last_name", "phone_number")
    ordering = ("-date_joined",)
    readonly_fields = ("date_joined", "updated_at", "last_login", "last_seen")
    fieldsets = (
        (_("Account"), {"fields": ("email", "password")}),
        (
            _("Identity"),
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "alias_name",
                    "phone_number",
                    "profile_picture",
                )
            },
        ),
        (_("Verification"), {"fields": ("is_email_verified", "is_phone_verified", "last_seen")}),
        (
            _("Permissions"),
            {
                "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined", "updated_at")}),
    )
    add_fieldsets = (
        (
            _("Create user"),
            {
                "classes": ("tab",),
                "fields": ("email", "first_name", "last_name", "alias_name", "password1", "password2"),
            },
        ),
    )

    @admin.display(description="Identity")
    def identity_snapshot(self, obj):
        display_name = obj.alias_name or obj.get_full_name()
        phone = obj.phone_number or "No phone"
        return format_html(
            '<div><strong>{}</strong><br><span style="color:#667085;">{}</span></div>',
            display_name,
            phone,
        )

    @admin.display(description="Verified")
    def verification_state(self, obj):
        if obj.is_verified:
            label, tone = "Verified", "#119279"
        elif obj.is_email_verified or obj.is_phone_verified:
            label, tone = "Partial", "#b45309"
        else:
            label, tone = "Pending", "#b42318"
        return status_badge(label, tone=tone)

    @admin.display(description="Staff")
    def staff_state(self, obj):
        return status_badge("Staff" if obj.is_staff else "Member", tone="#1d4ed8" if obj.is_staff else "#475467")

    @admin.display(description="Active")
    def activity_state(self, obj):
        return status_badge("Active" if obj.is_active else "Disabled", tone="#0f766e" if obj.is_active else "#b42318")

    @admin.display(description="Last seen")
    def last_seen(self, obj):
        if not obj.last_login:
            return "Never"
        return f"{timesince(obj.last_login)} ago"


@admin.register(ActiveUser)
class ActiveUserAdmin(UserAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).active()


@admin.register(PendingVerificationUser)
class PendingVerificationUserAdmin(UserAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).unverified()


@admin.register(PasswordResetOTP)
class PasswordResetOTPAdmin(ModelAdmin):
    list_fullwidth = True
    list_display = ("email", "otp_code", "is_valid_now", "created_at", "expires_at")
    list_filter = ("created_at", "expires_at")
    search_fields = ("email",)
    readonly_fields = ("email", "otp_code", "created_at", "expires_at", "validity_window")

    @admin.display(description="Status")
    def is_valid_now(self, obj):
        return status_badge("Expired" if obj.is_expired else "Valid", tone="#b42318" if obj.is_expired else "#119279")

    @admin.display(description="Validity")
    def validity_window(self, obj):
        return f"Created {timesince(obj.created_at)} ago"


@admin.register(EmailVerificationOTP)
class EmailVerificationOTPAdmin(ModelAdmin):
    list_fullwidth = True
    list_display = ("user", "otp_code", "is_valid_now", "created_at", "expires_at")
    list_filter = ("created_at", "expires_at")
    search_fields = ("user__email", "user__alias_name")
    readonly_fields = ("user", "otp_code", "created_at", "expires_at")
    raw_id_fields = ("user",)

    @admin.display(description="Status")
    def is_valid_now(self, obj):
        return status_badge("Expired" if obj.is_expired else "Waiting", tone="#b42318" if obj.is_expired else "#1d4ed8")


@admin.register(CeleryTaskError)
class CeleryTaskErrorAdmin(ModelAdmin):
    list_fullwidth = True
    list_display = ("task_name", "timestamp", "exception_preview")
    list_filter = ("timestamp",)
    search_fields = ("task_name", "args", "kwargs", "exception")
    readonly_fields = ("task_name", "args", "kwargs", "exception", "timestamp")

    @admin.display(description="Exception")
    def exception_preview(self, obj):
        text = (obj.exception or "").strip()
        return text[:120] + ("..." if len(text) > 120 else "")


@admin.register(UserDevice)
class UserDeviceAdmin(ModelAdmin):
    list_fullwidth = True
    list_display = ("user", "device_type", "device_name", "active_state", "last_used_at", "created_at")
    list_filter = ("device_type", "is_active", "created_at")
    search_fields = ("user__email", "user__alias_name", "device_name", "fcm_token")
    readonly_fields = ("fcm_token", "created_at", "last_used_at", "active_state")
    raw_id_fields = ("user",)
    ordering = ("-last_used_at",)

    @admin.display(description="Status")
    def active_state(self, obj):
        return status_badge("Active" if obj.is_active else "Stale", tone="#0f766e" if obj.is_active else "#b42318")

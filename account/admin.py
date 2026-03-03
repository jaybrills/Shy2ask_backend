from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User, PasswordResetOTP, EmailVerificationOTP, CeleryTaskError


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Admin interface for the custom User model.
    """
    list_display = ('email', 'alias_name', 'first_name', 'last_name', 'phone_number', 'is_verified', 'is_staff', 'is_active', 'date_joined')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'date_joined')
    search_fields = ('email', 'alias_name', 'first_name', 'last_name', 'phone_number')
    ordering = ('-date_joined',)
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal info'), {
            'fields': ('first_name', 'last_name', 'alias_name', 'phone_number', 'profile_picture', 'is_verified')
        }),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Important dates'), {'fields': ('last_login', 'date_joined', 'updated_at')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'password1', 'password2'),
        }),
    )
    
    readonly_fields = ('date_joined', 'updated_at', 'last_login')


@admin.register(PasswordResetOTP)
class PasswordResetOTPAdmin(admin.ModelAdmin):
    list_display = ("email", "otp_code", "created_at", "expires_at")
    list_filter = ("created_at",)
    search_fields = ("email",)
    readonly_fields = ("email", "otp_code", "created_at", "expires_at")


@admin.register(EmailVerificationOTP)
class EmailVerificationOTPAdmin(admin.ModelAdmin):
    list_display = ("user", "otp_code", "created_at", "expires_at")
    list_filter = ("created_at",)
    search_fields = ("user__email",)
    readonly_fields = ("user", "otp_code", "created_at", "expires_at")
    raw_id_fields = ("user",)


@admin.register(CeleryTaskError)
class CeleryTaskErrorAdmin(admin.ModelAdmin):
    list_display = ('task_name', 'timestamp', 'exception')
    search_fields = ('task_name', 'args', 'kwargs', 'exception')
    readonly_fields = ('task_name', 'args', 'kwargs', 'exception', 'timestamp')
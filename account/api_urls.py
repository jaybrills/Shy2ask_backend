from django.urls import path

from .api_views import (
    CheckAliasView,
    CheckEmailView,
    DeviceRegisterView,
    DeviceUnregisterView,
    ForgotPasswordView,
    LoginView,
    ProfileMeView,
    RegisterView,
    ResendVerificationView,
    ResetPasswordView,
    UserNameByEmailView,
    UserListView,
    VerifyEmailView,
)
from .notification_views import (
    MarkAllReadView,
    MarkNotificationReadView,
    NotificationListView,
    UnreadCountView,
)


urlpatterns = [
    path("auth/register", RegisterView.as_view()),
    path("auth/register/", RegisterView.as_view()),
    path("auth/login", LoginView.as_view()),
    path("auth/login/", LoginView.as_view()),
    path("auth/forgot-password", ForgotPasswordView.as_view()),
    path("auth/forgot-password/", ForgotPasswordView.as_view()),
    path("auth/reset-password", ResetPasswordView.as_view()),
    path("auth/reset-password/", ResetPasswordView.as_view()),
    path("auth/verify-email", VerifyEmailView.as_view()),
    path("auth/verify-email/", VerifyEmailView.as_view()),
    path("auth/resend-verification", ResendVerificationView.as_view()),
    path("auth/resend-verification/", ResendVerificationView.as_view()),
    path("auth/check-email", CheckEmailView.as_view()),
    path("auth/check-email/", CheckEmailView.as_view()),
    path("auth/check-alias", CheckAliasView.as_view()),
    path("auth/check-alias/", CheckAliasView.as_view()),
    path("auth/user-name", UserNameByEmailView.as_view()),
    path("auth/user-name/", UserNameByEmailView.as_view()),
    path("profile/me", ProfileMeView.as_view()),
    path("profile/me/", ProfileMeView.as_view()),
    path("profile/users", UserListView.as_view()),
    path("profile/users/", UserListView.as_view()),
    path("profile/devices/register", DeviceRegisterView.as_view()),
    path("profile/devices/register/", DeviceRegisterView.as_view()),
    path("profile/devices/unregister", DeviceUnregisterView.as_view()),
    path("profile/devices/unregister/", DeviceUnregisterView.as_view()),

    # ── Notification history ──────────────────────────────────────────────
    path("notifications", NotificationListView.as_view()),
    path("notifications/", NotificationListView.as_view()),
    path("notifications/unread-count", UnreadCountView.as_view()),
    path("notifications/unread-count/", UnreadCountView.as_view()),
    path("notifications/mark-all-read", MarkAllReadView.as_view()),
    path("notifications/mark-all-read/", MarkAllReadView.as_view()),
    path("notifications/<int:pk>/read", MarkNotificationReadView.as_view()),
    path("notifications/<int:pk>/read/", MarkNotificationReadView.as_view()),
]

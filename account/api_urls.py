from django.urls import re_path

from .api_views import (
    CheckEmailView,
    ForgotPasswordView,
    LoginView,
    ProfileMeView,
    RegisterView,
    ResendVerificationView,
    ResetPasswordView,
    UserListView,
    VerifyEmailView,
)


urlpatterns = [
    re_path(r"^auth/register/?$", RegisterView.as_view()),
    re_path(r"^auth/login/?$", LoginView.as_view()),
    re_path(r"^auth/forgot-password/?$", ForgotPasswordView.as_view()),
    re_path(r"^auth/reset-password/?$", ResetPasswordView.as_view()),
    re_path(r"^auth/verify-email/?$", VerifyEmailView.as_view()),
    re_path(r"^auth/resend-verification/?$", ResendVerificationView.as_view()),
    re_path(r"^auth/check-email/?$", CheckEmailView.as_view()),
    re_path(r"^profile/me/?$", ProfileMeView.as_view()),
    re_path(r"^profile/users/?$", UserListView.as_view()),
]

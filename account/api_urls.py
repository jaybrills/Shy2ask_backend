from django.urls import path

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
    path("auth/register", RegisterView.as_view()),
    path("auth/login", LoginView.as_view()),
    path("auth/forgot-password", ForgotPasswordView.as_view()),
    path("auth/reset-password", ResetPasswordView.as_view()),
    path("auth/verify-email", VerifyEmailView.as_view()),
    path("auth/resend-verification", ResendVerificationView.as_view()),
    path("auth/check-email", CheckEmailView.as_view()),
    path("profile/me", ProfileMeView.as_view()),
    path("profile/users", UserListView.as_view()),
]
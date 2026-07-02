from rest_framework.permissions import BasePermission


class IsVerified(BasePermission):
    """
    Allows access only to users who have verified either their email or their phone number.
    Use this instead of IsAuthenticated on any endpoint that requires a fully active account.
    Verification endpoints (verify-email, verify-phone) must NOT use this — they use IsAuthenticated.
    """

    message = "Account not verified. Please verify your email or phone number."

    def has_permission(self, request, view):
        return (
            bool(request.user and request.user.is_authenticated)
            and request.user.is_verified
        )

"""
Django Ninja auth and profile API.
- Register, login (email only), forgot password, reset password (OTP), profile.
- List users (staff only) with pagination and filter.
"""
from typing import Optional

from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpRequest
from ninja import File, Router, Schema, UploadedFile
from ninja.security import HttpBearer
from rest_framework.authtoken.models import Token

from .models import User
from .services import (
    create_and_send_reset_otp,
    create_and_send_verification_otp,
    verify_otp_and_reset_password,
    verify_email_otp,
)
from .validators import validate_disposable_email

auth_router = Router(tags=["Auth"])
profile_router = Router(tags=["Profile"])


# ---------- Schemas ----------
class RegisterIn(Schema):
    email: str
    password: str
    first_name: str = ""
    last_name: str = ""
    alias_name: str = ""
    phone_number: str = ""


class RegisterOut(Schema):
    id: int
    email: str
    first_name: str
    last_name: str
    alias_name: str
    is_verified: bool
    token: str
    message: str = "Please verify your email with the OTP sent to your inbox."


class LoginIn(Schema):
    email: str
    password: str


class LoginOut(Schema):
    token: str
    user: dict


class VerifyEmailIn(Schema):
    email: str
    otp_code: str


class VerifyEmailOut(Schema):
    message: str
    user: dict


class ResendVerificationIn(Schema):
    email: str


class ResendVerificationOut(Schema):
    message: str


class CheckEmailIn(Schema):
    email: str


class CheckEmailOut(Schema):
    is_available: bool
    message: str


class ForgotPasswordIn(Schema):
    email: str


class ForgotPasswordOut(Schema):
    message: str


class ResetPasswordIn(Schema):
    email: str
    otp: str
    new_password: str


class ResetPasswordOut(Schema):
    message: str


class ProfileOut(Schema):
    id: int
    email: str
    first_name: str
    last_name: str
    alias_name: str
    phone_number: str
    profile_picture: Optional[str] = None
    is_verified: bool
    date_joined: str
    updated_at: str


class ProfileUpdateIn(Schema):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    alias_name: Optional[str] = None
    phone_number: Optional[str] = None


class UserListItem(Schema):
    id: int
    email: str
    first_name: str
    last_name: str
    alias_name: str
    is_active: bool
    date_joined: str


class PaginatedUsers(Schema):
    count: int
    limit: int
    offset: int
    items: list[UserListItem]


# ---------- Auth: Bearer token ----------
class AuthBearer(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str):
        t = Token.objects.filter(key=token).select_related("user").first()
        if t and t.user.is_active:
            return t.user
        return None


# ---------- Auth endpoints ----------
@auth_router.post("/register", response={201: RegisterOut, 400: dict})
def register(request, payload: RegisterIn):
    """Register a new user. Email verification OTP is sent; verify with /auth/verify-email."""
    try:
        validate_disposable_email(payload.email)
    except ValidationError as e:
        return 400, {"detail": str(e.message)}

    existing = User.objects.filter(email__iexact=payload.email).first()
    if existing:
        if not existing.is_verified:
            create_and_send_verification_otp(existing)
            token, _ = Token.objects.get_or_create(user=existing)
            return 201, {
                "id": existing.id,
                "email": existing.email,
                "first_name": existing.first_name,
                "last_name": existing.last_name,
                "alias_name": existing.alias_name,
                "is_verified": False,
                "token": token.key,
                "message": "Verification OTP resent. Please verify your email.",
            }
        return 400, {"detail": "A user with this email already exists."}
    user = User.objects.create_user(
        email=payload.email,
        password=payload.password,
        first_name=payload.first_name or "",
        last_name=payload.last_name or "",
        alias_name=payload.alias_name or "",
        phone_number=payload.phone_number or "",
    )
    user.is_verified = False
    user.save(update_fields=["is_verified"])
    create_and_send_verification_otp(user)
    token, _ = Token.objects.get_or_create(user=user)
    return 201, {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "alias_name": user.alias_name,
        "is_verified": False,
        "token": token.key,
        "message": "Please verify your email with the OTP sent to your inbox.",
    }


@auth_router.post("/login", response={200: LoginOut, 401: dict, 403: dict})
def login(request, payload: LoginIn):
    """Login with email and password. Email must be verified first."""
    user = authenticate(
        request,
        username=payload.email,
        password=payload.password,
    )
    if user is None or not user.is_active:
        return 401, {"detail": "Invalid email or password."}
    if not getattr(user, "is_verified", True):
        return 403, {
            "detail": "Please verify your email first. Check your inbox for the OTP.",
            "code": "email_not_verified",
        }
    token, _ = Token.objects.get_or_create(user=user)
    return 200, {
        "token": token.key,
        "user": {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "alias_name": user.alias_name,
            "phone_number": user.phone_number,
            "is_verified": user.is_verified,
        },
    }


@auth_router.post("/forgot-password", response={200: ForgotPasswordOut, 400: dict})
def forgot_password(request, payload: ForgotPasswordIn):
    """Send OTP to email for password reset. Always returns 200 to avoid email enumeration."""
    create_and_send_reset_otp(payload.email)
    return 200, {"message": "If an account exists for this email, a reset code has been sent."}


@auth_router.post("/reset-password", response={200: ResetPasswordOut, 400: dict})
def reset_password(request, payload: ResetPasswordIn):
    """Reset password using email + OTP from forgot-password email."""
    if len(payload.new_password) < 8:
        return 400, {"detail": "Password must be at least 8 characters."}
    ok = verify_otp_and_reset_password(
        payload.email, payload.otp, payload.new_password
    )
    if not ok:
        return 400, {"detail": "Invalid or expired OTP. Request a new code."}
    return 200, {"message": "Password has been reset. You can now log in."}


@auth_router.post("/verify-email", response={200: VerifyEmailOut, 400: dict})
def verify_email(request, payload: VerifyEmailIn):
    """Verify email with OTP sent after register. Requires email + otp_code."""
    try:
        validate_disposable_email(payload.email)
    except ValidationError as e:
        return 400, {"detail": str(e.message)}
    
    user = verify_email_otp(payload.email, payload.otp_code)
    if not user:
        return 400, {"detail": "Invalid or expired OTP code. Request a new one via resend-verification."}
    return 200, {
        "message": "Email verified successfully.",
        "user": {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "alias_name": user.alias_name,
            "phone_number": user.phone_number,
            "is_verified": user.is_verified,
        },
    }


@auth_router.post("/resend-verification", response={200: ResendVerificationOut, 400: dict})
def resend_verification(request, payload: ResendVerificationIn):
    """Resend email verification OTP. Use if user did not receive or OTP expired."""
    try:
        validate_disposable_email(payload.email)
    except ValidationError as e:
        return 400, {"detail": str(e.message)}
        
    user = User.objects.filter(email__iexact=payload.email.strip()).first()
    if not user:
        return 200, {"message": "If an account exists for this email, a verification code has been sent."}
    if user.is_verified:
        return 400, {"detail": "Email is already verified."}
    create_and_send_verification_otp(user)
    return 200, {"message": "Verification code sent. Check your email."}


@auth_router.post("/check-email", response={200: CheckEmailOut, 400: dict})
def check_email(request, payload: CheckEmailIn):
    """Check if an email is available for registration and valid."""
    try:
        validate_disposable_email(payload.email)
    except ValidationError as e:
        return 200, {
            "is_available": False,
            "message": str(e.message)
        }

    existing = User.objects.filter(email__iexact=payload.email).exists()
    if existing:
        return 200, {
            "is_available": False,
            "message": "This email is already registered."
        }
    
    return 200, {
        "is_available": True,
        "message": "Email is available."
    }


# ---------- Profile (authenticated) ----------
def _profile_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "alias_name": user.alias_name,
        "phone_number": user.phone_number,
        "profile_picture": user.profile_picture.url if user.profile_picture else None,
        "is_verified": getattr(user, "is_verified", False),
        "date_joined": user.date_joined.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }


@profile_router.get("/me", response={200: ProfileOut}, auth=AuthBearer())
def profile_me(request):
    """Get current user profile."""
    return 200, _profile_to_dict(request.auth)


@profile_router.patch("/me", response={200: ProfileOut, 400: dict}, auth=AuthBearer())
def profile_update(
    request,
    payload: ProfileUpdateIn,
    profile_picture: Optional[UploadedFile] = File(None),
):
    """Update current user profile. Optionally upload profile_picture (multipart)."""
    user = request.auth
    if payload.first_name is not None:
        user.first_name = payload.first_name
    if payload.last_name is not None:
        user.last_name = payload.last_name
    if payload.alias_name is not None:
        user.alias_name = payload.alias_name
    if payload.phone_number is not None:
        user.phone_number = payload.phone_number
    if profile_picture:
        user.profile_picture = profile_picture
    try:
        user.save()
    except Exception as e:
        return 400, {"detail": str(e)}
    return 200, _profile_to_dict(user)


# ---------- List users (staff only): pagination + filter ----------
@profile_router.get(
    "/users",
    response={200: PaginatedUsers, 403: dict},
    auth=AuthBearer(),
)
def list_users(request, limit: int = 20, offset: int = 0, search: Optional[str] = None):
    """
    List users with pagination and optional search (staff only).
    Query: limit, offset, search (email, first_name, last_name, alias_name).
    """
    if not getattr(request.auth, "is_staff", False):
        return 403, {"detail": "Staff only."}
    qs = User.objects.all().order_by("-date_joined")
    if search and search.strip():
        s = search.strip()
        qs = qs.filter(
            Q(email__icontains=s)
            | Q(first_name__icontains=s)
            | Q(last_name__icontains=s)
            | Q(alias_name__icontains=s)
        )
    count = qs.count()
    items = qs[offset : offset + limit]
    return 200, {
        "count": count,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": u.id,
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "alias_name": u.alias_name,
                "is_active": u.is_active,
                "date_joined": u.date_joined.isoformat(),
            }
            for u in items
        ],
    }

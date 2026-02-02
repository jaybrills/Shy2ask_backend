"""Auth services: OTP generation, email sending, token management."""
import random
import string
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone


def generate_otp(length=6):
    return "".join(random.choices(string.digits, k=length))


def _from_email():
    return getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@shy2ask.com")


def send_otp_email(email: str, otp: str):
    """Send password reset OTP email (uses EMAIL_* from env)."""
    subject = "Shy2Ask – Password reset code"
    body = f"Your password reset code is: {otp}\n\nIt is valid for 15 minutes.\n\nIf you did not request this, ignore this email."
    send_mail(
        subject,
        body,
        _from_email(),
        [email],
        fail_silently=False,
    )


def send_verification_email(email: str, otp: str):
    """Send email verification OTP (uses EMAIL_* from env)."""
    subject = "Shy2Ask – Verify your email"
    body = f"Your email verification code is: {otp}\n\nIt is valid for 10 minutes.\n\nIf you did not create an account, ignore this email."
    send_mail(
        subject,
        body,
        _from_email(),
        [email],
        fail_silently=False,
    )


def create_and_send_reset_otp(email: str):
    from .models import PasswordResetOTP, User

    email = User.objects.normalize_email(email)
    user = User.objects.filter(email=email).first()
    if not user:
        return None  # Don't reveal if email exists
    otp = generate_otp(6)
    expires_at = timezone.now() + timedelta(minutes=15)
    PasswordResetOTP.objects.create(email=email, otp_code=otp, expires_at=expires_at)
    send_otp_email(email, otp)
    return otp  # For tests; production might not return it


def verify_otp_and_reset_password(email: str, otp_code: str, new_password: str):
    from .models import PasswordResetOTP, User

    email = User.objects.normalize_email(email)
    now = timezone.now()
    record = (
        PasswordResetOTP.objects.filter(
            email=email, otp_code=otp_code, expires_at__gt=now
        )
        .order_by("-created_at")
        .first()
    )
    if not record:
        return False
    user = User.objects.filter(email=email).first()
    if not user:
        return False
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    record.delete()
    return True


# ---------- Email verification (like Storemate) ----------
def create_and_send_verification_otp(user):
    """Create email verification OTP for user and send email. Returns OTP record."""
    from .models import EmailVerificationOTP

    otp_code = generate_otp(6)
    expires_at = timezone.now() + timedelta(minutes=10)
    EmailVerificationOTP.objects.filter(user=user).delete()
    record = EmailVerificationOTP.objects.create(
        user=user,
        otp_code=otp_code,
        expires_at=expires_at,
    )
    send_verification_email(user.email, otp_code)
    return record


def verify_email_otp(email: str, otp_code: str):
    """
    Verify email OTP. If valid, mark user as verified and return user; else return None.
    """
    from .models import EmailVerificationOTP, User

    email = User.objects.normalize_email(email)
    user = User.objects.filter(email=email).first()
    if not user:
        return None
    now = timezone.now()
    record = (
        EmailVerificationOTP.objects.filter(
            user=user,
            otp_code=otp_code.strip(),
            expires_at__gt=now,
        )
        .order_by("-created_at")
        .first()
    )
    if not record:
        return None
    user.is_verified = True
    user.save(update_fields=["is_verified", "updated_at"])
    record.delete()
    return user

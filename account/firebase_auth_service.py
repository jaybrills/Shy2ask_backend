"""
Firebase Auth service — verify ID tokens and resolve/create local users.

Flow:
  1. Mobile SDK signs in via Google, Apple, or Phone → receives a Firebase ID token.
  2. Token is sent to POST /api/auth/firebase-login.
  3. verify_firebase_token() validates it against Firebase (checks expiry + revocation).
  4. get_firebase_login_result() dispatches to the correct handler by provider.

Provider behaviour:
  - google.com / apple.com  →  find-or-create user, set is_email_verified=True
  - phone                   →  find existing user by SocialAccount or phone_number.
                               If not found returns (None, True) — caller must redirect
                               frontend to complete-phone-registration.

Security:
  - check_revoked=True detects tokens from deleted/disabled Firebase accounts.
  - email_verified is required before auto-linking to an existing email account
    to prevent account-takeover via an unverified provider email.
  - Phone number collision links the provider to the existing account safely.
"""
import logging

import firebase_admin.auth
from django.db import transaction

from account.firebase import get_firebase_app
from account.models import SocialAccount, User

logger = logging.getLogger(__name__)

_SOCIAL_PROVIDER_MAP = {
    "google.com": SocialAccount.PROVIDER_GOOGLE,
    "apple.com": SocialAccount.PROVIDER_APPLE,
}


def verify_firebase_token(id_token: str) -> dict:
    """
    Validate a Firebase ID token and return the decoded claims.

    Raises:
        firebase_admin.auth.ExpiredIdTokenError   — token has expired
        firebase_admin.auth.RevokedIdTokenError   — token was revoked
        firebase_admin.auth.InvalidIdTokenError   — malformed / wrong project
        RuntimeError                              — Firebase not configured
    """
    app = get_firebase_app()
    if app is None:
        raise RuntimeError("Firebase is not configured on this server.")
    return firebase_admin.auth.verify_id_token(id_token, app=app, check_revoked=True)


def get_firebase_login_result(decoded_token: dict) -> tuple:
    """
    Unified entry point for all Firebase providers.

    Returns (user, is_new_user).
      - Google / Apple: user is always a User instance.
      - Phone (existing): user is a User instance, is_new_user=False.
      - Phone (new):      user is None, is_new_user=True.
        Caller must return { is_new_user: true, phone_number } and redirect
        frontend to POST /api/auth/complete-phone-registration.

    Raises:
        ValueError        — unsupported provider
        PermissionError   — account deactivated
    """
    sign_in_provider: str = decoded_token.get("firebase", {}).get("sign_in_provider", "")

    if sign_in_provider == "phone":
        return _handle_phone_login(decoded_token)

    return _handle_social_login(decoded_token)


# ── Phone ─────────────────────────────────────────────────────────────────────

def _handle_phone_login(decoded_token: dict) -> tuple:
    """
    Look up an existing user by SocialAccount (UID) or phone_number.
    Returns (None, True) for brand-new phone users — no user is created here.
    """
    uid: str = decoded_token["uid"]
    phone_number: str = decoded_token.get("phone_number", "")

    with transaction.atomic():
        # 1. Existing SocialAccount (repeat login — fastest path)
        try:
            social = (
                SocialAccount.objects
                .select_related("user")
                .select_for_update()
                .get(provider=SocialAccount.PROVIDER_PHONE, provider_uid=uid)
            )
            user = social.user
            if not user.is_active:
                raise PermissionError("This account has been deactivated.")
            logger.info("Firebase phone login: existing account uid=%s user_id=%s", uid, user.id)
            return user, False
        except SocialAccount.DoesNotExist:
            pass

        # 2. Existing user matched by phone_number (phone re-used on new device)
        if phone_number:
            user = (
                User.objects
                .filter(phone_number=phone_number)
                .select_for_update()
                .first()
            )
            if user is not None:
                if not user.is_active:
                    raise PermissionError("This account has been deactivated.")
                SocialAccount.objects.create(
                    user=user,
                    provider=SocialAccount.PROVIDER_PHONE,
                    provider_uid=uid,
                    email="",
                )
                user.is_phone_verified = True
                user.save(update_fields=["is_phone_verified", "updated_at"])
                logger.info(
                    "Firebase phone login: linked phone to existing user_id=%s (phone match)",
                    user.id,
                )
                return user, False

        # 3. New phone user — do NOT create here, signal frontend
        logger.info("Firebase phone login: new phone user uid=%s phone=%s", uid, phone_number)
        return None, True


# ── Google / Apple ────────────────────────────────────────────────────────────

def _handle_social_login(decoded_token: dict) -> tuple:
    """
    Find or create a user from a Google or Apple Firebase token.

    Lookup order:
      1. Existing SocialAccount  →  return its linked user (fast path on repeat logins)
      2. Existing User by email  →  link provider, return user (email collision)
         — only when email_verified=True in the token to prevent account-takeover
      3. Create new User + SocialAccount  (first-time social signup)
    """
    uid: str = decoded_token["uid"]
    email: str = (decoded_token.get("email") or "").lower().strip()
    email_verified: bool = bool(decoded_token.get("email_verified", False))
    sign_in_provider: str = decoded_token.get("firebase", {}).get("sign_in_provider", "")

    provider = _SOCIAL_PROVIDER_MAP.get(sign_in_provider)
    if not provider:
        raise ValueError(
            f"Unsupported sign-in provider: '{sign_in_provider}'. Supported: google.com, apple.com, phone"
        )

    with transaction.atomic():
        # 1. Already linked
        try:
            social = (
                SocialAccount.objects
                .select_related("user")
                .select_for_update()
                .get(provider=provider, provider_uid=uid)
            )
            user = social.user
            if not user.is_active:
                raise PermissionError("This account has been deactivated.")
            logger.info(
                "Firebase social login: existing account uid=%s provider=%s user_id=%s",
                uid, provider, user.id,
            )
            return user, False
        except SocialAccount.DoesNotExist:
            pass

        # 2. Email collision — link to existing account
        user = None
        if email and email_verified:
            user = (
                User.objects
                .filter(email=email)
                .select_for_update()
                .first()
            )
            if user is not None:
                if not user.is_active:
                    raise PermissionError("This account has been deactivated.")
                SocialAccount.objects.create(
                    user=user,
                    provider=provider,
                    provider_uid=uid,
                    email=email,
                )
                logger.info(
                    "Firebase social login: linked %s to existing user_id=%s (email match)",
                    provider, user.id,
                )
                return user, False

        # 3. Brand-new user
        user = _create_social_user(decoded_token)
        SocialAccount.objects.create(
            user=user,
            provider=provider,
            provider_uid=uid,
            email=email,
        )
        logger.info("Firebase social login: created new user_id=%s via %s", user.id, provider)
        return user, True


def handle_google_signup(decoded_token: dict) -> tuple[User, bool]:
    """
    Create or return an existing user from a Google Firebase token.

    Returns:
        (user, is_new_user) — is_new_user is False when the account already existed.

    Raises:
        ValueError        — wrong provider, missing/unverified email
        PermissionError   — account deactivated
    """
    sign_in_provider: str = decoded_token.get("firebase", {}).get("sign_in_provider", "")
    if sign_in_provider != "google.com":
        raise ValueError("This endpoint only accepts Google authentication tokens.")

    uid: str = decoded_token["uid"]
    email: str = (decoded_token.get("email") or "").lower().strip()
    email_verified: bool = bool(decoded_token.get("email_verified", False))

    if not email:
        raise ValueError("Google account must have an email address.")
    if not email_verified:
        raise ValueError("Google account email is not verified.")

    with transaction.atomic():
        social = (
            SocialAccount.objects
            .filter(provider=SocialAccount.PROVIDER_GOOGLE, provider_uid=uid)
            .select_related("user")
            .select_for_update()
            .first()
        )
        if social is not None:
            if not social.user.is_active:
                raise PermissionError("This account has been deactivated.")
            logger.info("Google signup: existing user_id=%s email=%s", social.user.id, email)
            return social.user, False

        existing_user = (
            User.objects
            .filter(email=email)
            .select_for_update()
            .first()
        )
        if existing_user is not None:
            if not existing_user.is_active:
                raise PermissionError("This account has been deactivated.")
            # Link Google to the existing account so future Google logins work.
            SocialAccount.objects.create(
                user=existing_user,
                provider=SocialAccount.PROVIDER_GOOGLE,
                provider_uid=uid,
                email=email,
            )
            logger.info("Google signup: linked Google to existing user_id=%s email=%s", existing_user.id, email)
            return existing_user, False

        user = _create_social_user(decoded_token)
        SocialAccount.objects.create(
            user=user,
            provider=SocialAccount.PROVIDER_GOOGLE,
            provider_uid=uid,
            email=email,
        )

    logger.info("Google signup: created new user_id=%s email=%s", user.id, email)
    return user, True


def _create_social_user(decoded_token: dict) -> User:
    email: str = (decoded_token.get("email") or "").lower().strip()
    display_name: str = decoded_token.get("name") or ""
    parts = display_name.split(" ", 1)
    first_name = parts[0] if parts else ""
    last_name = parts[1] if len(parts) > 1 else ""

    user = User(
        email=email,
        first_name=first_name,
        last_name=last_name,
        is_email_verified=True,   # Firebase already verified the email
        is_phone_verified=False,  # Phone must still be verified separately
    )
    user.set_unusable_password()
    user.save()
    return user

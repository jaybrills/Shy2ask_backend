"""
Firebase Auth service — verify ID tokens and resolve/create local users.

Flow:
  1. Mobile SDK signs in via Google or Apple → receives a Firebase ID token.
  2. Token is sent to POST /api/auth/firebase-login.
  3. verify_firebase_token() validates it against Firebase (checks expiry + revocation).
  4. get_or_create_user_from_firebase() finds or creates the local User and links
     the provider via SocialAccount.

Security:
  - check_revoked=True detects tokens from deleted/disabled Firebase accounts.
  - email_verified is required before auto-linking to an existing email account
    to prevent account-takeover via an unverified provider email.
"""
import logging

import firebase_admin.auth
from django.db import transaction

from account.firebase import get_firebase_app
from account.models import SocialAccount, User

logger = logging.getLogger(__name__)

_FIREBASE_PROVIDER_MAP = {
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


def get_or_create_user_from_firebase(decoded_token: dict) -> tuple[User, bool]:
    """
    Return (user, created).

    Lookup order:
      1. Existing SocialAccount  →  return its linked user (fast path on repeat logins)
      2. Existing User by email  →  link provider, return user (email collision)
         — only when email_verified=True in the token to prevent account-takeover
      3. Create new User + SocialAccount  (first-time social signup)

    The whole operation runs inside a transaction with select_for_update on any
    existing user row so concurrent requests for the same UID cannot create duplicates.
    """
    uid: str = decoded_token["uid"]
    email: str = (decoded_token.get("email") or "").lower().strip()
    email_verified: bool = bool(decoded_token.get("email_verified", False))
    sign_in_provider: str = decoded_token.get("firebase", {}).get("sign_in_provider", "")

    provider = _FIREBASE_PROVIDER_MAP.get(sign_in_provider)
    if not provider:
        raise ValueError(f"Unsupported sign-in provider: '{sign_in_provider}'. Supported: google.com, apple.com")

    with transaction.atomic():
        # ── 1. Already linked ─────────────────────────────────────────────
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
            logger.info("Firebase login: existing social account uid=%s provider=%s user_id=%s", uid, provider, user.id)
            return user, False
        except SocialAccount.DoesNotExist:
            pass

        # ── 2. Email collision — link to existing account ─────────────────
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
                    "Firebase login: linked %s to existing user_id=%s (email match)",
                    provider, user.id,
                )
                return user, False

        # ── 3. Brand-new user ─────────────────────────────────────────────
        user = _create_social_user(decoded_token)
        SocialAccount.objects.create(
            user=user,
            provider=provider,
            provider_uid=uid,
            email=email,
        )
        logger.info("Firebase login: created new user_id=%s via %s", user.id, provider)
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
        is_verified=True,  # Firebase already verified the identity
    )
    user.set_unusable_password()  # social users cannot use email/password login
    user.save()
    return user

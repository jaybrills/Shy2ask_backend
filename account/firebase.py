"""
Firebase Admin SDK — initializer and push-notification helpers.

Lazy singleton: the app is initialised on first use, not at import time,
so a missing or misconfigured service-account file only causes failures
at call-time rather than at server startup.
"""
import logging
import os

import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings

logger = logging.getLogger(__name__)

_firebase_app: firebase_admin.App | None = None


def get_firebase_app() -> firebase_admin.App | None:
    """Return the initialised Firebase app, or None if FCM is not configured."""
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    service_account_path = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_PATH", "")
    if not service_account_path:
        logger.warning("FIREBASE_SERVICE_ACCOUNT_PATH not set — push notifications disabled.")
        return None

    full_path = os.path.join(settings.BASE_DIR, service_account_path)
    if not os.path.exists(full_path):
        logger.error("Firebase service account file not found: %s", full_path)
        return None

    try:
        cred = credentials.Certificate(full_path)
        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialised successfully.")
    except Exception:
        logger.exception("Firebase initialisation failed.")
        return None

    return _firebase_app


def _build_message(*, token: str, title: str, body: str, data: dict) -> messaging.Message:
    return messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data={str(k): str(v) for k, v in data.items()},
        token=token,
        android=messaging.AndroidConfig(priority="high"),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default"),
            )
        ),
    )


def send_to_user_devices(*, user_id: int, title: str, body: str, data: dict | None = None) -> dict:
    """
    Send a push notification to every active device registered for a user.

    Uses FCM's send_each (batch) so a single HTTP round-trip covers all devices.
    Stale/unregistered tokens are deactivated in bulk after the batch completes.

    Returns a stats dict:
        {sent: int, failed: int, deactivated: int, skipped: bool}
    """
    from account.models import UserDevice  # local import avoids circular dependency

    stats = {"sent": 0, "failed": 0, "deactivated": 0, "skipped": False}

    app = get_firebase_app()
    if app is None:
        stats["skipped"] = True
        return stats

    devices = list(
        UserDevice.objects.active()
        .filter(user_id=user_id)
        .values("id", "fcm_token")
    )
    if not devices:
        stats["skipped"] = True
        return stats

    normalized_data = {str(k): str(v) for k, v in (data or {}).items()}
    messages = [
        _build_message(token=d["fcm_token"], title=title, body=body, data=normalized_data)
        for d in devices
    ]

    try:
        batch_response: messaging.BatchResponse = messaging.send_each(messages)
    except Exception:
        logger.exception("FCM send_each failed for user_id=%s", user_id)
        raise

    stale_ids: list[int] = []
    for device, response in zip(devices, batch_response.responses):
        if response.success:
            stats["sent"] += 1
        else:
            stats["failed"] += 1
            if isinstance(response.exception, messaging.UnregisteredError):
                stale_ids.append(device["id"])
                stats["deactivated"] += 1
            else:
                logger.warning(
                    "FCM delivery failed for device_id=%s: %s",
                    device["id"],
                    response.exception,
                )

    if stale_ids:
        UserDevice.objects.deactivate_tokens(stale_ids)
        logger.info("Deactivated %d stale FCM token(s) for user_id=%s", len(stale_ids), user_id)

    return stats

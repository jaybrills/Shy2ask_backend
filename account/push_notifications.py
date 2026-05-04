"""
Push notification template registry — 18 active notifications.

Only RED (critical) and ORANGE (important) notifications are implemented.
White/informational rows from the spec are intentionally excluded.

Priority:
  HIGH   = red rows   — action-required / critical events
  MEDIUM = orange rows — follow-up / warnings

Usage
-----
    from account.push_notifications import N, REGISTRY
    from account.tasks import send_push_notification_task

    title, body = N.REQUEST_COMPLETED.render()
    send_push_notification_task.delay(
        user_id=user.id,
        title=title,
        body=body,
        data={"type": N.REQUEST_COMPLETED.key, "request_id": str(request.id)},
    )
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Priority(str, Enum):
    HIGH = "high"      # red in spec
    MEDIUM = "medium"  # orange in spec


@dataclass(frozen=True)
class PushTemplate:
    key: str
    title: str
    body: str
    priority: Priority

    def render(self, **kwargs) -> tuple[str, str]:
        """
        Interpolate {placeholders} and return (title, body).
        Missing keys fall back silently — placeholder stays as-is.
        """
        try:
            rendered_title = self.title.format(**kwargs)
        except KeyError:
            rendered_title = self.title
        try:
            rendered_body = self.body.format(**kwargs)
        except KeyError:
            rendered_body = self.body
        return rendered_title, rendered_body


class N:
    """All active push notification templates. Access as N.REQUEST_COMPLETED etc."""

    # ── RED — critical / action-required ──────────────────────────────────────

    REQUEST_SUBMITTED = PushTemplate(                   # #5
        key="request_submitted",
        title="Request Submitted",
        body="Your request is under review.",
        priority=Priority.HIGH,
    )

    REQUEST_IN_PROGRESS = PushTemplate(                 # #6
        key="request_in_progress",
        title="Request In Progress",
        body="Good news — your request is now being processed.",
        priority=Priority.HIGH,
    )

    REQUEST_COMPLETED = PushTemplate(                   # #7
        key="request_completed",
        title="Request Completed",
        body="Your request has been completed. Tap to view the response.",
        priority=Priority.HIGH,
    )

    REQUEST_REJECTED = PushTemplate(                    # #8
        key="request_rejected",
        title="Request Not Accepted",
        body="Your request was not accepted. Tap to see the details.",
        priority=Priority.HIGH,
    )

    NEW_MESSAGE = PushTemplate(                         # #9
        key="new_message",
        title="New Message",
        body="You have a new message on your request.",
        priority=Priority.HIGH,
    )

    SUBSCRIPTION_ACTIVATED = PushTemplate(              # #20
        key="subscription_activated",
        title="Subscription Active",
        body="Your subscription is now active. Enjoy Shy2Ask!",
        priority=Priority.HIGH,
    )

    PAYMENT_FAILED = PushTemplate(                      # #21
        key="payment_failed",
        title="Payment Failed",
        body="Your payment failed. Please update your payment method.",
        priority=Priority.HIGH,
    )

    SUBSCRIPTION_CANCELED = PushTemplate(               # #22
        key="subscription_canceled",
        title="Subscription Canceled",
        body="Your subscription has been canceled.",
        priority=Priority.HIGH,
    )

    TICKET_STAFF_REPLY = PushTemplate(                  # #28
        key="ticket_staff_reply",
        title="Staff Replied to Your Ticket",
        body="A staff member replied to your support ticket.",
        priority=Priority.HIGH,
    )

    # ── ORANGE — important follow-ups / warnings ───────────────────────────────

    MESSAGE_REPLIED = PushTemplate(                     # #10
        key="message_replied",
        title="New Reply",
        body="Someone replied to your message.",
        priority=Priority.MEDIUM,
    )

    SUBSCRIPTION_UPDATE = PushTemplate(                 # #12
        key="subscription_update",
        title="Request Updated",
        body="A request you're following has a new update.",
        priority=Priority.MEDIUM,
    )

    DEAL_ALERT = PushTemplate(                          # #13
        key="deal_alert",
        title="Deal Alert",
        body="A new deal has been detected on a request you follow.",
        priority=Priority.MEDIUM,
    )

    TRIAL_ENDING_SOON = PushTemplate(                   # #23
        key="trial_ending_soon",
        title="Trial Ending Soon",
        body="Your free trial ends in {days} day(s). Subscribe to keep access.",
        priority=Priority.MEDIUM,
    )

    SUBSCRIPTION_PAST_DUE = PushTemplate(               # #25
        key="subscription_past_due",
        title="Account Past Due",
        body="Your account is past due. Update billing to avoid interruption.",
        priority=Priority.MEDIUM,
    )

    SUBSCRIPTION_RENEWED = PushTemplate(                # #26
        key="subscription_renewed",
        title="Subscription Renewed",
        body="Your subscription has been renewed.",
        priority=Priority.MEDIUM,
    )

    TICKET_RESOLVED = PushTemplate(                     # #29
        key="ticket_resolved",
        title="Ticket Resolved",
        body="Your support ticket has been marked as resolved.",
        priority=Priority.MEDIUM,
    )

    TICKET_CLOSED = PushTemplate(                       # #30
        key="ticket_closed",
        title="Ticket Closed",
        body="Your support ticket has been closed.",
        priority=Priority.MEDIUM,
    )

    HIGH_PRIORITY_TICKET = PushTemplate(                # #32
        key="high_priority_ticket",
        title="High Priority Support Ticket",
        body="A high-priority support ticket needs attention.",
        priority=Priority.MEDIUM,
    )


# Flat lookup used by the test_push command and admin action
REGISTRY: dict[str, PushTemplate] = {
    v.key: v
    for attr in dir(N)
    if not attr.startswith("_") and isinstance(v := getattr(N, attr), PushTemplate)
}

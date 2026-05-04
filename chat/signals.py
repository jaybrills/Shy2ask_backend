"""
Django signals for push notifications on model state changes.

Handles events that happen outside the normal request cycle
(admin actions, management commands, direct ORM calls).

Covered here:
  #29 — Ticket status → RESOLVED  (push to ticket owner)
  #30 — Ticket status → CLOSED    (push to ticket owner)
"""
import logging

from django.db.models.signals import pre_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(pre_save, sender="chat.SupportTicket")
def on_ticket_status_change(sender, instance, **kwargs):
    """
    Detect RESOLVED / CLOSED transitions and fire push to the ticket owner.
    pre_save lets us compare old vs new status without an extra DB query.
    """
    if not instance.pk:
        return  # new ticket — handled in SupportTicket.save()

    try:
        from .models import SupportTicket
        old = SupportTicket.objects.filter(pk=instance.pk).values("status").first()
        if not old:
            return

        old_status = old["status"]
        new_status = instance.status

        if old_status == new_status:
            return

        owner_id = instance.user_id
        if not owner_id:
            return

        from account.push_notifications import N
        from account.tasks import send_push_notification_task

        if new_status == SupportTicket.Status.RESOLVED:
            title, body = N.TICKET_RESOLVED.render()
            send_push_notification_task.delay(
                user_id=owner_id,
                title=title,
                body=body,
                data={"type": N.TICKET_RESOLVED.key, "ticket_id": str(instance.pk)},
            )
        elif new_status == SupportTicket.Status.CLOSED:
            title, body = N.TICKET_CLOSED.render()
            send_push_notification_task.delay(
                user_id=owner_id,
                title=title,
                body=body,
                data={"type": N.TICKET_CLOSED.key, "ticket_id": str(instance.pk)},
            )
    except Exception:
        logger.exception("Signal push failed for ticket pk=%s", instance.pk)

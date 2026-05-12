"""
Django signals for push notifications on model state changes.
Connected in chat/apps.py ready() using actual model classes (not strings).

Covered:
  #29 — Ticket status → RESOLVED
  #30 — Ticket status → CLOSED
"""
import logging

logger = logging.getLogger(__name__)


def on_ticket_status_change(sender, instance, **kwargs):
    """
    Detect RESOLVED / CLOSED transitions and fire push to the ticket owner.
    pre_save lets us compare old vs new status without an extra DB query.
    """
    if not instance.pk:
        return  # new ticket — handled in SupportTicket.save()

    try:
        old = sender.objects.filter(pk=instance.pk).values("status").first()
        if not old or old["status"] == instance.status:
            return

        owner_id = instance.user_id
        if not owner_id:
            return

        from account.push_notifications import N
        from account.tasks import send_push_notification_task

        if instance.status == sender.Status.RESOLVED:
            title, body = N.TICKET_RESOLVED.render()
            send_push_notification_task.delay(
                user_id=owner_id,
                title=title,
                body=body,
                data={"type": N.TICKET_RESOLVED.key, "ticket_id": str(instance.pk) , "priority": N.TICKET_RESOLVED.priority},
            )
            logger.info("Push queued: ticket_resolved for user_id=%s", owner_id)

        elif instance.status == sender.Status.CLOSED:
            title, body = N.TICKET_CLOSED.render()
            send_push_notification_task.delay(
                user_id=owner_id,
                title=title,
                body=body,
                data={"type": N.TICKET_CLOSED.key, "ticket_id": str(instance.pk), "priority": N.TICKET_CLOSED.priority},
            )
            logger.info("Push queued: ticket_closed for user_id=%s", owner_id)

    except Exception:
        logger.exception("Signal push failed for ticket pk=%s", instance.pk)

import logging

from celery import shared_task
from django.conf import settings

from account.emailing import build_email_context, get_info_connection, send_templated_email

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_notification_email_task(self, subject: str, recipient: str, body: str, tracking_code: str = "") -> None:
    try:
        send_templated_email(
            subject=subject,
            recipient=recipient,
            text_template="emails/notification.txt",
            html_template="emails/notification.html",
            context=build_email_context(
                preheader=subject,
                headline=subject,
                intro="You have a new update from Shy2Ask.com.",
                body=body,
                tracking_code=tracking_code,
                footer_note="You are receiving this notification because activity occurred on a request connected to your account.",
            ),
            connection=get_info_connection(),
            from_email=settings.EMAIL_INFO_USER,
        )
    except Exception as exc:
        logger.exception("Notification email task failed for %s", recipient)
        raise self.retry(exc=exc)


@shared_task
def process_request_created_task(request_id: int) -> None:
    from .emailing import send_request_created_emails
    from .models import ShyRequest
    from .views import send_notification
    from .websocket_utils import get_request_inbox_user_ids, send_received_request_inbox_websocket

    try:
        shy_request = ShyRequest.objects.with_related().get(pk=request_id)
    except ShyRequest.DoesNotExist:
        logger.warning("Request %s disappeared before async create processing", request_id)
        return

    try:
        send_request_created_emails(shy_request)
    except Exception:
        logger.exception("Failed to send request-created emails for request %s", request_id)

    try:
        send_notification(
            subject="Request created successfully",
            body=f"Your request {shy_request.tracking_code} is live.",
            recipient=shy_request.requester_email,
            related_request=shy_request,
            use_ai_enhance=False,
            deliver_email=False,
            push_type="request_submitted",
        )
    except Exception:
        logger.exception("Failed requester notification for request %s", request_id)

    if shy_request.target_email:
        try:
            send_notification(
                subject="You received a new request",
                body=f"A new request {shy_request.tracking_code} is waiting for your reply.",
                recipient=shy_request.target_email,
                related_request=shy_request,
                use_ai_enhance=False,
                deliver_email=False,
                push_type="new_request",
            )
        except Exception:
            logger.exception("Failed target notification for request %s", request_id)

    try:
        for user_id in get_request_inbox_user_ids(shy_request):
            send_received_request_inbox_websocket(user_id)
    except Exception:
        logger.exception("Failed request inbox websocket refresh for request %s", request_id)


@shared_task
def process_request_reply_side_effects_task(request_id: int, sender: str, body: str, reply_to_id: int | None = None) -> None:
    from .message_service import run_post_message_business_logic
    from .models import ShyRequest

    try:
        shy_request = ShyRequest.objects.with_related().get(pk=request_id)
    except ShyRequest.DoesNotExist:
        logger.warning("Request %s disappeared before async reply processing", request_id)
        return

    try:
        run_post_message_business_logic(shy_request=shy_request, sender=sender, body=body, reply_to_id=reply_to_id)
    except Exception:
        logger.exception("Failed reply side effects for request %s", request_id)


@shared_task
def process_support_ticket_created_task(ticket_id: int) -> None:
    from .emailing import send_ticket_created_emails
    from .models import SupportTicket

    try:
        ticket = SupportTicket.objects.with_related().get(pk=ticket_id)
    except SupportTicket.DoesNotExist:
        logger.warning("Support ticket %s disappeared before async create processing", ticket_id)
        return

    try:
        send_ticket_created_emails(ticket)
    except Exception:
        logger.exception("Failed support ticket create emails for ticket %s", ticket_id)


@shared_task
def process_support_ticket_reply_task(ticket_id: int, reply_id: int) -> None:
    from .emailing import send_ticket_reply_emails
    from .models import SupportTicket, SupportTicketReply

    try:
        ticket = SupportTicket.objects.with_related().get(pk=ticket_id)
        reply = SupportTicketReply.objects.select_related("ticket", "author").get(pk=reply_id, ticket_id=ticket_id)
    except (SupportTicket.DoesNotExist, SupportTicketReply.DoesNotExist):
        logger.warning("Support ticket reply %s/%s disappeared before async processing", ticket_id, reply_id)
        return

    try:
        send_ticket_reply_emails(ticket, reply)
    except Exception:
        logger.exception("Failed support ticket reply emails for ticket %s reply %s", ticket_id, reply_id)


@shared_task
def run_deal_detection_and_notify_task(request_id: int) -> None:
    from .ai_services import run_deal_detection_and_notify

    try:
        run_deal_detection_and_notify(request_id)
    except Exception:
        logger.exception("Failed deal detection for request %s", request_id)

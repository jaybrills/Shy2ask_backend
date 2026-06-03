from django.conf import settings

from account.emailing import (
    build_email_context,
    build_request_reply_url,
    get_mobile_store_links,
    get_request_connection,
    get_support_connection,
    send_templated_email,
)

from .models import Message, ShyRequest, SupportTicket, SupportTicketReply


def _send_request_email(
    *,
    shy_request: ShyRequest,
    recipient: str,
    recipient_name: str,
    recipient_role_label: str,
    subject: str,
    headline: str,
    intro: str,
    summary_title: str,
    summary_body: str,
    message_body: str = "",
    message_label: str = "",
) -> None:
    if not recipient:
        return

    reply_url = build_request_reply_url(tracking_code=shy_request.tracking_code)
    ios_app_url, android_app_url = get_mobile_store_links()

    send_templated_email(
        subject=subject,
        recipient=recipient,
        text_template="emails/request_update.txt",
        html_template="emails/request_update.html",
        connection=get_request_connection(),
        from_email=settings.EMAIL_REQUEST_USER,
        context=build_email_context(
            preheader=subject,
            headline=headline,
            intro=intro,
            footer_note="This email was sent because you are part of this Shy2Ask request.",
            recipient_name=recipient_name or recipient_role_label,
            recipient_role_label=recipient_role_label,
            tracking_code=shy_request.tracking_code,
            service_channel=shy_request.get_service_channel_display(),
            status_label=shy_request.get_status_display(),
            summary_title=summary_title,
            summary_body=summary_body,
            has_new_message=bool((message_body or "").strip()),
            message_label=message_label,
            message_hidden=True,
            reply_url=reply_url,
            ios_app_url=ios_app_url,
            android_app_url=android_app_url,
        ),
    )


def send_request_created_emails(shy_request: ShyRequest) -> None:
    _send_request_email(
        shy_request=shy_request,
        recipient=shy_request.requester_email,
        recipient_name=shy_request.requester_display_name,
        recipient_role_label="Requester",
        subject=f"Your request {shy_request.tracking_code} is live",
        headline="Your request has been created",
        intro="Your message is now on Shy2Ask and ready for the responder to review and reply to.",
        summary_title="What happens next",
        summary_body="Keep your tracking code safe. You can use it to follow progress and continue the conversation.",
    )

    _send_request_email(
        shy_request=shy_request,
        recipient=shy_request.target_email,
        recipient_name=shy_request.target_display_name,
        recipient_role_label="Responder",
        subject="A new private request is waiting for you",
        headline="A new request is waiting for you",
        intro="Someone used Shy2Ask to contact you privately. You will be able to review the request and reply from the app experience.",
        summary_title="Why you received this",
        summary_body="You were added as the responder for this request. Replying will notify the requester and keep the conversation in one place.",
    )


def send_request_reply_emails(shy_request: ShyRequest, sender: str, body: str) -> None:
    clean_body = (body or "").strip()
    if sender == Message.Actor.TARGET:
        recipient_subject = f"New reply on request {shy_request.tracking_code}"
        recipient_headline = "You received a new reply"
        recipient_intro = "The responder has replied to your request on Shy2Ask."
        recipient_summary = "You can continue the discussion in the app once the in-app experience is connected."
    else:
        recipient_subject = f"New message on request {shy_request.tracking_code}"
        recipient_headline = "You received a new message"
        recipient_intro = "The requester sent a new message on Shy2Ask."
        recipient_summary = "You can review the latest message and reply in the app once the in-app experience is connected."

    _send_request_email(
        shy_request=shy_request,
        recipient=shy_request.requester_email if sender == Message.Actor.TARGET else shy_request.target_email,
        recipient_name=shy_request.requester_display_name if sender == Message.Actor.TARGET else shy_request.target_display_name,
        recipient_role_label="Requester" if sender == Message.Actor.TARGET else "Responder",
        subject=recipient_subject,
        headline=recipient_headline,
        intro=recipient_intro,
        summary_title="Latest update",
        summary_body=recipient_summary,
        message_body=clean_body,
        message_label="Latest message",
    )

    _send_request_email(
        shy_request=shy_request,
        recipient=shy_request.target_email if sender == Message.Actor.TARGET else shy_request.requester_email,
        recipient_name=shy_request.target_display_name if sender == Message.Actor.TARGET else shy_request.requester_display_name,
        recipient_role_label="Responder" if sender == Message.Actor.TARGET else "Requester",
        subject=f"Your reply on {shy_request.tracking_code} was sent",
        headline="Your message was delivered",
        intro="We sent your reply and updated the conversation for everyone involved in this request.",
        summary_title="Sent successfully",
        summary_body="You will be able to review the thread and send another message in the app once that flow is connected.",
        message_body=clean_body,
        message_label="Your message",
    )


# ---------------------------------------------------------------------------
# Support ticket emails  (sent from support@shy2ask.com)
# ---------------------------------------------------------------------------

def _send_support_email(
    *,
    ticket: SupportTicket,
    recipient: str,
    recipient_name: str,
    subject: str,
    headline: str,
    intro: str,
    summary_title: str,
    summary_body: str,
    message_body: str = "",
    message_label: str = "",
) -> None:
    if not recipient:
        return

    send_templated_email(
        subject=subject,
        recipient=recipient,
        text_template="emails/support_ticket.txt",
        html_template="emails/support_ticket.html",
        connection=get_support_connection(),
        from_email=settings.EMAIL_SUPPORT_USER,
        context=build_email_context(
            preheader=subject,
            headline=headline,
            intro=intro,
            footer_note="This email was sent because you are part of this Shy2Ask support ticket.",
            recipient_name=recipient_name or "there",
            ticket_ref=ticket.tracking_code,
            ticket_subject=ticket.subject,
            status_label=ticket.get_status_display(),
            priority_label=ticket.get_priority_display(),
            summary_title=summary_title,
            summary_body=summary_body,
            message_body=(message_body or "").strip(),
            message_label=message_label,
        ),
    )


def send_ticket_created_emails(ticket: SupportTicket) -> None:
    user_name = ticket.user.get_full_name() if ticket.user else ""

    _send_support_email(
        ticket=ticket,
        recipient=ticket.email,
        recipient_name=user_name,
        subject=f"Your support request {ticket.tracking_code} has been received",
        headline="We've received your support request",
        intro="Our support team will review your message and get back to you as soon as possible.",
        summary_title="What happens next",
        summary_body="You will receive an email notification when a member of our team responds to your ticket.",
    )

    _send_support_email(
        ticket=ticket,
        recipient=settings.EMAIL_SUPPORT_USER,
        recipient_name="Support Team",
        subject=f"[{ticket.get_priority_display()}] New support ticket {ticket.tracking_code}",
        headline="A new support ticket has been opened",
        intro=f"A user submitted a new support ticket on Shy2Ask.",
        summary_title="Ticket details",
        summary_body=f"Review and respond from the admin panel.",
        message_body=ticket.message,
        message_label="User's message",
    )


def send_ticket_reply_emails(ticket: SupportTicket, reply: SupportTicketReply) -> None:
    clean_body = (reply.body or "").strip()
    user_name = ticket.user.get_full_name() if ticket.user else ""

    if reply.sender_type in {SupportTicketReply.SenderType.STAFF, SupportTicketReply.SenderType.ADMIN}:
        _send_support_email(
            ticket=ticket,
            recipient=ticket.email,
            recipient_name=user_name,
            subject=f"Update on your support ticket {ticket.tracking_code}",
            headline="Our team has replied to your ticket",
            intro="A member of the Shy2Ask support team has responded to your support request.",
            summary_title="Their reply",
            summary_body="You can continue the conversation by replying to this email or from within the app.",
            message_body=clean_body,
            message_label="Support team reply",
        )
    else:
        _send_support_email(
            ticket=ticket,
            recipient=settings.EMAIL_SUPPORT_USER,
            recipient_name="Support Team",
            subject=f"[{ticket.get_priority_display()}] User replied on ticket {ticket.tracking_code}",
            headline="A user replied to a support ticket",
            intro=f"The user submitted a new reply on ticket {ticket.tracking_code}.",
            summary_title="User's reply",
            summary_body="Log in to the admin panel to respond.",
            message_body=clean_body,
            message_label="User's reply",
        )

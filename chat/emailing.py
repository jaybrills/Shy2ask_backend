from account.emailing import build_email_context, send_templated_email

from .models import Message, ShyRequest


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

    send_templated_email(
        subject=subject,
        recipient=recipient,
        text_template="emails/request_update.txt",
        html_template="emails/request_update.html",
        context=build_email_context(
            preheader=subject,
            headline=headline,
            intro=intro,
            footer_note="This email was sent because you are part of this Shy2Ask request.",
            recipient_name=recipient_name or recipient_role_label,
            recipient_role_label=recipient_role_label,
            tracking_code=shy_request.tracking_code,
            request_description=shy_request.description,
            service_channel=shy_request.get_service_channel_display(),
            status_label=shy_request.get_status_display(),
            summary_title=summary_title,
            summary_body=summary_body,
            message_body=(message_body or "").strip(),
            message_label=message_label,
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

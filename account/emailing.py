from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def build_email_context(**extra):
    context = {
        "app_name": "Shy2Ask.com",
        "support_email": settings.DEFAULT_FROM_EMAIL,
        "site_url": "https://backend.shy2ask.com",
    }
    context.update(extra)
    return context


def send_templated_email(*, subject: str, recipient: str, text_template: str, html_template: str, context: dict):
    text_body = render_to_string(text_template, context)
    html_body = render_to_string(html_template, context)
    email = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    email.attach_alternative(html_body, "text/html")
    email.send(fail_silently=False)

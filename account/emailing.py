from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def build_email_context(**extra):
    site_url = getattr(settings, "SITE_URL", "https://backend.shy2ask.com").rstrip("/")
    context = {
        "app_name": "Shy2Ask.com",
        "support_email": settings.DEFAULT_FROM_EMAIL,
        "site_url": site_url,
        "brand_color": "#6B46C1",
        "brand_color_dark": "#312E81",
        "logo_url": f"{site_url}/static/core/img/shy2ask-email-logo.svg",
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

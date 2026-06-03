from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string

from shy2ask.branding import get_logo_url


def build_email_context(**extra):
    site_url = (extra.get("site_url") or getattr(settings, "SITE_URL", "https://backend.shy2ask.com")).rstrip("/")
    context = {
        "app_name": "Shy2Ask.com",
        "support_email": settings.EMAIL_SUPPORT_USER,
        "site_url": site_url,
        "brand_color": "#6B46C1",
        "brand_color_dark": "#312E81",
        "logo_url": get_logo_url(absolute=True, site_url=site_url),
    }
    context.update(extra)
    return context


def build_request_reply_url(*, tracking_code: str, site_url: str | None = None) -> str:
    template = (getattr(settings, "REQUEST_REPLY_URL_TEMPLATE", "") or "").strip()
    if not template:
        return ""
    resolved_site_url = (site_url or getattr(settings, "SITE_URL", "https://backend.shy2ask.com")).rstrip("/")
    return template.format(tracking_code=tracking_code, site_url=resolved_site_url)


def get_mobile_store_links() -> tuple[str, str]:
    ios_url = (getattr(settings, "IOS_APP_URL", "") or "").strip()
    android_url = (getattr(settings, "ANDROID_APP_URL", "") or "").strip()
    return ios_url, android_url


_SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


def _make_connection(username: str, password: str):
    if settings.EMAIL_BACKEND != _SMTP_BACKEND:
        return get_connection()
    return get_connection(
        backend=_SMTP_BACKEND,
        host=settings.EMAIL_HOST,
        port=settings.EMAIL_PORT,
        username=username,
        password=password,
        use_ssl=getattr(settings, "EMAIL_USE_SSL", True),
        use_tls=getattr(settings, "EMAIL_USE_TLS", False),
    )


def get_info_connection():
    return _make_connection(settings.EMAIL_INFO_USER, settings.EMAIL_INFO_PASSWORD)


def get_request_connection():
    return _make_connection(settings.EMAIL_REQUEST_USER, settings.EMAIL_REQUEST_PASSWORD)


def get_support_connection():
    return _make_connection(settings.EMAIL_SUPPORT_USER, settings.EMAIL_SUPPORT_PASSWORD)


def send_templated_email(
    *,
    subject: str,
    recipient: str,
    text_template: str,
    html_template: str,
    context: dict,
    connection=None,
    from_email: str = None,
):
    text_body = render_to_string(text_template, context)
    html_body = render_to_string(html_template, context)
    email = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
        connection=connection,
    )
    email.attach_alternative(html_body, "text/html")
    email.send(fail_silently=False)

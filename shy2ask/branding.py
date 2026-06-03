from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError
from django.templatetags.static import static

DEFAULT_LOGO_STATIC_PATH = "core/img/shy2ask-logo.png"


def _absolute_url(site_url: str, path: str) -> str:
    return f"{site_url.rstrip('/')}/{path.lstrip('/')}"


def get_site_branding():
    try:
        from chat.models import SiteBranding

        return SiteBranding.get_solo()
    except (OperationalError, ProgrammingError):
        return None


def get_logo_url(*, absolute: bool = False, site_url: str | None = None) -> str:
    branding = get_site_branding()
    if branding and branding.logo:
        logo_url = branding.logo.url
    else:
        logo_url = static(DEFAULT_LOGO_STATIC_PATH)

    if logo_url and not logo_url.startswith(("http://", "https://", "/")):
        logo_url = f"/{logo_url.lstrip('/')}"

    if absolute:
        resolved_site_url = (site_url or getattr(settings, "SITE_URL", "") or "").strip()
        if resolved_site_url:
            return _absolute_url(resolved_site_url, logo_url)

    return logo_url

from .branding import get_logo_url


def branding(request):
    return {
        "site_logo_url": get_logo_url(),
    }

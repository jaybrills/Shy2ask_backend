"""
URL configuration for shy2ask project.
Django Ninja docs: http://0.0.0.0:8000/docs
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from .api import api

_ninja_urls = api.urls
urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("account.urls", namespace="account")),
    path("api/", include("chat.api_urls")),
    path("", api.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

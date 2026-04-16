"""
URL configuration for shy2ask project.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularJSONAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from .api import ApiIndexView


urlpatterns = [
    path("admin/", admin.site.urls),
    path("openapi.json", SpectacularJSONAPIView.as_view(), name="schema"),
    path("swagger/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/", ApiIndexView.as_view(), name="api-index"),
    path("api/", include("account.api_urls")),
    path("api/", include("chat.api_urls")),
    path("api/billing/", include("billing.urls")),
    path("", include("account.urls", namespace="account")),
    path("", include("account.api_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

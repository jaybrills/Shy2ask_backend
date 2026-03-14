from rest_framework.routers import DefaultRouter
from django.urls import re_path

from .api_views import (
    CensorImageView,
    CensorTextView,
    ShyRequestViewSet,
    SubscriptionDetailView,
    SubscriptionListCreateView,
)

router = DefaultRouter()
router.trailing_slash = "/?"
router.register("requests", ShyRequestViewSet, basename="requests")

urlpatterns = [
    re_path(r"^censor/text/?$", CensorTextView.as_view()),
    re_path(r"^censor/image/?$", CensorImageView.as_view()),
    re_path(r"^subscriptions/?$", SubscriptionListCreateView.as_view()),
    re_path(r"^subscriptions/(?P<subscription_id>\d+)/?$", SubscriptionDetailView.as_view()),
]
urlpatterns += router.urls

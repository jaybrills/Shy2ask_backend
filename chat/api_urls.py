from rest_framework.routers import DefaultRouter
from django.urls import path

from .api_views import (
    CensorImageView,
    CensorTextView,
    ShyRequestViewSet,
    SubscriptionDetailView,
    SubscriptionListCreateView,
    UnreadNotificationListView,
)

router = DefaultRouter()
router.trailing_slash = "/?"
router.register("requests", ShyRequestViewSet, basename="requests")

urlpatterns = [
    path("censor/text", CensorTextView.as_view()),
    path("censor/text/", CensorTextView.as_view()),
    path("censor/image", CensorImageView.as_view()),
    path("censor/image/", CensorImageView.as_view()),
    path("subscriptions", SubscriptionListCreateView.as_view()),
    path("subscriptions/", SubscriptionListCreateView.as_view()),
    path("subscriptions/<int:subscription_id>", SubscriptionDetailView.as_view()),
    path("subscriptions/<int:subscription_id>/", SubscriptionDetailView.as_view()),
    path("notifications/unread", UnreadNotificationListView.as_view()),
    path("notifications/unread/", UnreadNotificationListView.as_view()),
    path("messages/unread", UnreadNotificationListView.as_view()),
    path("messages/unread/", UnreadNotificationListView.as_view()),
]
urlpatterns += router.urls

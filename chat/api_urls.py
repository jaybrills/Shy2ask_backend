from rest_framework.routers import DefaultRouter
from django.urls import path

from .api_views import (
    CensorImageView,
    CensorTextView,
    FAQListView,
    ShyRequestViewSet,
    SubscriptionDetailView,
    SubscriptionListCreateView,
    SupportTicketViewSet,
    UnreadNotificationListView,
)

router = DefaultRouter()
router.trailing_slash = "/?"
router.register("requests", ShyRequestViewSet, basename="requests")
router.register("support/tickets", SupportTicketViewSet, basename="support-tickets")

urlpatterns = [
    path("faq", FAQListView.as_view()),
    path("faq/", FAQListView.as_view()),
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

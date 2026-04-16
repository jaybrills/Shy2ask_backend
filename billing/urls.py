from django.urls import path

from .views import (
    CreateCheckoutSessionView,
    CustomerPortalView,
    EnrollFreePlanView,
    PlanListView,
    StripeWebhookView,
    SubscriptionStatusView,
)

# All paths are mounted under /api/billing/ in shy2ask/urls.py
urlpatterns = [
    # GET  /api/billing/plans/               → list available plans
    path("plans/", PlanListView.as_view(), name="billing-plans"),
    path("plans", PlanListView.as_view()),

    # POST /api/billing/checkout/            → create Stripe checkout session
    path("checkout/", CreateCheckoutSessionView.as_view(), name="billing-checkout"),
    path("checkout", CreateCheckoutSessionView.as_view()),

    # POST /api/billing/portal/              → create customer portal session
    path("portal/", CustomerPortalView.as_view(), name="billing-portal"),
    path("portal", CustomerPortalView.as_view()),

    # GET  /api/billing/subscription/        → current subscription status
    path("subscription/", SubscriptionStatusView.as_view(), name="billing-subscription"),
    path("subscription", SubscriptionStatusView.as_view()),

    # POST /api/billing/free/                → enroll in free plan (no Stripe involved)
    path("free/", EnrollFreePlanView.as_view(), name="billing-free-plan"),
    path("free", EnrollFreePlanView.as_view()),

    # POST /api/billing/webhook/             → Stripe webhook receiver (no auth)
    path("webhook/", StripeWebhookView.as_view(), name="billing-webhook"),
    path("webhook", StripeWebhookView.as_view()),
]

from django.urls import path

from .views import (
    BillingConfigView,
    CancelSubscriptionView,
    CreateCheckoutSessionView,
    CustomerPortalView,
    EnrollFreePlanView,
    InvoiceListView,
    MobileSubscribeView,
    PaymentMethodDeleteView,
    PaymentMethodListView,
    PaymentSheetView,
    PlanListView,
    StripeWebhookView,
    SubscriptionStatusView,
)

# All paths are mounted under /api/billing/ in shy2ask/urls.py
urlpatterns = [
    # ── Shared (web + mobile) ────────────────────────────────────────────────
    # GET  /api/billing/plans/
    path("plans/", PlanListView.as_view(), name="billing-plans"),
    path("plans", PlanListView.as_view()),

    # GET  /api/billing/subscription/
    path("subscription/", SubscriptionStatusView.as_view(), name="billing-subscription"),
    path("subscription", SubscriptionStatusView.as_view()),

    # POST /api/billing/free/
    path("free/", EnrollFreePlanView.as_view(), name="billing-free-plan"),
    path("free", EnrollFreePlanView.as_view()),

    # POST /api/billing/webhook/
    path("webhook/", StripeWebhookView.as_view(), name="billing-webhook"),
    path("webhook", StripeWebhookView.as_view()),

    # ── Web-only (redirect-based flows) ─────────────────────────────────────
    # POST /api/billing/checkout/
    path("checkout/", CreateCheckoutSessionView.as_view(), name="billing-checkout"),
    path("checkout", CreateCheckoutSessionView.as_view()),

    # POST /api/billing/portal/
    path("portal/", CustomerPortalView.as_view(), name="billing-portal"),
    path("portal", CustomerPortalView.as_view()),

    # ── React Native / Mobile SDK ────────────────────────────────────────────
    # GET  /api/billing/config/
    path("config/", BillingConfigView.as_view(), name="billing-config"),
    path("config", BillingConfigView.as_view()),

    # POST /api/billing/payment-sheet/
    path("payment-sheet/", PaymentSheetView.as_view(), name="billing-payment-sheet"),
    path("payment-sheet", PaymentSheetView.as_view()),

    # POST /api/billing/subscribe/
    path("subscribe/", MobileSubscribeView.as_view(), name="billing-subscribe-mobile"),
    path("subscribe", MobileSubscribeView.as_view()),

    # POST /api/billing/cancel/
    path("cancel/", CancelSubscriptionView.as_view(), name="billing-cancel"),
    path("cancel", CancelSubscriptionView.as_view()),

    # GET  /api/billing/payment-methods/
    path("payment-methods/", PaymentMethodListView.as_view(), name="billing-payment-methods"),
    path("payment-methods", PaymentMethodListView.as_view()),

    # DELETE /api/billing/payment-methods/<pm_id>/
    path("payment-methods/<str:pm_id>/", PaymentMethodDeleteView.as_view(), name="billing-payment-method-delete"),
    path("payment-methods/<str:pm_id>", PaymentMethodDeleteView.as_view()),

    # GET  /api/billing/invoices/
    path("invoices/", InvoiceListView.as_view(), name="billing-invoices"),
    path("invoices", InvoiceListView.as_view()),
]

import logging

import stripe
from django.conf import settings
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from account.api_views import BearerTokenAuthentication

from .models import StripeCustomer, StripeEvent, StripePlan, StripeSubscription
from .serializers import (
    CheckoutSessionResponseSerializer,
    CreateCheckoutSessionSerializer,
    CustomerPortalResponseSerializer,
    CustomerPortalSerializer,
    EnrollFreePlanSerializer,
    StripePlanSerializer,
    StripeSubscriptionSerializer,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create_stripe_customer(user) -> str:
    """Return the Stripe customer ID for *user*, creating one if needed."""
    try:
        return user.stripe_customer.stripe_customer_id
    except StripeCustomer.DoesNotExist:
        pass

    customer = stripe.Customer.create(
        email=user.email,
        name=getattr(user, "get_full_name", lambda: "")() or user.email,
        metadata={"user_id": str(user.pk)},
    )
    StripeCustomer.objects.create(user=user, stripe_customer_id=customer.id)
    return customer.id


def _sync_subscription_from_stripe(stripe_sub, user=None):
    """
    Create or update a local StripeSubscription from a Stripe subscription
    object. Returns the Django model instance.
    """
    # Resolve the plan from the first item's price ID
    price_id = None
    if stripe_sub.get("items") and stripe_sub["items"].get("data"):
        price_id = stripe_sub["items"]["data"][0]["price"]["id"]

    plan = None
    if price_id:
        plan = StripePlan.objects.filter(stripe_price_id=price_id).first()

    # Resolve user if not provided
    if user is None:
        try:
            stripe_customer = StripeCustomer.objects.get(
                stripe_customer_id=stripe_sub["customer"]
            )
            user = stripe_customer.user
        except StripeCustomer.DoesNotExist:
            logger.error(
                "No StripeCustomer found for customer %s", stripe_sub["customer"]
            )
            return None

    period_start = (
        timezone.datetime.fromtimestamp(
            stripe_sub["current_period_start"], tz=timezone.utc
        )
        if stripe_sub.get("current_period_start")
        else None
    )
    period_end = (
        timezone.datetime.fromtimestamp(
            stripe_sub["current_period_end"], tz=timezone.utc
        )
        if stripe_sub.get("current_period_end")
        else None
    )
    trial_end = (
        timezone.datetime.fromtimestamp(stripe_sub["trial_end"], tz=timezone.utc)
        if stripe_sub.get("trial_end")
        else None
    )
    canceled_at = (
        timezone.datetime.fromtimestamp(stripe_sub["canceled_at"], tz=timezone.utc)
        if stripe_sub.get("canceled_at")
        else None
    )

    obj, _ = StripeSubscription.objects.update_or_create(
        stripe_subscription_id=stripe_sub["id"],
        defaults={
            "user": user,
            "plan": plan,
            "stripe_customer_id": stripe_sub["customer"],
            "status": stripe_sub["status"],
            "current_period_start": period_start,
            "current_period_end": period_end,
            "cancel_at_period_end": stripe_sub.get("cancel_at_period_end", False),
            "canceled_at": canceled_at,
            "trial_end": trial_end,
        },
    )
    return obj


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class PlanListView(APIView):
    """List all active subscription plans."""

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="List available plans",
        responses={200: StripePlanSerializer(many=True)},
    )
    def get(self, request):
        plans = StripePlan.objects.filter(is_active=True)
        return Response(StripePlanSerializer(plans, many=True).data)


class CreateCheckoutSessionView(APIView):
    """
    Create a Stripe Checkout Session for a subscription.

    The client receives a `url` and should redirect the user there.
    After payment, Stripe redirects to `success_url`; on cancel to `cancel_url`.
    """

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Create Stripe Checkout Session",
        request=CreateCheckoutSessionSerializer,
        responses={200: CheckoutSessionResponseSerializer},
    )
    def post(self, request):
        serializer = CreateCheckoutSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        price_id = data.get("price_id") or getattr(settings, "STRIPE_DEFAULT_PRICE_ID", "")
        if not price_id:
            return Response(
                {"detail": "No price_id provided and STRIPE_DEFAULT_PRICE_ID not configured."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reject if the price belongs to a free plan — use /api/billing/free/ instead
        plan = StripePlan.objects.filter(stripe_price_id=price_id).first()
        if plan and plan.is_free:
            return Response(
                {"detail": "This is a free plan. Use POST /api/billing/free/ to enroll."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            customer_id = _get_or_create_stripe_customer(request.user)

            session = stripe.checkout.Session.create(
                customer=customer_id,
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=data["success_url"],
                cancel_url=data["cancel_url"],
                metadata={"user_id": str(request.user.pk)},
                subscription_data={
                    "metadata": {"user_id": str(request.user.pk)},
                },
            )
        except stripe.StripeError as exc:
            logger.error("Stripe checkout session creation failed: %s", exc)
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {"session_id": session.id, "url": session.url},
            status=status.HTTP_200_OK,
        )


class CustomerPortalView(APIView):
    """
    Create a Stripe Billing Portal session so users can manage their
    subscription (cancel, update payment method, download invoices, etc.).
    """

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Create Stripe Customer Portal Session",
        request=CustomerPortalSerializer,
        responses={200: CustomerPortalResponseSerializer},
    )
    def post(self, request):
        serializer = CustomerPortalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            customer_id = _get_or_create_stripe_customer(request.user)

            portal = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=serializer.validated_data["return_url"],
            )
        except stripe.StripeError as exc:
            logger.error("Stripe portal session creation failed: %s", exc)
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"url": portal.url}, status=status.HTTP_200_OK)


class SubscriptionStatusView(APIView):
    """
    Return the authenticated user's current (most recent active) subscription.
    Returns 404 if the user has no subscription.
    """

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get current subscription status",
        responses={200: StripeSubscriptionSerializer, 404: None},
    )
    def get(self, request):
        sub = (
            StripeSubscription.objects.filter(user=request.user)
            .select_related("plan")
            .order_by("-created_at")
            .first()
        )
        if not sub:
            return Response(
                {"detail": "No subscription found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(StripeSubscriptionSerializer(sub).data)


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(APIView):
    """
    Stripe sends signed webhook events to this endpoint.

    Events handled:
    - checkout.session.completed
    - customer.subscription.updated
    - customer.subscription.deleted
    - invoice.payment_succeeded
    - invoice.payment_failed
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    # ------------------------------------------------------------------ #
    # Main entry point                                                     #
    # ------------------------------------------------------------------ #
    @extend_schema(exclude=True)  # hide from public docs
    def post(self, request):
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")

        # Verify signature
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except stripe.errors.SignatureVerificationError as exc:
            logger.warning("Stripe webhook signature verification failed: %s", exc)
            return Response({"detail": "Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.error("Stripe webhook parsing error: %s", exc)
            return Response({"detail": "Bad payload."}, status=status.HTTP_400_BAD_REQUEST)

        # Idempotency guard — skip already-processed events
        if StripeEvent.objects.filter(stripe_event_id=event["id"]).exists():
            return Response({"detail": "Already processed."}, status=status.HTTP_200_OK)

        error_message = ""
        try:
            self._dispatch(event)
        except Exception as exc:
            logger.exception("Error handling Stripe event %s: %s", event["id"], exc)
            error_message = str(exc)

        # Always persist the event (even on error, so we can retry manually)
        StripeEvent.objects.create(
            stripe_event_id=event["id"],
            event_type=event["type"],
            payload=dict(event),
            processing_error=error_message,
        )

        return Response({"detail": "OK"}, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------ #
    # Dispatcher                                                           #
    # ------------------------------------------------------------------ #
    def _dispatch(self, event):
        handlers = {
            "checkout.session.completed": self._handle_checkout_completed,
            "customer.subscription.updated": self._handle_subscription_updated,
            "customer.subscription.deleted": self._handle_subscription_deleted,
            "invoice.payment_succeeded": self._handle_invoice_payment_succeeded,
            "invoice.payment_failed": self._handle_invoice_payment_failed,
        }
        handler = handlers.get(event["type"])
        if handler:
            handler(event["data"]["object"])
        else:
            logger.debug("Unhandled Stripe event type: %s", event["type"])

    # ------------------------------------------------------------------ #
    # Handlers                                                             #
    # ------------------------------------------------------------------ #
    def _handle_checkout_completed(self, session):
        """Checkout finished — fetch the subscription and persist it."""
        if session.get("mode") != "subscription":
            return  # ignore one-time payment sessions

        subscription_id = session.get("subscription")
        if not subscription_id:
            return

        # Fetch full subscription object from Stripe
        stripe_sub = stripe.Subscription.retrieve(subscription_id)

        # Resolve user via metadata (set when creating the session)
        user = None
        user_id = (session.get("metadata") or {}).get("user_id")
        if user_id:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.filter(pk=user_id).first()

        # Ensure StripeCustomer exists
        customer_id = session.get("customer")
        if user and customer_id:
            StripeCustomer.objects.get_or_create(
                user=user,
                defaults={"stripe_customer_id": customer_id},
            )

        _sync_subscription_from_stripe(stripe_sub, user=user)
        logger.info(
            "Subscription %s activated for user_id=%s", subscription_id, user_id
        )

    def _handle_subscription_updated(self, stripe_sub):
        """Subscription changed (status, plan, renewal, cancel_at_period_end)."""
        _sync_subscription_from_stripe(stripe_sub)
        logger.info(
            "Subscription %s updated — status=%s",
            stripe_sub["id"],
            stripe_sub["status"],
        )

    def _handle_subscription_deleted(self, stripe_sub):
        """Subscription canceled immediately (e.g. via API or admin)."""
        _sync_subscription_from_stripe(stripe_sub)
        logger.info("Subscription %s deleted/canceled", stripe_sub["id"])

    def _handle_invoice_payment_succeeded(self, invoice):
        """
        Successful renewal payment. Re-sync subscription to capture new
        period_start / period_end dates.
        """
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return

        stripe_sub = stripe.Subscription.retrieve(subscription_id)
        _sync_subscription_from_stripe(stripe_sub)
        logger.info(
            "Invoice payment succeeded for subscription %s", subscription_id
        )

    def _handle_invoice_payment_failed(self, invoice):
        """
        Failed payment — subscription may become past_due or unpaid.
        Re-sync so our DB reflects the new status.
        """
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return

        stripe_sub = stripe.Subscription.retrieve(subscription_id)
        _sync_subscription_from_stripe(stripe_sub)
        logger.warning(
            "Invoice payment FAILED for subscription %s — new status=%s",
            subscription_id,
            stripe_sub["status"],
        )


class EnrollFreePlanView(APIView):
    """
    Enroll the authenticated user in the free plan.

    No Stripe objects are created — the subscription is recorded locally only.
    If the user already has an active free subscription it is returned as-is.
    If they have a paid subscription this returns 400 (they should use the
    Stripe portal to downgrade).
    """

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Enroll in the free plan",
        request=EnrollFreePlanSerializer,
        responses={200: StripeSubscriptionSerializer, 201: StripeSubscriptionSerializer},
    )
    def post(self, request):
        serializer = EnrollFreePlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan_id = serializer.validated_data.get("plan_id")

        # Resolve the free plan
        qs = StripePlan.objects.filter(is_free=True, is_active=True)
        if plan_id:
            qs = qs.filter(pk=plan_id)
        plan = qs.first()

        if not plan:
            return Response(
                {"detail": "No active free plan found. Ask an admin to create one."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check for an existing active paid subscription
        paid_active = StripeSubscription.objects.filter(
            user=request.user,
            status__in=[StripeSubscription.Status.ACTIVE, StripeSubscription.Status.TRIALING],
            stripe_subscription_id__isnull=False,
        ).exists()
        if paid_active:
            return Response(
                {"detail": "You already have an active paid subscription. Use the billing portal to change your plan."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check for an existing free subscription on this plan
        existing = StripeSubscription.objects.filter(
            user=request.user,
            plan=plan,
            stripe_subscription_id__isnull=True,
            status=StripeSubscription.Status.ACTIVE,
        ).first()
        if existing:
            return Response(
                StripeSubscriptionSerializer(existing).data,
                status=status.HTTP_200_OK,
            )

        # Create the free subscription record (no Stripe IDs needed)
        sub = StripeSubscription.objects.create(
            user=request.user,
            plan=plan,
            stripe_subscription_id=None,
            stripe_customer_id=None,
            status=StripeSubscription.Status.ACTIVE,
        )
        logger.info("User %s enrolled in free plan '%s'", request.user, plan.name)
        return Response(
            StripeSubscriptionSerializer(sub).data,
            status=status.HTTP_201_CREATED,
        )

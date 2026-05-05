import logging
import uuid

import stripe
from django.conf import settings
from django.utils import timezone as django_timezone
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from datetime import timezone as t
from account.api_views import BearerTokenAuthentication

from .models import StripeCustomer, StripeEvent, StripePlan, StripeSubscription
from .serializers import (
    BillingConfigSerializer,
    CancelSubscriptionSerializer,
    CheckoutSessionResponseSerializer,
    CreateCheckoutSessionSerializer,
    CustomerPortalResponseSerializer,
    CustomerPortalSerializer,
    EnrollFreePlanSerializer,
    InvoiceSerializer,
    MobileSubscribeResponseSerializer,
    MobileSubscribeSerializer,
    PaymentMethodSerializer,
    PaymentSheetResponseSerializer,
    StripePlanSerializer,
    StripeSubscriptionSerializer,
)

logger = logging.getLogger(__name__)


def _push(user, template, **render_kwargs):
    """Fire a push notification task for a billing event. Silently no-ops if user is None."""
    if not user:
        return
    try:
        from account.tasks import send_push_notification_task
        title, body = template.render(**render_kwargs)
        send_push_notification_task.delay(
            user_id=user.id,
            title=title,
            body=body,
            data={"type": template.key, "priority": template.priority.value},
        )
    except Exception:
        logger.exception("Billing push failed for user_id=%s type=%s", getattr(user, "id", None), getattr(template, "key", None))


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
    try:
        StripeCustomer.objects.create(user=user, stripe_customer_id=customer.id)
    except IntegrityError:
        # Concurrent request already created the record — delete the orphan and return the winner
        stripe.Customer.delete(customer.id)
        return user.stripe_customer.stripe_customer_id
    return customer.id


def _ts_to_dt(unix_ts):
    """Convert a Unix timestamp to a UTC datetime, or None."""
    if not unix_ts:
        return None
    return timezone.datetime.fromtimestamp(unix_ts, tz=t.utc)


def _extract_period(stripe_sub):
    """
    Get current_period_start / current_period_end from a Stripe Subscription.

    Stripe API ≥2024-12-18 moved these fields from the subscription level to
    the subscription item level. This helper checks both locations so it works
    across SDK / API versions.

    Returns: (period_start_ts, period_end_ts) — both Unix timestamps or None.
    """
    # Try subscription-level (older API)
    start = stripe_sub.get("current_period_start") if hasattr(stripe_sub, "get") else getattr(stripe_sub, "current_period_start", None)
    end = stripe_sub.get("current_period_end") if hasattr(stripe_sub, "get") else getattr(stripe_sub, "current_period_end", None)

    if start and end:
        return start, end

    # Fallback: subscription item level (newer API 2024-12+)
    items = stripe_sub.get("items") if hasattr(stripe_sub, "get") else getattr(stripe_sub, "items", None)
    if items:
        items_data = items.get("data") if hasattr(items, "get") else getattr(items, "data", None)
        if items_data and len(items_data) > 0:
            first_item = items_data[0]
            start = start or (
                first_item.get("current_period_start") if hasattr(first_item, "get")
                else getattr(first_item, "current_period_start", None)
            )
            end = end or (
                first_item.get("current_period_end") if hasattr(first_item, "get")
                else getattr(first_item, "current_period_end", None)
            )

    return start, end


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

    # Period start/end — handle both old (sub-level) and new (item-level) API
    period_start_ts, period_end_ts = _extract_period(stripe_sub)
    period_start = _ts_to_dt(period_start_ts)
    period_end = _ts_to_dt(period_end_ts)

    # Log a warning if we still couldn't find the period — useful for debugging
    if not period_start or not period_end:
        logger.warning(
            "Subscription %s has no current_period_start/end. "
            "Check Stripe API version. Raw data: items=%s",
            stripe_sub.get("id"),
            stripe_sub.get("items"),
        )

    trial_end = _ts_to_dt(stripe_sub.get("trial_end"))
    canceled_at = _ts_to_dt(stripe_sub.get("canceled_at"))

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

        if not webhook_secret:
            logger.error("STRIPE_WEBHOOK_SECRET is not configured — rejecting all webhooks")
            return Response({"detail": "Webhook not configured."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Verify signature
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except stripe.error.SignatureVerificationError as exc:
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

        # Ensure StripeCustomer exists and points to the correct customer ID
        customer_id = session.get("customer")
        if user and customer_id:
            StripeCustomer.objects.update_or_create(
                user=user,
                defaults={"stripe_customer_id": customer_id},
            )

        _sync_subscription_from_stripe(stripe_sub, user=user)
        logger.info("Subscription %s activated for user_id=%s", subscription_id, user_id)

        from account.push_notifications import N
        _push(user, N.SUBSCRIPTION_ACTIVATED)

    def _handle_subscription_updated(self, stripe_sub):
        """Subscription changed (status, plan, renewal, cancel_at_period_end)."""
        local_sub = _sync_subscription_from_stripe(stripe_sub)
        logger.info("Subscription %s updated — status=%s", stripe_sub["id"], stripe_sub["status"])

        if not local_sub or not local_sub.user:
            return

        from account.push_notifications import N
        new_status = stripe_sub.get("status", "")

        if new_status == "canceled":
            _push(local_sub.user, N.SUBSCRIPTION_CANCELED)
        elif new_status == "past_due":
            _push(local_sub.user, N.SUBSCRIPTION_PAST_DUE)

        # Trial ending soon — notify when trial_end is within 3 days
        trial_end_ts = stripe_sub.get("trial_end")
        if trial_end_ts:
            from datetime import timezone as dt_tz, datetime
            trial_end_dt = datetime.fromtimestamp(trial_end_ts, tz=dt_tz.utc)
            days_left = (trial_end_dt - django_timezone.now()).days
            if 0 <= days_left <= 3:
                _push(local_sub.user, N.TRIAL_ENDING_SOON, days=str(days_left))

    def _handle_subscription_deleted(self, stripe_sub):
        """Subscription canceled immediately (e.g. via API or admin)."""
        local_sub = _sync_subscription_from_stripe(stripe_sub)
        logger.info("Subscription %s deleted/canceled", stripe_sub["id"])

        from account.push_notifications import N
        if local_sub and local_sub.user:
            _push(local_sub.user, N.SUBSCRIPTION_CANCELED)

    def _handle_invoice_payment_succeeded(self, invoice):
        """
        Successful renewal payment. Re-sync subscription to capture new
        period_start / period_end dates.
        """
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return

        stripe_sub = stripe.Subscription.retrieve(subscription_id)
        local_sub = _sync_subscription_from_stripe(stripe_sub)
        logger.info("Invoice payment succeeded for subscription %s", subscription_id)

        from account.push_notifications import N
        if local_sub and local_sub.user:
            _push(local_sub.user, N.SUBSCRIPTION_RENEWED)

    def _handle_invoice_payment_failed(self, invoice):
        """
        Failed payment — subscription may become past_due or unpaid.
        Re-sync so our DB reflects the new status.
        """
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return

        stripe_sub = stripe.Subscription.retrieve(subscription_id)
        local_sub = _sync_subscription_from_stripe(stripe_sub)
        logger.warning("Invoice payment FAILED for subscription %s — new status=%s", subscription_id, stripe_sub["status"])

        from account.push_notifications import N
        if local_sub and local_sub.user:
            _push(local_sub.user, N.PAYMENT_FAILED)


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

        # Check for an existing active or in-progress paid subscription
        paid_active = StripeSubscription.objects.filter(
            user=request.user,
            status__in=[
                StripeSubscription.Status.ACTIVE,
                StripeSubscription.Status.TRIALING,
                StripeSubscription.Status.INCOMPLETE,
                StripeSubscription.Status.PAST_DUE,
            ],
            stripe_subscription_id__isnull=False,
        ).exists()
        if paid_active:
            return Response(
                {"detail": "You already have an active paid subscription. Use the billing portal to change your plan."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check-and-create atomically to prevent concurrent duplicate free subscriptions
        with transaction.atomic():
            existing = StripeSubscription.objects.select_for_update().filter(
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

        from account.push_notifications import N
        _push(request.user, N.SUBSCRIPTION_ACTIVATED)

        return Response(
            StripeSubscriptionSerializer(sub).data,
            status=status.HTTP_201_CREATED,
        )


# ── React Native / Mobile SDK views ──────────────────────────────────────────

class BillingConfigView(APIView):
    """Return the Stripe publishable key for SDK initialisation."""

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Get Stripe publishable key",
        responses={200: BillingConfigSerializer},
    )
    def get(self, request):
        return Response(
            {"publishable_key": getattr(settings, "STRIPE_PUBLISHABLE_KEY", "")},
            status=status.HTTP_200_OK,
        )


class PaymentSheetView(APIView):
    """
    Initialise a Stripe Payment Sheet for saving a payment method.

    Returns the three values required by the React Native
    `initPaymentSheet({ customerId, customerEphemeralKeySecret,
    setupIntentClientSecret })` call.
    """

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    # Stripe API version expected by the React Native SDK
    _STRIPE_API_VERSION = "2024-06-20"

    @extend_schema(
        summary="Initialise Payment Sheet (mobile)",
        responses={200: PaymentSheetResponseSerializer},
    )
    def post(self, request):
        try:
            customer_id = _get_or_create_stripe_customer(request.user)

            ephemeral_key = stripe.EphemeralKey.create(
                customer=customer_id,
                stripe_version=self._STRIPE_API_VERSION,
            )

            setup_intent = stripe.SetupIntent.create(
                customer=customer_id,
                payment_method_types=["card"],
                metadata={"user_id": str(request.user.pk)},
            )
        except stripe.StripeError as exc:
            logger.error("PaymentSheet init failed: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            {
                "customer_id": customer_id,
                "ephemeral_key_secret": ephemeral_key.secret,
                "setup_intent_client_secret": setup_intent.client_secret,
                "publishable_key": getattr(settings, "STRIPE_PUBLISHABLE_KEY", ""),
            },
            status=status.HTTP_200_OK,
        )


class MobileSubscribeView(APIView):
    """
    Create a Stripe subscription and return a client_secret for the mobile SDK.

    Handles three scenarios automatically:
      1. Paid subscription, bills immediately → returns PaymentIntent client_secret
      2. Paid subscription, bills in future (custom billing cycle) / trial
         → returns SetupIntent client_secret (saves card for auto-charge)
      3. $0 / fully credited → returns null (no payment needed)

    Response always includes `intent_type`:
      - "payment" → frontend uses `paymentIntentClientSecret` in initPaymentSheet
      - "setup"   → frontend uses `setupIntentClientSecret` in initPaymentSheet
      - null      → subscription already active, no Payment Sheet needed
    """

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Subscribe to a plan (mobile)",
        request=MobileSubscribeSerializer,
        responses={200: MobileSubscribeResponseSerializer, 201: MobileSubscribeResponseSerializer},
    )
    def post(self, request):
        serializer = MobileSubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        price_id = serializer.validated_data["price_id"]

        # ── Validate plan ────────────────────────────────────────────────────
        plan = StripePlan.objects.filter(stripe_price_id=price_id, is_active=True).first()
        if not plan:
            return Response(
                {"detail": "No active plan found for that price_id."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if plan.is_free:
            return Response(
                {"detail": "This is a free plan. Use POST /api/billing/free/ to enroll."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Guard: handle existing subscriptions by status ──────────────────
        existing_sub = StripeSubscription.objects.filter(
            user=request.user,
            status__in=[
                StripeSubscription.Status.ACTIVE,
                StripeSubscription.Status.TRIALING,
                StripeSubscription.Status.INCOMPLETE,
                StripeSubscription.Status.PAST_DUE,
            ],
            stripe_subscription_id__isnull=False,
        ).order_by("-created_at").first()

        if existing_sub:
            # ── Truly active / trialing → hard block ────────────────────────
            if existing_sub.status in (
                StripeSubscription.Status.ACTIVE,
                StripeSubscription.Status.TRIALING,
            ):
                return Response(
                    {"detail": "You already have an active subscription. Use POST /api/billing/cancel/ to change plans."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # ── Past due → must fix payment method, not re-subscribe ────────
            if existing_sub.status == StripeSubscription.Status.PAST_DUE:
                return Response(
                    {"detail": "Your subscription is past due. Please update your payment method via /api/billing/payment-methods/."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # ── Incomplete → user cancelled the Payment Sheet previously ────
            # Strategy:
            #   Same plan  → reuse the existing Stripe subscription (return
            #                 a fresh client_secret so user can try again).
            #   Diff plan  → cancel the stale incomplete sub, fall through to
            #                 create a new one for the requested plan.
            if existing_sub.status == StripeSubscription.Status.INCOMPLETE:
                same_plan = (
                    existing_sub.plan_id is not None
                    and existing_sub.plan
                    and existing_sub.plan.stripe_price_id == price_id
                )

                if same_plan:
                    # Retrieve the live Stripe object to confirm it is still incomplete
                    try:
                        stripe_sub = stripe.Subscription.retrieve(
                            existing_sub.stripe_subscription_id,
                            expand=[
                                "latest_invoice.payment_intent",
                                "latest_invoice.confirmation_secret",
                                "pending_setup_intent",
                                "items",
                            ],
                        )
                    except stripe.StripeError as exc:
                        logger.error(
                            "Failed to retrieve incomplete subscription %s: %s",
                            existing_sub.stripe_subscription_id,
                            exc,
                        )
                        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

                    # Sync whatever Stripe now says (it may have auto-expired)
                    _sync_subscription_from_stripe(stripe_sub, user=request.user)

                    if stripe_sub.status == "incomplete":
                        # Still live — resolve a new client_secret and let the
                        # user try the Payment Sheet again (no new sub created)
                        customer_id = (
                            existing_sub.stripe_customer_id
                            or _get_or_create_stripe_customer(request.user)
                        )
                        client_secret, intent_type = self._resolve_client_secret(
                            stripe_sub=stripe_sub,
                            customer_id=customer_id,
                            price_id=price_id,
                            user_pk=request.user.pk,
                        )
                        logger.info(
                            "Reusing incomplete subscription %s for user_id=%s (retry after cancel)",
                            stripe_sub.id,
                            request.user.pk,
                        )
                        return Response(
                            {
                                "subscription_id": stripe_sub.id,
                                "client_secret": client_secret,
                                "intent_type": intent_type,
                                "status": stripe_sub.status,
                            },
                            status=status.HTTP_200_OK,  # 200 = reused, not 201
                        )
                    # Else: Stripe already expired/canceled it — fall through
                    # to create a brand-new subscription below.

                else:
                    # Different plan requested — cancel the stale incomplete sub
                    # so Stripe doesn't hold the customer in limbo.
                    try:
                        stripe.Subscription.cancel(existing_sub.stripe_subscription_id)
                        logger.info(
                            "Canceled stale incomplete subscription %s (user switching plan)",
                            existing_sub.stripe_subscription_id,
                        )
                    except stripe.StripeError as exc:
                        logger.warning(
                            "Could not cancel stale incomplete subscription %s: %s",
                            existing_sub.stripe_subscription_id,
                            exc,
                        )
                    # Update local record regardless of Stripe call outcome
                    existing_sub.status = StripeSubscription.Status.CANCELED
                    existing_sub.save(update_fields=["status", "updated_at"])
                    # Fall through to create a new subscription for the new plan

        # ── Create subscription ──────────────────────────────────────────────
        try:
            customer_id = _get_or_create_stripe_customer(request.user)

            stripe_sub = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                payment_behavior="default_incomplete",
                payment_settings={"save_default_payment_method": "on_subscription"},
                expand=[
                    "latest_invoice.payment_intent",
                    "latest_invoice.confirmation_secret",
                    "pending_setup_intent",
                    "items",  # ensures items.data[].current_period_start/end are populated
                ],
                metadata={"user_id": str(request.user.pk)},
                idempotency_key=f"mobile-sub-{request.user.pk}-{price_id}-{uuid.uuid4().hex}",
            )
        except stripe.StripeError as exc:
            logger.error("Mobile subscribe failed: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        # Persist locally before any fallback API calls
        _sync_subscription_from_stripe(stripe_sub, user=request.user)

        # ── Resolve a usable client_secret ───────────────────────────────────
        client_secret, intent_type = self._resolve_client_secret(
            stripe_sub=stripe_sub,
            customer_id=customer_id,
            price_id=price_id,
            user_pk=request.user.pk,
        )

        if not client_secret:
            # Truly no payment required (already active, fully credited, etc.)
            return Response(
                {
                    "subscription_id": stripe_sub.id,
                    "client_secret": None,
                    "intent_type": None,
                    "status": stripe_sub.status,
                    "detail": "No payment required. Subscription is already active or fully credited.",
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            {
                "subscription_id": stripe_sub.id,
                "client_secret": client_secret,
                "intent_type": intent_type,  # "payment" or "setup"
                "status": stripe_sub.status,
            },
            status=status.HTTP_201_CREATED,
        )

    # ------------------------------------------------------------------ #
    # Helper: multi-strategy client_secret resolver                       #
    # ------------------------------------------------------------------ #
    def _resolve_client_secret(self, stripe_sub, customer_id, price_id, user_pk):
        """
        Try 4 strategies in order:
          1. latest_invoice.confirmation_secret  (Stripe API 2024-12+)
          2. latest_invoice.payment_intent.client_secret  (classic)
          3. subscription.pending_setup_intent.client_secret  (trials / future billing)
          4. Create a fresh SetupIntent  (last-resort fallback)

        Returns (client_secret, intent_type) or (None, None).
        """

        # ── Strategy 1 & 2: latest_invoice ──────────────────────────────────
        latest_invoice = self._get_attr(stripe_sub, "latest_invoice")

        if isinstance(latest_invoice, str):
            # Bare ID — fetch the full object
            try:
                latest_invoice = stripe.Invoice.retrieve(
                    latest_invoice,
                    expand=["payment_intent", "confirmation_secret"],
                )
            except stripe.StripeError as exc:
                logger.warning("Failed to retrieve invoice: %s", exc)
                latest_invoice = None

        if latest_invoice:
            # Strategy 1: confirmation_secret (newer API, object with client_secret+type)
            confirmation_secret = self._get_attr(latest_invoice, "confirmation_secret")
            if confirmation_secret:
                cs = self._get_attr(confirmation_secret, "client_secret")
                ctype = self._get_attr(confirmation_secret, "type") or "payment_intent"
                if cs:
                    intent_type = "setup" if ctype == "setup_intent" else "payment"
                    logger.info("Using confirmation_secret for subscription %s", stripe_sub.id)
                    return cs, intent_type

            # Strategy 2: classic payment_intent on the invoice
            payment_intent = self._get_attr(latest_invoice, "payment_intent")
            if isinstance(payment_intent, str):
                try:
                    payment_intent = stripe.PaymentIntent.retrieve(payment_intent)
                except stripe.StripeError as exc:
                    logger.warning("Failed to retrieve PaymentIntent: %s", exc)
                    payment_intent = None
            if payment_intent:
                cs = self._get_attr(payment_intent, "client_secret")
                if cs:
                    logger.info("Using invoice.payment_intent for subscription %s", stripe_sub.id)
                    return cs, "payment"

        # ── Strategy 3: pending_setup_intent (trials / future billing) ──────
        pending_setup_intent = self._get_attr(stripe_sub, "pending_setup_intent")
        if isinstance(pending_setup_intent, str):
            try:
                pending_setup_intent = stripe.SetupIntent.retrieve(pending_setup_intent)
            except stripe.StripeError as exc:
                logger.warning("Failed to retrieve pending SetupIntent: %s", exc)
                pending_setup_intent = None
        if pending_setup_intent:
            cs = self._get_attr(pending_setup_intent, "client_secret")
            if cs:
                logger.info("Using pending_setup_intent for subscription %s", stripe_sub.id)
                return cs, "setup"

        # ── Strategy 4: Create a fresh SetupIntent as a last resort ─────────
        # This covers products with a custom future billing_cycle_anchor,
        # where Stripe doesn't generate the invoice until the anchor date.
        # The saved card will be used to auto-charge when billing starts.
        try:
            setup_intent = stripe.SetupIntent.create(
                customer=customer_id,
                payment_method_types=["card"],
                usage="off_session",
                # Link to the subscription so Stripe auto-charges this card when billing starts
                metadata={
                    "subscription_id": stripe_sub.id,
                    "price_id": price_id,
                    "user_id": str(user_pk),
                },
            )
            # Attach the SetupIntent to the subscription so the saved card is used for billing
            stripe.Subscription.modify(
                stripe_sub.id,
                payment_settings={"save_default_payment_method": "on_subscription"},
            )
            logger.info("Fallback SetupIntent %s created for subscription %s",
                        setup_intent.id, stripe_sub.id)
            return setup_intent.client_secret, "setup"
        except stripe.StripeError as exc:
            logger.error("Fallback SetupIntent creation failed: %s", exc)
            return None, None

    @staticmethod
    def _get_attr(obj, key):
        """Stripe SDK v12 objects support both attribute and dict access, but
        defensively try both in case of version differences."""
        if obj is None:
            return None
        if hasattr(obj, key) and getattr(obj, key) is not None:
            return getattr(obj, key)
        if hasattr(obj, "get"):
            try:
                return obj.get(key)
            except Exception:
                return None
        return None



class CancelSubscriptionView(APIView):
    """
    Cancel the authenticated user's active subscription without requiring a
    browser redirect to the Stripe portal.

    Pass `{ "immediately": true }` to cancel right now; omit or set false to
    cancel at the end of the current billing period.
    """

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Cancel subscription (mobile)",
        request=CancelSubscriptionSerializer,
        responses={200: StripeSubscriptionSerializer},
    )
    def post(self, request):
        serializer = CancelSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        immediately = serializer.validated_data.get("immediately", False)

        sub = (
            StripeSubscription.objects.filter(
                user=request.user,
                status__in=[
                    StripeSubscription.Status.ACTIVE,
                    StripeSubscription.Status.TRIALING,
                    StripeSubscription.Status.PAST_DUE,
                    StripeSubscription.Status.INCOMPLETE,
                ],
                stripe_subscription_id__isnull=False,
            )
            .order_by("-created_at")
            .first()
        )

        if not sub:
            return Response(
                {"detail": "No cancellable paid subscription found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            if immediately:
                stripe_sub = stripe.Subscription.cancel(sub.stripe_subscription_id)
            else:
                stripe_sub = stripe.Subscription.modify(
                    sub.stripe_subscription_id,
                    cancel_at_period_end=True,
                )
        except stripe.StripeError as exc:
            logger.error("Subscription cancellation failed: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        updated_sub = _sync_subscription_from_stripe(stripe_sub, user=request.user)

        from account.push_notifications import N
        _push(request.user, N.SUBSCRIPTION_CANCELED)

        return Response(StripeSubscriptionSerializer(updated_sub).data, status=status.HTTP_200_OK)


class PaymentMethodListView(APIView):
    """
    List the authenticated user's saved payment methods (cards).

    Marks the default payment method (attached to the Stripe customer) as
    `is_default: true`.
    """

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="List saved payment methods (mobile)",
        responses={200: PaymentMethodSerializer(many=True)},
    )
    def get(self, request):
        try:
            customer_id = _get_or_create_stripe_customer(request.user)

            # Fetch customer to get the default payment method
            stripe_customer = stripe.Customer.retrieve(customer_id)
            default_pm_id = (
                stripe_customer.get("invoice_settings", {}).get("default_payment_method")
                or stripe_customer.get("default_source")
            )

            payment_methods = stripe.PaymentMethod.list(
                customer=customer_id,
                type="card",
            )
        except stripe.StripeError as exc:
            logger.error("List payment methods failed: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        results = []
        for pm in payment_methods.data:
            card = pm.get("card") or {}
            results.append(
                {
                    "id": pm["id"],
                    "type": pm["type"],
                    "card": {
                        "brand": card.get("brand", ""),
                        "last4": card.get("last4", ""),
                        "exp_month": card.get("exp_month", 0),
                        "exp_year": card.get("exp_year", 0),
                    } if card else None,
                    "is_default": pm["id"] == default_pm_id,
                    "created": pm["created"],
                }
            )

        return Response(results, status=status.HTTP_200_OK)


class PaymentMethodDeleteView(APIView):
    """
    Detach a payment method from the authenticated user's Stripe customer.

    Returns 204 on success.
    """

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Remove a saved payment method (mobile)",
        responses={204: None, 403: None, 404: None},
    )
    def delete(self, request, pm_id: str):
        try:
            stripe_cust = StripeCustomer.objects.get(user=request.user)
        except StripeCustomer.DoesNotExist:
            return Response({"detail": "No payment methods found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            pm = stripe.PaymentMethod.retrieve(pm_id)
            if pm.get("customer") != stripe_cust.stripe_customer_id:
                return Response(
                    {"detail": "Payment method does not belong to this user."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            stripe.PaymentMethod.detach(pm_id)
        except stripe.StripeError as exc:
            logger.error("Detach payment method failed: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(status=status.HTTP_204_NO_CONTENT)


class InvoiceListView(APIView):
    """
    List the authenticated user's Stripe invoices (most recent first).

    Each invoice includes a `invoice_pdf` link for download and a
    `hosted_invoice_url` for viewing in a browser/web view.
    """

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="List invoices (mobile)",
        responses={200: InvoiceSerializer(many=True)},
    )
    def get(self, request):
        try:
            customer_id = _get_or_create_stripe_customer(request.user)

            invoices = stripe.Invoice.list(customer=customer_id, limit=24)
        except stripe.StripeError as exc:
            logger.error("List invoices failed: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        results = [
            {
                "id": inv["id"],
                "amount_due": inv["amount_due"],
                "amount_paid": inv["amount_paid"],
                "currency": inv["currency"],
                "status": inv["status"],
                "created": inv["created"],
                "invoice_pdf": inv.get("invoice_pdf"),
                "hosted_invoice_url": inv.get("hosted_invoice_url"),
                "period_start": inv.get("period_start") or 0,
                "period_end": inv.get("period_end") or 0,
            }
            for inv in invoices.data
        ]

        return Response(results, status=status.HTTP_200_OK)

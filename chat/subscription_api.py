"""Subscription API: subscribe to request updates and deal alerts (AI-based)."""
from ninja import Router, Schema

from account.api import AuthBearer

subscription_router = Router(tags=["Subscription"], auth=AuthBearer())


class SubscribeIn(Schema):
    subscription_type: str  # "request_updates" | "deal_alerts" | "daily_digest"
    request_id: int | None = None  # required for request_updates; null for deal_alerts (all deals)


class SubscriptionOut(Schema):
    id: int
    subscription_type: str
    request_id: int | None
    tracking_code: str | None
    is_active: bool
    created_at: str


@subscription_router.get("/subscriptions", response={200: list[SubscriptionOut]})
def list_my_subscriptions(request):
    """List current user's subscriptions (request updates, deal alerts)."""
    from .models import Subscription
    qs = Subscription.objects.filter(user=request.auth, is_active=True).select_related("request")
    return 200, [
        {
            "id": s.id,
            "subscription_type": s.subscription_type,
            "request_id": s.request_id,
            "tracking_code": s.request.tracking_code if s.request else None,
            "is_active": s.is_active,
            "created_at": s.created_at.isoformat(),
        }
        for s in qs
    ]


@subscription_router.post("/subscriptions", response={201: SubscriptionOut, 400: dict})
def subscribe(request, payload: SubscribeIn):
    """Subscribe to request updates (for a request) or deal alerts (AI-detected deals)."""
    from .models import Subscription, ShyRequest
    st = (payload.subscription_type or "").strip()
    if st not in ("request_updates", "deal_alerts", "daily_digest"):
        return 400, {"detail": "subscription_type must be request_updates, deal_alerts, or daily_digest"}
    req = None
    if st == "request_updates":
        if not payload.request_id:
            return 400, {"detail": "request_id required for request_updates"}
        try:
            req = ShyRequest.objects.get(pk=payload.request_id, user=request.auth)
        except ShyRequest.DoesNotExist:
            return 400, {"detail": "Request not found or not yours."}
    sub, created = Subscription.objects.get_or_create(
        user=request.auth,
        request=req,
        subscription_type=st,
        defaults={"is_active": True},
    )
    if not created:
        sub.is_active = True
        sub.save(update_fields=["is_active"])
    return 201, {
        "id": sub.id,
        "subscription_type": sub.subscription_type,
        "request_id": sub.request_id,
        "tracking_code": sub.request.tracking_code if sub.request else None,
        "is_active": sub.is_active,
        "created_at": sub.created_at.isoformat(),
    }


@subscription_router.delete("/subscriptions/{subscription_id}", response={204: None, 404: dict})
def unsubscribe(request, subscription_id: int):
    """Unsubscribe (deactivate) a subscription."""
    from .models import Subscription
    try:
        sub = Subscription.objects.get(pk=subscription_id, user=request.auth)
    except Subscription.DoesNotExist:
        return 404, {"detail": "Subscription not found."}
    sub.is_active = False
    sub.save(update_fields=["is_active"])
    return 204, None

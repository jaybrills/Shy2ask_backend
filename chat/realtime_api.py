from typing import List, Optional
from datetime import datetime
from ninja import Router, Schema
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from .models import ShyRequest, Message, Attachment
from account.api import AuthBearer
from .message_service import MessageAccessError, can_access_conversation, create_message_for_request, resolve_display_name
from .views import send_notification
from rest_framework.authtoken.models import Token

realtime_router = Router(tags=["Requests"])

# ---------- Schemas ----------

class AttachmentOut(Schema):
    id: int
    file: str
    uploaded_at: datetime

class MessageOut(Schema):
    id: int
    sender: str
    sender_display_name: str
    display_name: str
    body: str
    clean_body: str
    is_blocked: bool
    created_at: datetime

class MessageIn(Schema):
    body: str
    alias: Optional[str] = None
    tracking_code: Optional[str] = None


class ReplyByTrackingIn(Schema):
    tracking_code: str
    body: str
    alias: Optional[str] = None

class ShyRequestIn(Schema):
    requester_name: str
    requester_email: str
    requester_phone: str = ""
    requester_alias: Optional[str] = None
    target_name: str = ""
    target_email: str = ""
    target_phone: str = ""
    target_address: str = ""
    description: str
    service_channel: str = "email"
    call_minutes: int = 0

class ShyRequestOut(Schema):
    id: int
    tracking_code: str
    requester_name: str
    requester_email: str
    requester_phone: str
    requester_alias: str
    target_name: str
    target_email: str
    target_phone: str
    target_address: str
    description: str
    service_channel: str
    call_minutes: int
    quoted_price_chf: float
    country_code: str
    status: str
    created_at: datetime
    attachments: List[AttachmentOut] = []

# ---------- Endpoints ----------

@realtime_router.post("/", response={201: ShyRequestOut}, auth=AuthBearer())
def create_request(request, payload: ShyRequestIn):
    """Create a new ShyRequest and send notifications."""
    user = request.auth
    
    # Logic from ShyRequestSerializer.create
    alias = payload.requester_alias or ""
    if user and not alias:
        alias = getattr(user, "alias_name", "") or ""
        
    country_code = getattr(request, "detected_country", "") or ""

    shy_request = ShyRequest.objects.create(
        user=user if user else None,
        requester_alias=alias,
        status=ShyRequest.Status.SUBMITTED,
        country_code=country_code,
        **payload.dict(exclude={'requester_alias'})
    )
    
    # Logic from ShyRequestViewSet.perform_create
    try:
        send_notification(
            subject="New request created",
            body=f"Your request with tracking code {shy_request.tracking_code} has been created successfully.",
            recipient=shy_request.requester_email,
            related_request=shy_request,
            use_ai_enhance=True
        )
    except Exception as e:
        print(f"Error sending initial notification: {e}")

    return 201, _shy_request_to_dict(shy_request)

@realtime_router.get("/", response=List[ShyRequestOut], auth=AuthBearer())
def list_requests(request):
    """List requests for the logged-in user."""
    user = request.auth
    qs = ShyRequest.objects.filter(
        Q(user=user)
        | Q(user__isnull=True, requester_email__iexact=user.email)
        | Q(target_email__iexact=user.email)
    ).order_by("-created_at")
    return [_shy_request_to_dict(r) for r in qs]

@realtime_router.get("/{request_id}/conversation", response={200: List[MessageOut], 403: dict})
def get_conversation(request, request_id: int):
    """Retrieve messages for a given request (owner token or tracking_code query param)."""
    shy_request = get_object_or_404(ShyRequest, pk=request_id)
    user = _get_user_from_request(request)
    tracking_code = (request.GET.get("tracking_code") or "").strip()
    if not can_access_conversation(shy_request, user=user, tracking_code=tracking_code):
        return 403, {"detail": "Provide owner Bearer token or valid tracking_code to access this conversation."}
    messages = Message.objects.filter(request=shy_request).select_related("author", "request").order_by("created_at")
    
    return 200, [_message_to_dict(msg) for msg in messages]

@realtime_router.post("/{request_id}/messages", response={201: MessageOut, 400: dict, 403: dict})
def send_message(request, request_id: int, payload: MessageIn):
    """Send a request message (owner token) or responder message (tracking_code)."""
    shy_request = get_object_or_404(ShyRequest, pk=request_id)

    user = _get_user_from_request(request)
    tracking_code = (payload.tracking_code or "").strip()
    if not can_access_conversation(shy_request, user=user, tracking_code=tracking_code):
        return 403, {
            "detail": "Provide owner Bearer token or valid tracking_code to access this request conversation."
        }
    try:
        msg = create_message_for_request(
            shy_request,
            payload.body,
            user=user,
            tracking_code=tracking_code,
            alias=payload.alias,
        )
    except MessageAccessError as exc:
        return 403, {"detail": str(exc)}
    except ValidationError as exc:
        return 400, {"detail": exc.messages}
    return 201, _message_to_dict(msg)


@realtime_router.post("/reply-by-tracking", response={201: MessageOut, 400: dict, 403: dict, 404: dict})
def reply_by_tracking(request, payload: ReplyByTrackingIn):
    """Reply to a request with tracking_code (no login required)."""
    shy_request = get_object_or_404(ShyRequest, tracking_code=payload.tracking_code.strip())
    try:
        msg = create_message_for_request(
            shy_request,
            payload.body,
            tracking_code=payload.tracking_code.strip(),
            alias=payload.alias,
        )
    except MessageAccessError as exc:
        return 403, {"detail": str(exc)}
    except ValidationError as exc:
        return 400, {"detail": exc.messages}
    return 201, _message_to_dict(msg)


@realtime_router.get("/by-tracking/{tracking_code}/conversation", response=List[MessageOut])
def get_conversation_by_tracking(request, tracking_code: str):
    """Get conversation by tracking code (for responder portal without login)."""
    shy_request = get_object_or_404(ShyRequest, tracking_code=tracking_code.strip())
    messages = Message.objects.filter(request=shy_request).select_related("author", "request").order_by("created_at")
    return [_message_to_dict(msg) for msg in messages]

# ---------- Helpers ----------

def _shy_request_to_dict(obj):
    return {
        "id": obj.id,
        "tracking_code": obj.tracking_code,
        "requester_name": obj.requester_name,
        "requester_email": obj.requester_email,
        "requester_phone": obj.requester_phone,
        "requester_alias": obj.requester_alias,
        "target_name": obj.target_name,
        "target_email": obj.target_email,
        "target_phone": obj.target_phone,
        "target_address": obj.target_address,
        "description": obj.description,
        "service_channel": obj.service_channel,
        "call_minutes": obj.call_minutes,
        "quoted_price_chf": float(obj.quoted_price_chf),
        "country_code": obj.country_code,
        "status": obj.status,
        "created_at": obj.created_at,
        "attachments": [
            {"id": a.id, "file": a.file.url, "uploaded_at": a.uploaded_at}
            for a in obj.attachments.all()
        ]
    }

def _message_to_dict(msg):
    display_name = resolve_display_name(msg)
    return {
        "id": msg.id,
        "sender": msg.sender,
        "sender_display_name": msg.sender_display_name,
        "display_name": display_name,
        "body": msg.body,
        "clean_body": msg.clean_body,
        "is_blocked": msg.is_blocked,
        "created_at": msg.created_at,
    }


def _get_user_from_request(request):
    """Auth is optional on these endpoints; attempt bearer token lookup when not already authenticated."""
    user = getattr(request, "auth", None) or getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return user
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if auth_header.lower().startswith("bearer "):
        token_key = auth_header.split(" ", 1)[1].strip()
        if token_key:
            tok = Token.objects.filter(key=token_key).select_related("user").first()
            if tok and tok.user and tok.user.is_active:
                return tok.user
    return None

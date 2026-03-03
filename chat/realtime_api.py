from typing import List, Optional
from datetime import datetime
from ninja import Router, Schema, ModelSchema
from django.db.models import Q
from django.shortcuts import get_object_or_404
from .models import ShyRequest, Conversation, Message, Attachment
from account.api import AuthBearer
from .views import send_notification
from .utils import censor_text

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
    """Create a new ShyRequest. Automatically creates a Conversation and sends notifications."""
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
    
    # Automatically create conversation (logic migrated from serializer)
    Conversation.objects.create(request=shy_request)
    
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
        Q(user=user) | Q(user__isnull=True, requester_email__iexact=user.email)
    ).order_by("-created_at")
    return [_shy_request_to_dict(r) for r in qs]

@realtime_router.get("/{request_id}/conversation", response=List[MessageOut])
def get_conversation(request, request_id: int):
    """Retrieve messages for a given request."""
    shy_request = get_object_or_404(ShyRequest, pk=request_id)
    conversation, _ = Conversation.objects.get_or_create(request=shy_request)
    messages = conversation.messages.order_by("created_at")
    
    return [_message_to_dict(msg) for msg in messages]

@realtime_router.post("/{request_id}/messages", response={201: MessageOut})
def send_message(request, request_id: int, payload: MessageIn):
    """Send a message for a request (REST alternative to WebSocket)."""
    shy_request = get_object_or_404(ShyRequest, pk=request_id)
    conversation, _ = Conversation.objects.get_or_create(request=shy_request)
    
    clean_body, blocked = censor_text(payload.body)
    
    author = request.auth if hasattr(request, 'auth') and request.auth else None
    
    msg = Message.objects.create(
        conversation=conversation,
        sender=Message.Sender.REQUESTER,
        author=author,
        sender_display_name=payload.alias or "",
        body=payload.body,
        clean_body=clean_body,
        is_blocked=blocked,
    )
    return 201, _message_to_dict(msg)

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
    # Resolve display name similar to MessageSerializer
    req = msg.conversation.request
    display_name = msg.sender_display_name
    if not display_name:
        if msg.sender == Message.Sender.REQUESTER and msg.author:
            display_name = getattr(msg.author, "alias_name", None) or req.requester_alias or req.requester_name
        elif msg.sender == Message.Sender.REQUESTER:
            display_name = req.requester_alias or req.requester_name
        elif msg.sender == Message.Sender.RESPONDER:
            display_name = req.requester_alias or req.requester_name or "Responder"
        else:
            display_name = "Staff"

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

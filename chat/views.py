from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import DealForm, MessageForm, ShyRequestForm, SignUpForm
from .models import Attachment, Conversation, Deal, Message, ShyRequest


def detect_country_code(request):
    """Try to detect ISO country code from common headers or an override."""
    override = request.GET.get("country_override")
    if override:
        return override.upper()
    header_name = getattr(settings, "COUNTRY_HEADER", "HTTP_X_COUNTRY_CODE")
    for header in [header_name, "HTTP_CF_IPCOUNTRY", "HTTP_X_COUNTRY"]:
        code = request.META.get(header)
        if code:
            return code.upper()
    return None


def country_is_allowed(request):
    allowed_code = getattr(settings, "ALLOWED_COUNTRY_CODE", "CH").upper()
    detected_code = detect_country_code(request)
    if detected_code:
        return detected_code == allowed_code, detected_code
    # If we cannot detect the country, allow only in DEBUG to keep local dev easy.
    return settings.DEBUG, detected_code


def coming_soon(request):
    _, detected_code = country_is_allowed(request)
    return render(
        request,
        "chat/coming_soon.html",
        {"country_code": detected_code, "allowed_code": settings.ALLOWED_COUNTRY_CODE},
    )


def home(request):
    allowed, detected = country_is_allowed(request)
    if not allowed:
        return coming_soon(request)
    context = {
        "form": ShyRequestForm(),
        "detected_country": detected or settings.ALLOWED_COUNTRY_CODE,
    }
    return render(request, "chat/home.html", context)


def request_create(request):
    allowed, detected = country_is_allowed(request)
    if not allowed:
        return coming_soon(request)

    if request.method == "POST":
        form = ShyRequestForm(request.POST, request.FILES)
        if form.is_valid():
            shy_request: ShyRequest = form.save(commit=False)
            if request.user.is_authenticated:
                shy_request.user = request.user
            shy_request.country_code = detected or settings.ALLOWED_COUNTRY_CODE
            shy_request.status = ShyRequest.Status.SUBMITTED
            shy_request.save()

            for upload in request.FILES.getlist("attachments"):
                Attachment.objects.create(request=shy_request, file=upload)

            conversation, _ = Conversation.objects.get_or_create(request=shy_request)
            Message.objects.create(
                conversation=conversation,
                sender=Message.Sender.REQUESTER,
                author=request.user if request.user.is_authenticated else None,
                body=shy_request.description,
            )
            Deal.objects.get_or_create(request=shy_request, defaults={"amount": 0})

            send_notification(
                subject="New Shy2Ask request submitted",
                body=f"Request {shy_request.id} from {shy_request.requester_email}",
                recipient=settings.ADMIN_NOTIFY_EMAIL,
                related_request=shy_request,
            )
            send_notification(
                subject="We received your shy request",
                body="Thanks for trusting Shy2Ask. We will contact the recipient and update you.",
                recipient=shy_request.requester_email,
                related_request=shy_request,
            )

            messages.success(
                request,
                "We received your shy question. We will reach out with an update soon.",
            )
            return redirect(reverse("core:request_success"))
    else:
        form = ShyRequestForm()

    return render(
        request,
        "chat/request_form.html",
        {
            "form": form,
            "detected_country": detected or settings.ALLOWED_COUNTRY_CODE,
        },
    )


def request_success(request):
    return render(request, "chat/request_success.html")


def send_notification(subject, body, recipient, related_request=None):
    if not recipient:
        return
    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [recipient],
        fail_silently=True,
    )
    from .models import Notification
    from .websocket_utils import send_notification_websocket

    notification = Notification.objects.create(
        recipient_email=recipient,
        subject=subject,
        body=body,
        related_request=related_request,
    )

    # Send WebSocket notification if user is logged in
    if related_request and related_request.user:
        send_notification_websocket(
            related_request.user.id,
            {
                "id": notification.id,
                "subject": notification.subject,
                "body": notification.body,
                "created_at": notification.created_at.isoformat(),
                "created_at_display": notification.created_at.strftime("%b %d, %H:%M"),
                "request_id": related_request.id if related_request else None,
                "tracking_code": related_request.tracking_code if related_request else None,
            }
        )


def pricing(request):
    return render(request, "chat/pricing.html")


def about(request):
    return render(request, "chat/about.html")


def features(request):
    return render(request, "chat/features.html")


def signup(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Welcome to Shy2Ask!")
            return redirect("core:dashboard")
    else:
        form = SignUpForm()
    return render(request, "chat/signup.html", {"form": form})


@login_required
def dashboard(request):
    requests = ShyRequest.objects.filter(user=request.user).order_by("-created_at")
    return render(
        request,
        "chat/dashboard.html",
        {"requests": requests, "deals": [getattr(r, 'deal', None) for r in requests]},
    )


@login_required
def chat_page(request, pk):
    """Dedicated full-screen chat page for a request conversation."""
    shy_request = get_object_or_404(ShyRequest, pk=pk, user=request.user)
    conversation, _ = Conversation.objects.get_or_create(request=shy_request)
    messages_qs = conversation.messages.order_by("created_at")
    form = MessageForm()
    return render(
        request,
        "chat/chat.html",
        {
            "request_obj": shy_request,
            "conversation": conversation,
            "messages": messages_qs,
            "form": form,
        },
    )


@login_required
def request_detail(request, pk):
    shy_request = get_object_or_404(ShyRequest, pk=pk, user=request.user)
    conversation, _ = Conversation.objects.get_or_create(request=shy_request)
    messages_qs = conversation.messages.order_by("created_at")
    form = MessageForm()
    deal_form = DealForm(instance=getattr(shy_request, "deal", None))
    return render(
        request,
        "chat/request_detail.html",
        {
            "request_obj": shy_request,
            "conversation": conversation,
            "messages": messages_qs,
            "form": form,
            "deal_form": deal_form,
        },
    )


@login_required
def post_message(request, pk):
    shy_request = get_object_or_404(ShyRequest, pk=pk, user=request.user)
    conversation, _ = Conversation.objects.get_or_create(request=shy_request)
    if request.method == "POST":
        form = MessageForm(request.POST)
        if form.is_valid():
            msg: Message = form.save(commit=False)
            msg.conversation = conversation
            msg.sender = Message.Sender.REQUESTER
            msg.author = request.user
            msg.save()
            
            # Send WebSocket message to chat room
            from .websocket_utils import send_chat_message_websocket
            send_chat_message_websocket(
                shy_request.id,
                {
                    "id": msg.id,
                    "body": msg.clean_body or msg.body,
                    "sender": msg.sender,
                    "sender_display": msg.get_sender_display(),
                    "is_blocked": msg.is_blocked,
                    "created_at": msg.created_at.isoformat(),
                    "created_at_display": msg.created_at.strftime("%b %d, %H:%M"),
                }
            )
            
            send_notification(
                subject="New reply from requester",
                body=msg.body,
                recipient=settings.ADMIN_NOTIFY_EMAIL,
                related_request=shy_request,
            )
            messages.success(request, "Reply sent.")
    # Redirect to chat page if coming from chat, otherwise request detail
    redirect_to = request.GET.get("redirect", "core:request_detail")
    if redirect_to == "core:chat":
        return redirect("core:chat", pk=shy_request.pk)
    return redirect("core:request_detail", pk=shy_request.pk)


@login_required
def confirm_deal(request, pk):
    shy_request = get_object_or_404(ShyRequest, pk=pk, user=request.user)
    deal, _ = Deal.objects.get_or_create(request=shy_request)
    if request.method == "POST":
        form = DealForm(request.POST, instance=deal)
        if form.is_valid():
            form.save()
            deal.status = Deal.Status.PAYMENT_DUE
            deal.save(update_fields=["status", "updated_at", "platform_fee"])
            send_notification(
                subject="Deal marked as agreed",
                body=f"Deal for request {shy_request.tracking_code} amount {deal.amount} {deal.currency}",
                recipient=settings.ADMIN_NOTIFY_EMAIL,
                related_request=shy_request,
            )
            messages.success(
                request,
                f"Deal stored. Platform fee is {deal.platform_fee} {deal.currency} (3%).",
            )
    return redirect("core:request_detail", pk=shy_request.pk)


def track(request):
    code = request.GET.get("code")
    request_obj = None
    if code:
        request_obj = ShyRequest.objects.filter(tracking_code=code).first()
    return render(request, "chat/track.html", {"request_obj": request_obj, "code": code})

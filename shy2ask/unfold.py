from django.conf import settings
from django.db.models import Sum
from django.templatetags.static import static
from django.urls import reverse


def logo_light(request):
    return static("admin/brand-wordmark.svg")


def logo_dark(request):
    return static("admin/brand-wordmark.svg")


def icon_light(request):
    return static("admin/brand-mark.svg")


def icon_dark(request):
    return static("admin/brand-mark.svg")


def environment_label(request):
    return "Production" if not settings.DEBUG else "Development"


def account_links(request):
    return [
        {"title": "Open site", "link": "/"},
        {"title": "API docs", "link": "/docs"},
        {"title": "My profile", "link": reverse("admin:account_user_change", args=[request.user.pk])},
    ]


def _count_badge(count: int) -> str:
    return str(count) if count < 100 else "99+"


def pending_users_badge(request):
    from account.models import PendingVerificationUser

    return _count_badge(PendingVerificationUser.objects.unverified().count())


def open_requests_badge(request):
    from chat.models import ActiveShyRequest

    return _count_badge(ActiveShyRequest.objects.count())


def blocked_messages_badge(request):
    from chat.models import Message

    return _count_badge(Message.objects.filter(is_blocked=True).count())


def unread_notifications_badge(request):
    from chat.models import Notification

    return _count_badge(Notification.objects.unread().count())


def sidebar_navigation(request):
    return [
        {
            "title": "Overview",
            "separator": True,
            "items": [
                {
                    "title": "Dashboard",
                    "icon": "dashboard",
                    "link": reverse("admin:index"),
                },
            ],
        },
        {
            "title": "Customer Identity",
            "items": [
                {
                    "title": "Users",
                    "icon": "group",
                    "link": reverse("admin:account_user_changelist"),
                },
                {
                    "title": "Pending Verification",
                    "icon": "mark_email_unread",
                    "link": reverse("admin:account_pendingverificationuser_changelist"),
                    "badge": "shy2ask.unfold.pending_users_badge",
                },
                {
                    "title": "Password Reset OTPs",
                    "icon": "password",
                    "link": reverse("admin:account_passwordresetotp_changelist"),
                },
            ],
        },
        {
            "title": "Operations",
            "items": [
                {
                    "title": "Requests",
                    "icon": "inbox",
                    "link": reverse("admin:chat_shyrequest_changelist"),
                },
                {
                    "title": "Active Requests",
                    "icon": "hourglass_top",
                    "link": reverse("admin:chat_activeshyrequest_changelist"),
                    "badge": "shy2ask.unfold.open_requests_badge",
                },
                {
                    "title": "Messages",
                    "icon": "chat",
                    "link": reverse("admin:chat_message_changelist"),
                },
                {
                    "title": "Conversation Stream",
                    "icon": "forum",
                    "link": reverse("admin:chat_conversationmessage_changelist"),
                },
                {
                    "title": "Notifications",
                    "icon": "notifications",
                    "link": reverse("admin:chat_notification_changelist"),
                    "badge": "shy2ask.unfold.unread_notifications_badge",
                },
                {
                    "title": "Deals",
                    "icon": "payments",
                    "link": reverse("admin:chat_deal_changelist"),
                },
            ],
        },
        {
            "title": "Trust & Safety",
            "items": [
                {
                    "title": "Blocked Messages",
                    "icon": "gpp_bad",
                    "link": f"{reverse('admin:chat_message_changelist')}?is_blocked__exact=1",
                    "badge": "shy2ask.unfold.blocked_messages_badge",
                },
                {
                    "title": "Censor Categories",
                    "icon": "category",
                    "link": reverse("admin:chat_censorcategory_changelist"),
                },
                {
                    "title": "Offensive Terms",
                    "icon": "policy_alert",
                    "link": reverse("admin:chat_offensiveterm_changelist"),
                },
                {
                    "title": "Censor Logs",
                    "icon": "fact_check",
                    "link": reverse("admin:chat_censorlog_changelist"),
                },
            ],
        },
    ]


def dashboard_callback(request, context):
    from account.models import PendingVerificationUser, User
    from chat.models import Deal, Message, Notification, ShyRequest, Subscription

    def serialize_panel_items(queryset, *, label, meta, admin_url_name):
        return [
            {
                "url": reverse(admin_url_name, args=[obj.pk]),
                "label": label(obj),
                "meta": meta(obj),
            }
            for obj in queryset
        ]

    total_revenue = (
        Deal.objects.filter(status__in=[Deal.Status.PAID, Deal.Status.COMPLETED]).aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )

    context.update(
        {
            "kpi_cards": [
                {
                    "title": "Users",
                    "value": User.objects.count(),
                    "caption": f"{PendingVerificationUser.objects.unverified().count()} pending verification",
                    "tone": "emerald",
                    "icon": "group",
                },
                {
                    "title": "Requests",
                    "value": ShyRequest.objects.count(),
                    "caption": f"{ShyRequest.objects.open().count()} active cases",
                    "tone": "amber",
                    "icon": "inbox",
                },
                {
                    "title": "Messages",
                    "value": Message.objects.count(),
                    "caption": f"{Message.objects.filter(is_blocked=True).count()} blocked by moderation",
                    "tone": "rose",
                    "icon": "chat",
                },
                {
                    "title": "Revenue",
                    "value": f"INR {total_revenue}",
                    "caption": f"{Deal.objects.count()} tracked deals",
                    "tone": "sky",
                    "icon": "payments",
                },
            ],
            "ops_panels": [
                {
                    "title": "Verification queue",
                    "items": serialize_panel_items(
                        PendingVerificationUser.objects.unverified().order_by("-date_joined")[:5],
                        admin_url_name="admin:account_pendingverificationuser_change",
                        label=lambda obj: obj.email,
                        meta=lambda obj: obj.date_joined.strftime("%d %b %Y, %H:%M"),
                    ),
                    "empty": "All users are verified.",
                },
                {
                    "title": "Fresh requests",
                    "items": serialize_panel_items(
                        ShyRequest.objects.with_related()[:5],
                        admin_url_name="admin:chat_shyrequest_change",
                        label=lambda obj: obj.tracking_code,
                        meta=lambda obj: f"{obj.requester_display_name} -> {obj.target_display_name}",
                    ),
                    "empty": "No requests yet.",
                },
                {
                    "title": "Unread notifications",
                    "items": serialize_panel_items(
                        Notification.objects.unread().select_related("related_request")[:5],
                        admin_url_name="admin:chat_notification_change",
                        label=lambda obj: obj.subject,
                        meta=lambda obj: obj.recipient_email,
                    ),
                    "empty": "No unread notifications.",
                },
                {
                    "title": "Active subscriptions",
                    "items": serialize_panel_items(
                        Subscription.objects.active().with_request()[:5],
                        admin_url_name="admin:chat_subscription_change",
                        label=lambda obj: obj.get_subscription_type_display(),
                        meta=lambda obj: getattr(obj.user, "email", ""),
                    ),
                    "empty": "No active subscriptions.",
                },
            ],
        }
    )
    return context

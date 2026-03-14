from django.conf import settings
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

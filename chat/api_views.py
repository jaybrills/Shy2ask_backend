import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework import serializers
from django.core.exceptions import ValidationError
from rest_framework.views import APIView

from .censor_engine import censor_image, censor_text_full
from .models import FAQ, FAQVideo, ConversationMessage, Message, Notification, ShyRequest, Subscription, SupportTicket, SupportTicketReply
from .message_service import (
    MessageAccessError,
    can_access_conversation,
    create_message_for_request,
)
from .websocket_utils import (
    get_request_inbox_user_ids,
    send_chat_message_websocket,
    send_received_request_inbox_websocket,
    serialize_message_for_websocket,
)
from account.api_views import BearerTokenAuthentication
from account.permissions import IsVerified
from .serializers import (
    BulkSoftDeleteSerializer,
    CensorImageResultSerializer,
    CensorResultSerializer,
    CensorTextInputSerializer,
    FAQSerializer,
    MessageInputSerializer,
    MessageSerializer,
    RequestBlockSerializer,
    ReplyByTrackingSerializer,
    ShyRequestSerializer,
    SubscriptionCreateSerializer,
    SubscriptionSerializer,
    SupportTicketReplyCreateSerializer,
    SupportTicketReplySerializer,
    SupportTicketSerializer,
)

logger = logging.getLogger(__name__)


def broadcast_chat_message(message):
    """Publish REST-created messages to connected chat WebSocket clients."""
    send_chat_message_websocket(message.request_id, serialize_message_for_websocket(message))


class ShyRequestViewSet(viewsets.ModelViewSet):
    serializer_class = ShyRequestSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = [BearerTokenAuthentication]
    http_method_names = ["get", "post", "delete"]

    def get_queryset(self):
        qs = ShyRequest.objects.with_related()
        tracking = self.request.query_params.get("tracking_code")
        if tracking:
            return qs.by_tracking_code(tracking)
        if self.request.user.is_authenticated:
            return qs.for_participant(user=self.request.user)
        return qs.none()

    def _with_target_reply_state(self, queryset):
        target_reply_qs = Message.objects.filter(
            request=OuterRef("pk"),
            sender=Message.Actor.TARGET,
            message_kind=Message.Kind.REPLY,
        )
        return queryset.annotate(has_target_reply=Exists(target_reply_qs))

    def perform_create(self, serializer):
        # Use any detected country code from earlier logic (if available)
        country_code = getattr(self.request, "detected_country", "") or ""
        instance = serializer.save(country_code=country_code)

        try:
            from .tasks import process_request_created_task

            transaction.on_commit(lambda: process_request_created_task.delay(instance.id))
        except Exception:
            logger.exception("Failed to queue request-created task for request %s", instance.id)

    def _tracking_code(self, request) -> str:
        return (request.data.get("tracking_code") or request.query_params.get("tracking_code") or "").strip()

    def _get_conversation_request(self, request, pk):
        shy_request = get_object_or_404(ShyRequest.objects.select_related("user"), pk=pk)
        tracking_code = self._tracking_code(request)
        if not can_access_conversation(shy_request, user=request.user, tracking_code=tracking_code):
            raise MessageAccessError("You are not allowed to access this conversation.")
        return shy_request, tracking_code

    def _viewer_role(self, request, shy_request, tracking_code: str = ""):
        user = request.user if request.user.is_authenticated else None
        if user and user.id in {shy_request.user_id, shy_request.requester_user_id}:
            return Message.Actor.REQUESTER
        if user and user.id == shy_request.target_user_id:
            return Message.Actor.TARGET
        if user and shy_request.target_email and getattr(user, "email", "").lower() == shy_request.target_email.lower():
            return Message.Actor.TARGET
        if tracking_code and tracking_code == shy_request.tracking_code:
            return Message.Actor.TARGET
        return None

    def _can_manage_request(self, request, shy_request):
        user = request.user if request.user.is_authenticated else None
        if not user:
            return False
        if getattr(user, "is_staff", False):
            return True
        return user.id in {shy_request.user_id, shy_request.requester_user_id, shy_request.target_user_id}

    def _can_block_request(self, request, shy_request):
        user = request.user if request.user.is_authenticated else None
        if user:
            return True
        if getattr(user, "is_staff", False):
            return True
        return False
    
    def _conversation_response(self, request, shy_request, messages_qs, tracking_code: str = ""):
        viewer_role = self._viewer_role(request, shy_request, tracking_code=tracking_code)
        serialized_messages = MessageSerializer(
            messages_qs,
            many=True,
            context={"viewer_role": viewer_role},
        ).data
        return {
            "request": {
                "id": shy_request.id,
                "tracking_code": shy_request.tracking_code,
                "status": shy_request.status,
                "service_channel": shy_request.service_channel,
                "description": shy_request.description,
                "created_at": shy_request.created_at,
            },
            "viewer": {
                "role": viewer_role,
                "label": "Requester" if viewer_role == Message.Actor.REQUESTER else "Target" if viewer_role == Message.Actor.TARGET else "Guest",
            },
            "participants": {
                "requester": {
                    "role": Message.Actor.REQUESTER,
                    "label": "Requester",
                    "name": shy_request.requester_display_name,
                    "email": shy_request.requester_email,
                    "is_me": viewer_role == Message.Actor.REQUESTER,
                },
                "target": {
                    "role": Message.Actor.TARGET,
                    "label": "Target",
                    "name": shy_request.target_display_name,
                    "email": shy_request.target_email,
                    "is_me": viewer_role == Message.Actor.TARGET,
                },
            },
            "messages": serialized_messages,
        }

    def _message_response(self, request, shy_request, message, tracking_code: str = ""):
        viewer_role = self._viewer_role(request, shy_request, tracking_code=tracking_code)
        return MessageSerializer(message, context={"viewer_role": viewer_role}).data

    def _visible_messages_qs(self, request, shy_request, tracking_code: str = ""):
        viewer_role = self._viewer_role(request, shy_request, tracking_code=tracking_code)
        return ConversationMessage.objects.for_request(shy_request).with_related().visible_to(viewer_role)

    @action(detail=True, methods=["post"], permission_classes=[permissions.AllowAny])
    def messages(self, request, pk=None):
        payload = MessageInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        try:
            shy_request, tracking_code = self._get_conversation_request(request, pk)
            msg = create_message_for_request(
                shy_request,
                payload.validated_data["body"],
                user=request.user,
                tracking_code=tracking_code or payload.validated_data.get("tracking_code"),
                alias=payload.validated_data.get("alias"),
                reply_to_id=payload.validated_data.get("reply_to_id"),
            )
        except MessageAccessError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_chat_message(msg)
        return Response(self._message_response(request, shy_request, msg, tracking_code=tracking_code), status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if not self._can_manage_request(request, instance):
            return Response({"detail": "You are not allowed to delete this request."}, status=status.HTTP_403_FORBIDDEN)
        target_user_ids = get_request_inbox_user_ids(instance)
        instance.delete()
        for target_user_id in target_user_ids:
            send_received_request_inbox_websocket(target_user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], permission_classes=[permissions.AllowAny])
    def conversation(self, request, pk=None):
        try:
            shy_request, tracking_code = self._get_conversation_request(request, pk)
        except MessageAccessError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        messages_qs = self._visible_messages_qs(request, shy_request, tracking_code=tracking_code)
        return Response(self._conversation_response(request, shy_request, messages_qs, tracking_code=tracking_code))

    @action(detail=False, methods=["post"], permission_classes=[IsVerified], url_path="bulk-delete")
    def bulk_delete(self, request):
        payload = BulkSoftDeleteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        queryset = ShyRequest.objects.for_participant(user=request.user).filter(id__in=payload.validated_data["ids"])
        target_user_ids = set()
        for shy_request in queryset.select_related("target_user"):
            target_user_ids.update(get_request_inbox_user_ids(shy_request))
        deleted_count = queryset.soft_delete()
        for target_user_id in target_user_ids:
            send_received_request_inbox_websocket(target_user_id)
        return Response({"deleted_count": deleted_count}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["delete"], permission_classes=[IsVerified], url_path=r"messages/(?P<message_id>[^/.]+)")
    def delete_message(self, request, pk=None, message_id=None):
        shy_request = get_object_or_404(ShyRequest.objects, pk=pk)
        if not self._can_manage_request(request, shy_request):
            return Response({"detail": "You are not allowed to delete messages for this request."}, status=status.HTTP_403_FORBIDDEN)

        message = get_object_or_404(Message.all_objects, pk=message_id, request=shy_request, is_deleted=False)
        deleted = message.delete(actor_role=self._viewer_role(request, shy_request))
        if not deleted:
            return Response({"detail": "You are not allowed to delete this message."}, status=status.HTTP_403_FORBIDDEN)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], permission_classes=[IsVerified], url_path="messages/bulk-delete")
    def bulk_delete_messages(self, request, pk=None):
        payload = BulkSoftDeleteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        shy_request = get_object_or_404(ShyRequest.objects, pk=pk)
        if not self._can_manage_request(request, shy_request):
            return Response({"detail": "You are not allowed to delete messages for this request."}, status=status.HTTP_403_FORBIDDEN)

        deleted_count = Message.all_objects.filter(
            request=shy_request,
            id__in=payload.validated_data["ids"],
            is_deleted=False,
        ).soft_delete_for_actor(self._viewer_role(request, shy_request))
        return Response({"deleted_count": deleted_count}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], permission_classes=[IsVerified])
    def block(self, request, pk=None):
        payload = RequestBlockSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        shy_request = get_object_or_404(ShyRequest.objects.select_related("requester_user", "user", "target_user"), pk=pk)
        if not self._can_block_request(request, shy_request):
            return Response({"detail": "You are not allowed to block this request."}, status=status.HTTP_403_FORBIDDEN)

        blocked_count, blocked_user = shy_request.block(
            actor=request.user,
            note=payload.validated_data.get("note", ""),
        )
        for target_user_id in get_request_inbox_user_ids(shy_request):
            send_received_request_inbox_websocket(target_user_id)
        return Response(
            {
                "request_id": shy_request.id,
                "is_blocked": shy_request.is_blocked,
                "status": shy_request.status,
                "blocked_requests_count": blocked_count,
                "requester_user_blocked": blocked_user,
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[permissions.AllowAny],
        url_path="reply",
    )
    def reply_on_request(self, request):
        payload = ReplyByTrackingSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        tracking_code = payload.validated_data["tracking_code"].strip()
        shy_request = get_object_or_404(ShyRequest, tracking_code=tracking_code)

        try:
            msg = create_message_for_request(
                shy_request,
                payload.validated_data["body"],
                tracking_code=tracking_code,
                alias=payload.validated_data.get("alias"),
                reply_to_id=payload.validated_data.get("reply_to_id"),
            )
        except MessageAccessError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        broadcast_chat_message(msg)
        return Response(
            {
                "request_id": shy_request.id,
                "tracking_code": shy_request.tracking_code,
                "viewer": {
                    "role": Message.Actor.TARGET,
                    "label": "Target",
                },
                "message": self._message_response(request, shy_request, msg, tracking_code=tracking_code),
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[permissions.AllowAny],
        url_path=r"conversation/by-tracking/(?P<tracking_code>[^/.]+)",
    )
    def conversation_by_tracking(self, request, tracking_code=None):
        normalized_tracking = (tracking_code or "").strip()
        shy_request = get_object_or_404(ShyRequest, tracking_code=normalized_tracking)
        messages_qs = self._visible_messages_qs(request, shy_request, tracking_code=normalized_tracking)
        return Response(self._conversation_response(request, shy_request, messages_qs, tracking_code=normalized_tracking))

    @extend_schema(responses=ShyRequestSerializer(many=True), tags=["Requests"])
    @action(detail=False, methods=["get"], permission_classes=[IsVerified])
    def unreplied(self, request):
        queryset = self._with_target_reply_state(
            ShyRequest.objects.with_related().for_participant(user=request.user)
        ).filter(has_target_reply=False)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class FAQListView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=FAQSerializer(many=True), tags=["FAQ"])
    def get(self, request):
        faqs = FAQ.objects.filter(is_active=True).prefetch_related(
            Prefetch("videos", queryset=FAQVideo.objects.filter(is_active=True), to_attr="active_videos")
        )
        return Response(FAQSerializer(faqs, many=True).data)


class SupportTicketViewSet(viewsets.ModelViewSet):
    serializer_class = SupportTicketSerializer
    permission_classes = [IsVerified]
    authentication_classes = [BearerTokenAuthentication]
    http_method_names = ["get", "post"]

    def get_queryset(self):
        return SupportTicket.objects.visible_to(self.request.user).with_related()

    def perform_create(self, serializer):
        ticket = serializer.save()
        try:
            from .tasks import process_support_ticket_created_task

            transaction.on_commit(lambda: process_support_ticket_created_task.delay(ticket.id))
        except Exception:
            pass

    @extend_schema(
        request=SupportTicketReplyCreateSerializer,
        responses=SupportTicketReplySerializer,
        tags=["Support"],
    )
    @action(detail=True, methods=["post"], permission_classes=[IsVerified])
    def replies(self, request, pk=None):
        ticket = get_object_or_404(self.get_queryset(), pk=pk)
        payload = SupportTicketReplyCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        try:
            reply = SupportTicketReply.objects.create(
                ticket=ticket,
                author=request.user,
                email=getattr(request.user, "email", ""),
                sender_type=SupportTicketReply.SenderType.USER,
                body=payload.validated_data["body"],
            )
        except ValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from .tasks import process_support_ticket_reply_task

            transaction.on_commit(lambda: process_support_ticket_reply_task.delay(ticket.id, reply.id))
        except Exception:
            pass

        return Response(SupportTicketReplySerializer(reply).data, status=status.HTTP_201_CREATED)


class CensorTextView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=CensorTextInputSerializer,
        responses=CensorResultSerializer,
        tags=["Censor"],
    )
    def post(self, request):
        text = request.data.get("text") or ""
        if not getattr(settings, "OPENAI_API_KEY", None):
            return Response(
                {
                    "censored_text": "[BLOCKED]",
                    "blocked": True,
                    "detected": [{"term": "[system]", "category": "moderation_unavailable"}],
                    "categories": ["moderation_unavailable"],
                    "ai_toxic_score": None,
                    "ai_provider": None,
                }
            )

        result = censor_text_full(
            text,
            use_db_terms=False,
            use_builtin_rules=False,
            use_ai_censor=True,
            log_source="api",
        )
        return Response(
            {
                "censored_text": "[BLOCKED]" if result.blocked else result.censored_text,
                "blocked": result.blocked,
                "detected": result.detected,
                "categories": result.categories,
                "ai_toxic_score": getattr(result, "ai_toxic_score", None),
                "ai_provider": getattr(result, "ai_provider", None),
            }
        )


class CensorImageView(APIView):
    permission_classes = [permissions.AllowAny]
    parser_classes = [MultiPartParser]

    @extend_schema(
        request=inline_serializer(
            name="CensorImageUpload",
            fields={"image": serializers.ImageField()},
        ),
        responses=CensorImageResultSerializer,
        tags=["Censor"],
    )
    def post(self, request):
        image = request.FILES.get("image")
        if not image:
            return Response({"detail": "No image file provided."}, status=status.HTTP_400_BAD_REQUEST)
        content = image.read()
        if not content:
            return Response({"detail": "Empty image file."}, status=status.HTTP_400_BAD_REQUEST)
        result = censor_image(
            content,
            content_type=getattr(image, "content_type", None),
            log_source="api",
        )
        return Response(
            {
                "censored_text": result.censored_text,
                "blocked": result.blocked,
                "detected": result.detected,
                "categories": result.categories,
                "extracted_text": result.extracted_text,
                "ocr_available": result.ocr_available,
                "ai_toxic_score": getattr(result, "ai_toxic_score", None),
                "ai_provider": getattr(result, "ai_provider", None),
            }
        )


class SubscriptionListCreateView(APIView):
    permission_classes = [IsVerified]
    authentication_classes = [BearerTokenAuthentication]

    @extend_schema(responses=SubscriptionSerializer(many=True), tags=["Subscriptions"])
    def get(self, request):
        qs = Subscription.objects.active().for_user(request.user).with_request()
        return Response(
            [
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
        )

    @extend_schema(
        request=SubscriptionCreateSerializer,
        responses=SubscriptionSerializer,
        tags=["Subscriptions"],
    )
    def post(self, request):
        subscription_type = (request.data.get("subscription_type") or "").strip()
        request_id = request.data.get("request_id")
        if subscription_type not in (
            Subscription.Type.REQUEST_UPDATES,
            Subscription.Type.DEAL_ALERTS,
            Subscription.Type.DAILY_DIGEST,
        ):
            return Response(
                {"detail": "subscription_type must be request_updates, deal_alerts, or daily_digest"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        shy_request = None
        if subscription_type == Subscription.Type.REQUEST_UPDATES:
            if not request_id:
                return Response({"detail": "request_id required for request_updates"}, status=status.HTTP_400_BAD_REQUEST)
            shy_request = ShyRequest.objects.for_participant(user=request.user).filter(pk=request_id).first()
            if not shy_request:
                return Response({"detail": "Request not found or not yours."}, status=status.HTTP_400_BAD_REQUEST)

        subscription, created = Subscription.objects.get_or_create(
            user=request.user,
            request=shy_request,
            subscription_type=subscription_type,
            defaults={"is_active": True},
        )
        if not created:
            subscription.is_active = True
            subscription.save(update_fields=["is_active"])
        return Response(
            {
                "id": subscription.id,
                "subscription_type": subscription.subscription_type,
                "request_id": subscription.request_id,
                "tracking_code": subscription.request.tracking_code if subscription.request else None,
                "is_active": subscription.is_active,
                "created_at": subscription.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )


class SubscriptionDetailView(APIView):
    permission_classes = [IsVerified]
    authentication_classes = [BearerTokenAuthentication]

    @extend_schema(responses={204: None}, tags=["Subscriptions"])
    def delete(self, request, subscription_id):
        subscription = Subscription.objects.for_user(request.user).filter(pk=subscription_id).first()
        if not subscription:
            return Response({"detail": "Subscription not found."}, status=status.HTTP_404_NOT_FOUND)
        subscription.is_active = False
        subscription.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class UnreadNotificationListView(APIView):
    permission_classes = [IsVerified]
    authentication_classes = [BearerTokenAuthentication]

    @extend_schema(tags=["Notifications"])
    def get(self, request):
        notifications = (
            Notification.objects.unread()
            .for_recipient(user=request.user)
            .select_related("related_request")
            .order_by("-created_at")
        )
        return Response(
            [
                {
                    "id": notification.id,
                    "subject": notification.subject,
                    "body": notification.body,
                    "is_read": notification.is_read,
                    "created_at": notification.created_at.isoformat() if notification.created_at else None,
                    "request_id": notification.related_request_id,
                    "tracking_code": notification.related_request.tracking_code if notification.related_request else None,
                }
                for notification in notifications
            ]
        )


class RealtimeDocumentationView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        tags=["Realtime"],
        operation_id="realtime_websocket_contract",
        summary="Realtime WebSocket contract",
        description=(
            "Documentation-only endpoint for the WebSocket protocol. Swagger/OpenAPI "
            "cannot execute WebSocket handshakes, but this response gives frontend "
            "clients the live chat and notification socket URLs, auth rules, and JSON event shapes."
        ),
        responses=inline_serializer(
            name="RealtimeDocumentation",
            fields={
                "chat": serializers.DictField(),
                "notifications": serializers.DictField(),
                "request_inbox": serializers.DictField(),
                "notes": serializers.ListField(child=serializers.CharField()),
            },
        ),
    )
    def get(self, request):
        base = request.build_absolute_uri("/").rstrip("/")
        ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
        return Response(
            {
                "chat": {
                    "url": f"{ws_base}/ws/chat/{{request_id}}/",
                    "json_url": f"{ws_base}/ws/chat/{{request_id}}/?format=json",
                    "requester_auth": "Use logged-in session cookies, Authorization: Bearer <token>, or ?token=<token>.",
                    "responder_auth": "Use ?tracking_code=<tracking_code>. Add &format=json for JSON events.",
                    "send": {
                        "type": "chat.message",
                        "body": "Hello from the realtime client",
                        "alias": "OptionalDisplayName",
                        "reply_to_id": 123,
                    },
                    "history_event": {
                        "type": "chat.history",
                        "request": {"id": 123, "tracking_code": "ABC123", "status": "submitted"},
                        "viewer": {"role": "requester", "label": "Requester"},
                        "messages": [],
                    },
                    "message_event": {
                        "type": "chat.message",
                        "message": {
                            "id": 1,
                            "request_id": 123,
                            "sender": "requester",
                            "recipient": "target",
                            "display_name": "OptionalDisplayName",
                            "body": "Hello",
                            "clean_body": "Hello",
                            "direction": "outbound",
                            "is_mine": True,
                            "created_at": "2026-04-22T10:00:00+00:00",
                        },
                    },
                },
                "notifications": {
                    "url": f"{ws_base}/ws/notifications/",
                    "token_url": f"{ws_base}/ws/notifications/?token=<token>",
                    "auth": "Logged-in user only. Use session cookies, Authorization: Bearer <token>, or ?token=<token>.",
                    "events": ["unread_notifications", "notification"],
                    "send_mark_read": {"type": "mark_read", "notification_id": 1},
                },
                "request_inbox": {
                    "url": f"{ws_base}/ws/requests/inbox/",
                    "token_url": f"{ws_base}/ws/requests/inbox/?token=<token>",
                    "auth": "Logged-in participant only. Use session cookies, Authorization: Bearer <token>, or ?token=<token>.",
                    "optional_query_params": {
                        "limit": "Number of recent connected requests to return (default 20, max 100).",
                    },
                    "events": ["request_inbox.snapshot", "request_inbox.updated"],
                    "snapshot_event": {
                        "type": "request_inbox.snapshot",
                        "viewer": {"id": 9, "role": "participant", "label": "Participant"},
                        "stats": {
                            "total_requests_count": 12,
                            "sent_requests_count": 5,
                            "received_requests_count": 12,
                            "pending_requests_count": 3,
                            "cancelled_requests_count": 2,
                            "rejected_requests_count": 2,
                            "blocked_requests_count": 1,
                        },
                        "recent_requests": [
                            {
                                "id": 123,
                                "tracking_code": "ABC123",
                                "status": "submitted",
                                "is_blocked": False,
                                "direction": "received",
                                "viewer_role": "target",
                                "requester_name": "Requester",
                                "requester_email": "requester@example.com",
                                "target_name": "Target",
                                "target_email": "target@example.com",
                                "counterparty_role": "requester",
                                "counterparty_label": "Requester",
                                "counterparty_name": "Requester",
                                "description": "Need help with my request",
                                "latest_message": {
                                    "id": 456,
                                    "sender": "requester",
                                    "recipient": "target",
                                    "body": "Hello",
                                    "clean_body": "Hello",
                                    "direction": "inbound",
                                    "is_mine": False,
                                    "created_at": "2026-04-22T10:00:00+00:00",
                                },
                            }
                        ],
                    },
                    "send_refresh": {"type": "request_inbox.refresh"},
                },
                "notes": [
                    "Use ws:// for HTTP and wss:// for HTTPS.",
                    "REST-created messages are broadcast to connected chat clients.",
                    "The default chat socket response is HTML for the existing HTMX page; pass ?format=json for API/mobile clients.",
                    "The request inbox socket is role-aware and can be used for both requester and target dashboards.",
                ],
            }
        )

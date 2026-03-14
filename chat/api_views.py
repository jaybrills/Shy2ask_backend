from django.conf import settings
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
from .models import ConversationMessage, Message, ShyRequest, Subscription
from .message_service import (
    MessageAccessError,
    can_access_conversation,
    create_message_for_request,
)
from account.api_views import BearerTokenAuthentication
from .serializers import (
    CensorImageResultSerializer,
    CensorResultSerializer,
    CensorTextInputSerializer,
    MessageInputSerializer,
    MessageSerializer,
    ReplyByTrackingSerializer,
    ShyRequestSerializer,
    SubscriptionCreateSerializer,
    SubscriptionSerializer,
)


class ShyRequestViewSet(viewsets.ModelViewSet):
    serializer_class = ShyRequestSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = [BearerTokenAuthentication]
    http_method_names = ["get", "post"]

    def get_queryset(self):
        qs = ShyRequest.objects.with_related()
        tracking = self.request.query_params.get("tracking_code")
        if tracking:
            return qs.by_tracking_code(tracking)
        if self.request.user.is_authenticated:
            return qs.for_participant(user=self.request.user)
        return qs.none()

    def perform_create(self, serializer):
        # Use any detected country code from earlier logic (if available)
        country_code = getattr(self.request, "detected_country", "") or ""
        instance = serializer.save(country_code=country_code)

        # Trigger real-time notifications for the newly created request
        try:
            from .views import send_notification
            send_notification(
                subject="New request created",
                body=f"Your request with tracking code {instance.tracking_code} has been created successfully.",
                recipient=instance.requester_email,
                related_request=instance,
                use_ai_enhance=True
            )
        except Exception as e:
            print(f"Error sending initial notification: {e}")

    def _tracking_code(self, request) -> str:
        return (request.data.get("tracking_code") or request.query_params.get("tracking_code") or "").strip()

    def _get_conversation_request(self, request, pk):
        shy_request = get_object_or_404(ShyRequest.objects.select_related("user"), pk=pk)
        tracking_code = self._tracking_code(request)
        if not can_access_conversation(shy_request, user=request.user, tracking_code=tracking_code):
            raise MessageAccessError("You are not allowed to access this conversation.")
        return shy_request, tracking_code

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
            )
        except MessageAccessError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(MessageSerializer(msg).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], permission_classes=[permissions.AllowAny])
    def conversation(self, request, pk=None):
        try:
            shy_request, _ = self._get_conversation_request(request, pk)
        except MessageAccessError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        messages_qs = ConversationMessage.objects.for_request(shy_request).with_related()
        data = MessageSerializer(messages_qs, many=True).data
        return Response({"description": shy_request.description, "messages": data})

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
            )
        except MessageAccessError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "request_id": shy_request.id,
                "tracking_code": shy_request.tracking_code,
                "message": MessageSerializer(msg).data,
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
        shy_request = get_object_or_404(ShyRequest, tracking_code=(tracking_code or "").strip())
        messages_qs = ConversationMessage.objects.for_request(shy_request).with_related()
        return Response(MessageSerializer(messages_qs, many=True).data)


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
    permission_classes = [permissions.IsAuthenticated]
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
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    @extend_schema(responses={204: None}, tags=["Subscriptions"])
    def delete(self, request, subscription_id):
        subscription = Subscription.objects.for_user(request.user).filter(pk=subscription_id).first()
        if not subscription:
            return Response({"detail": "Subscription not found."}, status=status.HTTP_404_NOT_FOUND)
        subscription.is_active = False
        subscription.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)

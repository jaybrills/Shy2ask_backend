from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from django.core.exceptions import ValidationError

from .models import Message, ShyRequest
from .message_service import (
    MessageAccessError,
    can_access_conversation,
    create_message_for_request,
)
from .serializers import (
    MessageInputSerializer,
    MessageSerializer,
    ReplyByTrackingSerializer,
    ShyRequestSerializer,
)


class ShyRequestViewSet(viewsets.ModelViewSet):
    serializer_class = ShyRequestSerializer
    permission_classes = [permissions.AllowAny]
    http_method_names = ["get", "post"]

    def get_queryset(self):
        qs = ShyRequest.objects.select_related("user").prefetch_related("attachments").order_by("-created_at")
        tracking = self.request.query_params.get("tracking_code")
        if tracking:
            return qs.filter(tracking_code=tracking)
        if self.request.user.is_authenticated:
            email = (self.request.user.email or "").lower()
            return qs.filter(
                Q(user=self.request.user)
                | Q(target_email__iexact=email)
            )
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

        messages_qs = Message.objects.filter(request=shy_request).select_related("author", "request").order_by("created_at")
        data = MessageSerializer(messages_qs, many=True).data
        return Response(data)

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
        messages_qs = Message.objects.filter(request=shy_request).select_related("author", "request").order_by("created_at")
        return Response(MessageSerializer(messages_qs, many=True).data)

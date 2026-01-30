from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Conversation, Message, ShyRequest
from .serializers import MessageSerializer, ShyRequestSerializer
from .utils import censor_text


class ShyRequestViewSet(viewsets.ModelViewSet):
    serializer_class = ShyRequestSerializer
    permission_classes = [permissions.AllowAny]
    http_method_names = ["get", "post"]

    def get_queryset(self):
        qs = ShyRequest.objects.order_by("-created_at")
        tracking = self.request.query_params.get("tracking_code")
        if tracking:
            return qs.filter(tracking_code=tracking)
        if self.request.user.is_authenticated:
            return qs.filter(user=self.request.user)
        return qs.none()

    def perform_create(self, serializer):
        # Use any detected country code from earlier logic (if available)
        country_code = getattr(self.request, "detected_country", "") or ""
        serializer.save(country_code=country_code)

    @action(detail=True, methods=["post"], permission_classes=[permissions.AllowAny])
    def messages(self, request, pk=None):
        shy_request = self.get_object()
        conversation, _ = Conversation.objects.get_or_create(request=shy_request)
        serializer = MessageSerializer(
            data=request.data,
            context={
                "conversation": conversation,
                "author": request.user if request.user.is_authenticated else None,
            },
        )
        serializer.is_valid(raise_exception=True)
        msg = serializer.save()
        return Response(MessageSerializer(msg).data, status=201)

    @action(detail=True, methods=["get"], permission_classes=[permissions.AllowAny])
    def conversation(self, request, pk=None):
        shy_request = self.get_object()
        conversation, _ = Conversation.objects.get_or_create(request=shy_request)
        messages_qs = conversation.messages.order_by("created_at")
        data = MessageSerializer(messages_qs, many=True).data
        return Response(data)


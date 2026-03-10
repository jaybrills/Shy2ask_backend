from rest_framework import serializers

from .models import Attachment, Message, ShyRequest
from .message_service import resolve_display_name


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ["id", "file", "uploaded_at"]
        read_only_fields = ["id", "uploaded_at"]


class MessageSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ["id", "sender", "sender_display_name", "display_name", "body", "clean_body", "is_blocked", "created_at"]
        read_only_fields = ["id", "clean_body", "is_blocked", "created_at", "sender", "display_name"]

    def get_display_name(self, obj):
        return resolve_display_name(obj)


class ShyRequestSerializer(serializers.ModelSerializer):
    attachments = AttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = ShyRequest
        fields = [
            "id",
            "tracking_code",
            "requester_name",
            "requester_email",
            "requester_phone",
            "requester_alias",
            "target_name",
            "target_email",
            "target_phone",
            "target_address",
            "description",
            "service_channel",
            "call_minutes",
            "quoted_price_chf",
            "country_code",
            "status",
            "created_at",
            "attachments",
        ]
        read_only_fields = [
            "id",
            "tracking_code",
            "quoted_price_chf",
            "status",
            "country_code",
            "created_at",
            "attachments",
        ]

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user if request.user.is_authenticated else None
        requester_alias = validated_data.pop("requester_alias", None) or ""
        if user and not requester_alias:
            requester_alias = getattr(user, "alias_name", "") or ""

        country_code = validated_data.pop("country_code", None) or self.context.get("country_code", "")
        shy_request = ShyRequest.objects.create(
            user=user,
            requester_alias=requester_alias,
            status=ShyRequest.Status.SUBMITTED,
            country_code=country_code,
            **validated_data,
        )
        return shy_request


class MessageInputSerializer(serializers.Serializer):
    body = serializers.CharField()
    alias = serializers.CharField(required=False, allow_blank=True)
    tracking_code = serializers.CharField(required=False, allow_blank=True)


class ReplyByTrackingSerializer(serializers.Serializer):
    tracking_code = serializers.CharField()
    body = serializers.CharField()
    alias = serializers.CharField(required=False, allow_blank=True)

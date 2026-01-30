from rest_framework import serializers

from .models import Attachment, Message, ShyRequest
from .utils import censor_text


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ["id", "file", "uploaded_at"]
        read_only_fields = ["id", "uploaded_at"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "sender", "body", "clean_body", "is_blocked", "created_at"]
        read_only_fields = ["id", "clean_body", "is_blocked", "created_at", "sender"]

    def create(self, validated_data):
        conversation = self.context["conversation"]
        author = self.context.get("author")
        body = validated_data["body"]
        clean_body, blocked = censor_text(body)
        return Message.objects.create(
            conversation=conversation,
            sender=Message.Sender.REQUESTER,
            author=author,
            body=body,
            clean_body=clean_body,
            is_blocked=blocked,
        )


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
        user = self.context["request"].user if self.context["request"].user.is_authenticated else None
        shy_request = ShyRequest.objects.create(
            user=user,
            status=ShyRequest.Status.SUBMITTED,
            country_code=self.context.get("country_code", ""),
            **validated_data,
        )
        return shy_request


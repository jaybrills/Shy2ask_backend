from rest_framework import serializers

from .models import Attachment, Message, ShyRequest
from .utils import censor_text


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
        if obj.sender_display_name:
            return obj.sender_display_name
        req = obj.conversation.request
        if obj.sender == Message.Sender.REQUESTER and obj.author:
            return getattr(obj.author, "alias_name", None) or req.requester_alias or req.requester_name
        if obj.sender == Message.Sender.REQUESTER:
            return req.requester_alias or req.requester_name
        if obj.sender == Message.Sender.RESPONDER:
            return req.requester_alias or req.requester_name or "Responder"
        return "Staff"

    def create(self, validated_data):
        conversation = self.context["conversation"]
        author = self.context.get("author")
        alias = self.context.get("alias")
        body = validated_data["body"]
        clean_body, blocked = censor_text(body)
        msg = Message.objects.create(
            conversation=conversation,
            sender=Message.Sender.REQUESTER,
            author=author,
            sender_display_name=alias or "",
            body=body,
            clean_body=clean_body,
            is_blocked=blocked,
        )
        return msg


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

        from .models import Conversation
        country_code = validated_data.pop("country_code", None) or self.context.get("country_code", "")
        shy_request = ShyRequest.objects.create(
            user=user,
            requester_alias=requester_alias,
            status=ShyRequest.Status.SUBMITTED,
            country_code=country_code,
            **validated_data,
        )
        Conversation.objects.create(request=shy_request)
        return shy_request


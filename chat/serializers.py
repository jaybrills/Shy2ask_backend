from django.contrib.auth import get_user_model
from rest_framework import serializers

from .message_service import resolve_display_name, resolve_recipient_name
from .models import Attachment, Message, ShyRequest, user_display_name_for


User = get_user_model()


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ["id", "file", "uploaded_at"]
        read_only_fields = ["id", "uploaded_at"]


class MessageSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    recipient_name = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "message_kind",
            "sender",
            "recipient",
            "sender_display_name",
            "recipient_display_name",
            "display_name",
            "recipient_name",
            "body",
            "clean_body",
            "is_blocked",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "message_kind",
            "clean_body",
            "is_blocked",
            "created_at",
            "sender",
            "recipient",
            "display_name",
            "recipient_name",
        ]

    def get_display_name(self, obj):
        return resolve_display_name(obj)

    def get_recipient_name(self, obj):
        return resolve_recipient_name(obj)

class ShyRequestSerializer(serializers.ModelSerializer):
    attachments = AttachmentSerializer(many=True, read_only=True)
    requester_user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True,
    )
    target_user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True,
    )
    requester_name = serializers.CharField(required=False, allow_blank=True)
    requester_email = serializers.EmailField(required=False, allow_blank=True)
    target_name = serializers.CharField(required=False, allow_blank=True)
    target_email = serializers.EmailField(required=False, allow_blank=True)

    class Meta:
        model = ShyRequest
        fields = [
            "id",
            "user",
            "requester_user",
            "target_user",
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
            "user",
            "tracking_code",
            "quoted_price_chf",
            "status",
            "country_code",
            "created_at",
            "attachments",
        ]

    def validate(self, attrs):
        request = self.context["request"]
        actor = request.user if request.user.is_authenticated else None

        requester_user = attrs.get("requester_user") or actor
        target_user = attrs.get("target_user")

        if requester_user:
            attrs.setdefault("requester_user", requester_user)
            attrs.setdefault("requester_email", getattr(requester_user, "email", ""))
            attrs.setdefault("requester_alias", getattr(requester_user, "alias_name", "") or "")
            attrs.setdefault("requester_name", user_display_name_for(requester_user))

        if target_user:
            attrs.setdefault("target_email", getattr(target_user, "email", ""))
            attrs.setdefault("target_name", user_display_name_for(target_user))

        if not attrs.get("requester_name"):
            raise serializers.ValidationError({"requester_name": "Requester name is required."})
        if not attrs.get("requester_email") and not attrs.get("requester_user"):
            raise serializers.ValidationError({"requester_email": "Requester email or requester_user is required."})

        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user if request.user.is_authenticated else None
        requester_alias = validated_data.pop("requester_alias", None) or ""
        if user and not requester_alias:
            requester_alias = getattr(user, "alias_name", "") or ""

        country_code = validated_data.pop("country_code", None) or self.context.get("country_code", "")
        shy_request = ShyRequest.objects.create_submission(
            actor=user,
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


class CensorTextInputSerializer(serializers.Serializer):
    text = serializers.CharField()


class CensorResultSerializer(serializers.Serializer):
    censored_text = serializers.CharField()
    blocked = serializers.BooleanField()
    detected = serializers.ListField(child=serializers.JSONField())
    categories = serializers.ListField(child=serializers.CharField())
    ai_toxic_score = serializers.FloatField(required=False, allow_null=True)
    ai_provider = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class CensorImageResultSerializer(CensorResultSerializer):
    extracted_text = serializers.CharField()
    ocr_available = serializers.BooleanField()


class SubscriptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    subscription_type = serializers.CharField()
    request_id = serializers.IntegerField(allow_null=True)
    tracking_code = serializers.CharField(allow_null=True)
    is_active = serializers.BooleanField()
    created_at = serializers.CharField()


class SubscriptionCreateSerializer(serializers.Serializer):
    subscription_type = serializers.CharField()
    request_id = serializers.IntegerField(required=False, allow_null=True)

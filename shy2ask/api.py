from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView


class ApiIndexSerializer(serializers.Serializer):
    openapi = serializers.CharField()
    swagger = serializers.CharField()
    redoc = serializers.CharField()
    markdown_docs = serializers.CharField()
    auth = serializers.DictField(child=serializers.CharField())
    profile = serializers.DictField(child=serializers.CharField())
    chat = serializers.DictField(child=serializers.CharField())


class ApiIndexView(APIView):
    authentication_classes = []
    permission_classes = []

    @extend_schema(responses=ApiIndexSerializer, tags=["Meta"])
    def get(self, request):
        base = request.build_absolute_uri("/").rstrip("/")
        return Response(
            {
                "openapi": f"{base}/openapi.json",
                "swagger": f"{base}/swagger/",
                "redoc": f"{base}/redoc/",
                "markdown_docs": f"{base}/docs/api.md",
                "auth": {
                    "register": f"{base}/api/auth/register",
                    "login": f"{base}/api/auth/login",
                    "verify_email": f"{base}/api/auth/verify-email",
                    "resend_verification": f"{base}/api/auth/resend-verification",
                    "forgot_password": f"{base}/api/auth/forgot-password",
                    "reset_password": f"{base}/api/auth/reset-password",
                    "check_email": f"{base}/api/auth/check-email",
                    "check_alias": f"{base}/api/auth/check-alias",
                },
                "profile": {
                    "me": f"{base}/api/profile/me",
                    "users": f"{base}/api/profile/users",
                },
                "chat": {
                    "requests": f"{base}/api/requests/",
                    "reply": f"{base}/api/requests/reply/",
                    "conversation_by_tracking": f"{base}/api/requests/conversation/by-tracking/{{tracking_code}}/",
                    "realtime_docs": f"{base}/api/realtime/docs/",
                    "websocket_chat": f"{base.replace('https://', 'wss://').replace('http://', 'ws://')}/ws/chat/{{request_id}}/?format=json",
                    "websocket_notifications": f"{base.replace('https://', 'wss://').replace('http://', 'ws://')}/ws/notifications/?token={{token}}",
                    "censor_text": f"{base}/api/censor/text/",
                    "censor_image": f"{base}/api/censor/image/",
                    "subscriptions": f"{base}/api/subscriptions/",
                },
            }
        )

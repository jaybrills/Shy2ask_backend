"""
Notification history API — lets the mobile app display every push notification
that was ever sent to the authenticated user, with read/unread tracking.

Endpoints
---------
GET  /api/notifications/                → paginated list (newest first)
GET  /api/notifications/unread-count/   → { "unread_count": N }
PATCH /api/notifications/<id>/read/     → mark single notification as read
POST /api/notifications/mark-all-read/  → mark every notification as read

Query params for GET /api/notifications/:
  ?is_read=true|false    filter by read status
  ?type=<key>            filter by notification_type (e.g. payment_failed)
  ?page=<n>              pagination (default page_size=20)
"""

import logging

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from account.api_views import BearerTokenAuthentication
from account.models import UserNotification
from account.permissions import IsVerified

logger = logging.getLogger(__name__)


# ── Pagination ────────────────────────────────────────────────────────────────

class NotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# ── Serializers ───────────────────────────────────────────────────────────────

class UserNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserNotification
        fields = [
            "id",
            "title",
            "body",
            "notification_type",
            "priority",
            "data",
            "is_read",
            "created_at",
        ]
        read_only_fields = fields


class UnreadCountSerializer(serializers.Serializer):
    unread_count = serializers.IntegerField()


class MarkReadSerializer(serializers.Serializer):
    """Used only for schema documentation of the PATCH body (empty body accepted)."""
    pass


# ── Views ─────────────────────────────────────────────────────────────────────

class NotificationListView(APIView):
    """
    List all notifications sent to the authenticated user, newest first.

    Optional query parameters:
      ?is_read=true|false   — filter by read/unread
      ?type=<key>           — filter by notification_type
      ?page=<n>             — page number
      ?page_size=<n>        — results per page (max 100, default 20)
    """

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [IsVerified]

    @extend_schema(
        summary="List notifications for the current user",
        parameters=[
            OpenApiParameter(
                name="is_read",
                description="Filter by read status. true = only read, false = only unread.",
                required=False,
                type=str,
                enum=["true", "false"],
            ),
            OpenApiParameter(
                name="type",
                description="Filter by notification_type key (e.g. payment_failed, subscription_activated).",
                required=False,
                type=str,
            ),
            OpenApiParameter(name="page", description="Page number.", required=False, type=int),
            OpenApiParameter(name="page_size", description="Results per page (max 100).", required=False, type=int),
        ],
        responses={200: UserNotificationSerializer(many=True)},
    )
    def get(self, request):
        qs = (
            UserNotification.objects.filter(user=request.user)
            .order_by("-created_at")
        )

        # ── Filters ──────────────────────────────────────────────────────────
        is_read_param = request.query_params.get("is_read")
        if is_read_param is not None:
            if is_read_param.lower() == "true":
                qs = qs.filter(is_read=True)
            elif is_read_param.lower() == "false":
                qs = qs.filter(is_read=False)

        notification_type = request.query_params.get("type")
        if notification_type:
            qs = qs.filter(notification_type=notification_type)

        # ── Paginate ─────────────────────────────────────────────────────────
        paginator = NotificationPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = UserNotificationSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class UnreadCountView(APIView):
    """Return the number of unread notifications for the authenticated user."""

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [IsVerified]

    @extend_schema(
        summary="Get unread notification count",
        responses={200: UnreadCountSerializer},
    )
    def get(self, request):
        count = UserNotification.objects.filter(
            user=request.user,
            is_read=False,
        ).count()
        return Response({"unread_count": count}, status=status.HTTP_200_OK)


class MarkNotificationReadView(APIView):
    """
    Mark a single notification as read.

    Returns 404 if the notification does not belong to the requesting user.
    Calling this on an already-read notification is a no-op (returns 200).
    """

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [IsVerified]

    @extend_schema(
        summary="Mark a notification as read",
        request=MarkReadSerializer,
        responses={
            200: UserNotificationSerializer,
            404: None,
        },
    )
    def patch(self, request, pk: int):
        try:
            notification = UserNotification.objects.get(pk=pk, user=request.user)
        except UserNotification.DoesNotExist:
            return Response(
                {"detail": "Notification not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=["is_read"])

        return Response(
            UserNotificationSerializer(notification).data,
            status=status.HTTP_200_OK,
        )


class MarkAllReadView(APIView):
    """Mark every unread notification for the authenticated user as read."""

    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [IsVerified]

    @extend_schema(
        summary="Mark all notifications as read",
        responses={
            200: UnreadCountSerializer,
        },
    )
    def post(self, request):
        updated = UserNotification.objects.filter(
            user=request.user,
            is_read=False,
        ).update(is_read=True)

        return Response(
            {"unread_count": 0, "marked_read": updated},
            status=status.HTTP_200_OK,
        )

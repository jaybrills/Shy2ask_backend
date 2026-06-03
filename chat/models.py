import logging
import secrets
import string
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .utils import censor_text

logger = logging.getLogger(__name__)


def generate_tracking_code(length: int = 10) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _normalize_email(email: str) -> str:
    if not email:
        return ""
    return get_user_model().objects.normalize_email(email).lower()


def _user_for_email(email: str):
    email = _normalize_email(email)
    if not email:
        return None
    return get_user_model().objects.filter(email__iexact=email).first()


def user_display_name_for(user) -> str:
    if not user:
        return ""
    alias = getattr(user, "alias_name", "") or ""
    if alias:
        return alias
    full_name_getter = getattr(user, "get_full_name", None)
    full_name = full_name_getter().strip() if callable(full_name_getter) else ""
    if full_name:
        return full_name
    email = _normalize_email(getattr(user, "email", ""))
    return email.split("@")[0] if email else ""


class CreatedAtModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class TimeStampedModel(CreatedAtModel):
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class EmailUserResolutionModel(models.Model):
    class Meta:
        abstract = True

    def _sync_email_user_pair(self, *, user_field: str, email_field: str):
        user = getattr(self, user_field, None)
        email = _normalize_email(getattr(self, email_field, ""))

        if user:
            email = _normalize_email(getattr(user, "email", "")) or email
        elif email:
            user = _user_for_email(email)

        setattr(self, user_field, user)
        setattr(self, email_field, email)
        return user, email


class SoftDeleteModel(models.Model):
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def soft_delete(self, *, save: bool = True):
        if self.is_deleted:
            return False
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if save:
            update_fields = ["is_deleted", "deleted_at"]
            if hasattr(self, "updated_at"):
                update_fields.append("updated_at")
            self.save(update_fields=update_fields)
        return True

    def restore(self, *, save: bool = True):
        if not self.is_deleted:
            return False
        self.is_deleted = False
        self.deleted_at = None
        if save:
            update_fields = ["is_deleted", "deleted_at"]
            if hasattr(self, "updated_at"):
                update_fields.append("updated_at")
            self.save(update_fields=update_fields)
        return True

    def hard_delete(self, *args, **kwargs):
        return super().delete(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self.soft_delete()


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(is_deleted=False)

    def deleted(self):
        return self.filter(is_deleted=True)

    def soft_delete(self):
        queryset = self.alive()
        timestamp = timezone.now()
        update_kwargs = {
            "is_deleted": True,
            "deleted_at": timestamp,
        }
        if any(field.name == "updated_at" for field in self.model._meta.fields):
            update_kwargs["updated_at"] = timestamp
        return queryset.update(**update_kwargs)

    def restore(self):
        queryset = self.deleted()
        timestamp = timezone.now()
        update_kwargs = {
            "is_deleted": False,
            "deleted_at": None,
        }
        if any(field.name == "updated_at" for field in self.model._meta.fields):
            update_kwargs["updated_at"] = timestamp
        return queryset.update(**update_kwargs)

    def hard_delete(self):
        return super().delete()

    def delete(self):
        return self.soft_delete()


class ShyRequestQuerySet(SoftDeleteQuerySet):
    def with_related(self):
        return self.select_related("user", "requester_user", "target_user").prefetch_related("attachments")

    def by_tracking_code(self, tracking_code: str | None):
        tracking_code = (tracking_code or "").strip()
        return self.filter(tracking_code=tracking_code) if tracking_code else self

    def open(self):
        return self.exclude(status__in=[ShyRequest.Status.COMPLETED, ShyRequest.Status.REJECTED])

    def submitted(self):
        return self.exclude(status=ShyRequest.Status.DRAFT)

    def for_participant(self, *, user=None, email: str = ""):
        clauses = models.Q()
        normalized_email = _normalize_email(email)
        if getattr(user, "is_authenticated", False):
            clauses |= models.Q(user=user)
            clauses |= models.Q(requester_user=user)
            clauses |= models.Q(target_user=user)
            normalized_email = normalized_email or _normalize_email(getattr(user, "email", ""))
        if normalized_email:
            clauses |= models.Q(requester_email__iexact=normalized_email)
            clauses |= models.Q(target_email__iexact=normalized_email)
        return self.filter(clauses) if clauses else self.none()

    def soft_delete(self):
        request_ids = list(self.alive().values_list("id", flat=True))
        if not request_ids:
            return 0
        Message.all_objects.filter(request_id__in=request_ids).soft_delete()
        return super().soft_delete()


class ShyRequestBaseManager(models.Manager.from_queryset(ShyRequestQuerySet)):
    pass


class ShyRequestManager(ShyRequestBaseManager):
    def get_queryset(self):
        return super().get_queryset().alive()

    def create_submission(self, *, actor=None, status=None, **validated_data):
        if actor and getattr(actor, "is_authenticated", False):
            validated_data.setdefault("user", actor)
            validated_data.setdefault("requester_user", actor)
            validated_data.setdefault("requester_email", getattr(actor, "email", ""))
            validated_data.setdefault("requester_alias", getattr(actor, "alias_name", "") or "")
            validated_data.setdefault("requester_name", user_display_name_for(actor))
        if status:
            validated_data.setdefault("status", status)
        instance = self.model(**validated_data)
        instance.save()
        return instance


class ActiveShyRequestManager(ShyRequestManager):
    def get_queryset(self):
        return super().get_queryset().open()


class ShyRequestAllManager(ShyRequestBaseManager):
    pass


class MessageQuerySet(SoftDeleteQuerySet):
    def with_related(self):
        return self.select_related("author", "request", "sender_user", "recipient_user", "parent_message")

    def conversation(self):
        return self.exclude(message_kind=Message.Kind.NOTE).order_by("created_at")

    def for_request(self, shy_request):
        return self.filter(request=shy_request)

    def visible_to(self, actor_role: str | None):
        if not actor_role:
            return self
        if actor_role == Message.Actor.REQUESTER:
            return self.exclude(
                models.Q(sender=Message.Actor.REQUESTER, deleted_by_sender=True)
                | models.Q(recipient=Message.Actor.REQUESTER, deleted_by_recipient=True)
            )
        if actor_role == Message.Actor.TARGET:
            return self.exclude(
                models.Q(sender=Message.Actor.TARGET, deleted_by_sender=True)
                | models.Q(recipient=Message.Actor.TARGET, deleted_by_recipient=True)
            )
        return self

    def soft_delete_for_actor(self, actor_role: str | None):
        if not actor_role:
            return 0
        timestamp = timezone.now()
        updated_count = 0
        if actor_role == Message.Actor.REQUESTER:
            updated_count += self.filter(
                sender=Message.Actor.REQUESTER,
                deleted_by_sender=False,
            ).update(deleted_by_sender=True, sender_deleted_at=timestamp)
            updated_count += self.filter(
                recipient=Message.Actor.REQUESTER,
                deleted_by_recipient=False,
            ).update(deleted_by_recipient=True, recipient_deleted_at=timestamp)
            return updated_count
        if actor_role == Message.Actor.TARGET:
            updated_count += self.filter(
                sender=Message.Actor.TARGET,
                deleted_by_sender=False,
            ).update(deleted_by_sender=True, sender_deleted_at=timestamp)
            updated_count += self.filter(
                recipient=Message.Actor.TARGET,
                deleted_by_recipient=False,
            ).update(deleted_by_recipient=True, recipient_deleted_at=timestamp)
            return updated_count
        return 0


class MessageBaseManager(models.Manager.from_queryset(MessageQuerySet)):
    pass


class MessageManager(MessageBaseManager):
    def get_queryset(self):
        return super().get_queryset().alive()


class MessageAllManager(MessageBaseManager):
    pass


class ConversationMessageManager(MessageManager):
    def get_queryset(self):
        return super().get_queryset().conversation()


class NotificationQuerySet(models.QuerySet):
    def unread(self):
        return self.filter(is_read=False)

    def for_recipient(self, *, user=None, email: str = ""):
        normalized_email = _normalize_email(email)
        clauses = models.Q()
        if getattr(user, "is_authenticated", False):
            clauses |= models.Q(recipient_user=user)
            normalized_email = normalized_email or _normalize_email(getattr(user, "email", ""))
        if normalized_email:
            clauses |= models.Q(recipient_email__iexact=normalized_email)
        return self.filter(clauses) if clauses else self.none()


class NotificationManager(models.Manager.from_queryset(NotificationQuerySet)):
    pass


class DealQuerySet(models.QuerySet):
    def with_related(self):
        return self.select_related("request", "requester_user", "target_user")


class DealManager(models.Manager.from_queryset(DealQuerySet)):
    pass


class SubscriptionQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def for_user(self, user):
        return self.filter(user=user)

    def with_request(self):
        return self.select_related("request")


class SubscriptionManager(models.Manager.from_queryset(SubscriptionQuerySet)):
    pass


class ShyRequest(SoftDeleteModel, TimeStampedModel, EmailUserResolutionModel):
    class ServiceChannel(models.TextChoices):
        EMAIL = ("email", "E-mail")
        LETTER = ("letter", "Letter")
        CALL = ("call", "Phone call")

    class Status(models.TextChoices):
        DRAFT = ("draft", "Draft")
        SUBMITTED = ("submitted", "Submitted")
        IN_PROGRESS = ("in_progress", "In progress")
        COMPLETED = ("completed", "Completed")
        REJECTED = ("rejected", "Rejected")
        
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    requester_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="requested_shy_requests",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="targeted_shy_requests",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    
    tracking_code = models.CharField(max_length=12, unique=True, blank=True)
    requester_name = models.CharField(max_length=120)
    requester_email = models.EmailField()
    requester_phone = models.CharField(max_length=50, blank=True)
    requester_alias = models.CharField(
        max_length=120,
        blank=True,
        help_text="Display name for this request (e.g. in chat). If blank, profile alias or requester_name is used.",
    )


    target_name = models.CharField(max_length=120, blank=True)
    target_email = models.EmailField(blank=True)
    target_phone = models.CharField(max_length=50, blank=True)
    target_address = models.CharField(max_length=255, blank=True)

    description = models.TextField()
    service_channel = models.CharField(
        max_length=20, choices=ServiceChannel.choices, default=ServiceChannel.EMAIL
    )
    call_minutes = models.PositiveIntegerField(
        default=0, help_text="Estimated minutes if we call."
    )
    quoted_price_chf = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    country_code = models.CharField(max_length=8, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    is_blocked = models.BooleanField(default=False)
    blocked_at = models.DateTimeField(null=True, blank=True)
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="blocked_shy_requests",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    block_note = models.CharField(max_length=255, blank=True)

    objects = ShyRequestManager()
    all_objects = ShyRequestAllManager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["requester_email", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["is_deleted", "-created_at"]),
            models.Index(fields=["is_blocked", "-created_at"]),
        ]

    def calculate_price(self) -> Decimal:
        """Apply simple pricing rules from the SRS."""
        if self.service_channel == self.ServiceChannel.EMAIL:
            return Decimal("1.00")
        if self.service_channel == self.ServiceChannel.LETTER:
            return Decimal("10.00")
        minutes = Decimal(self.call_minutes or 0)
        return Decimal("20.00") + minutes

    def change_status(self, new_status: str):
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])

    @property
    def requester_identity(self):
        return self.requester_user or self.user

    @property
    def requester_display_name(self) -> str:
        return self.requester_alias or self.requester_name or user_display_name_for(self.requester_identity)

    @property
    def target_display_name(self) -> str:
        return self.target_name or user_display_name_for(self.target_user) or "Target"

    def _generate_unique_tracking_code(self) -> str:
        while True:
            tracking_code = generate_tracking_code()
            exists = type(self).all_objects.filter(tracking_code=tracking_code).exclude(pk=self.pk).exists()
            if not exists:
                return tracking_code

    def sync_participants(self, save: bool = True):
        if self.user_id and not self.requester_user_id:
            self.requester_user = self.user

        requester_user, _ = self._sync_email_user_pair(
            user_field="requester_user",
            email_field="requester_email",
        )
        target_user, _ = self._sync_email_user_pair(
            user_field="target_user",
            email_field="target_email",
        )

        if requester_user:
            self.user = requester_user
        elif self.user_id and not self.requester_user_id:
            self.requester_user = self.user
            requester_user = self.user

        if requester_user:
            self.requester_alias = self.requester_alias or getattr(requester_user, "alias_name", "") or ""
            self.requester_name = self.requester_name or user_display_name_for(requester_user)
        if target_user:
            self.target_name = self.target_name or user_display_name_for(target_user)

        if save:
            self.save(
                update_fields=[
                    "user",
                    "requester_user",
                    "target_user",
                    "requester_email",
                    "target_email",
                    "updated_at",
                ]
            )

    def ensure_description_message(self):
        message = Message.objects.filter(
            request=self,
            message_kind=Message.Kind.INITIAL_REQUEST,
        ).first()
        if message:
            message.sender = Message.Actor.REQUESTER
            message.recipient = Message.Actor.TARGET
            message.author = self.requester_identity
            message.sender_user = self.requester_identity
            message.recipient_user = self.target_user
            message.sender_email = self.requester_email
            message.recipient_email = self.target_email
            message.sender_display_name = self.requester_display_name
            message.recipient_display_name = self.target_display_name
            message.body = self.description
            message.clean_body = self.description
            message.is_blocked = False
            message._skip_censor = True
            message.save()
        else:
            message = Message(
                request=self,
                message_kind=Message.Kind.INITIAL_REQUEST,
                sender=Message.Actor.REQUESTER,
                recipient=Message.Actor.TARGET,
                author=self.requester_identity,
                sender_user=self.requester_identity,
                recipient_user=self.target_user,
                sender_email=self.requester_email,
                recipient_email=self.target_email,
                sender_display_name=self.requester_display_name,
                recipient_display_name=self.target_display_name,
                body=self.description,
                clean_body=self.description,
                is_blocked=False,
            )
            message._skip_censor = True
            message.save()
        return message

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if not self.tracking_code:
            self.tracking_code = self._generate_unique_tracking_code()
        self.quoted_price_chf = self.calculate_price()
        self.sync_participants(save=False)
        # Validate description content for safety (same censor as messages)
        if self.description:
            clean_body, blocked = censor_text(self.description)
            if blocked:
                raise ValidationError({"description": ["Description contains blocked content."]})
            self.description = clean_body
        super().save(*args, **kwargs)
        if self.description or is_new:
            self.ensure_description_message()

    def soft_delete(self, *, save: bool = True):
        if not super().soft_delete(save=save):
            return False
        Message.all_objects.filter(request=self).soft_delete()
        return True

    def _blocked_request_count_for_requester(self):
        requester = self.requester_user or self.user
        if not requester:
            return 0
        return type(self).all_objects.filter(
            models.Q(requester_user=requester) | models.Q(user=requester, requester_user__isnull=True),
            is_blocked=True,
        ).count()

    def block(self, *, actor=None, note: str = ""):
        if self.is_blocked:
            return self._blocked_request_count_for_requester(), False

        self.is_blocked = True
        self.blocked_at = timezone.now()
        self.blocked_by = actor if getattr(actor, "is_authenticated", False) else None
        self.block_note = (note or "").strip()
        self.status = self.Status.REJECTED
        self.save(update_fields=["is_blocked", "blocked_at", "blocked_by", "block_note", "status", "updated_at"])

        requester = self.requester_user or self.user
        blocked_user = False
        blocked_count = self._blocked_request_count_for_requester()
        if requester and blocked_count >= 3 and requester.is_active:
            requester.is_active = False
            requester.save(update_fields=["is_active", "updated_at"])
            blocked_user = True
        return blocked_count, blocked_user

    def __str__(self) -> str:
        return f"Request by {self.requester_name} ({self.service_channel})"


class Attachment(models.Model):
    request = models.ForeignKey(
        ShyRequest, related_name="attachments", on_delete=models.CASCADE
    )
    file = models.FileField(upload_to="attachments/%Y/%m/%d")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.file.name


class Message(SoftDeleteModel, EmailUserResolutionModel, CreatedAtModel):
    class Actor(models.TextChoices):
        REQUESTER = ("requester", "Requester")
        STAFF = ("staff", "Staff")
        TARGET = ("target", "Target")
        SYSTEM = ("system", "System")

    class Kind(models.TextChoices):
        INITIAL_REQUEST = ("initial_request", "Initial request")
        REPLY = ("reply", "Reply")
        NOTE = ("note", "Note")

    request = models.ForeignKey(
        ShyRequest, related_name="messages", on_delete=models.CASCADE
    )
    parent_message = models.ForeignKey(
        "self",
        related_name="replies",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    sender = models.CharField(max_length=20, choices=Actor.choices)
    recipient = models.CharField(
        max_length=20, choices=Actor.choices, default=Actor.TARGET
    )
    message_kind = models.CharField(
        max_length=30, choices=Kind.choices, default=Kind.REPLY
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="authored_chat_messages",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="sent_chat_messages",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="received_chat_messages",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    sender_email = models.EmailField(blank=True)
    recipient_email = models.EmailField(blank=True)
    sender_display_name = models.CharField(
        max_length=120,
        blank=True,
        help_text="Display name for this message (e.g. alias). If blank, derived from request/profile.",
    )
    recipient_display_name = models.CharField(max_length=120, blank=True)
    body = models.TextField()
    clean_body = models.TextField(blank=True)
    is_blocked = models.BooleanField(default=False)
    deleted_by_sender = models.BooleanField(default=False)
    sender_deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by_recipient = models.BooleanField(default=False)
    recipient_deleted_at = models.DateTimeField(null=True, blank=True)
    objects = MessageManager()
    all_objects = MessageAllManager()

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["request", "created_at"]),
            models.Index(fields=["parent_message", "created_at"]),
            models.Index(fields=["sender", "created_at"]),
            models.Index(fields=["recipient", "created_at"]),
            models.Index(fields=["author", "created_at"]),
            models.Index(fields=["is_deleted", "created_at"]),
            models.Index(fields=["deleted_by_sender", "created_at"]),
            models.Index(fields=["deleted_by_recipient", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_sender_display()}: {self.body[:40]}"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        self._sync_email_user_pair(user_field="sender_user", email_field="sender_email")
        self._sync_email_user_pair(user_field="recipient_user", email_field="recipient_email")
        if self.parent_message_id:
            if self.parent_message_id == self.pk:
                raise ValidationError("A message cannot reply to itself.")
            if self.parent_message.request_id != self.request_id:
                raise ValidationError("Reply target must belong to the same request.")
            if self.parent_message.is_deleted:
                raise ValidationError("Reply target has been deleted.")
        if not self.author_id:
            self.author = self.sender_user
        if self.sender == self.Actor.REQUESTER and not self.sender_display_name:
            self.sender_display_name = self.request.requester_display_name
        if self.sender == self.Actor.TARGET and not self.sender_display_name:
            self.sender_display_name = self.request.target_display_name
        if self.recipient == self.Actor.REQUESTER and not self.recipient_display_name:
            self.recipient_display_name = self.request.requester_display_name
        if self.recipient == self.Actor.TARGET and not self.recipient_display_name:
            self.recipient_display_name = self.request.target_display_name
        if getattr(self, "_skip_censor", False):
            self.clean_body = self.body or ""
            self.is_blocked = False
        else:
            clean_body, blocked = censor_text(self.body or "")
            self.clean_body = clean_body
            self.is_blocked = blocked
            if blocked:
                raise ValidationError("Message contains blocked content.")

    def is_visible_to(self, actor_role: str | None) -> bool:
        if self.is_deleted:
            return False
        if not actor_role:
            return True
        if self.sender == actor_role and self.deleted_by_sender:
            return False
        if self.recipient == actor_role and self.deleted_by_recipient:
            return False
        return True

    def soft_delete_for_actor(self, actor_role: str | None, *, save: bool = True):
        if actor_role == self.sender:
            if self.deleted_by_sender:
                return False
            self.deleted_by_sender = True
            self.sender_deleted_at = timezone.now()
            if save:
                self.save(update_fields=["deleted_by_sender", "sender_deleted_at"])
            return True
        if actor_role == self.recipient:
            if self.deleted_by_recipient:
                return False
            self.deleted_by_recipient = True
            self.recipient_deleted_at = timezone.now()
            if save:
                self.save(update_fields=["deleted_by_recipient", "recipient_deleted_at"])
            return True
        return False

    def delete(self, *args, actor_role: str | None = None, **kwargs):
        if actor_role:
            return self.soft_delete_for_actor(actor_role)
        return self.soft_delete()


class Notification(EmailUserResolutionModel, models.Model):
    recipient_email = models.EmailField()
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_notifications",
    )
    subject = models.CharField(max_length=200)
    body = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    related_request = models.ForeignKey(
        ShyRequest, on_delete=models.CASCADE, null=True, blank=True
    )
    objects = NotificationManager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient_email", "-created_at"]),
            models.Index(fields=["related_request", "is_read", "-created_at"]),
        ]

    def save(self, *args, **kwargs):
        self._sync_email_user_pair(user_field="recipient_user", email_field="recipient_email")
        if not self.created_at:
            from django.utils import timezone
            self.created_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Notification to {self.recipient_email}"


class Deal(TimeStampedModel):
    class Status(models.TextChoices):
        PROPOSED = ("proposed", "Proposed")
        AGREED = ("agreed", "Agreed")
        PAYMENT_DUE = ("payment_due", "Payment due")
        PAID = ("paid", "Paid")
        COMPLETED = ("completed", "Completed")
        CANCELLED = ("cancelled", "Cancelled")

    class Payer(models.TextChoices):
        REQUESTER = ("requester", "Requester")
        RECIPIENT = ("recipient", "Recipient")
        SPLIT = ("split", "Split")

    request = models.OneToOneField(
        ShyRequest, related_name="deal", on_delete=models.CASCADE
    )
    requester_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="requester_deals",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="target_deals",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=8, default="INR")
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payer = models.CharField(max_length=20, choices=Payer.choices, default=Payer.REQUESTER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROPOSED)
    payment_reference = models.CharField(max_length=120, blank=True)
    invoice_number = models.CharField(max_length=40, blank=True)
    ai_detected = models.BooleanField(default=False, help_text="True if deal was detected by AI from conversation.")
    ai_summary = models.TextField(blank=True, help_text="AI-generated summary of the deal.")
    objects = DealManager()

    def calculate_fee(self) -> Decimal:
        return (self.amount or Decimal("0")) * Decimal("0.03")

    def save(self, *args, **kwargs):
        if self.request_id:
            self.requester_user = self.request.requester_user or self.request.user
            self.target_user = self.request.target_user
        self.platform_fee = self.calculate_fee()
        if not self.invoice_number:
            self.invoice_number = f"INV-{self.request.tracking_code}-{self.pk or ''}".strip("-")
        super().save(*args, **kwargs)

    def mark_paid(self, reference: str):
        self.payment_reference = reference
        self.status = self.Status.PAID
        self.save(update_fields=["payment_reference", "status", "updated_at", "platform_fee"])


class Subscription(CreatedAtModel):
    """User subscriptions: request updates, deal alerts, optional daily digest (all AI-enhanced)."""
    class Type(models.TextChoices):
        REQUEST_UPDATES = ("request_updates", "Request updates (new messages)")
        DEAL_ALERTS = ("deal_alerts", "Deal alerts (AI-detected deals)")
        DAILY_DIGEST = ("daily_digest", "Daily digest (AI summary)")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions"
    )
    request = models.ForeignKey(
        ShyRequest, on_delete=models.CASCADE, null=True, blank=True, related_name="subscriptions"
    )
    subscription_type = models.CharField(max_length=30, choices=Type.choices)
    is_active = models.BooleanField(default=True)
    objects = SubscriptionManager()

    class Meta:
        unique_together = [["user", "request", "subscription_type"]]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} {self.get_subscription_type_display()} ({self.request_id or 'all'})"


class ActiveShyRequest(ShyRequest):
    objects = ActiveShyRequestManager()

    class Meta:
        proxy = True
        verbose_name = "Active request"
        verbose_name_plural = "Active requests"


class ConversationMessage(Message):
    objects = ConversationMessageManager()

    class Meta:
        proxy = True
        verbose_name = "Conversation message"
        verbose_name_plural = "Conversation messages"


class FAQ(TimeStampedModel):
    question = models.CharField(max_length=255)
    answer = models.TextField()
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "question"]
        indexes = [
            models.Index(fields=["is_active", "sort_order"]),
        ]

    def __str__(self) -> str:
        return self.question


class FAQVideo(TimeStampedModel):
    faq = models.ForeignKey(FAQ, related_name="videos", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    video_url = models.URLField()
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "created_at"]
        indexes = [
            models.Index(fields=["faq", "is_active", "sort_order"]),
        ]

    def __str__(self) -> str:
        return self.title


class SupportTicketQuerySet(models.QuerySet):
    def with_related(self):
        return self.select_related("user", "assigned_to").prefetch_related(
            models.Prefetch("replies", queryset=SupportTicketReply.objects.select_related("author"))
        )

    def visible_to(self, user):
        if getattr(user, "is_staff", False):
            return self
        if getattr(user, "is_authenticated", False):
            return self.filter(user=user)
        return self.none()


class SupportTicketManager(models.Manager.from_queryset(SupportTicketQuerySet)):
    pass


class SupportTicket(TimeStampedModel, EmailUserResolutionModel):
    class Status(models.TextChoices):
        OPEN = ("open", "Open")
        IN_PROGRESS = ("in_progress", "In progress")
        RESOLVED = ("resolved", "Resolved")
        CLOSED = ("closed", "Closed")

    class Priority(models.TextChoices):
        LOW = ("low", "Low")
        MEDIUM = ("medium", "Medium")
        HIGH = ("high", "High")
        URGENT = ("urgent", "Urgent")

    tracking_code = models.CharField(max_length=12, unique=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="support_tickets",
        on_delete=models.CASCADE,
    )
    email = models.EmailField(blank=True)
    subject = models.CharField(max_length=255)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="assigned_support_tickets",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    last_reply_at = models.DateTimeField(null=True, blank=True)
    objects = SupportTicketManager()

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status", "-updated_at"]),
            models.Index(fields=["tracking_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.tracking_code or 'TICKET'} - {self.subject}"

    def _generate_unique_tracking_code(self) -> str:
        while True:
            tracking_code = generate_tracking_code()
            exists = type(self).objects.filter(tracking_code=tracking_code).exclude(pk=self.pk).exists()
            if not exists:
                return tracking_code

    @property
    def latest_reply(self):
        return self.replies.order_by("-created_at").first()

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if not self.tracking_code:
            self.tracking_code = self._generate_unique_tracking_code()
        self._sync_email_user_pair(user_field="user", email_field="email")
        if self.message:
            clean_message, blocked = censor_text(self.message)
            if blocked:
                raise ValidationError({"message": ["Message contains blocked content."]})
            self.message = clean_message
        super().save(*args, **kwargs)

        if is_new:
            self._push_ticket_created()

    def _push_ticket_created(self):
        try:
            from account.push_notifications import N
            from account.tasks import send_push_notification_task

            # #32 — notify ALL staff when ticket is HIGH or URGENT priority
            if self.priority in (self.Priority.HIGH, self.Priority.URGENT):
                User = get_user_model()
                staff_ids = list(User.objects.filter(is_staff=True, is_active=True).values_list("id", flat=True))
                title, body = N.HIGH_PRIORITY_TICKET.render()
                for staff_id in staff_ids:
                    send_push_notification_task.delay(
                        user_id=staff_id,
                        title=title,
                        body=body,
                        data={"type": N.HIGH_PRIORITY_TICKET.key, "ticket_id": str(self.pk)},
                    )
                logger.info("Push queued: high_priority_ticket to %d staff for ticket pk=%s", len(staff_ids), self.pk)

        except Exception:
            logger.exception("Push failed for new support ticket pk=%s", self.pk)


class SupportTicketReply(TimeStampedModel, EmailUserResolutionModel):
    class SenderType(models.TextChoices):
        USER = ("user", "User")
        STAFF = ("staff", "Staff")
        ADMIN = ("admin", "Admin")

    ticket = models.ForeignKey(SupportTicket, related_name="replies", on_delete=models.CASCADE)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="support_ticket_replies",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    sender_type = models.CharField(max_length=20, choices=SenderType.choices)
    email = models.EmailField(blank=True)
    body = models.TextField()

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["ticket", "created_at"]),
            models.Index(fields=["sender_type", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.ticket.tracking_code} - {self.get_sender_type_display()}"

    def save(self, *args, **kwargs):
        self._sync_email_user_pair(user_field="author", email_field="email")
        if self.body:
            clean_body, blocked = censor_text(self.body)
            if blocked:
                raise ValidationError({"body": ["Reply contains blocked content."]})
            self.body = clean_body
        super().save(*args, **kwargs)
        ticket_status = SupportTicket.Status.IN_PROGRESS if self.sender_type in {self.SenderType.STAFF, self.SenderType.ADMIN} else SupportTicket.Status.OPEN
        SupportTicket.objects.filter(pk=self.ticket_id).update(
            last_reply_at=self.created_at,
            status=ticket_status if self.ticket.status != SupportTicket.Status.CLOSED else self.ticket.status,
            updated_at=self.created_at,
        )
        self._push_reply()

    def _push_reply(self):
        try:
            from account.push_notifications import N
            from account.tasks import send_push_notification_task

            owner_id = self.ticket.user_id

            # #28 — notify ticket owner when staff/admin replies
            if self.sender_type in (self.SenderType.STAFF, self.SenderType.ADMIN):
                if owner_id:
                    title, body = N.TICKET_STAFF_REPLY.render()
                    send_push_notification_task.delay(
                        user_id=owner_id,
                        title=title,
                        body=body,
                        data={"type": N.TICKET_STAFF_REPLY.key, "ticket_id": str(self.ticket_id)},
                    )
                    logger.info("Push queued: ticket_staff_reply to user_id=%s", owner_id)

        except Exception:
            logger.exception("Push failed for ticket reply pk=%s", self.pk)


def link_user_references(user):
    email = _normalize_email(getattr(user, "email", ""))
    if not email:
        return

    ShyRequest.objects.filter(requester_user__isnull=True, requester_email__iexact=email).update(
        requester_user=user,
        user=user,
    )
    ShyRequest.objects.filter(target_user__isnull=True, target_email__iexact=email).update(
        target_user=user,
    )
    Message.objects.filter(sender_user__isnull=True, sender_email__iexact=email).update(
        sender_user=user,
    )
    Message.objects.filter(recipient_user__isnull=True, recipient_email__iexact=email).update(
        recipient_user=user,
    )
    Notification.objects.filter(recipient_user__isnull=True, recipient_email__iexact=email).update(
        recipient_user=user,
    )
    Deal.objects.filter(requester_user__isnull=True, request__requester_email__iexact=email).update(
        requester_user=user,
    )
    Deal.objects.filter(target_user__isnull=True, request__target_email__iexact=email).update(
        target_user=user,
    )


# ----- Censor engine: store offensive terms in DB (any language) -----
class CensorCategory(models.Model):
    """Category for offensive terms (abusive, illegal, drugs, etc.)."""
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=50, unique=True, help_text="e.g. abusive, illegal, human_trafficking")
    description = models.CharField(max_length=255, blank=True)
    is_blocking = models.BooleanField(
        default=True,
        help_text="If True, matching content is blocked (rejected).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Censor category"
        verbose_name_plural = "Censor categories"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.slug})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            from .censor_loader import invalidate_censor_cache
            invalidate_censor_cache()
        except Exception:
            pass


class OffensiveTerm(models.Model):
    """Single offensive word or phrase, any language. Loaded by censor engine."""
    class TermType(models.TextChoices):
        WORD = ("word", "Word")
        PHRASE = ("phrase", "Phrase")

    category = models.ForeignKey(
        CensorCategory,
        on_delete=models.CASCADE,
        related_name="terms",
    )
    term = models.CharField(max_length=255, help_text="Word or phrase to detect (case-insensitive).")
    term_type = models.CharField(
        max_length=10,
        choices=TermType.choices,
        default=TermType.WORD,
    )
    language_code = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="ISO 639-1 e.g. en, ar, hi. Empty = any language.",
    )
    is_blocking = models.BooleanField(
        default=True,
        help_text="If True, content containing this term is blocked.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Offensive term"
        verbose_name_plural = "Offensive terms"
        ordering = ["category", "term_type", "-term"]
        indexes = [
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["language_code", "is_active"]),
        ]

    def __str__(self):
        return f"{self.term} ({self.category.slug})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            from .censor_loader import invalidate_censor_cache
            invalidate_censor_cache()
        except Exception:
            pass


class CensorLog(models.Model):
    """Log when content was blocked by censor (for safety and tuning)."""
    source = models.CharField(max_length=32, blank=True, help_text="e.g. api, chat, upload")
    categories = models.JSONField(default=list, help_text="List of category slugs that triggered.")
    detected_terms = models.JSONField(default=list, help_text="List of detected term strings.")
    blocked = models.BooleanField(default=True)
    text_preview = models.CharField(max_length=500, blank=True, help_text="First 500 chars of input (redacted).")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Censor log"
        verbose_name_plural = "Censor logs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"CensorLog {self.id} blocked={self.blocked} {self.created_at}"


class CensorTrainingExample(models.Model):
    """
    Training data for our own AI model.
    When Google API detects toxic content (and our model missed it), we save here.
    Then we retrain our model on this data so it learns over time.
    """
    class Source(models.TextChoices):
        GOOGLE_API = ("google_api", "Google API (fallback detected)")
        OUR_MODEL = ("our_model", "Our model detected")
        MANUAL = ("manual", "Manual label")

    text = models.TextField(help_text="Input text (truncated for storage).")
    is_toxic = models.BooleanField(help_text="True = offensive/toxic, False = safe.")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.GOOGLE_API)
    score = models.FloatField(null=True, blank=True, help_text="Toxicity score from API or model.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Censor training example"
        verbose_name_plural = "Censor training examples"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["source", "is_toxic"])]

    def __str__(self):
        return f"{'toxic' if self.is_toxic else 'safe'} ({self.source})"


class SiteBranding(TimeStampedModel):
    singleton_key = models.CharField(max_length=32, default="site-branding", unique=True, editable=False)
    logo = models.ImageField(upload_to="branding/logos/")

    class Meta:
        verbose_name = "Site branding"
        verbose_name_plural = "Site branding"
        ordering = ["-updated_at", "-created_at"]

    def __str__(self) -> str:
        return "Site branding"

    @classmethod
    def get_solo(cls):
        return cls.objects.order_by("-updated_at", "-created_at").first()

    def save(self, *args, **kwargs):
        old_logo_name = None
        if self.pk:
            old_logo_name = type(self).objects.filter(pk=self.pk).values_list("logo", flat=True).first()

        super().save(*args, **kwargs)

        if old_logo_name and old_logo_name != self.logo.name:
            self.logo.storage.delete(old_logo_name)

    def delete(self, *args, **kwargs):
        logo_name = self.logo.name
        storage = self.logo.storage
        result = super().delete(*args, **kwargs)
        if logo_name:
            storage.delete(logo_name)
        return result

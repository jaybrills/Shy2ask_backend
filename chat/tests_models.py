import os
import tempfile
from django.test import TestCase
from django.test import override_settings
from decimal import Decimal
from django.core.files.uploadedfile import SimpleUploadedFile

from account.emailing import build_email_context
from account.models import User
from chat.message_service import create_message_for_request
from chat.models import ActiveShyRequest, ConversationMessage, Deal, Message, Notification, ShyRequest, SiteBranding

class ChatModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="sender@shy2ask.com", password="password")
        self.request = ShyRequest.objects.create(
            requester_name="Requester",
            requester_email="req@shy2ask.com",
            description="Test"
        )

    def test_shy_request_creation(self):
        self.assertEqual(self.request.status, ShyRequest.Status.DRAFT)
        self.assertTrue(self.request.tracking_code)
        self.assertTrue(
            Message.objects.filter(
                request=self.request,
                message_kind=Message.Kind.INITIAL_REQUEST,
            ).exists()
        )

    def test_message_creation(self):
        msg = Message.objects.create(
            request=self.request,
            sender=Message.Actor.REQUESTER,
            recipient=Message.Actor.TARGET,
            body="Hello"
        )
        self.assertEqual(msg.body, "Hello")
        self.assertEqual(msg.clean_body, "Hello") # Assuming no censorship

    def test_deal_creation(self):
        deal = Deal.objects.create(
            request=self.request,
            amount=Decimal("100.00"),
            currency="INR"
        )
        self.assertEqual(deal.amount, Decimal("100.00"))
        self.assertTrue(deal.invoice_number.startswith("INV-"))

    def test_notification_creation(self):
        notif = Notification.objects.create(
            recipient_email="notif@example.com",
            subject="Test",
            body="Body",
            related_request=self.request
        )
        self.assertEqual(notif.subject, "Test")

    def test_request_auto_links_users_and_emails(self):
        target = User.objects.create_user(email="target@shy2ask.com", password="password", alias_name="Target Alias")

        shy_request = ShyRequest.objects.create(
            requester_user=self.user,
            target_email=target.email,
            description="Linked request",
        )

        self.assertEqual(shy_request.user, self.user)
        self.assertEqual(shy_request.requester_email, self.user.email)
        self.assertEqual(shy_request.target_user, target)
        self.assertEqual(shy_request.target_name, "Target Alias")

    def test_proxy_models_use_custom_querysets(self):
        open_request = ShyRequest.objects.create(
            requester_name="Requester 2",
            requester_email="req2@shy2ask.com",
            description="Open request",
            status=ShyRequest.Status.SUBMITTED,
        )
        closed_request = ShyRequest.objects.create(
            requester_name="Requester 3",
            requester_email="req3@shy2ask.com",
            description="Closed request",
            status=ShyRequest.Status.COMPLETED,
        )

        self.assertIn(open_request, ActiveShyRequest.objects.all())
        self.assertNotIn(closed_request, ActiveShyRequest.objects.all())
        self.assertTrue(ConversationMessage.objects.for_request(self.request).exists())

    def test_message_visible_to_honors_participant_soft_delete(self):
        message = Message.objects.create(
            request=self.request,
            sender=Message.Actor.REQUESTER,
            recipient=Message.Actor.TARGET,
            body="Hide for requester only",
        )

        message.soft_delete_for_actor(Message.Actor.REQUESTER)

        self.assertFalse(Message.objects.visible_to(Message.Actor.REQUESTER).filter(id=message.id).exists())
        self.assertTrue(Message.objects.visible_to(Message.Actor.TARGET).filter(id=message.id).exists())

    def test_reply_creation_marks_request_ongoing(self):
        self.request.status = ShyRequest.Status.SUBMITTED
        self.request.save(update_fields=["status", "updated_at"])

        create_message_for_request(
            self.request,
            "A real reply should move the request forward",
            tracking_code=self.request.tracking_code,
            run_async_business_logic=False,
        )

        self.request.refresh_from_db()
        self.assertEqual(self.request.status, ShyRequest.Status.ONGOING)

    def test_mark_read_for_actor_updates_only_recipient_messages(self):
        inbound = Message.objects.create(
            request=self.request,
            sender=Message.Actor.REQUESTER,
            recipient=Message.Actor.TARGET,
            body="Unread for target",
        )
        outbound = Message.objects.create(
            request=self.request,
            sender=Message.Actor.TARGET,
            recipient=Message.Actor.REQUESTER,
            body="Not unread for target",
        )

        updated_count = Message.objects.for_request(self.request).mark_read_for_actor(Message.Actor.TARGET)

        inbound.refresh_from_db()
        outbound.refresh_from_db()
        self.assertEqual(updated_count, 2)
        self.assertTrue(inbound.is_read)
        self.assertIsNotNone(inbound.read_at)
        self.assertFalse(outbound.is_read)

    def test_default_email_context_uses_static_logo(self):
        context = build_email_context(site_url="https://backend.shy2ask.com")

        self.assertEqual(context["logo_url"], "https://backend.shy2ask.com/static/core/img/shy2ask-logo.png")

    def test_updating_site_branding_deletes_old_media_logo(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root, MEDIA_URL="/media/", SITE_URL="https://backend.shy2ask.com"):
                branding = SiteBranding.objects.create(
                    logo=SimpleUploadedFile("logo-one.png", b"first-logo", content_type="image/png"),
                )
                old_logo_path = branding.logo.path

                branding.logo = SimpleUploadedFile("logo-two.png", b"second-logo", content_type="image/png")
                branding.save()

                branding.refresh_from_db()
                self.assertFalse(branding.logo.name.endswith("logo-one.png"))
                self.assertFalse(os.path.exists(old_logo_path))
                self.assertTrue(os.path.exists(branding.logo.path))

                context = build_email_context()
                self.assertEqual(context["logo_url"], f"https://backend.shy2ask.com{branding.logo.url}")

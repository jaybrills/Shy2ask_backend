from django.test import TestCase
from decimal import Decimal
from chat.models import ShyRequest, Conversation, Message, Notification, Deal
from account.models import User

class ChatModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="sender@example.com", password="password")
        self.request = ShyRequest.objects.create(
            requester_name="Requester",
            requester_email="req@example.com",
            description="Test"
        )

    def test_shy_request_creation(self):
        self.assertEqual(self.request.status, ShyRequest.Status.DRAFT)
        self.assertTrue(self.request.tracking_code)
        # Conversation should be created by signal/serializer (I added it to serializer)
        # Actually in models.py it's not automated yet, I put it in Serializer.
        # But for tests creating via models.objects.create won't trigger serializer.
        # Let's check if there's a signal. None found.
        # So I should create it manually if it's a model test.
        conv = Conversation.objects.create(request=self.request)
        self.assertEqual(str(conv), f"Conversation for {self.request}")

    def test_message_creation(self):
        conv = Conversation.objects.create(request=self.request)
        msg = Message.objects.create(
            conversation=conv,
            sender=Message.Sender.REQUESTER,
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

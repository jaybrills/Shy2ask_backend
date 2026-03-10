from django.test import TestCase
from decimal import Decimal
from chat.models import ShyRequest, Message, Notification, Deal
from account.models import User

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

    def test_message_creation(self):
        msg = Message.objects.create(
            request=self.request,
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

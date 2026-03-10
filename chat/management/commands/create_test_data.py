from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from chat.models import ShyRequest, Message, Deal, Attachment
from decimal import Decimal
from datetime import datetime, timedelta


class Command(BaseCommand):
    help = 'Create test data for mailtokhajan@gmail.com user'

    def handle(self, *args, **options):
        # Create or get user
        user, created = User.objects.get_or_create(
            username='khajan',
            defaults={
                'email': 'mailtokhajan@gmail.com',
                'first_name': 'Khajan',
                'last_name': 'Test',
            }
        )
        if created:
            user.set_password('test123')
            user.save()
            self.stdout.write(self.style.SUCCESS(f'Created user: {user.username}'))
        else:
            self.stdout.write(self.style.WARNING(f'User already exists: {user.username}'))

        # Create comprehensive test requests
        requests_data = [
            {
                'requester_name': 'Khajan',
                'requester_email': 'mailtokhajan@gmail.com',
                'requester_phone': '+41 79 123 4567',
                'target_name': 'John Smith',
                'target_email': 'john.smith@example.com',
                'target_phone': '+41 79 987 6543',
                'description': 'I saw John has a vintage car for sale. Can you ask if he would be willing to sell it to me? I\'m too shy to ask directly.',
                'service_channel': ShyRequest.ServiceChannel.EMAIL,
                'status': ShyRequest.Status.IN_PROGRESS,
            },
            {
                'requester_name': 'Khajan',
                'requester_email': 'mailtokhajan@gmail.com',
                'requester_phone': '+41 79 123 4567',
                'target_name': 'Sarah Johnson',
                'target_email': 'sarah.j@example.com',
                'target_address': 'Bahnhofstrasse 1, 8001 Zürich, Switzerland',
                'description': 'I would like to know if Sarah would consider me for a job position at her company. I don\'t want to seem too pushy by asking directly.',
                'service_channel': ShyRequest.ServiceChannel.LETTER,
                'status': ShyRequest.Status.SUBMITTED,
            },
            {
                'requester_name': 'Khajan',
                'requester_email': 'mailtokhajan@gmail.com',
                'target_name': 'Michael Brown',
                'target_email': 'm.brown@example.com',
                'target_phone': '+41 79 555 1234',
                'description': 'Can you ask Michael if he would be interested in collaborating on a project? I think we could work well together but I\'m hesitant to reach out.',
                'service_channel': ShyRequest.ServiceChannel.CALL,
                'call_minutes': 5,
                'status': ShyRequest.Status.COMPLETED,
            },
            {
                'requester_name': 'Khajan',
                'requester_email': 'mailtokhajan@gmail.com',
                'requester_phone': '+41 79 123 4567',
                'target_name': 'Emma Wilson',
                'target_email': 'emma.wilson@example.com',
                'description': 'I noticed Emma has a beautiful apartment for rent. Could you ask if she would consider renting it to me? I\'m too nervous to ask in person.',
                'service_channel': ShyRequest.ServiceChannel.EMAIL,
                'status': ShyRequest.Status.DRAFT,
            },
            {
                'requester_name': 'Khajan',
                'requester_email': 'mailtokhajan@gmail.com',
                'target_name': 'David Lee',
                'target_email': 'david.lee@example.com',
                'target_phone': '+41 79 777 8888',
                'description': 'David mentioned he might be selling his bike. Can you ask if it\'s still available and what price he\'s looking for?',
                'service_channel': ShyRequest.ServiceChannel.CALL,
                'call_minutes': 3,
                'status': ShyRequest.Status.IN_PROGRESS,
            },
            {
                'requester_name': 'Khajan',
                'requester_email': 'mailtokhajan@gmail.com',
                'target_name': 'Lisa Anderson',
                'target_email': 'lisa.a@example.com',
                'target_address': 'Rue du Rhône 5, 1204 Genève, Switzerland',
                'description': 'I\'d like to know if Lisa would be interested in a business partnership. I have a great idea but I\'m too shy to approach her directly.',
                'service_channel': ShyRequest.ServiceChannel.LETTER,
                'status': ShyRequest.Status.REJECTED,
            },
        ]

        created_requests = []
        for req_data in requests_data:
            request_obj, created = ShyRequest.objects.get_or_create(
                user=user,
                requester_email=req_data['requester_email'],
                target_email=req_data['target_email'],
                description=req_data['description'],
                defaults={
                    'requester_name': req_data['requester_name'],
                    'requester_phone': req_data.get('requester_phone', ''),
                    'target_name': req_data.get('target_name', ''),
                    'target_phone': req_data.get('target_phone', ''),
                    'target_address': req_data.get('target_address', ''),
                    'service_channel': req_data['service_channel'],
                    'call_minutes': req_data.get('call_minutes', 0),
                    'status': req_data['status'],
                    'country_code': 'CH',
                }
            )
            if created:
                created_requests.append(request_obj)
                self.stdout.write(self.style.SUCCESS(f'Created request: {request_obj.tracking_code}'))
            else:
                created_requests.append(request_obj)
                self.stdout.write(self.style.WARNING(f'Request already exists: {request_obj.tracking_code}'))

        # Create comprehensive request messages
        messages_data = [
            {
                'request_index': 0,
                'messages': [
                    {
                        'sender': Message.Sender.REQUESTER,
                        'body': 'Hi, I saw John has a vintage car for sale. Can you ask if he would be willing to sell it to me? I\'m too shy to ask directly.',
                        'created_at_offset': -2,
                    },
                    {
                        'sender': Message.Sender.STAFF,
                        'body': 'Hello! We\'ve received your request and will contact John about the car. We\'ll keep you updated.',
                        'created_at_offset': -1.5,
                    },
                    {
                        'sender': Message.Sender.STAFF,
                        'body': 'Good news! We contacted John and he said the car is still available. He\'s asking for CHF 15,000. Would you like to proceed?',
                        'created_at_offset': -0.5,
                    },
                    {
                        'sender': Message.Sender.REQUESTER,
                        'body': 'Yes, that sounds great! I\'m definitely interested. Can you help arrange the purchase?',
                        'created_at_offset': 0,
                    },
                ]
            },
            {
                'request_index': 1,
                'messages': [
                    {
                        'sender': Message.Sender.REQUESTER,
                        'body': 'I would like to know if Sarah would consider me for a job position. I don\'t want to seem too pushy.',
                        'created_at_offset': -3,
                    },
                    {
                        'sender': Message.Sender.STAFF,
                        'body': 'We\'ve sent a letter to Sarah. We\'ll update you once we receive a response.',
                        'created_at_offset': -2,
                    },
                    {
                        'sender': Message.Sender.STAFF,
                        'body': 'Update: The letter has been delivered. We\'re waiting for Sarah\'s response.',
                        'created_at_offset': -1,
                    },
                ]
            },
            {
                'request_index': 2,
                'messages': [
                    {
                        'sender': Message.Sender.REQUESTER,
                        'body': 'Can you ask Michael if he would be interested in collaborating on a project?',
                        'created_at_offset': -5,
                    },
                    {
                        'sender': Message.Sender.STAFF,
                        'body': 'We called Michael and he\'s very interested! He said he\'d love to discuss the collaboration.',
                        'created_at_offset': -4,
                    },
                    {
                        'sender': Message.Sender.REQUESTER,
                        'body': 'That\'s great! Can you set up a meeting time?',
                        'created_at_offset': -3,
                    },
                    {
                        'sender': Message.Sender.STAFF,
                        'body': 'Michael suggested next Tuesday at 2 PM. Does that work for you?',
                        'created_at_offset': -2,
                    },
                    {
                        'sender': Message.Sender.REQUESTER,
                        'body': 'Perfect! Tuesday at 2 PM works great. Thank you so much for helping!',
                        'created_at_offset': -1,
                    },
                    {
                        'sender': Message.Sender.STAFF,
                        'body': 'Great! The meeting is confirmed. We\'ll send you a reminder closer to the date.',
                        'created_at_offset': 0,
                    },
                ]
            },
            {
                'request_index': 3,
                'messages': [
                    {
                        'sender': Message.Sender.REQUESTER,
                        'body': 'I noticed Emma has a beautiful apartment for rent. Could you ask if she would consider renting it to me?',
                        'created_at_offset': -1,
                    },
                ]
            },
            {
                'request_index': 4,
                'messages': [
                    {
                        'sender': Message.Sender.REQUESTER,
                        'body': 'David mentioned he might be selling his bike. Can you ask if it\'s still available?',
                        'created_at_offset': -2,
                    },
                    {
                        'sender': Message.Sender.STAFF,
                        'body': 'We\'ve contacted David. He said the bike is still available and he\'s asking CHF 800.',
                        'created_at_offset': -1,
                    },
                    {
                        'sender': Message.Sender.REQUESTER,
                        'body': 'That\'s a bit more than I expected. Can you ask if he\'d consider CHF 650?',
                        'created_at_offset': -0.5,
                    },
                    {
                        'sender': Message.Sender.REQUESTER,
                        'body': 'I want to kill the deal if he doesn\'t lower the price.',
                        'created_at_offset': -0.3,
                    },
                    {
                        'sender': Message.Sender.STAFF,
                        'body': 'We\'ll negotiate on your behalf. We\'ll get back to you soon!',
                        'created_at_offset': 0,
                    },
                ]
            },
            {
                'request_index': 5,
                'messages': [
                    {
                        'sender': Message.Sender.REQUESTER,
                        'body': 'I\'d like to know if Lisa would be interested in a business partnership.',
                        'created_at_offset': -4,
                    },
                    {
                        'sender': Message.Sender.STAFF,
                        'body': 'We\'ve sent your request to Lisa via letter. Unfortunately, she declined the partnership opportunity.',
                        'created_at_offset': -3,
                    },
                    {
                        'sender': Message.Sender.REQUESTER,
                        'body': 'I understand. Thank you for trying anyway.',
                        'created_at_offset': -2,
                    },
                ]
            },
        ]

        for msg_group in messages_data:
            request_obj = created_requests[msg_group['request_index']]
            for msg_data in msg_group['messages']:
                created_at = datetime.now() + timedelta(days=msg_data['created_at_offset'])
                message, created = Message.objects.get_or_create(
                    request=request_obj,
                    sender=msg_data['sender'],
                    body=msg_data['body'],
                    defaults={
                        'author': user if msg_data['sender'] == Message.Sender.REQUESTER else None,
                        'created_at': created_at,
                    }
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f'Created message for request {request_obj.tracking_code}'))

        # Create deals for multiple requests
        deals_data = [
            {
                'request_index': 0,
                'amount': Decimal('15000.00'),
                'currency': 'CHF',
                'payer': Deal.Payer.REQUESTER,
                'status': Deal.Status.PAYMENT_DUE,
            },
            {
                'request_index': 2,
                'amount': Decimal('5000.00'),
                'currency': 'CHF',
                'payer': Deal.Payer.REQUESTER,
                'status': Deal.Status.COMPLETED,
            },
            {
                'request_index': 4,
                'amount': Decimal('800.00'),
                'currency': 'CHF',
                'payer': Deal.Payer.REQUESTER,
                'status': Deal.Status.PAYMENT_DUE,
            },
        ]
        
        for deal_data in deals_data:
            if deal_data['request_index'] < len(created_requests):
                deal_request = created_requests[deal_data['request_index']]
                deal, created = Deal.objects.get_or_create(
                    request=deal_request,
                    defaults={
                        'amount': deal_data['amount'],
                        'currency': deal_data['currency'],
                        'payer': deal_data['payer'],
                        'status': deal_data['status'],
                    }
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f'Created deal for request {deal_request.tracking_code}: {deal_data["amount"]} {deal_data["currency"]}'))

        self.stdout.write(self.style.SUCCESS('\n✅ Test data created successfully!'))
        self.stdout.write(self.style.SUCCESS(f'Login with: username=khajan, password=test123'))
        self.stdout.write(self.style.SUCCESS(f'Email: mailtokhajan@gmail.com'))

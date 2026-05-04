from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'chat'

    def ready(self):
        from django.db.models.signals import pre_save
        from chat.signals import on_ticket_status_change
        from chat.models import SupportTicket
        pre_save.connect(on_ticket_status_change, sender=SupportTicket)

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User


@receiver(post_save, sender=User)
def sync_chat_references_for_user(sender, instance, **kwargs):
    from chat.models import link_user_references

    link_user_references(instance)

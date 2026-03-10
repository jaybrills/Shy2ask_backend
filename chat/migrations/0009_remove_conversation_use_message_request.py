from django.db import migrations, models
import django.db.models.deletion


def copy_request_from_conversation(apps, schema_editor):
    Message = apps.get_model("chat", "Message")

    for msg in Message.objects.select_related("conversation__request").all().iterator():
        if msg.conversation_id and not msg.request_id:
            msg.request_id = msg.conversation.request_id
            msg.save(update_fields=["request"])


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0008_alter_message_options_alter_notification_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="request",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="messages",
                to="chat.shyrequest",
            ),
        ),
        migrations.RunPython(copy_request_from_conversation, migrations.RunPython.noop),
        migrations.RemoveIndex(
            model_name="message",
            name="chat_messag_convers_3154fc_idx",
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(fields=["request", "created_at"], name="chat_messag_request_0fd1bc_idx"),
        ),
        migrations.AlterField(
            model_name="message",
            name="request",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="messages",
                to="chat.shyrequest",
            ),
        ),
        migrations.RemoveField(
            model_name="message",
            name="conversation",
        ),
        migrations.DeleteModel(
            name="Conversation",
        ),
    ]

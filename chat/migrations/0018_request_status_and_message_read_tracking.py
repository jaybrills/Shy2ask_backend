from django.db import migrations, models


def backfill_request_status_and_message_reads(apps, schema_editor):
    ShyRequest = apps.get_model("chat", "ShyRequest")
    Message = apps.get_model("chat", "Message")

    ShyRequest.objects.filter(status="in_progress").update(status="ongoing")
    Message.objects.filter(is_read=False).update(is_read=True, read_at=models.F("created_at"))


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0017_sitebranding"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="is_read",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="message",
            name="read_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="shyrequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("submitted", "Submitted"),
                    ("ongoing", "Ongoing"),
                    ("completed", "Completed"),
                    ("rejected", "Rejected"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_request_status_and_message_reads, noop_reverse),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(
                fields=["request", "recipient", "is_read", "created_at"],
                name="chat_messag_request_46ac25_idx",
            ),
        ),
    ]

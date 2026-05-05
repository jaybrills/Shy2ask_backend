from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0010_userdevice"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255, verbose_name="title")),
                ("body", models.TextField(verbose_name="body")),
                ("notification_type", models.CharField(
                    db_index=True,
                    help_text="Key from PushTemplate (e.g. subscription_activated, payment_failed).",
                    max_length=100,
                    verbose_name="notification type",
                )),
                ("priority", models.CharField(
                    choices=[("high", "High"), ("medium", "Medium")],
                    default="medium",
                    max_length=20,
                    verbose_name="priority",
                )),
                ("data", models.JSONField(
                    blank=True,
                    default=dict,
                    help_text="Full data payload delivered with the notification.",
                    verbose_name="extra data",
                )),
                ("is_read", models.BooleanField(db_index=True, default=False, verbose_name="read")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="sent at")),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="notifications",
                    to=settings.AUTH_USER_MODEL,
                    verbose_name="user",
                )),
            ],
            options={
                "verbose_name": "user notification",
                "verbose_name_plural": "user notifications",
                "db_table": "account_user_notification",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="usernotification",
            index=models.Index(
                fields=["user", "-created_at"],
                name="account_notif_user_date_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="usernotification",
            index=models.Index(
                fields=["user", "is_read"],
                name="account_notif_user_read_idx",
            ),
        ),
    ]

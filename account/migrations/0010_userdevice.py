from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0009_user_unique_alias_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserDevice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="created at")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="devices",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="user",
                    ),
                ),
                (
                    "fcm_token",
                    models.TextField(
                        unique=True,
                        verbose_name="FCM token",
                        help_text="Firebase Cloud Messaging registration token for this device.",
                    ),
                ),
                (
                    "device_type",
                    models.CharField(
                        choices=[("android", "Android"), ("ios", "iOS"), ("web", "Web")],
                        default="android",
                        max_length=10,
                        verbose_name="device type",
                    ),
                ),
                (
                    "device_name",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional human-readable label, e.g. 'iPhone 15 Pro'.",
                        max_length=100,
                        verbose_name="device name",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Unset automatically when FCM reports the token as unregistered.",
                        verbose_name="active",
                    ),
                ),
                ("last_used_at", models.DateTimeField(auto_now=True, verbose_name="last used at")),
            ],
            options={
                "verbose_name": "user device",
                "verbose_name_plural": "user devices",
                "db_table": "account_user_device",
            },
        ),
        migrations.AddIndex(
            model_name="userdevice",
            index=models.Index(
                fields=["user", "is_active"],
                name="account_device_user_active_idx",
            ),
        ),
    ]

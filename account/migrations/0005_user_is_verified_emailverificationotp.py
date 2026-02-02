# Generated manually: is_verified + EmailVerificationOTP

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0004_passwordresetotp"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_verified",
            field=models.BooleanField(
                default=False,
                help_text="Designates whether this user has verified their email with OTP.",
                verbose_name="verified",
            ),
        ),
        migrations.CreateModel(
            name="EmailVerificationOTP",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("otp_code", models.CharField(max_length=8, verbose_name="OTP code")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="created at")),
                ("expires_at", models.DateTimeField(verbose_name="expires at")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="email_verification_otps",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "email verification OTP",
                "verbose_name_plural": "email verification OTPs",
                "ordering": ["-created_at"],
            },
        ),
    ]

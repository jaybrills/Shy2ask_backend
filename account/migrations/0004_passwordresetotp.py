# Generated manually for PasswordResetOTP

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0003_alter_user_phone_number"),
    ]

    operations = [
        migrations.CreateModel(
            name="PasswordResetOTP",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(db_index=True, max_length=254, verbose_name="email address")),
                ("otp_code", models.CharField(max_length=8, verbose_name="OTP code")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="created at")),
                ("expires_at", models.DateTimeField(verbose_name="expires at")),
            ],
            options={
                "verbose_name": "password reset OTP",
                "verbose_name_plural": "password reset OTPs",
                "ordering": ["-created_at"],
            },
        ),
    ]

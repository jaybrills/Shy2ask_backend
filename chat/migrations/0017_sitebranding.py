from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0016_message_deleted_by_recipient_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SiteBranding",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("singleton_key", models.CharField(default="site-branding", editable=False, max_length=32, unique=True)),
                ("logo", models.ImageField(upload_to="branding/logos/")),
            ],
            options={
                "verbose_name": "Site branding",
                "verbose_name_plural": "Site branding",
                "ordering": ["-updated_at", "-created_at"],
            },
        ),
    ]

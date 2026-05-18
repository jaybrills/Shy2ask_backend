from django.db import migrations, models


def copy_is_verified_to_email(apps, schema_editor):
    """
    Carry the old is_verified value into is_email_verified.
    Old is_verified meant 'email was verified', so it maps directly.
    is_phone_verified stays False for all — no one had phone verification before.
    """
    User = apps.get_model("account", "User")
    User.objects.filter(is_verified=True).update(is_email_verified=True)


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0013_rename_account_social_provider_uid_idx_account_soc_provide_d2fe83_idx"),
    ]

    operations = [
        # Step 1 — add new fields (both default False)
        migrations.AddField(
            model_name="user",
            name="is_email_verified",
            field=models.BooleanField(
                default=False,
                help_text="Designates whether this user has verified their email address.",
                verbose_name="email verified",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="is_phone_verified",
            field=models.BooleanField(
                default=False,
                help_text="Designates whether this user has verified their phone number via Firebase.",
                verbose_name="phone verified",
            ),
        ),
        # Step 2 — copy old is_verified → is_email_verified before dropping
        migrations.RunPython(
            copy_is_verified_to_email,
            reverse_code=migrations.RunPython.noop,
        ),
        # Step 3 — drop the old column
        migrations.RemoveField(
            model_name="user",
            name="is_verified",
        ),
    ]

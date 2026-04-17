from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0001_initial"),
    ]

    operations = [
        # StripePlan: stripe_price_id → nullable (free plans have no Stripe price)
        migrations.AlterField(
            model_name="stripeplan",
            name="stripe_price_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Leave blank for free plans.",
                max_length=255,
                null=True,
                unique=True,
            ),
        ),
        # StripePlan: amount → default 0
        migrations.AlterField(
            model_name="stripeplan",
            name="amount",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="Price in smallest currency units (e.g. cents). 0 for free plans.",
                max_digits=10,
            ),
        ),
        # StripePlan: add is_free flag
        migrations.AddField(
            model_name="stripeplan",
            name="is_free",
            field=models.BooleanField(
                default=False,
                help_text="Free plans bypass Stripe checkout entirely.",
            ),
        ),
        # StripeSubscription: stripe_subscription_id → nullable (free plans)
        migrations.AlterField(
            model_name="stripesubscription",
            name="stripe_subscription_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=255,
                null=True,
                unique=True,
            ),
        ),
        # StripeSubscription: stripe_customer_id → nullable (free plans)
        migrations.AlterField(
            model_name="stripesubscription",
            name="stripe_customer_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=255,
                null=True,
            ),
        ),
    ]

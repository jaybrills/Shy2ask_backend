import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StripePlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("stripe_price_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("stripe_product_id", models.CharField(blank=True, max_length=255)),
                ("amount", models.DecimalField(decimal_places=2, help_text="Price in smallest currency units (e.g. cents)", max_digits=10)),
                ("currency", models.CharField(default="chf", max_length=10)),
                (
                    "interval",
                    models.CharField(
                        choices=[("month", "Monthly"), ("year", "Yearly")],
                        default="month",
                        max_length=10,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"verbose_name": "Stripe Plan", "verbose_name_plural": "Stripe Plans", "ordering": ["amount"]},
        ),
        migrations.CreateModel(
            name="StripeCustomer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stripe_customer_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stripe_customer",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"verbose_name": "Stripe Customer", "verbose_name_plural": "Stripe Customers"},
        ),
        migrations.CreateModel(
            name="StripeSubscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stripe_subscription_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("stripe_customer_id", models.CharField(db_index=True, max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("canceled", "Canceled"),
                            ("incomplete", "Incomplete"),
                            ("incomplete_expired", "Incomplete Expired"),
                            ("past_due", "Past Due"),
                            ("paused", "Paused"),
                            ("trialing", "Trialing"),
                            ("unpaid", "Unpaid"),
                        ],
                        default="incomplete",
                        max_length=30,
                    ),
                ),
                ("current_period_start", models.DateTimeField(blank=True, null=True)),
                ("current_period_end", models.DateTimeField(blank=True, null=True)),
                ("cancel_at_period_end", models.BooleanField(default=False)),
                ("canceled_at", models.DateTimeField(blank=True, null=True)),
                ("trial_end", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "plan",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="subscriptions",
                        to="billing.stripeplan",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stripe_subscriptions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"verbose_name": "Stripe Subscription", "verbose_name_plural": "Stripe Subscriptions", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="StripeEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stripe_event_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("event_type", models.CharField(max_length=255)),
                ("payload", models.JSONField()),
                ("processed_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("processing_error", models.TextField(blank=True)),
            ],
            options={"verbose_name": "Stripe Webhook Event", "verbose_name_plural": "Stripe Webhook Events", "ordering": ["-processed_at"]},
        ),
    ]

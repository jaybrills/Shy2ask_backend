"""
Management command: test_push

Test push notifications without needing a real FCM token or a mobile device.

Usage examples
--------------
# List all available notification types
python manage.py test_push --list

# Dry-run: print what WOULD be sent to a user (no actual delivery)
python manage.py test_push --user-id=1 --type=request_completed --dry-run

# Actually deliver via Celery task (requires Redis + FCM credentials)
python manage.py test_push --user-id=1 --type=request_completed

# Send to a user by email instead of ID
python manage.py test_push --email=user@example.com --type=payment_failed

# Send ALL 18 notifications to a user as a dry-run checklist
python manage.py test_push --user-id=1 --all --dry-run
"""
import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from account.push_notifications import REGISTRY, Priority

User = get_user_model()


class Command(BaseCommand):
    help = "Test push notifications — works without FCM credentials using --dry-run."

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true", help="Print all available notification types and exit.")
        parser.add_argument("--type", type=str, help="Notification key to send (see --list).")
        parser.add_argument("--all", action="store_true", dest="send_all", help="Send every notification type (use with --dry-run).")
        parser.add_argument("--user-id", type=int, dest="user_id", help="Target user primary key.")
        parser.add_argument("--email", type=str, help="Target user email (alternative to --user-id).")
        parser.add_argument("--dry-run", action="store_true", help="Print payload only — no Celery task enqueued, no FCM call made.")

    def handle(self, *args, **options):
        if options["list"]:
            self._print_list()
            return

        user = self._resolve_user(options)

        if options["send_all"]:
            self._send_all(user, dry_run=options["dry_run"])
        else:
            key = options.get("type")
            if not key:
                raise CommandError("Provide --type=<key> or --all. Use --list to see available keys.")
            self._send_one(user, key, dry_run=options["dry_run"])

    # ── helpers ────────────────────────────────────────────────────────────────

    def _print_list(self):
        self.stdout.write("\nAvailable push notification types:\n")
        self.stdout.write(f"  {'KEY':<30} {'PRIORITY':<10} TITLE\n")
        self.stdout.write("  " + "-" * 70 + "\n")
        for key, tpl in sorted(REGISTRY.items()):
            colour = self.style.ERROR if tpl.priority == Priority.HIGH else self.style.WARNING
            self.stdout.write(f"  {colour(key):<30} {tpl.priority.value:<10} {tpl.title}")
        self.stdout.write(f"\nTotal: {len(REGISTRY)} notifications\n")

    def _resolve_user(self, options):
        user_id = options.get("user_id")
        email = options.get("email")
        if not user_id and not email:
            raise CommandError("Provide --user-id or --email to specify the target user.")
        try:
            if user_id:
                return User.objects.get(pk=user_id)
            return User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise CommandError(f"User not found (user_id={user_id}, email={email}).")

    def _send_one(self, user, key: str, *, dry_run: bool):
        tpl = REGISTRY.get(key)
        if not tpl:
            raise CommandError(
                f"Unknown notification type '{key}'. Run --list to see valid keys."
            )

        # Fill sample placeholder values so the render doesn't error
        sample_kwargs = {
            "tracking_code": "TRK-TEST01",
            "days": "3",
            "amount": "9.90",
            "ticket_code": "TKT-0001",
        }
        title, body = tpl.render(**sample_kwargs)
        data = {
            "type": tpl.key,
            "priority": tpl.priority.value,
            "test": "true",
        }

        if dry_run:
            self._print_dry_run(user, title, body, data, tpl)
            return

        # Check device registration
        from account.models import UserDevice
        devices = list(UserDevice.objects.active_for_user(user))
        if not devices:
            self.stdout.write(self.style.WARNING(
                f"\n[!] User {user.email} has no registered devices.\n"
                "    Register a device first via POST /api/profile/devices/register\n"
                "    or use --dry-run to test without a device.\n"
            ))
            return

        from account.tasks import send_push_notification_task
        send_push_notification_task.delay(
            user_id=user.id,
            title=title,
            body=body,
            data=data,
        )
        self.stdout.write(self.style.SUCCESS(
            f"\n[✓] Task enqueued for user '{user.email}' ({len(devices)} device(s))\n"
            f"    Type    : {tpl.key}\n"
            f"    Title   : {title}\n"
            f"    Body    : {body}\n"
            f"    Priority: {tpl.priority.value}\n"
        ))

    def _send_all(self, user, *, dry_run: bool):
        self.stdout.write(f"\nSending all {len(REGISTRY)} notification types to {user.email}...\n")
        for key in sorted(REGISTRY):
            self._send_one(user, key, dry_run=dry_run)

    def _print_dry_run(self, user, title, body, data, tpl):
        colour = self.style.ERROR if tpl.priority == Priority.HIGH else self.style.WARNING
        self.stdout.write(colour(
            f"\n[DRY-RUN] {tpl.key}  (priority={tpl.priority.value})\n"
        ))
        payload = {
            "user_id": user.id,
            "user_email": user.email,
            "title": title,
            "body": body,
            "data": data,
        }
        self.stdout.write(json.dumps(payload, indent=2))
        self.stdout.write("")

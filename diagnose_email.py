#!/usr/bin/env python3
"""
diagnose_email.py  –  Shy2Ask server email + Redis diagnostics
Run: python diagnose_email.py [your-test-email@example.com]
"""
import os
import sys
import socket
import smtplib
import ssl

# ── 0. Load .env ──────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("[.env]  Loaded .env via python-dotenv")
except ImportError:
    print("[.env]  python-dotenv not installed – reading os.environ only")

TEST_RECIPIENT = sys.argv[1] if len(sys.argv) > 1 else os.getenv("ADMIN_NOTIFY_EMAIL", "")

EMAIL_HOST     = os.getenv("EMAIL_HOST",     "smtp.office365.com")
EMAIL_PORT     = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER     = os.getenv("EMAIL_HOST_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
FROM_EMAIL     = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_USER)
USE_TLS        = os.getenv("EMAIL_USE_TLS", "True").lower() in ("1", "true", "yes")

print("\n" + "="*60)
print("  SHY2ASK  –  Email & Redis Diagnostics")
print("="*60)

# ── 1. Config snapshot ────────────────────────────────────────────────────────
print("\n[1] Email config from environment:")
print(f"    EMAIL_HOST        = {EMAIL_HOST}")
print(f"    EMAIL_PORT        = {EMAIL_PORT}")
print(f"    EMAIL_HOST_USER   = {EMAIL_USER}")
print(f"    EMAIL_PASSWORD    = {'<set>' if EMAIL_PASSWORD else '<NOT SET ❌>'}")
print(f"    DEFAULT_FROM      = {FROM_EMAIL}")
print(f"    USE_TLS           = {USE_TLS}")
print(f"    TEST_RECIPIENT    = {TEST_RECIPIENT or '<none – pass as arg>'}")

# ── 2. DNS resolution ─────────────────────────────────────────────────────────
print(f"\n[2] DNS lookup for {EMAIL_HOST} …")
try:
    ip = socket.gethostbyname(EMAIL_HOST)
    print(f"    ✅  Resolved to {ip}")
except Exception as e:
    print(f"    ❌  DNS FAILED: {e}")
    print("       → The server cannot reach the internet / SMTP host.")

# ── 3. TCP connection ─────────────────────────────────────────────────────────
print(f"\n[3] TCP connect {EMAIL_HOST}:{EMAIL_PORT} …")
try:
    s = socket.create_connection((EMAIL_HOST, EMAIL_PORT), timeout=10)
    s.close()
    print(f"    ✅  TCP connection OK")
except Exception as e:
    print(f"    ❌  TCP FAILED: {e}")
    print("       → Port 587 may be blocked by Azure firewall / NSG outbound rules.")

# ── 4. SMTP EHLO + STARTTLS + Auth ────────────────────────────────────────────
print(f"\n[4] SMTP handshake (EHLO + STARTTLS + AUTH) …")
if not EMAIL_USER or not EMAIL_PASSWORD:
    print("    ⚠️  EMAIL_HOST_USER or EMAIL_HOST_PASSWORD not set – skipping SMTP auth test")
else:
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=15) as smtp:
            smtp.ehlo()
            if USE_TLS:
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(EMAIL_USER, EMAIL_PASSWORD)
            print(f"    ✅  SMTP login successful as {EMAIL_USER}")

            # ── 5. Send test email ────────────────────────────────────────────
            if TEST_RECIPIENT:
                print(f"\n[5] Sending test email to {TEST_RECIPIENT} …")
                msg = (
                    f"From: {FROM_EMAIL}\r\n"
                    f"To: {TEST_RECIPIENT}\r\n"
                    f"Subject: [Shy2Ask] Server email test\r\n\r\n"
                    f"This is a test email sent from the server diagnose_email.py script.\n"
                    f"If you see this, SMTP is working correctly on the server.\n"
                )
                smtp.sendmail(FROM_EMAIL, [TEST_RECIPIENT], msg)
                print(f"    ✅  Email sent! Check {TEST_RECIPIENT} inbox.")
            else:
                print("\n[5] Skipping send test – no recipient provided. Pass email as arg:")
                print("    python diagnose_email.py your@email.com")
    except smtplib.SMTPAuthenticationError as e:
        print(f"    ❌  AUTH FAILED: {e}")
        print("       → Wrong username/password, or Office365 requires App Password / modern auth.")
        print("       → Check: https://aka.ms/smtp-client-auth-disabled")
    except smtplib.SMTPException as e:
        print(f"    ❌  SMTP ERROR: {e}")
    except Exception as e:
        print(f"    ❌  UNEXPECTED ERROR: {e}")

# ── 6. Django send_mail via settings ─────────────────────────────────────────
print("\n[6] Django send_mail test …")
try:
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shy2ask.settings")
    django.setup()
    from django.core.mail import send_mail as django_send_mail
    from django.conf import settings as djsettings

    print(f"    EMAIL_BACKEND = {djsettings.EMAIL_BACKEND}")

    if TEST_RECIPIENT and djsettings.EMAIL_BACKEND != "django.core.mail.backends.console.EmailBackend":
        django_send_mail(
            subject="[Shy2Ask] Django send_mail test",
            message="Django send_mail is working correctly on the server.",
            from_email=djsettings.DEFAULT_FROM_EMAIL,
            recipient_list=[TEST_RECIPIENT],
            fail_silently=False,
        )
        print(f"    ✅  Django send_mail succeeded → {TEST_RECIPIENT}")
    elif djsettings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend":
        print("    ⚠️  EMAIL_BACKEND is console – emails would only print, not be sent!")
        print("       → Set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend in .env")
    else:
        print("    ℹ️  No recipient – skipped Django send_mail test")
except Exception as e:
    print(f"    ❌  Django setup/send_mail ERROR: {e}")

# ── 7. Redis connectivity ─────────────────────────────────────────────────────
print("\n[7] Redis connectivity …")
try:
    import redis
    r = redis.Redis(host="127.0.0.1", port=6379, db=0, socket_connect_timeout=3)
    r.ping()
    info = r.info("server")
    print(f"    ✅  Redis is running – version {info.get('redis_version', '?')}")
except ImportError:
    print("    ⚠️  redis-py not installed (pip install redis)")
except Exception as e:
    print(f"    ❌  Redis FAILED: {e}")
    print("       → Redis may not be running. Start with: sudo systemctl start redis")

# ── 8. Celery check ───────────────────────────────────────────────────────────
print("\n[8] Celery in project …")
try:
    import celery
    print(f"    ℹ️  celery installed (version {celery.__version__})")
    try:
        from shy2ask.celery import app
        print(f"    ✅  Celery app loaded: {app}")
    except ImportError:
        print("    ⚠️  No shy2ask/celery.py found – project does NOT use Celery")
        print("       → Emails are sent synchronously (blocking the request thread)")
except ImportError:
    print("    ℹ️  Celery not installed – project sends emails synchronously")

print("\n" + "="*60)
print("  Diagnostics complete")
print("="*60 + "\n")

"""
AI-based services: notification enhancement, deal detection, subscription digests.
Uses OpenAI when OPENAI_API_KEY is set; otherwise falls back to plain text.
"""
import json
import logging
import re
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)


def ai_notification_enhance(subject: str, body: str, context: Optional[dict] = None) -> tuple[str, str]:
    """
    Use OpenAI to make notification subject/body short, friendly, and engaging.
    Returns (enhanced_subject, enhanced_body). On error or no key, returns (subject, body).
    """
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key or not subject and not body:
        return subject, body
    context = context or {}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        prompt = (
            "Rewrite this notification to be short, friendly, and engaging (max 1 line subject, 2-3 lines body). "
            "Keep the same meaning. No greetings/signoffs. "
            "Context: " + json.dumps(context)[:200] + "\n\n"
            f"Subject: {subject}\nBody: {body}\n\n"
            "Reply ONLY with JSON: {\"subject\": \"...\", \"body\": \"...\"}"
        )
        r = client.chat.completions.create(
            model=getattr(settings, "OPENAI_NOTIFICATION_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
        )
        raw = (r.choices[0].message.content or "").strip()
        start = raw.find("{")
        if start == -1:
            return subject, body
        depth, end = 0, start
        for i, c in enumerate(raw[start:], start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        data = json.loads(raw[start : end + 1])
        return (
            (data.get("subject") or subject)[:200],
            (data.get("body") or body)[:2000],
        )
    except Exception as e:
        logger.warning("ai_notification_enhance failed: %s", e)
        return subject, body


def ai_deal_detect(conversation_text: str) -> Optional[dict]:
    """
    Use OpenAI to detect if conversation mentions a deal/agreement with amount or price.
    Returns None or {"detected": True, "amount": float, "currency": str, "summary": str, "payer": "requester"|"recipient"|"split"}.
    """
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key or not (conversation_text or "").strip():
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        prompt = (
            "Does this conversation mention a deal, agreement, or payment with a specific amount or price? "
            "Reply ONLY with JSON. If no deal/amount: {\"detected\": false}. "
            "If yes: {\"detected\": true, \"amount\": number, \"currency\": \"CHF\" or \"INR\" or \"USD\", "
            "\"summary\": \"one line\", \"payer\": \"requester\" or \"recipient\" or \"split\"}. "
            "Extract amount as number (e.g. 50 or 100.50).\n\nConversation:\n" + (conversation_text or "")[:6000]
        )
        r = client.chat.completions.create(
            model=getattr(settings, "OPENAI_DEAL_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
        )
        raw = (r.choices[0].message.content or "").strip()
        start = raw.find("{")
        if start == -1:
            return None
        depth, end = 0, start
        for i, c in enumerate(raw[start:], start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        data = json.loads(raw[start : end + 1])
        if not data.get("detected"):
            return None
        amount = data.get("amount")
        if amount is None:
            return None
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return None
        if amount <= 0:
            return None
        currency = (data.get("currency") or "CHF").upper()[:8]
        payer = (data.get("payer") or "requester").lower()
        if payer not in ("requester", "recipient", "split"):
            payer = "requester"
        return {
            "detected": True,
            "amount": amount,
            "currency": currency,
            "summary": (data.get("summary") or "Deal detected")[:500],
            "payer": payer,
        }
    except Exception as e:
        logger.warning("ai_deal_detect failed: %s", e)
        return None


def run_deal_detection_and_notify(request_id: int):
    """
    Load conversation messages for request, run AI deal detection; if detected create/update Deal
    and send engaging notification to deal_alerts subscribers. Call from consumer after new message.
    """
    from django.db import transaction
    from .models import Conversation, Deal, ShyRequest

    try:
        request = ShyRequest.objects.get(pk=request_id)
        conv, _ = Conversation.objects.get_or_create(request=request)
    except ShyRequest.DoesNotExist:
        return
    text = " ".join(
        (m.clean_body or m.body) for m in conv.messages.order_by("created_at")
    ).strip()
    if not text:
        return
    result = ai_deal_detect(text)
    if not result or not result.get("detected"):
        return
    from decimal import Decimal
    amount = Decimal(str(result["amount"]))
    currency = (result.get("currency") or "CHF")[:8]
    payer = result.get("payer") or "requester"
    summary = (result.get("summary") or "Deal detected")[:500]
    with transaction.atomic():
        deal, created = Deal.objects.get_or_create(
            request=request,
            defaults={
                "amount": amount,
                "currency": currency,
                "payer": deal_payer(payer),
                "status": Deal.Status.PROPOSED,
                "ai_detected": True,
                "ai_summary": summary,
            },
        )
        if not created and not getattr(deal, "ai_detected", False):
            deal.ai_detected = True
            deal.ai_summary = summary
            deal.amount = amount
            deal.currency = currency
            deal.payer = deal_payer(payer)
            deal.save(update_fields=["ai_detected", "ai_summary", "amount", "currency", "payer", "updated_at"])
    from django.utils import timezone
    subject = "Deal detected"
    body = f"Request {request.tracking_code}: {summary} — {amount} {currency}"
    from .views import send_notification, _notify_subscribers
    if request.user_id:
        send_notification(subject, body, request.user.email, request, use_ai_enhance=True)
    now = timezone.now()
    _notify_subscribers(request, {
        "id": f"deal-{deal.id}",
        "type": "deal_alert",
        "subject": subject,
        "body": body,
        "created_at": now.isoformat(),
        "created_at_display": now.strftime("%b %d, %H:%M"),
        "request_id": request.id,
        "tracking_code": request.tracking_code,
        "deal_id": deal.id,
        "amount": str(amount),
        "currency": currency,
        "summary": summary,
    }, subscription_type="deal_alerts", exclude_user_id=request.user_id)
    return deal


def deal_payer(payer: str) -> str:
    from .models import Deal
    if payer == "recipient":
        return Deal.Payer.RECIPIENT
    if payer == "split":
        return Deal.Payer.SPLIT
    return Deal.Payer.REQUESTER

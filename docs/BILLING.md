# Billing App — Complete Reference

## Table of Contents

1. [Overview](#1-overview)
2. [Setup](#2-setup)
3. [Data Models](#3-data-models)
4. [API Endpoints](#4-api-endpoints)
5. [User Flows](#5-user-flows)
   - [Flow A — New user signs up (Free Plan)](#flow-a--new-user-signs-up-free-plan)
   - [Flow B — User upgrades to a Paid Plan](#flow-b--user-upgrades-to-a-paid-plan)
   - [Flow C — User cancels their paid subscription](#flow-c--user-cancels-their-paid-subscription)
   - [Flow D — Subscription renews automatically](#flow-d--subscription-renews-automatically)
   - [Flow E — Payment fails](#flow-e--payment-fails)
   - [Flow F — User manages billing via portal](#flow-f--user-manages-billing-via-portal)
6. [Webhook Reference](#6-webhook-reference)
7. [Checking Subscription in Your Code](#7-checking-subscription-in-your-code)
8. [Admin Panel](#8-admin-panel)

---

## 1. Overview

The `billing` app lives at `billing/` and handles everything subscription-related:

- **Free plans** — assigned locally, no Stripe involvement at all
- **Paid plans** — go through Stripe Checkout; all lifecycle changes (renewals, cancellations, failures) arrive via webhooks and are synced to the local database
- **Customer portal** — lets users manage their own subscription (cancel, change card, download invoices) without you writing any UI

**Key principle:** Your database is always the source of truth. The webhook handler keeps it in sync with Stripe automatically. Your application code only ever needs to query the local `StripeSubscription` table — it never calls Stripe at runtime to check access.

```
User ──► Your Frontend ──► /api/billing/* ──► Stripe API
                                    ▲
                                    │ webhooks
                               Stripe ──► /api/billing/webhook/
```

---

## 2. Setup

### Step 1 — Install the Stripe SDK

```bash
pip install -r requirements.txt   # stripe==12.0.0 is already listed
```

### Step 2 — Add keys to `.env`

```ini
STRIPE_PUBLISHABLE_KEY=pk_test_...          # your frontend uses this
STRIPE_SECRET_KEY=sk_test_...               # backend uses this to call Stripe API
STRIPE_WEBHOOK_SECRET=whsec_...             # validates incoming webhook signatures
STRIPE_DEFAULT_PRICE_ID=price_...          # optional — used when no price_id sent to checkout
```

Get keys from: **Stripe Dashboard → Developers → API Keys**

### Step 3 — Migrate the database

```bash
python manage.py migrate billing
```

This creates four tables: `billing_stripeplan`, `billing_stripecustomer`, `billing_stripesubscription`, `billing_stripeevent`.

### Step 4 — Seed your plans in the admin

Go to **Admin → Billing → Stripe Plans → Add Plan**.

**For a free plan:**
| Field | Value |
|---|---|
| Name | Free |
| Stripe Price ID | *(leave blank)* |
| Amount | `0` |
| Currency | `chf` |
| Interval | `month` |
| Is Free | ✓ checked |
| Is Active | ✓ checked |

**For a paid plan:**
| Field | Value |
|---|---|
| Name | Pro Monthly |
| Stripe Price ID | `price_1RaBC...` ← from Stripe Dashboard → Products |
| Amount | `1990` ← CHF 19.90 in cents |
| Currency | `chf` |
| Interval | `month` |
| Is Free | ☐ unchecked |
| Is Active | ✓ checked |

### Step 5 — Register the webhook in Stripe

1. **Stripe Dashboard → Developers → Webhooks → Add endpoint**
2. Set URL: `https://yourdomain.com/api/billing/webhook/`
3. Select these events:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
4. Copy the **Signing secret** → paste into `STRIPE_WEBHOOK_SECRET` in your `.env`

**For local development**, use the Stripe CLI:
```bash
stripe login
stripe listen --forward-to localhost:8000/api/billing/webhook/
# Copy the printed "whsec_..." secret into STRIPE_WEBHOOK_SECRET
```

---

## 3. Data Models

### `StripePlan`

Represents a subscription plan. You create these in the admin — they mirror your Stripe Products/Prices.

| Field | Type | Description |
|---|---|---|
| `id` | int | Django PK |
| `name` | string | Display name (e.g. "Free", "Pro Monthly") |
| `stripe_price_id` | string \| null | Stripe Price ID. **Null for free plans** |
| `stripe_product_id` | string | Stripe Product ID (optional, for reference) |
| `amount` | decimal | Price in smallest currency unit (cents). `0` for free |
| `currency` | string | e.g. `"chf"`, `"usd"`, `"eur"` |
| `interval` | string | `"month"` or `"year"` |
| `is_free` | bool | `true` = free plan, bypasses Stripe entirely |
| `is_active` | bool | Only active plans appear in the plans list |

---

### `StripeCustomer`

Links a Django user to their Stripe Customer object. Created automatically the first time a user hits any paid Stripe endpoint. One-to-one with the user.

| Field | Type | Description |
|---|---|---|
| `user` | FK(User) | The Django user |
| `stripe_customer_id` | string | Stripe's `cus_...` ID |

> Free-plan users never get a `StripeCustomer` record — it's only created when they start a Stripe checkout.

---

### `StripeSubscription`

The central table. Every user's plan is tracked here — free or paid.

| Field | Type | Description |
|---|---|---|
| `id` | int | Django PK |
| `user` | FK(User) | The subscriber |
| `plan` | FK(StripePlan) | Which plan they're on |
| `stripe_subscription_id` | string \| **null** | Stripe's `sub_...` ID. **Null for free plans** |
| `stripe_customer_id` | string \| **null** | Stripe's `cus_...` ID. **Null for free plans** |
| `status` | string | See status values below |
| `current_period_start` | datetime \| null | When the current billing period started |
| `current_period_end` | datetime \| null | When the current billing period ends |
| `cancel_at_period_end` | bool | User cancelled but still has access until period ends |
| `canceled_at` | datetime \| null | When it was cancelled |
| `trial_end` | datetime \| null | When the trial ends (if on a trial) |
| `is_active` | bool (computed) | `true` if status is `active` or `trialing` |
| `is_past_due` | bool (computed) | `true` if status is `past_due` |

**Status values:**

| Status | Meaning |
|---|---|
| `active` | Paid and in good standing (or free plan enrolled) |
| `trialing` | In a free trial period |
| `past_due` | Payment failed, Stripe is retrying |
| `unpaid` | All retries exhausted, subscription not canceled yet |
| `incomplete` | Initial payment not yet confirmed |
| `incomplete_expired` | Initial payment window expired |
| `paused` | Paused via Stripe (rare) |
| `canceled` | Subscription ended |

---

### `StripeEvent`

Idempotency log — every webhook event received from Stripe is stored here. If Stripe retries delivery, the second call is a no-op.

| Field | Type | Description |
|---|---|---|
| `stripe_event_id` | string | Stripe's `evt_...` ID (unique) |
| `event_type` | string | e.g. `"checkout.session.completed"` |
| `payload` | JSON | Full raw event from Stripe |
| `processing_error` | string | Empty if handled successfully |

---

## 4. API Endpoints

All endpoints live under `/api/billing/`. Trailing slash is optional on all routes.

---

### `GET /api/billing/plans/`

Returns all active plans. Use this to build your pricing page.

**Authentication:** None required (public).

**Request:** No body.

**Response `200`:**
```json
[
  {
    "id": 1,
    "name": "Free",
    "stripe_price_id": null,
    "amount": "0.00",
    "currency": "chf",
    "interval": "month",
    "is_free": true,
    "is_active": true
  },
  {
    "id": 2,
    "name": "Pro Monthly",
    "stripe_price_id": "price_1RaBC...",
    "amount": "1990.00",
    "currency": "chf",
    "interval": "month",
    "is_free": false,
    "is_active": true
  }
]
```

---

### `POST /api/billing/free/`

Enrolls the authenticated user in a free plan. **No Stripe API call is made.** The subscription is stored locally only.

**Authentication:** `Authorization: Bearer <token>` required.

**Request body:**
```json
{}
```
Or optionally pass a specific plan ID if you have multiple free tiers:
```json
{ "plan_id": 1 }
```
If `plan_id` is omitted, the first active free plan found is used automatically.

**Response `201`** — newly enrolled:
```json
{
  "id": 5,
  "stripe_subscription_id": null,
  "status": "active",
  "plan": {
    "id": 1,
    "name": "Free",
    "stripe_price_id": null,
    "amount": "0.00",
    "currency": "chf",
    "interval": "month",
    "is_free": true,
    "is_active": true
  },
  "current_period_start": null,
  "current_period_end": null,
  "cancel_at_period_end": false,
  "canceled_at": null,
  "trial_end": null,
  "is_active": true,
  "is_past_due": false,
  "created_at": "2026-04-16T09:00:00Z",
  "updated_at": "2026-04-16T09:00:00Z"
}
```

**Response `200`** — already enrolled (returns the existing record, nothing changes).

**Error `404`:**
```json
{ "detail": "No active free plan found. Ask an admin to create one." }
```
The admin hasn't seeded a free plan yet.

**Error `400`:**
```json
{ "detail": "You already have an active paid subscription. Use the billing portal to change your plan." }
```
User is already on a paid plan — direct them to `/api/billing/portal/` to downgrade.

---

### `POST /api/billing/checkout/`

Creates a Stripe Checkout Session for a **paid** subscription. Your frontend receives a URL and redirects the user's browser there. Stripe hosts the entire payment page — you don't handle card details.

**Authentication:** `Authorization: Bearer <token>` required.

**Request body:**
```json
{
  "price_id": "price_1RaBC...",
  "success_url": "https://yourapp.com/billing/success?session_id={CHECKOUT_SESSION_ID}",
  "cancel_url": "https://yourapp.com/pricing"
}
```

| Field | Required | Description |
|---|---|---|
| `price_id` | No | Stripe Price ID for the plan. Can be omitted if `STRIPE_DEFAULT_PRICE_ID` is set in `.env` |
| `success_url` | Yes | Where Stripe redirects after successful payment. `{CHECKOUT_SESSION_ID}` is a literal placeholder Stripe fills in |
| `cancel_url` | Yes | Where Stripe redirects if the user clicks "Back" |

**Response `200`:**
```json
{
  "session_id": "cs_test_...",
  "url": "https://checkout.stripe.com/pay/cs_test_..."
}
```

Redirect the user to `url`. Do not store `session_id` — the webhook handles everything after that.

**Error `400` — no price:**
```json
{ "detail": "No price_id provided and STRIPE_DEFAULT_PRICE_ID not configured." }
```

**Error `400` — free plan passed by mistake:**
```json
{ "detail": "This is a free plan. Use POST /api/billing/free/ to enroll." }
```

**Error `502`:** Stripe API is unreachable or returned an error.

> **What happens next:** After the user pays, Stripe fires `checkout.session.completed` to `/api/billing/webhook/`. The webhook creates the `StripeSubscription` row automatically. Your `success_url` page should call `GET /api/billing/subscription/` to confirm the subscription is active.

---

### `GET /api/billing/subscription/`

Returns the user's most recent subscription (free or paid).

**Authentication:** `Authorization: Bearer <token>` required.

**Request:** No body.

**Response `200`:**
```json
{
  "id": 12,
  "stripe_subscription_id": "sub_1RxYZ...",
  "status": "active",
  "plan": {
    "id": 2,
    "name": "Pro Monthly",
    "stripe_price_id": "price_1RaBC...",
    "amount": "1990.00",
    "currency": "chf",
    "interval": "month",
    "is_free": false,
    "is_active": true
  },
  "current_period_start": "2026-04-01T00:00:00Z",
  "current_period_end": "2026-05-01T00:00:00Z",
  "cancel_at_period_end": false,
  "canceled_at": null,
  "trial_end": null,
  "is_active": true,
  "is_past_due": false,
  "created_at": "2026-04-01T10:30:00Z",
  "updated_at": "2026-04-01T10:30:00Z"
}
```

**Response `404`:**
```json
{ "detail": "No subscription found." }
```
The user has never enrolled in any plan. You should redirect them to your pricing page.

> **Note:** This returns the single most recent record by `created_at`. A user who upgraded from free → paid will have two rows; this always returns the latest (paid) one.

---

### `POST /api/billing/portal/`

Creates a Stripe Billing Portal session. Redirect the user to the returned URL. From there Stripe lets them:

- Cancel their subscription
- Update their credit card
- Switch to a different plan
- Download past invoices

When they're done, Stripe redirects them back to your `return_url`.

**Authentication:** `Authorization: Bearer <token>` required.

**Request body:**
```json
{
  "return_url": "https://yourapp.com/account"
}
```

**Response `200`:**
```json
{
  "url": "https://billing.stripe.com/session/..."
}
```

Redirect the user's browser to this URL.

**Error `502`:** Stripe API unreachable.

> **Important:** This creates a Stripe Customer for the user if one doesn't exist yet (so the portal has something to show), but this is harmless — the portal will just show an empty state if they have no paid history.

---

### `POST /api/billing/webhook/`

**This endpoint is called by Stripe — not your frontend. Do not call it yourself.**

- No `Authorization` header.
- Stripe sends a `Stripe-Signature` header which the code verifies against `STRIPE_WEBHOOK_SECRET`.
- Always returns `200` to Stripe (even on processing errors) so Stripe doesn't retry indefinitely.
- Stores every event in `StripeEvent` for auditing and idempotency.

---

## 5. User Flows

### Flow A — New user signs up (Free Plan)

```
1. User registers → POST /api/auth/register → verifies email → POST /api/auth/login → gets Bearer token

2. Frontend calls:
   POST /api/billing/free/
   Authorization: Bearer <token>
   Body: {}

3. Server creates a StripeSubscription row locally:
   status = "active", stripe_subscription_id = null, plan = Free plan

4. Response 201 — user is on the free plan immediately.

5. Frontend shows the free tier features.
```

No Stripe interaction. No card required.

---

### Flow B — User upgrades to a Paid Plan

```
1. User is logged in (has Bearer token).

2. Frontend loads the pricing page:
   GET /api/billing/plans/
   → display plans where is_free = false

3. User clicks "Upgrade to Pro" — frontend calls:
   POST /api/billing/checkout/
   Authorization: Bearer <token>
   Body: {
     "price_id": "price_1RaBC...",
     "success_url": "https://yourapp.com/billing/success?session_id={CHECKOUT_SESSION_ID}",
     "cancel_url": "https://yourapp.com/pricing"
   }

4. Server:
   a. Creates a Stripe Customer for the user if one doesn't exist (cus_...)
   b. Creates a Stripe Checkout Session
   c. Returns { "session_id": "cs_test_...", "url": "https://checkout.stripe.com/pay/..." }

5. Frontend redirects user's browser to the url.

6. User completes payment on Stripe's hosted page.

7. Stripe fires webhook: checkout.session.completed
   → /api/billing/webhook/ receives it
   → verifies signature
   → fetches full subscription from Stripe API
   → creates StripeSubscription row: status = "active"
   → stores event in StripeEvent

8. Stripe redirects user to success_url.

9. Frontend calls (on the success page):
   GET /api/billing/subscription/
   Authorization: Bearer <token>
   → returns { status: "active", plan: { name: "Pro Monthly" }, is_active: true }

10. User now has full access.
```

---

### Flow C — User cancels their paid subscription

```
1. User clicks "Cancel subscription" — frontend calls:
   POST /api/billing/portal/
   Authorization: Bearer <token>
   Body: { "return_url": "https://yourapp.com/account" }

2. Server creates a Stripe Billing Portal session.
   Returns: { "url": "https://billing.stripe.com/session/..." }

3. Frontend redirects user to that url.

4. User clicks "Cancel plan" inside the Stripe portal → confirms.

5. Stripe fires webhook: customer.subscription.updated
   → cancel_at_period_end = true, status still "active"
   → webhook syncs StripeSubscription: cancel_at_period_end = true

6. User is redirected back to return_url.

7. Frontend calls:
   GET /api/billing/subscription/
   → { status: "active", cancel_at_period_end: true, current_period_end: "2026-05-01T..." }
   → Show: "Your plan ends on May 1st"

8. When the billing period ends, Stripe fires: customer.subscription.deleted
   → webhook syncs StripeSubscription: status = "canceled"
   → is_active becomes false → user loses paid access
```

---

### Flow D — Subscription renews automatically

Nothing you need to do. This happens in the background:

```
1. On the renewal date, Stripe charges the card.

2. Stripe fires: invoice.payment_succeeded
   → webhook fetches the subscription from Stripe
   → updates StripeSubscription: new current_period_start and current_period_end
   → status stays "active"

3. User continues to have access uninterrupted.
```

---

### Flow E — Payment fails

```
1. Stripe attempts to charge the card on renewal — card is declined.

2. Stripe fires: invoice.payment_failed
   → webhook syncs StripeSubscription: status = "past_due"
   → is_past_due = true

3. Your code can check is_past_due and show a banner:
   "Your payment failed. Please update your card."
   Direct them to POST /api/billing/portal/ to update their card.

4. Stripe automatically retries (based on your Stripe retry settings).

5a. If retry succeeds:
    → invoice.payment_succeeded fires
    → status back to "active"

5b. If all retries fail:
    → status → "unpaid" or Stripe cancels the subscription
    → customer.subscription.deleted fires
    → status → "canceled", is_active = false
    → User loses access
```

---

### Flow F — User manages billing via portal

Any time a user wants to:
- Change their credit card
- Download an invoice
- Switch plans (if configured in Stripe)

```
1. Frontend calls:
   POST /api/billing/portal/
   Authorization: Bearer <token>
   Body: { "return_url": "https://yourapp.com/account" }

2. Returns: { "url": "..." }

3. Redirect user there. Stripe handles everything.

4. Any changes they make (plan change, card update) trigger webhooks automatically:
   customer.subscription.updated → synced to your DB
```

---

## 6. Webhook Reference

Webhook endpoint: `POST /api/billing/webhook/`

The endpoint verifies the `Stripe-Signature` header on every request. Requests without a valid signature return `400`. All valid events are stored in `StripeEvent` — even ones with processing errors.

| Event | What triggers it | What the handler does |
|---|---|---|
| `checkout.session.completed` | User completes checkout payment | Fetches full subscription from Stripe, creates `StripeCustomer` if needed, creates/updates `StripeSubscription` with `status=active` |
| `customer.subscription.updated` | Any change to a subscription (cancel scheduled, plan changed, renewal) | Re-syncs the `StripeSubscription` row — status, dates, `cancel_at_period_end` |
| `customer.subscription.deleted` | Subscription immediately canceled | Syncs `status=canceled`, `is_active` becomes `false` |
| `invoice.payment_succeeded` | Renewal payment goes through | Re-syncs subscription with updated `current_period_start` / `current_period_end` |
| `invoice.payment_failed` | Payment declined | Re-syncs subscription — status typically becomes `past_due` |

**Idempotency:** If Stripe sends the same event twice (it retries on 5xx), the second call checks `StripeEvent` and returns `200 Already processed` without doing anything again.

**Error handling:** If the handler crashes, the error is logged to `StripeEvent.processing_error` and `200` is still returned to Stripe. This prevents infinite retries. You can replay failed events from the admin.

---

## 7. Checking Subscription in Your Code

Query the local database — never call the Stripe API at runtime for access checks.

**Check if a user has any active subscription:**
```python
from billing.models import StripeSubscription

def has_active_subscription(user) -> bool:
    return StripeSubscription.objects.filter(
        user=user,
        status__in=["active", "trialing"],
    ).exists()
```

**Get the user's current subscription:**
```python
sub = (
    StripeSubscription.objects
    .filter(user=user)
    .select_related("plan")
    .order_by("-created_at")
    .first()
)

if sub is None:
    # No plan at all — show pricing page
    pass
elif sub.is_active:
    if sub.plan.is_free:
        # On free plan
        pass
    else:
        # On paid plan
        if sub.cancel_at_period_end:
            # Cancels at sub.current_period_end
            pass
elif sub.is_past_due:
    # Payment failed — prompt to update card
    pass
elif sub.status == "canceled":
    # Subscription ended
    pass
```

**Check from a DRF view (protect an endpoint):**
```python
from billing.models import StripeSubscription

class PremiumFeatureView(APIView):
    authentication_classes = [BearerTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        has_paid = StripeSubscription.objects.filter(
            user=request.user,
            status__in=["active", "trialing"],
            plan__is_free=False,
        ).exists()

        if not has_paid:
            return Response(
                {"detail": "This feature requires a paid subscription."},
                status=403,
            )

        # ... return premium content
```

---

## 8. Admin Panel

After migrating, four sections appear under **Admin → Billing**:

### Stripe Plans
Create and manage your plans here. This is the only manual step required — everything else is automatic.

- Set `is_free=True` and leave `stripe_price_id` blank for your free tier.
- Copy the `stripe_price_id` exactly from **Stripe Dashboard → Products → [your product] → Pricing**.
- Deactivating a plan (`is_active=False`) hides it from the API but doesn't affect existing subscribers.

### Stripe Customers
Auto-populated when a user first hits a paid Stripe endpoint. Each row maps one Django user to one `cus_...` customer in Stripe. Read-only — do not edit.

### Stripe Subscriptions
Every subscription — free and paid — appears here. Useful for:
- Manually checking a specific user's status
- Seeing `processing_error` on a specific record

Fields are read-only because they're owned by Stripe webhooks.

### Stripe Webhook Events
Audit log of every webhook received. If `has_error` shows `True`, the `processing_error` column explains what went wrong. You can use the Stripe Dashboard to replay the original event, which will create a new `StripeEvent` row and re-run the handler.

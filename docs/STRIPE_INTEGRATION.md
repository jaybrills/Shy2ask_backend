# Stripe Subscription Integration

## Overview

A dedicated `billing` Django app handles all Stripe subscription logic:

| Concern | File |
|---|---|
| Models | `billing/models.py` |
| API views | `billing/views.py` |
| Serializers | `billing/serializers.py` |
| URL routes | `billing/urls.py` |
| Admin | `billing/admin.py` |
| DB migration | `billing/migrations/0001_initial.py` |

---

## Setup

### 1. Install the Stripe SDK

```bash
pip install stripe==12.0.0
# or just:
pip install -r requirements.txt
```

### 2. Configure `.env`

Copy the keys from your [Stripe Dashboard](https://dashboard.stripe.com/apikeys):

```ini
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_DEFAULT_PRICE_ID=price_...   # optional default plan
```

### 3. Migrate the database

```bash
python manage.py migrate billing
```

### 4. Seed plans in the admin

Go to **Admin → Billing → Stripe Plans → Add** and fill in:

**Free plan:**

| Field | Value |
|---|---|
| Name | Free |
| Stripe Price ID | *(leave blank)* |
| Stripe Product ID | *(leave blank)* |
| Amount | `0` |
| Currency | `chf` |
| Interval | `month` |
| Is Free | ✓ |
| Is Active | ✓ |

**Paid plan:**

| Field | Example |
|---|---|
| Name | Pro Monthly |
| Stripe Price ID | `price_1RaBC…` (from Stripe Dashboard → Products) |
| Stripe Product ID | `prod_XYZ…` |
| Amount | `1990` (CHF 19.90 expressed in cents) |
| Currency | `chf` |
| Interval | `month` |
| Is Free | ☐ |
| Is Active | ✓ |

### 5. Register the webhook in Stripe

1. Go to **Stripe Dashboard → Developers → Webhooks → Add endpoint**.
2. URL: `https://yourdomain.com/api/billing/webhook/`
3. Select events:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
4. Copy the **Signing secret** into `STRIPE_WEBHOOK_SECRET`.

For local development use the [Stripe CLI](https://stripe.com/docs/stripe-cli):

```bash
stripe login
stripe listen --forward-to localhost:8000/api/billing/webhook/
# Copy the printed webhook secret into STRIPE_WEBHOOK_SECRET
```

---

## API Reference

All endpoints are under `/api/billing/`.

### `GET /api/billing/plans/`

List all active subscription plans seeded in the admin.

**Auth:** None required.

**Response `200`:**
```json
[
  {
    "id": 1,
    "name": "Pro Monthly",
    "stripe_price_id": "price_1RaBC...",
    "amount": "19.90",
    "currency": "chf",
    "interval": "month",
    "is_active": true
  }
]
```

---

### `POST /api/billing/checkout/`

Creates a Stripe Checkout Session. Redirect the user's browser to the returned `url`.

**Auth:** `Bearer <token>` required.

**Request body:**
```json
{
  "price_id": "price_1RaBC...",   // optional if STRIPE_DEFAULT_PRICE_ID is set
  "success_url": "https://yourapp.com/billing/success?session_id={CHECKOUT_SESSION_ID}",
  "cancel_url": "https://yourapp.com/billing/cancel"
}
```

**Response `200`:**
```json
{
  "session_id": "cs_test_...",
  "url": "https://checkout.stripe.com/pay/cs_test_..."
}
```

**Errors:**
- `400` – missing `price_id` and no default configured.
- `502` – Stripe API error.

**Flow:**
1. Your frontend calls this endpoint.
2. Redirect user to `url`.
3. User completes payment on Stripe's hosted page.
4. Stripe redirects to `success_url` and fires `checkout.session.completed`.

---

### `POST /api/billing/portal/`

Creates a Stripe Billing Portal session so the user can manage their subscription (cancel, change plan, update card, download invoices).

**Auth:** `Bearer <token>` required.

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

---

### `GET /api/billing/subscription/`

Returns the user's most recent subscription.

**Auth:** `Bearer <token>` required.

**Response `200`:**
```json
{
  "id": 1,
  "stripe_subscription_id": "sub_1RaBC...",
  "status": "active",
  "plan": {
    "id": 1,
    "name": "Pro Monthly",
    "stripe_price_id": "price_1RaBC...",
    "amount": "19.90",
    "currency": "chf",
    "interval": "month",
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

**Response `404`:** `{ "detail": "No subscription found." }`

---

### `POST /api/billing/free/`

Enroll the authenticated user in the free plan. No Stripe objects are created — the record is stored locally only.

**Auth:** `Bearer <token>` required.

**Request body (all optional):**
```json
{
  "plan_id": 1
}
```
Omit `plan_id` to auto-select the only active free plan.

**Response `201`** (enrolled) / **`200`** (already enrolled):
```json
{
  "id": 2,
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
  "created_at": "2026-04-15T10:00:00Z",
  "updated_at": "2026-04-15T10:00:00Z"
}
```

**Errors:**
- `404` — no active free plan seeded in the admin yet.
- `400` — user already has an active paid subscription (direct them to the portal to downgrade).

---

### `POST /api/billing/webhook/`

**This endpoint is called by Stripe — not your frontend.**

- No auth header required.
- CSRF exempt.
- Verifies `Stripe-Signature` header using `STRIPE_WEBHOOK_SECRET`.
- Idempotent: duplicate events (Stripe retries) are silently skipped.

**Events handled:**

| Event | Action |
|---|---|
| `checkout.session.completed` | Creates `StripeCustomer` + `StripeSubscription`; sets status to `active` |
| `customer.subscription.updated` | Syncs status, dates, `cancel_at_period_end` |
| `customer.subscription.deleted` | Syncs status to `canceled` |
| `invoice.payment_succeeded` | Re-syncs subscription with new period dates |
| `invoice.payment_failed` | Re-syncs subscription (status → `past_due` or `unpaid`) |

All received events are stored in the `StripeEvent` table for audit/replay.

---

## Database Models

### `StripeCustomer`
Maps a Django user ↔ Stripe customer ID (one-to-one).

### `StripePlan`
Mirrors a Stripe Price object. Seed manually from the admin.

### `StripeSubscription`
Mirrors a Stripe Subscription. Created/updated by webhooks.

| Field | Description |
|---|---|
| `status` | `active`, `canceled`, `past_due`, `trialing`, etc. |
| `is_active` | `True` when status is `active` or `trialing` |
| `is_past_due` | `True` when status is `past_due` |
| `cancel_at_period_end` | User requested cancel; access continues until period end |
| `current_period_end` | When the current billing period ends |

### `StripeEvent`
Idempotency log of every webhook event received. Prevents double-processing.

---

## Test Cases

### Prerequisites

- Stripe test mode enabled (use `pk_test_…` / `sk_test_…` keys).
- Stripe CLI running and forwarding webhooks locally.
- At least one `StripePlan` seeded in the admin.
- A registered, verified, and logged-in user (with `Bearer` token).

---

### Case 1 — List Plans

```http
GET /api/billing/plans/
```

**Expected:** `200` with an array of plans.  
**Check:** Plans you seeded in the admin appear with correct `stripe_price_id`.

---

### Case 2 — Create Checkout Session (Happy Path)

```http
POST /api/billing/checkout/
Authorization: Bearer <token>
Content-Type: application/json

{
  "price_id": "price_YOUR_TEST_PRICE_ID",
  "success_url": "http://localhost:3000/success?session_id={CHECKOUT_SESSION_ID}",
  "cancel_url": "http://localhost:3000/cancel"
}
```

**Expected:** `200` with `session_id` and `url`.  
**Check:** Open the `url` in a browser → Stripe checkout page loads.

---

### Case 3 — Complete a Subscription (Stripe Test Card)

1. Open the checkout `url` from Case 2.
2. Use Stripe test card: **`4242 4242 4242 4242`**, any future expiry, any CVC.
3. Complete payment.
4. **Expected webhook:** `checkout.session.completed` fires → Stripe CLI prints it.
5. **Check DB:** A `StripeSubscription` row with `status=active` is created.
6. **Check API:**
   ```http
   GET /api/billing/subscription/
   Authorization: Bearer <token>
   ```
   Returns subscription with `status=active` and `is_active=true`.

---

### Case 4 — Checkout Session Without price_id (uses default)

Set `STRIPE_DEFAULT_PRICE_ID` in `.env`, then:

```http
POST /api/billing/checkout/
Authorization: Bearer <token>
Content-Type: application/json

{
  "success_url": "http://localhost:3000/success",
  "cancel_url": "http://localhost:3000/cancel"
}
```

**Expected:** `200` — default price used.

---

### Case 5 — Checkout Session Without price_id (no default)

Remove `STRIPE_DEFAULT_PRICE_ID` from `.env`, then send the same body.

**Expected:** `400` — `"No price_id provided and STRIPE_DEFAULT_PRICE_ID not configured."`

---

### Case 6 — Customer Portal

```http
POST /api/billing/portal/
Authorization: Bearer <token>
Content-Type: application/json

{
  "return_url": "http://localhost:3000/account"
}
```

**Expected:** `200` with a `url` that opens the Stripe billing portal.  
**Note:** Requires the user to have an active subscription (Case 3 must succeed first).

---

### Case 7 — Cancel Subscription via Portal

1. Open the portal URL from Case 6.
2. Click **Cancel plan** → confirm.
3. **Expected webhook:** `customer.subscription.updated` with `cancel_at_period_end=true`.
4. **Check API:** `GET /api/billing/subscription/` → `"cancel_at_period_end": true`.

---

### Case 8 — Simulate Payment Failure (Stripe CLI)

```bash
stripe trigger invoice.payment_failed
```

**Expected webhook:** `invoice.payment_failed` → subscription synced to `past_due`/`unpaid`.  
**Check API:** `GET /api/billing/subscription/` → `"is_past_due": true`.

---

### Case 9 — Duplicate Webhook (Idempotency)

Send the same webhook event twice (replay in Stripe Dashboard or re-fire with CLI).

**Expected:** Second call returns `200` with `"Already processed."` — no duplicate DB row.  
**Check DB:** Only one `StripeEvent` row for that `stripe_event_id`.

---

### Case 10 — Invalid Webhook Signature

Send a `POST /api/billing/webhook/` request with a bad or missing `Stripe-Signature` header.

**Expected:** `400` — `"Invalid signature."`

---

### Case 11 — Unauthenticated Checkout Request

```http
POST /api/billing/checkout/
Content-Type: application/json

{
  "price_id": "price_...",
  "success_url": "http://localhost:3000/success",
  "cancel_url": "http://localhost:3000/cancel"
}
```

**Expected:** `401` — authentication required.

---

### Case 12 — Subscription Status When None Exists

For a fresh user with no subscription:

```http
GET /api/billing/subscription/
Authorization: Bearer <new_user_token>
```

**Expected:** `404` — `"No subscription found."`

---

### Case 13 — Enroll in Free Plan (Happy Path)

First seed a free plan in the admin (`is_free=True`, `amount=0`, `stripe_price_id` blank).

```http
POST /api/billing/free/
Authorization: Bearer <token>
Content-Type: application/json

{}
```

**Expected:** `201` — subscription with `status=active`, `stripe_subscription_id=null`, `is_active=true`.  
**Check API:** `GET /api/billing/subscription/` now returns the free plan.

---

### Case 14 — Enroll in Free Plan Again (Idempotent)

Call the same endpoint a second time with the same user.

**Expected:** `200` — same subscription returned, no duplicate created.

---

### Case 15 — Free Plan While on Paid Plan

User has an active paid subscription (Case 3 done). Try to enroll free:

```http
POST /api/billing/free/
Authorization: Bearer <paid_user_token>
Content-Type: application/json

{}
```

**Expected:** `400` — `"You already have an active paid subscription. Use the billing portal to change your plan."`

---

### Case 16 — Checkout With Free Plan's price_id

If someone somehow passes a `price_id` that belongs to a plan marked `is_free=True`:

```http
POST /api/billing/checkout/
Authorization: Bearer <token>
Content-Type: application/json

{
  "price_id": "price_of_a_free_plan",
  "success_url": "...",
  "cancel_url": "..."
}
```

**Expected:** `400` — `"This is a free plan. Use POST /api/billing/free/ to enroll."`

---

### Case 17 — No Free Plan Seeded Yet

Call `/api/billing/free/` before any free plan exists in the admin.

**Expected:** `404` — `"No active free plan found. Ask an admin to create one."`

---

## Admin Panel

After migrating, these sections appear under **Admin → Billing**:

| Section | Purpose |
|---|---|
| Stripe Plans | Seed/manage pricing plans |
| Stripe Customers | View user ↔ Stripe customer mappings |
| Stripe Subscriptions | Browse all subscriptions and statuses |
| Stripe Webhook Events | Audit log of every received webhook |

---

## Checking Subscription in Application Code

```python
from billing.models import StripeSubscription

def user_has_active_subscription(user) -> bool:
    return StripeSubscription.objects.filter(
        user=user,
        status__in=["active", "trialing"],
    ).exists()
```

Or via the model property:

```python
sub = user.stripe_subscriptions.order_by("-created_at").first()
if sub and sub.is_active:
    # grant access
    pass
```

# Shy2Ask – API Documentation

Base URL (example): `http://localhost:8000`

- **Swagger UI (try APIs in browser):** [http://localhost:8000/docs](http://localhost:8000/docs) — for UI/frontend developers.
- **OpenAPI JSON:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)
- **Swagger usage:** [SWAGGER_UI.md](SWAGGER_UI.md) — how to open and use Swagger from web URL.

---

## 1. Django Ninja API (root)

All Ninja endpoints are under the base URL (no `/api/` prefix). Auth uses **Bearer token** where required.

### 1.1 Auth (`/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/register` | No | Register; sends email verification OTP |
| POST | `/auth/verify-email` | No | Verify email with OTP |
| POST | `/auth/resend-verification` | No | Resend verification OTP |
| POST | `/auth/login` | No | Login (email verified only); returns token |
| POST | `/auth/forgot-password` | No | Send password-reset OTP to email |
| POST | `/auth/reset-password` | No | Reset password with OTP |

#### POST `/auth/register`

**Request body (JSON):**
```json
{
  "email": "user@example.com",
  "password": "securepass123",
  "first_name": "John",
  "last_name": "Doe",
  "alias_name": "johnd",
  "phone_number": "+41..."
}
```
All except `email` and `password` are optional.

**Response:** `201 Created`
```json
{
  "id": 1,
  "email": "user@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "alias_name": "johnd",
  "is_verified": false,
  "token": "abc123...",
  "message": "Please verify your email with the OTP sent to your inbox."
}
```
**Errors:** `400` – email already exists (and verified).

---

#### POST `/auth/verify-email`

**Request body (JSON):**
```json
{
  "email": "user@example.com",
  "otp_code": "123456"
}
```

**Response:** `200 OK`
```json
{
  "message": "Email verified successfully.",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "alias_name": "johnd",
    "phone_number": "+41...",
    "is_verified": true
  }
}
```
**Errors:** `400` – invalid or expired OTP.

---

#### POST `/auth/resend-verification`

**Request body (JSON):**
```json
{
  "email": "user@example.com"
}
```

**Response:** `200 OK` – `{"message": "Verification code sent. Check your email."}`  
**Errors:** `400` – email already verified.

---

#### POST `/auth/login`

**Request body (JSON):**
```json
{
  "email": "user@example.com",
  "password": "securepass123"
}
```

**Response:** `200 OK`
```json
{
  "token": "abc123...",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "alias_name": "johnd",
    "phone_number": "+41...",
    "is_verified": true
  }
}
```
**Errors:**  
- `401` – invalid email or password.  
- `403` – email not verified (`code: "email_not_verified"`).

---

#### POST `/auth/forgot-password`

**Request body (JSON):**
```json
{
  "email": "user@example.com"
}
```

**Response:** `200 OK` – `{"message": "If an account exists for this email, a reset code has been sent."}`  
(Always 200 to avoid email enumeration.)

---

#### POST `/auth/reset-password`

**Request body (JSON):**
```json
{
  "email": "user@example.com",
  "otp": "123456",
  "new_password": "newsecurepass8"
}
```
`new_password` must be at least 8 characters.

**Response:** `200 OK` – `{"message": "Password has been reset. You can now log in."}`  
**Errors:** `400` – invalid/expired OTP or password too short.

---

### 1.2 Profile (`/profile`)

Requires **Bearer token:** `Authorization: Bearer <token>`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/profile/me` | Bearer | Get current user profile |
| PATCH | `/profile/me` | Bearer | Update profile (optional `profile_picture` upload) |
| GET | `/profile/users` | Bearer (staff) | List users with pagination and search |

#### GET `/profile/me`

**Response:** `200 OK`
```json
{
  "id": 1,
  "email": "user@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "alias_name": "johnd",
  "phone_number": "+41...",
  "profile_picture": "https://... or null",
  "is_verified": true,
  "date_joined": "2025-01-01T00:00:00",
  "updated_at": "2025-01-15T12:00:00"
}
```

---

#### PATCH `/profile/me`

**Request:** JSON body and/or multipart with `profile_picture` file.

**JSON body (all optional):**
```json
{
  "first_name": "Jane",
  "last_name": "Doe",
  "alias_name": "janed",
  "phone_number": "+41..."
}
```

**Response:** `200 OK` – same shape as GET `/profile/me`.  
**Errors:** `400` – validation error.

---

#### GET `/profile/users`

**Query parameters:**
- `limit` (int, default 20)
- `offset` (int, default 0)
- `search` (string) – search in email, first_name, last_name, alias_name

**Response:** `200 OK`
```json
{
  "count": 100,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "id": 1,
      "email": "user@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "alias_name": "johnd",
      "is_active": true,
      "date_joined": "2025-01-01T00:00:00"
    }
  ]
}
```
**Errors:** `403` – staff only.

---

### 1.3 Censor (`/censor`)

No auth required. **Multilingual:** OpenAI Moderation supports 40+ languages; Google Perspective (fallback) supports a wide language list. Uses rule-based lists + AI (OpenAI Moderation/Vision when `OPENAI_API_KEY` is set). Evasive spelling (e.g. `d.r.u.g.s`, `buy.your.girl`) is normalized and matched.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/censor/text` | No | Censor plain text |
| POST | `/censor/image` | No | Upload image → OCR + text censor + optional image content check (Vision) |

#### POST `/censor/text`

**Request body (JSON):**
```json
{
  "text": "Your message to check..."
}
```

**Response:** `200 OK`
```json
{
  "censored_text": "Your m***** to check...",
  "blocked": true,
  "detected": [
    {
      "term": "drugs",
      "category": "drugs"
    }
  ],
  "categories": ["drugs"],
  "ai_toxic_score": 0.85,
  "ai_provider": "openai"
}
```
- `censored_text` – text with matched terms masked/redacted.  
- `blocked` – true if content should be blocked (rules or AI).  
- `detected` – list of `{ "term", "category" }`.  
- `ai_toxic_score`, `ai_provider` – set when AI was used (e.g. `openai`, `perspective`).

---

#### POST `/censor/image`

**Request:** `multipart/form-data` with file field `image` (e.g. JPEG, PNG).

**Response:** `200 OK`
```json
{
  "censored_text": "[REDACTED] ...",
  "blocked": true,
  "detected": [
    {
      "term": "[AI image]",
      "category": "ai_toxic"
    }
  ],
  "categories": ["ai_toxic"],
  "extracted_text": "Raw text from OCR...",
  "ocr_available": true,
  "ai_toxic_score": 0.9,
  "ai_provider": "openai"
}
```
- `extracted_text` – text from OCR (empty if OCR failed).  
- `ocr_available` – whether Tesseract OCR succeeded.  
- Image content is also checked by OpenAI Vision when `OPENAI_API_KEY` is set.

**Errors:** `400` – no image or empty file.

---

## 2. DRF API (`/api/`)

REST framework under `/api/`. No auth required for create/list by default; filtering by user when authenticated.

### 2.1 Requests (`/api/requests/`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/requests/` | List requests (authenticated: own; or filter by `?tracking_code=XXX`) |
| POST | `/api/requests/` | Create a new request |
| GET | `/api/requests/{id}/` | Retrieve one request |
| POST | `/api/requests/{id}/messages/` | Send a message in this request’s conversation |
| GET | `/api/requests/{id}/conversation/` | Get all messages in this request’s conversation |

#### GET `/api/requests/`

**Query:** `tracking_code` (optional) – filter by tracking code.

**Response:** `200 OK` – array of request objects (see below).

---

#### POST `/api/requests/`

**Request body (JSON):**
```json
{
  "requester_name": "John Doe",
  "requester_email": "john@example.com",
  "requester_phone": "",
  "requester_alias": "MyNick",
  "target_name": "Jane",
  "target_email": "jane@example.com",
  "target_phone": "",
  "target_address": "",
  "description": "Request description...",
  "service_channel": "email",
  "call_minutes": 0
}
```
- `requester_alias` (optional): display name for this request (e.g. in chat). If omitted and user is logged in, profile `alias_name` is used.
- `service_channel`: `"email"` \| `"letter"` \| `"call"`  
- `tracking_code`, `quoted_price_chf`, `status`, `country_code`, `created_at`, `attachments` are read-only.

**Response:** `201 Created` – created request object.

---

#### GET `/api/requests/{id}/`

**Response:** `200 OK` – single request object, e.g.:
```json
{
  "id": 1,
  "tracking_code": "ABC12XYZ",
  "requester_name": "John Doe",
  "requester_email": "john@example.com",
  "requester_phone": "",
  "target_name": "Jane",
  "target_email": "jane@example.com",
  "target_phone": "",
  "target_address": "",
  "description": "...",
  "service_channel": "email",
  "call_minutes": 0,
  "quoted_price_chf": "1.00",
  "country_code": "CH",
  "status": "submitted",
  "created_at": "2025-01-15T12:00:00Z",
  "attachments": []
}
```

---

#### POST `/api/requests/{id}/messages/`

**Request body (JSON):**
```json
{
  "body": "Message text..."
}
```
Message is censored; `clean_body` and `is_blocked` are set by the backend.

**Request body (JSON):** `body` (required), optional `alias` (display name for this message).
```json
{
  "body": "Message text...",
  "alias": "MyNick"
}
```
If `alias` is omitted, the requester’s profile `alias_name` or the request’s `requester_alias` is used.

**Response:** `201 Created` – message object:
```json
{
  "id": 1,
  "sender": "requester",
  "sender_display_name": "MyNick",
  "display_name": "MyNick",
  "body": "Original text",
  "clean_body": "Censored text",
  "is_blocked": false,
  "created_at": "2025-01-15T12:00:00Z"
}
```

---

#### GET `/api/requests/{id}/conversation/`

**Response:** `200 OK` – array of message objects (same shape as above, with `display_name`).

---

## 3. WebSockets (WS / WSS)

Use **ws://** on HTTP and **wss://** on HTTPS (same path). Example: `wss://yourdomain.com/ws/chat/123/`.

| Purpose | URL | Auth / access |
|--------|-----|----------------|
| **Chat (conversation)** | `ws://host/ws/chat/<request_id>/` or `wss://host/ws/chat/<request_id>/` | Requester: logged-in owner of request. Responder: `?tracking_code=XXX`. |
| **Notifications** | `ws://host/ws/notifications/` or `wss://host/ws/notifications/` | Logged-in user only. |

### Chat WebSocket

- **Connect:** `ws://localhost:8000/ws/chat/<request_id>/` (requester) or `ws://localhost:8000/ws/chat/<request_id>/?tracking_code=ABC123` (responder).
- **Send message (JSON):**
  - `body` (required): message text.
  - `alias` (optional): display name for this request/conversation. If omitted, profile `alias_name` or request `requester_alias` or `requester_name` is used.
```json
{"body": "Hello!", "alias": "MyNick"}
```
- **Receive:** server sends HTML fragments (HTMX OOB) or message payloads; each includes `display_name` (alias or default).

---

## 4. Other routes

| Path | Description |
|------|-------------|
| `/admin/` | Django admin |
| `/docs` | Swagger UI for Ninja API |
| `/openapi.json` | OpenAPI 3 schema for Ninja API |

---

## 5. Quick reference

| Area | Base | Auth |
|------|------|------|
| Ninja (auth, profile, censor) | `/` | Bearer for `/profile/*` |
| DRF (requests, messages) | `/api/` | Optional; staff for some actions |
| WebSockets | `ws://.../ws/` | As per app |

**Bearer token:** Use the `token` from `/auth/login` or `/auth/register` in the header:
```http
Authorization: Bearer <token>
```

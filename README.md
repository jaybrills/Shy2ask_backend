# Shy2Ask

Django API with Django Ninja (auth, profile), DRF (chat), and real-time WebSockets (Daphne).

## Run

```bash
pip install -r requirements.txt
python manage.py migrate
daphne -b 0.0.0.0 -p 8000 shy2ask.asgi:application
```

Or: `python manage.py runserver 0.0.0.0:8000`

**Swagger UI (for UI / frontend devs):** [http://localhost:8000/docs](http://localhost:8000/docs) — open in browser to try all endpoints.  
**OpenAPI schema:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)  
**Swagger usage guide:** [docs/SWAGGER_UI.md](docs/SWAGGER_UI.md)  
**Full API reference:** [docs/API.md](docs/API.md)

## Django Ninja API (Auth & Profile)

Login with **email only**. **Email verification** and **forgot/reset password** use OTP by email (like Storemate).

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/register` | No | Register → sends **email verification OTP**; user must verify before login |
| POST | `/auth/verify-email` | No | Verify email: `email`, `otp_code` (from register email) |
| POST | `/auth/resend-verification` | No | Resend verification OTP to `email` |
| POST | `/auth/login` | No | Login: email, password → returns token (only if **email verified**) |
| POST | `/auth/forgot-password` | No | Send **password reset OTP** to email |
| POST | `/auth/reset-password` | No | Reset password: `email`, `otp`, `new_password` |
| GET | `/profile/me` | Bearer | Get current user profile (includes `is_verified`) |
| PATCH | `/profile/me` | Bearer | Update profile (optional: profile_picture multipart) |
| GET | `/profile/users` | Bearer (staff) | List users: `?limit=&offset=&search=` |

**Authorization:** `Authorization: Bearer <token>` (from login or register).

**Config:** Copy `env.example` to `.env` and set `EMAIL_*` (and optional `DB_*`, `SECRET_KEY`, etc.). Email is used for verification and password-reset OTPs.

## Censor engine (text + image, rule-based + AI)

- **Text:** Rule-based lists (DB + built-in) catch banned words/phrases; **evasive spelling** with dots, dashes, underscores is normalized (e.g. `d.r.u.g.s`, `buy.your.girl` still match). Then **OpenAI Moderation API** (if `OPENAI_API_KEY` in `.env`) or Google Perspective API for toxicity.
- **Image:** OCR (Tesseract) → text censor on extracted text; if `OPENAI_API_KEY` is set, **OpenAI Vision** also checks image content (violence, adult, drugs, etc.).
- **To use OpenAI (recommended):** In your `.env` set `OPENAI_API_KEY=sk-...` (get key at [platform.openai.com](https://platform.openai.com/)). Do not put the key in code.
- **Flow:** Our local model (optional) → **OpenAI** (text Moderation + image Vision when key set) → Google API fallback. API responses are saved to **Censor training examples** for retraining.
- **Fetch training data:**  
  `python manage.py fetch_censor_training_data --samples` or `samples.txt` (one text per line).  
- **Train our model:**  
  `python manage.py train_censor_model` (needs ≥50 examples); `--add-offensive-terms` adds DB terms.  
  Model saved to `CENSOR_MODEL_PATH`.
- **Settings:** `OPENAI_API_KEY`, `CENSOR_OPENAI_VISION_MODEL` (default `gpt-4o-mini`), `CENSOR_AI_THRESHOLD`, `PERSPECTIVE_API_KEY` (fallback).

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/censor/text` | No | Body: `{"text": "..."}` → `censored_text`, `blocked`, `detected`, `categories`, `ai_toxic_score`, `ai_provider` |
| POST | `/censor/image` | No | Multipart: `image` file → OCR + censor; same response + `extracted_text`, `ocr_available` |

**Image OCR:** Install [Tesseract](https://github.com/tesseract-ocr/tesseract); else `ocr_available: false`.

## Other routes

- **HTTP:** `/admin/`, `/api/` (DRF chat requests/messages)
- **WebSocket:** `/ws/chat/<request_id>/`, `/ws/notifications/`, `/ws/requests/inbox/`
- **OpenAPI schema:** `/openapi.json`

Optional: Redis for channel layer; without it, in-memory layer is used (single process).

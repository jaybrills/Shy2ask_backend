# Shy2Ask (Django)

Prototype that follows the provided SRS: Swiss-only access, cartoon-styled landing page, and a flow to submit shy requests with attachments and simple pricing.

## Requirements

- Python 3.10+
- Virtualenv (created as `venv/`)

## Setup

```bash
cd /home/khajan/project/shy2ask
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## Features

- Location gate: only Switzerland (ISO code `CH`) is allowed; others see “service coming soon.”
- Landing page styled with comic-inspired bubbles and hero section.
- Request form with contact details for the recipient, description, and optional attachments (images/videos/docs).
- Pricing rules from the SRS: CHF 1 email, CHF 10 letter, CHF 20 + 1/min call; auto-calculated and stored.
- Admin registration for managing requests and their attachments.

## Country detection

- Looks for ISO country code in header `X-Country-Code` (configurable via `COUNTRY_HEADER`).
- Fallback headers checked: `CF-IPCountry`, `X-Country`.
- If no header is present:
  - `DEBUG=True`: allowed for local development.
  - `DEBUG=False`: blocked (renders coming-soon page).
- Override for testing: add `?country_override=US` or `?country_override=CH` to URLs.

## File storage

- User uploads are stored under `media/attachments/<year>/<month>/<day>/`.
- Static assets live in `core/static/core/`; extra global assets can go in `static/`.

## Useful URLs

- `/` – landing page
- `/request/new/` – create a shy request
- `/admin/` – Django admin (create a superuser via `python manage.py createsuperuser`)

## Safety disclaimer

The UI and form copy explicitly reject violent or unlawful requests, as requested in the SRS. Adjust wording in `templates/core/*.html` if you need stricter language.


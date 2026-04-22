import os
from pathlib import Path
import sys
import environ
import os

env = environ.Env(
    DEBUG=(bool, False)
)
BASE_DIR = Path(__file__).resolve().parent.parent
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# Django
SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = ['*']
AUTH_USER_MODEL = "account.User"
INSTALLED_APPS = [
    'daphne',  # ASGI server; must be before django.contrib so runserver uses Daphne
    'unfold',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'channels',
    'rest_framework',
    'rest_framework.authtoken',
    'drf_spectacular',
    'account',
    'chat',
    'corsheaders',
    'django_celery_beat',
    'django_celery_results',
    'billing',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Must be before CommonMiddleware so CORS headers are added to all responses.
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'shy2ask.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'shy2ask.wsgi.application'
ASGI_APPLICATION = 'shy2ask.asgi.application'

# Channel layers (for WebSocket groups). Prefer Redis; fallback to in-memory.
try:
    import redis

    redis.Redis(host="127.0.0.1", port=6379, db=0, socket_connect_timeout=1).ping()
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [("127.0.0.1", 6379)]},
        },
    }
except Exception:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": "localhost",
        "PORT": "5432",
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Europe/Zurich'

USE_I18N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

UNFOLD = {
    "SITE_TITLE": "Shy2Ask Control Center",
    "SITE_HEADER": "Shy2Ask Control Center",
    "SITE_SUBHEADER": "Operations, trust, and conversation workflows",
    "SITE_SYMBOL": "shield_lock",
    "SITE_URL": "/",
    "SITE_LOGO": {
        "light": "shy2ask.unfold.logo_light",
        "dark": "shy2ask.unfold.logo_dark",
    },
    "SITE_ICON": {
        "light": "shy2ask.unfold.icon_light",
        "dark": "shy2ask.unfold.icon_dark",
    },
    "SITE_FAVICONS": [
        {
            "rel": "icon",
            "type": "image/svg+xml",
            "href": "/static/admin/brand-mark.svg",
        },
    ],
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "SHOW_BACK_BUTTON": True,
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": "shy2ask.unfold.sidebar_navigation",
    },
    "ACCOUNT": {
        "navigation": "shy2ask.unfold.account_links",
    },
    "ENVIRONMENT": "shy2ask.unfold.environment_label",
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Security (from env)
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000,http://127.0.0.1:8000,http://10.0.2.2:8000",
    "https://backend.shy2ask.com",
]
# SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT")
SESSION_COOKIE_SECURE = env("SESSION_COOKIE_SECURE")
CSRF_COOKIE_SECURE = env("CSRF_COOKIE_SECURE")

# CORS_ALLOWED_ORIGINS = [
#     "http://localhost:3000,http://127.0.0.1:3000,http://10.0.2.2:3000,"
#     "http://localhost:8081,http://127.0.0.1:8081,http://10.0.2.2:8081", ]
# Allow LAN dev clients (e.g. physical phone on same Wi-Fi).

# Logging
LOG_LEVEL = "INFO"
LOG_FILE = "logs/django.log"

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Country gating (default to Switzerland). For non-Swiss traffic we display
# "service coming soon".
ALLOWED_COUNTRY_CODE = "CH"
COUNTRY_HEADER = "HTTP_X_COUNTRY_CODE"

# Email (from env; SMTP for production)
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.office365.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "info@doappointment.com"
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")  # use normal password if 2FA off, else app password
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# Censor engine: our model first, then AI (OpenAI preferred if key set, else Google); save internet AI for training
CENSOR_AI_ENABLED = True
CENSOR_USE_OUR_MODEL_FIRST = False
CENSOR_MODEL_PATH = str(BASE_DIR / "media" / "censor_model.joblib")
CENSOR_OUR_MODEL_THRESHOLD = 0.6
OPENAI_API_KEY = env("OPENAI_API_KEY")
CENSOR_OPENAI_VISION_MODEL = "gpt-4o-mini"  # image content check (any language)
# omni-moderation-latest = 40+ languages; leave empty to use API default
CENSOR_OPENAI_MODERATION_MODEL = "omni-moderation-latest"
CENSOR_AI_THRESHOLD = 0.5
CENSOR_SAVE_SAFE_EXAMPLES = False

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Shy2Ask API",
    "DESCRIPTION": (
        "Live OpenAPI schema for the Shy2Ask backend. Realtime chat and "
        "notifications are available over WebSockets; see the Realtime tag "
        "or GET /api/realtime/docs/ for connection URLs, auth rules, and JSON event shapes."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ── Stripe ────────────────────────────────────────────────────────────────────
import stripe as _stripe

STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
# Optional: a single default Price ID used when none is supplied in the request
STRIPE_DEFAULT_PRICE_ID = env("STRIPE_DEFAULT_PRICE_ID", default="")

# Initialise the stripe SDK globally so all views pick up the key automatically
if STRIPE_SECRET_KEY:
    _stripe.api_key = STRIPE_SECRET_KEY

# ── Celery ────────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = "redis://127.0.0.1:6379/1"
CELERY_RESULT_BACKEND ="redis://127.0.0.1:6379/2"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
# Retry on broker connection error at startup (avoids crash if Redis not ready yet)
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

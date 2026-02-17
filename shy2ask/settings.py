"""
Django settings for shy2ask project.
Load from environment: .env or os.environ (see env.example).
"""

import os
from pathlib import Path

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent


def env(key, default=None, cast=str):
    v = os.getenv(key, default)
    if v is None or v == "":
        return default
    if cast is bool:
        return str(v).lower() in ("1", "true", "yes")
    if cast is int:
        return int(v)
    return str(v)


def env_list(key, default=""):
    return [item.strip() for item in env(key, default).split(",") if item.strip()]


# Django
SECRET_KEY = env("SECRET_KEY", "django-insecure-change-me")
DEBUG = env("DEBUG", "True", cast=bool)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,10.0.2.2")
if DEBUG and "*" not in ALLOWED_HOSTS:
    # Dev default: avoid host-header rejects from emulator/LAN testing.
    ALLOWED_HOSTS.append("*")


# Application definition

AUTH_USER_MODEL = "account.User"

INSTALLED_APPS = [
    'daphne',  # ASGI server; must be before django.contrib so runserver uses Daphne
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
    'account',
    'chat',
    'corsheaders',
]

MIDDLEWARE = [
    'ninja.compatibility.files.fix_request_files_middleware',
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


# Database (PostgreSQL if DB_* set; else SQLite)
_db_engine = env("DB_ENGINE", "").lower()
if env("DB_NAME") and _db_engine != "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME"),
            "USER": env("DB_USER", ""),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "localhost"),
            "PORT": env("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
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

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Security (from env)
CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000,http://10.0.2.2:8000",
)
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", "False", cast=bool)
SESSION_COOKIE_SECURE = env("SESSION_COOKIE_SECURE", "False", cast=bool)
CSRF_COOKIE_SECURE = env("CSRF_COOKIE_SECURE", "False", cast=bool)

# CORS
CORS_ALLOW_ALL_ORIGINS = env("CORS_ALLOW_ALL_ORIGINS", str(DEBUG), cast=bool)
CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://10.0.2.2:3000,"
    "http://localhost:8081,http://127.0.0.1:8081,http://10.0.2.2:8081",
)
# Allow LAN dev clients (e.g. physical phone on same Wi-Fi).
CORS_ALLOWED_ORIGIN_REGEXES = env_list(
    "CORS_ALLOWED_ORIGIN_REGEXES",
    r"^https?://192\.168\.\d{1,3}\.\d{1,3}(:\d+)?$,"
    r"^https?://10\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?$,"
    r"^https?://172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}(:\d+)?$",
)

# Logging
LOG_LEVEL = env("LOG_LEVEL", "INFO")
LOG_FILE = env("LOG_FILE", "logs/django.log")

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Country gating (default to Switzerland). For non-Swiss traffic we display
# "service coming soon".
ALLOWED_COUNTRY_CODE = os.getenv("ALLOWED_COUNTRY_CODE", "CH")
COUNTRY_HEADER = os.getenv("COUNTRY_HEADER", "HTTP_X_COUNTRY_CODE")

# Auth redirects (for admin / API; no frontend)
LOGIN_REDIRECT_URL = "/admin/"
LOGOUT_REDIRECT_URL = "/admin/"

# Email (from env; SMTP for production)
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "smtp.office365.com")
EMAIL_PORT = env("EMAIL_PORT", "587", cast=int)
EMAIL_USE_TLS = env("EMAIL_USE_TLS", "True", cast=bool)
EMAIL_USE_SSL = env("EMAIL_USE_SSL", "False", cast=bool)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "info@doappointment.com")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "no-reply@shy2ask.com")
ADMIN_NOTIFY_EMAIL = env("ADMIN_NOTIFY_EMAIL", DEFAULT_FROM_EMAIL)

# Censor engine: our model first, then AI (OpenAI preferred if key set, else Google); save internet AI for training
CENSOR_AI_ENABLED = env("CENSOR_AI_ENABLED", "True", cast=bool)
CENSOR_USE_OUR_MODEL_FIRST = env("CENSOR_USE_OUR_MODEL_FIRST", "True", cast=bool)
CENSOR_MODEL_PATH = env("CENSOR_MODEL_PATH", "") or str(BASE_DIR / "media" / "censor_model.joblib")
CENSOR_OUR_MODEL_THRESHOLD = float(env("CENSOR_OUR_MODEL_THRESHOLD", "0.6"))
OPENAI_API_KEY = env("OPENAI_API_KEY", "")
CENSOR_OPENAI_VISION_MODEL = env("CENSOR_OPENAI_VISION_MODEL", "gpt-4o-mini")  # image content check (any language)
# omni-moderation-latest = 40+ languages; leave empty to use API default
CENSOR_OPENAI_MODERATION_MODEL = env("CENSOR_OPENAI_MODERATION_MODEL", "omni-moderation-latest")
PERSPECTIVE_API_KEY = env("PERSPECTIVE_API_KEY", "")
CENSOR_AI_API_KEY = env("CENSOR_AI_API_KEY", "") or PERSPECTIVE_API_KEY
# 0.5 = stricter (more languages / borderline content flagged); 0.7 = less strict
CENSOR_AI_THRESHOLD = float(env("CENSOR_AI_THRESHOLD", "0.5"))
CENSOR_SAVE_SAFE_EXAMPLES = env("CENSOR_SAVE_SAFE_EXAMPLES", "False", cast=bool)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
}

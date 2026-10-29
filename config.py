import os
import secrets
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def load_env_file(path=os.path.join(BASE_DIR, ".env")):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value


load_env_file()

INSTANCE_DIR = os.path.abspath(os.environ.get("DATA_DIR") or os.path.join(BASE_DIR, "instance"))


def load_secret_key(instance_dir=INSTANCE_DIR):
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    os.makedirs(instance_dir, exist_ok=True)
    key_path = os.path.join(instance_dir, "secret_key")
    if not os.path.exists(key_path):
        with open(key_path, "w", encoding="utf-8") as fh:
            fh.write(secrets.token_hex(32))
    with open(key_path, encoding="utf-8") as fh:
        return fh.read().strip()


ON_HOSTING = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_ENVIRONMENT_NAME")
                  or os.environ.get("RENDER") or os.environ.get("BEHIND_PROXY") == "1")


class Config:
    DATABASE = os.path.join(INSTANCE_DIR, "events.db")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = ON_HOSTING
    BEHIND_PROXY = ON_HOSTING
    PREFERRED_URL_SCHEME = "https" if ON_HOSTING else "http"
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    WTF_CSRF_TIME_LIMIT = None
    SCHEDULER_ENABLED = True
    REMINDER_CHECK_SECONDS = 20
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "EskeSalKzBot")
    TELEGRAM_LINK_MINUTES = 15
    VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:noreply@esimde.app")

from datetime import timedelta

import pytest

from app import create_app
from utils import local_now

TZ = "Asia/Almaty"


def make_app(db_path, **extra):
    config = {"TESTING": True, "DATABASE": str(db_path), "SECRET_KEY": "test-secret",
              "WTF_CSRF_ENABLED": False, "TELEGRAM_BOT_TOKEN": ""}
    config.update(extra)
    return create_app(config)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def app(db_path):
    return make_app(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, name="Әлия", email="aliya@mail.kz", password="secret1", confirm=None):
    return client.post("/register", data={"name": name, "email": email, "password": password,
                                          "password_confirm": confirm if confirm is not None else password})


def login(client, email="aliya@mail.kz", password="secret1"):
    return client.post("/login", data={"email": email, "password": password})


@pytest.fixture
def auth_client(client):
    register(client)
    return client


def future(days=0, hours=0, minutes=0):
    dt = local_now(TZ) + timedelta(days=days, hours=hours, minutes=minutes)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def event_form(title="Математика емтиханы", date=None, time=None, **kw):
    if date is None:
        date, time = future(days=3)
    data = {"title": title, "description": "Аудитория 305", "category": "study", "event_date": date,
            "event_time": time, "priority": "high", "reminder_mode": "30m", "reminder_custom": ""}
    data.update(kw)
    return data

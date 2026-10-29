import sqlite3
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import event_form, future, make_app, register

import telegram_bot
from database import connect, init_db
from reminder_service import process_due_reminders
from utils import to_utc_str, utc_now


class FakeClient:
    def __init__(self):
        self.sent = []
        self.answers = []
        self.edits = []
        self.fail_with = None

    def send_message(self, chat_id, text, buttons=None):
        if self.fail_with:
            raise telegram_bot.TelegramError(self.fail_with, "fake error")
        self.sent.append((str(chat_id), text, buttons))
        return {"message_id": len(self.sent)}

    def answer_callback(self, callback_id, text):
        self.answers.append(text)

    def edit_message_text(self, chat_id, message_id, text):
        self.edits.append(text)


CHAT = 555001


@pytest.fixture
def fake():
    return FakeClient()


@pytest.fixture
def tg_app(db_path, fake):
    return make_app(db_path, TELEGRAM_CLIENT=fake)


@pytest.fixture
def tg_client(tg_app):
    c = tg_app.test_client()
    register(c)
    return c


def _start(db_path, fake, text, chat=CHAT, username="aliya_kz"):
    update = {"update_id": 1, "message": {"chat": {"id": chat}, "from": {"username": username}, "text": text}}
    telegram_bot.handle_update(str(db_path), update, fake)


def _link(client, db_path, fake, chat=CHAT):
    url = client.post("/api/telegram/link").get_json()["url"]
    token = parse_qs(urlparse(url).query)["start"][0]
    _start(db_path, fake, f"/start {token}", chat=chat)
    return url


def _settings(db_path, user_id=1):
    return connect(str(db_path)).execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()


def test_link_flow(tg_client, db_path, fake):
    assert tg_client.get("/api/telegram/status").get_json()["linked"] is False
    url = _link(tg_client, db_path, fake)
    assert url.startswith("https://t.me/EskeSalKzBot?start=")
    s = _settings(db_path)
    assert s["telegram_chat_id"] == str(CHAT) and s["telegram_link_token"] is None
    assert "Аккаунт сәтті қосылды" in fake.sent[-1][1]
    status = tg_client.get("/api/telegram/status").get_json()
    assert status["linked"] is True and status["name"] == "aliya_kz"


def test_invalid_or_expired_token_rejected(tg_client, db_path, fake):
    _start(db_path, fake, "/start wrong-token")
    assert "жарамсыз" in fake.sent[-1][1]
    tg_client.post("/api/telegram/link")
    db = connect(str(db_path))
    token = db.execute("SELECT telegram_link_token FROM user_settings").fetchone()[0]
    db.execute("UPDATE user_settings SET telegram_link_expires = ?", (to_utc_str(utc_now() - timedelta(minutes=1)),))
    db.commit()
    _start(db_path, fake, f"/start {token}")
    assert _settings(db_path)["telegram_chat_id"] is None


def test_token_is_single_use(tg_client, db_path, fake):
    url = tg_client.post("/api/telegram/link").get_json()["url"]
    token = parse_qs(urlparse(url).query)["start"][0]
    _start(db_path, fake, f"/start {token}")
    _start(db_path, fake, f"/start {token}", chat=999)
    assert _settings(db_path)["telegram_chat_id"] == str(CHAT)
    assert "жарамсыз" in fake.sent[-1][1]


def test_unknown_chat_gets_instructions(db_path, fake, tg_app):
    _start(db_path, fake, "/upcoming", chat=777)
    assert "Telegram-ды қосу" in fake.sent[-1][1]


def test_link_requires_login_and_configured_bot(db_path, fake):
    anon = make_app(db_path, TELEGRAM_CLIENT=fake).test_client()
    assert anon.post("/api/telegram/link").status_code == 401
    no_bot = make_app(db_path).test_client()
    register(no_bot)
    assert no_bot.post("/api/telegram/link").status_code == 503
    assert "Бот бапталмаған" in no_bot.get("/settings").get_data(as_text=True)


def test_reminder_delivered_once_with_done_button(tg_client, db_path, fake):
    _link(tg_client, db_path, fake)
    d, t = future(minutes=20)
    tg_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="30m"))
    process_due_reminders(str(db_path))
    fake.sent.clear()
    assert telegram_bot.deliver_pending(str(db_path), fake) == 1
    assert telegram_bot.deliver_pending(str(db_path), fake) == 0
    chat, text, buttons = fake.sent[0]
    assert chat == str(CHAT)
    assert "Еске салу" in text and "Математика емтиханы" in text and "Оқу" in text
    assert buttons[0] == [{"text": "✅ Орындалды", "callback_data": "done:1"}]
    assert [b["callback_data"] for b in buttons[1]] == ["snooze:1:10", "snooze:1:60"]


def test_not_delivered_when_disabled_or_not_linked(tg_client, db_path, fake):
    d, t = future(minutes=20)
    tg_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="30m"))
    process_due_reminders(str(db_path))
    assert telegram_bot.deliver_pending(str(db_path), fake) == 0
    _link(tg_client, db_path, fake)
    assert telegram_bot.deliver_pending(str(db_path), fake) == 0
    tg_client.post("/settings", data={"timezone": "Asia/Almaty", "date_format": "long",
                                      "default_reminder": "30m"})
    tg_client.post("/events/add", data=event_form(title="B", date=d, time=t, reminder_mode="10m"))
    process_due_reminders(str(db_path), now=utc_now() + timedelta(minutes=11))
    assert telegram_bot.deliver_pending(str(db_path), fake) == 0


def test_failed_send_is_retried_and_blocked_bot_unlinks(tg_client, db_path, fake):
    _link(tg_client, db_path, fake)
    d, t = future(minutes=20)
    tg_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="30m"))
    process_due_reminders(str(db_path))
    fake.fail_with = 500
    assert telegram_bot.deliver_pending(str(db_path), fake) == 0
    fake.fail_with = None
    assert telegram_bot.deliver_pending(str(db_path), fake) == 1

    tg_client.post("/events/add", data=event_form(title="B", date=d, time=t, reminder_mode="10m"))
    process_due_reminders(str(db_path), now=utc_now() + timedelta(minutes=11))
    fake.fail_with = 403
    telegram_bot.deliver_pending(str(db_path), fake)
    assert _settings(db_path)["telegram_chat_id"] is None


def _callback(db_path, fake, data, chat=CHAT):
    update = {"update_id": 2, "callback_query": {"id": "cb1", "data": data,
              "message": {"message_id": 10, "chat": {"id": chat}, "text": "Еске салу"}}}
    telegram_bot.handle_update(str(db_path), update, fake)


def test_done_button_marks_event_completed(tg_client, db_path, fake):
    _link(tg_client, db_path, fake)
    tg_client.post("/events/add", data=event_form())
    _callback(db_path, fake, "done:1")
    assert tg_client.get("/api/events/1").get_json()["is_completed"] is True
    assert fake.answers[-1].startswith("Орындалды")
    assert "Орындалды деп белгіленді" in fake.edits[-1]


def test_done_button_cannot_touch_other_users_event(tg_app, db_path, fake):
    a = tg_app.test_client()
    register(a)
    a.post("/events/add", data=event_form(title="Әлияның оқиғасы"))
    b = tg_app.test_client()
    register(b, name="Бақыт", email="bakyt@mail.kz")
    _link(b, db_path, fake, chat=888)
    _callback(db_path, fake, "done:1", chat=888)
    assert a.get("/api/events/1").get_json()["is_completed"] is False
    assert fake.answers[-1] == "Оқиға табылмады."


def test_upcoming_and_stop_commands(tg_client, db_path, fake):
    _link(tg_client, db_path, fake)
    tg_client.post("/events/add", data=event_form(title="Кездесу <b>"))
    _start(db_path, fake, "/upcoming")
    text = fake.sent[-1][1]
    assert "Алдағы оқиғалар" in text and "Кездесу &lt;b&gt;" in text
    _start(db_path, fake, "/stop")
    assert _settings(db_path)["telegram_chat_id"] is None


def test_test_message_and_unlink_api(tg_client, db_path, fake):
    assert tg_client.post("/api/telegram/test").status_code == 400
    _link(tg_client, db_path, fake)
    assert tg_client.post("/api/telegram/test").status_code == 200
    assert "Тексеру хабарламасы" in fake.sent[-1][1]
    tg_client.post("/api/telegram/unlink")
    assert tg_client.get("/api/telegram/status").get_json()["linked"] is False


def test_old_database_is_migrated_without_data_loss(tmp_path):
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                            password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE user_settings (user_id INTEGER PRIMARY KEY, language TEXT NOT NULL DEFAULT 'kk',
            timezone TEXT NOT NULL DEFAULT 'Asia/Almaty', browser_notifications INTEGER NOT NULL DEFAULT 1,
            default_reminder TEXT NOT NULL DEFAULT '30m', date_format TEXT NOT NULL DEFAULT 'long');
        CREATE TABLE notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            event_id INTEGER, event_title TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'sent',
            scheduled_for TEXT NOT NULL, created_at TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
            UNIQUE(event_id, scheduled_for));
        INSERT INTO users VALUES (1, 'Аружан', 'a@mail.kz', 'hash', '2026-10-27 13:53:35');
        INSERT INTO user_settings (user_id) VALUES (1);
    """)
    old.commit()
    old.close()
    init_db(path)
    init_db(path)
    db = connect(path)
    assert db.execute("SELECT name FROM users").fetchone()[0] == "Аружан"
    cols = {r["name"] for r in db.execute("PRAGMA table_info(user_settings)")}
    assert {"telegram_chat_id", "telegram_enabled", "telegram_link_token"} <= cols
    assert db.execute("SELECT telegram_enabled FROM user_settings").fetchone()[0] == 1

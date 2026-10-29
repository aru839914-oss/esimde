from datetime import date, timedelta

from conftest import event_form, future, make_app, register

import telegram_bot
from database import connect
from reminder_service import advance_recurring, process_due_reminders
from utils import next_occurrence, occurrence, occurrences_between, parse_utc_str, utc_now


def _db(db_path):
    return connect(str(db_path))


def _reminders(db_path, event_id=1):
    return _db(db_path).execute("SELECT * FROM reminders WHERE event_id = ? ORDER BY remind_at",
                                (event_id,)).fetchall()


def _event(db_path, event_id=1):
    return _db(db_path).execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()


def _multi(**kw):
    data = event_form(**kw)
    data.pop("reminder_mode")
    return data


def test_multiple_reminders_saved(auth_client, db_path):
    data = _multi(date="2026-11-10", time="09:00")
    data["reminders"] = ["1d", "1h", "10m"]
    auth_client.post("/events/add", data=data)
    rows = _reminders(db_path)
    assert [r["remind_at"] for r in rows] == ["2026-11-09 04:00:00", "2026-11-10 03:00:00", "2026-11-10 03:50:00"]
    ev = _event(db_path)
    assert ev["reminder_mode"] == "1d,1h,10m"
    assert ev["reminder_datetime"] == "2026-11-09 04:00:00"


def test_each_reminder_sent_separately_once(auth_client, db_path):
    d, t = future(minutes=50)
    data = _multi(date=d, time=t)
    data["reminders"] = ["1h", "30m", "10m"]
    auth_client.post("/events/add", data=data)
    assert process_due_reminders(str(db_path))["late"] == 1
    assert sum(process_due_reminders(str(db_path)).values()) == 0
    soon = utc_now() + timedelta(minutes=21)
    assert process_due_reminders(str(db_path), now=soon)["sent"] == 1
    later = utc_now() + timedelta(minutes=41)
    assert process_due_reminders(str(db_path), now=later)["sent"] == 1
    assert len(_db(db_path).execute("SELECT * FROM notifications").fetchall()) == 3
    assert _event(db_path)["reminder_sent"] == 1


def test_edit_keeps_sent_status_of_unchanged_reminders(auth_client, db_path):
    d, t = future(minutes=50)
    data = _multi(date=d, time=t)
    data["reminders"] = ["1h", "10m"]
    auth_client.post("/events/add", data=data)
    process_due_reminders(str(db_path))
    data["reminders"] = ["1h", "10m", "30m"]
    auth_client.post("/events/1/edit", data=data)
    sent = {r["offset_minutes"]: r["sent"] for r in _reminders(db_path)}
    assert sent == {60: 1, 30: 0, 10: 0}


def test_edit_form_shows_selected_reminders(auth_client):
    data = _multi()
    data["reminders"] = ["1d", "30m"]
    auth_client.post("/events/add", data=data)
    page = auth_client.get("/events/1/edit").get_data(as_text=True)
    assert 'id="rem-1d" value="1d"' in page
    assert page.count("checked") >= 2


def test_legacy_single_reminder_migrated(tmp_path):
    import sqlite3
    from database import init_db
    path = str(tmp_path / "legacy.db")
    init_db(path)
    db = sqlite3.connect(path)
    db.execute("INSERT INTO users (name, email, password_hash, created_at) VALUES ('A', 'a@a.kz', 'h', '2026-01-01 00:00:00')")
    db.execute("""INSERT INTO events (user_id, title, event_date, event_time, event_at_utc, reminder_enabled,
                  reminder_mode, reminder_datetime, reminder_sent, created_at, updated_at)
                  VALUES (1, 'Ескі', '2026-11-10', '09:00', '2026-11-10 04:00:00', 1, '30m',
                          '2026-11-10 03:30:00', 0, 'x', 'x')""")
    db.commit()
    db.close()
    init_db(path)
    init_db(path)
    rows = connect(path).execute("SELECT * FROM reminders").fetchall()
    assert len(rows) == 1 and rows[0]["offset_minutes"] == 30 and rows[0]["remind_at"] == "2026-11-10 03:30:00"


def test_snooze_creates_extra_reminder(auth_client, db_path):
    d, t = future(minutes=15)
    auth_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="30m"))
    process_due_reminders(str(db_path))
    resp = auth_client.post("/api/events/1/snooze", json={"minutes": 10})
    assert resp.status_code == 200 and "10 минуттан кейін" in resp.get_json()["message"]
    assert process_due_reminders(str(db_path))["sent"] == 0
    result = process_due_reminders(str(db_path), now=utc_now() + timedelta(minutes=11))
    assert result["sent"] == 1
    kinds = [r["kind"] for r in _reminders(db_path)]
    assert "snooze" in kinds


def test_snooze_after_event_start_is_still_delivered(auth_client, db_path):
    d, t = future(minutes=5)
    auth_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="10m"))
    auth_client.post("/api/events/1/snooze", json={"minutes": 30})
    result = process_due_reminders(str(db_path), now=utc_now() + timedelta(minutes=31))
    assert result["sent"] + result["late"] >= 1
    msg = _db(db_path).execute("SELECT message FROM notifications ORDER BY id DESC").fetchone()[0]
    assert "басталды" in msg


def test_snooze_validation_and_isolation(tg_free_two_users):
    a, b = tg_free_two_users
    assert b.post("/api/events/1/snooze", json={"minutes": 10}).status_code == 404
    assert a.post("/api/events/1/snooze", json={"minutes": 7}).status_code == 400
    a.post("/api/events/1/complete", json={"completed": True})
    assert a.post("/api/events/1/snooze", json={"minutes": 10}).status_code == 400


def test_telegram_snooze_button(db_path):
    from test_telegram import FakeClient, _link
    fake = FakeClient()
    c = make_app(db_path, TELEGRAM_CLIENT=fake).test_client()
    register(c)
    _link(c, db_path, fake)
    c.post("/events/add", data=event_form())
    update = {"update_id": 5, "callback_query": {"id": "cb", "data": "snooze:1:60",
              "message": {"message_id": 3, "chat": {"id": 555001}, "text": "Еске салу"}}}
    telegram_bot.handle_update(str(db_path), update, fake)
    assert "қайта еске саламын" in fake.answers[-1]
    assert any(r["kind"] == "snooze" for r in _reminders(db_path))


def test_occurrence_math():
    assert occurrence(date(2026, 1, 31), "monthly", 1) == date(2026, 2, 28)
    assert occurrence(date(2026, 1, 31), "monthly", 2) == date(2026, 3, 31)
    assert occurrence(date(2024, 2, 29), "yearly", 1) == date(2025, 2, 28)
    assert next_occurrence(date(2026, 1, 5), "weekly", date(2026, 1, 20)) == date(2026, 1, 26)
    assert next_occurrence(date(2020, 5, 1), "yearly", date(2026, 5, 1)) == date(2027, 5, 1)
    days = occurrences_between(date(2026, 11, 1), "daily", date(2026, 11, 10), date(2026, 11, 13))
    assert days == [date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12)]


def test_completing_recurring_event_moves_to_next_occurrence(auth_client, db_path):
    d, t = future(days=2)
    data = _multi(title="Ағылшын сабағы", date=d, time=t, recurrence="weekly")
    data["reminders"] = ["1h"]
    auth_client.post("/events/add", data=data)
    resp = auth_client.post("/api/events/1/complete", json={"completed": True}).get_json()
    assert resp["advanced"] is True and "Келесі қайталану" in resp["message"]
    ev = _event(db_path)
    assert ev["event_date"] == (date.fromisoformat(d) + timedelta(days=7)).isoformat()
    assert ev["is_completed"] == 0
    rem = _reminders(db_path)[0]
    assert rem["sent"] == 0
    assert parse_utc_str(ev["event_at_utc"]) - parse_utc_str(rem["remind_at"]) == timedelta(hours=1)


def test_past_recurring_event_advances_automatically(auth_client, db_path):
    auth_client.post("/events/add", data=event_form(title="Туған күн", date="2020-03-15", time="10:00",
                                                    category="birthday", recurrence="yearly",
                                                    reminder_mode="1d"))
    assert advance_recurring(str(db_path)) == 1
    ev = _event(db_path)
    assert ev["event_date"] > date.today().isoformat() and ev["event_date"].endswith("-03-15")
    assert advance_recurring(str(db_path)) == 0
    assert _reminders(db_path)[0]["sent"] == 0


def test_birthday_defaults_to_yearly(auth_client):
    page = auth_client.get("/events/add?category=birthday").get_data(as_text=True)
    assert '<option value="yearly" selected>' in page


def test_calendar_shows_future_occurrences(auth_client):
    auth_client.post("/events/add", data=event_form(title="Жүгіру", date="2026-11-02", time="07:00",
                                                    recurrence="weekly"))
    feed = auth_client.get("/api/events?start=2026-11-01&end=2026-12-01").get_json()
    starts = [e["start"] for e in feed]
    assert starts == ["2026-11-02T07:00:00", "2026-11-09T07:00:00", "2026-11-16T07:00:00",
                      "2026-11-23T07:00:00", "2026-11-30T07:00:00"]
    assert all(e["extendedProps"]["id"] == 1 for e in feed)
    assert feed[0]["extendedProps"]["recurrence_label"] == "Апта сайын"


def test_invalid_recurrence_rejected(auth_client):
    resp = auth_client.post("/events/add", data=event_form(recurrence="hourly"))
    assert resp.status_code == 400


import pytest


@pytest.fixture
def tg_free_two_users(app):
    a = app.test_client()
    register(a)
    d, t = future(days=1)
    a.post("/events/add", data=event_form(date=d, time=t))
    b = app.test_client()
    register(b, name="Бақыт", email="bakyt@mail.kz")
    return a, b

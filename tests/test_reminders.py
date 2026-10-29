from datetime import datetime, timedelta, timezone

from conftest import TZ, event_form, future, make_app, register

from database import connect
from reminder_service import process_due_reminders
from utils import compute_reminder_utc, local_to_utc, parse_utc_str, utc_now


def _event(db_path, event_id=1):
    return connect(str(db_path)).execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()


def _notifications(db_path):
    return connect(str(db_path)).execute("SELECT * FROM notifications ORDER BY id").fetchall()


def test_reminder_time_calculation_unit():
    event_utc = local_to_utc("2026-11-10", "09:00", TZ)
    assert event_utc == datetime(2026, 11, 10, 4, 0, tzinfo=timezone.utc)
    assert compute_reminder_utc(event_utc, "10m") == event_utc - timedelta(minutes=10)
    assert compute_reminder_utc(event_utc, "30m") == datetime(2026, 11, 10, 3, 30, tzinfo=timezone.utc)
    assert compute_reminder_utc(event_utc, "1h") == datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)
    assert compute_reminder_utc(event_utc, "1d") == datetime(2026, 11, 9, 4, 0, tzinfo=timezone.utc)
    assert compute_reminder_utc(event_utc, "none") is None
    assert compute_reminder_utc(event_utc, "custom", "2026-11-09T20:00", TZ) == \
        datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)


def test_reminder_time_saved_in_database(auth_client, db_path):
    auth_client.post("/events/add", data=event_form(date="2026-11-10", time="09:00", reminder_mode="30m"))
    ev = _event(db_path)
    assert ev["event_at_utc"] == "2026-11-10 04:00:00"
    assert ev["reminder_datetime"] == "2026-11-10 03:30:00"
    auth_client.post("/events/add", data=event_form(reminder_mode="none"))
    ev2 = _event(db_path, 2)
    assert ev2["reminder_enabled"] == 0 and ev2["reminder_datetime"] is None


def test_reminder_not_sent_before_time(auth_client, db_path):
    d, t = future(days=2)
    auth_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="1h"))
    assert process_due_reminders(str(db_path)) == {"sent": 0, "late": 0, "missed": 0}
    assert _event(db_path)["reminder_sent"] == 0


def test_reminder_sent_on_time_with_kazakh_message(auth_client, db_path):
    d, t = future(days=1)
    auth_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="30m"))
    reminder_at = parse_utc_str(_event(db_path)["reminder_datetime"])
    result = process_due_reminders(str(db_path), now=reminder_at + timedelta(seconds=10))
    assert result["sent"] == 1
    n = _notifications(db_path)[0]
    assert n["status"] == "sent" and n["delivered"] == 0
    assert n["message"] == "Еске салу: «Математика емтиханы» оқиғасына 30 минут қалды!"
    assert _event(db_path)["reminder_sent"] == 1


def test_reminder_one_day_message(auth_client, db_path):
    d, t = future(days=3)
    auth_client.post("/events/add", data=event_form(title="Кездесу", date=d, time=t, reminder_mode="1d"))
    reminder_at = parse_utc_str(_event(db_path)["reminder_datetime"])
    process_due_reminders(str(db_path), now=reminder_at)
    assert _notifications(db_path)[0]["message"].startswith("Еске салу: Ертең «Кездесу» оқиғасы бар")


def test_reminder_not_sent_twice(auth_client, db_path):
    d, t = future(minutes=20)
    auth_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="30m"))
    first = process_due_reminders(str(db_path))
    second = process_due_reminders(str(db_path))
    third = process_due_reminders(str(db_path), now=utc_now() + timedelta(minutes=5))
    assert sum(first.values()) == 1
    assert sum(second.values()) == 0 and sum(third.values()) == 0
    assert len(_notifications(db_path)) == 1


def test_parallel_workers_do_not_duplicate(auth_client, db_path):
    import threading
    d, t = future(minutes=5)
    for i in range(5):
        auth_client.post("/events/add", data=event_form(title=f"E{i}", date=d, time=t, reminder_mode="10m"))
    threads = [threading.Thread(target=process_due_reminders, args=(str(db_path),)) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    rows = _notifications(db_path)
    assert len(rows) == 5
    assert len({r["event_id"] for r in rows}) == 5


def test_completed_event_gets_no_reminder(auth_client, db_path):
    d, t = future(minutes=20)
    auth_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="30m"))
    auth_client.post("/api/events/1/complete", json={"completed": True})
    assert sum(process_due_reminders(str(db_path)).values()) == 0
    assert _notifications(db_path) == []


def test_past_event_reminder_marked_missed_not_delivered(auth_client, db_path):
    d, t = future(days=1)
    auth_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="1h"))
    event_at = parse_utc_str(_event(db_path)["event_at_utc"])
    result = process_due_reminders(str(db_path), now=event_at + timedelta(hours=2))
    assert result == {"sent": 0, "late": 0, "missed": 1}
    n = _notifications(db_path)[0]
    assert n["status"] == "missed" and n["delivered"] == 1
    assert auth_client.get("/api/notifications/pending").get_json() == []


def test_late_reminder_after_downtime_still_delivered(auth_client, db_path):
    d, t = future(days=1)
    auth_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="1h"))
    reminder_at = parse_utc_str(_event(db_path)["reminder_datetime"])
    result = process_due_reminders(str(db_path), now=reminder_at + timedelta(minutes=40))
    assert result["late"] == 1
    assert "20 минут қалды" in _notifications(db_path)[0]["message"]


def test_editing_reminder_time_reschedules(auth_client, db_path):
    d, t = future(minutes=20)
    auth_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="30m"))
    process_due_reminders(str(db_path))
    assert _event(db_path)["reminder_sent"] == 1
    d2, t2 = future(days=2)
    auth_client.post("/events/1/edit", data=event_form(date=d2, time=t2, reminder_mode="1h"))
    assert _event(db_path)["reminder_sent"] == 0
    process_due_reminders(str(db_path), now=parse_utc_str(_event(db_path)["reminder_datetime"]))
    auth_client.post("/events/1/edit", data=event_form(date=d2, time=t2, reminder_mode="1h", description="Жаңа"))
    assert _event(db_path)["reminder_sent"] == 1


def test_reminders_restored_after_restart(db_path):
    c1 = make_app(db_path).test_client()
    register(c1)
    d, t = future(days=1)
    c1.post("/events/add", data=event_form(date=d, time=t, reminder_mode="30m"))
    make_app(db_path)
    reminder_at = parse_utc_str(_event(db_path)["reminder_datetime"])
    assert process_due_reminders(str(db_path), now=reminder_at)["sent"] == 1


def test_in_app_notifications_work_without_browser_permission(auth_client, db_path):
    auth_client.post("/settings", data={"timezone": TZ, "date_format": "long", "default_reminder": "30m"})
    page = auth_client.get("/").get_data(as_text=True)
    assert 'data-browser-notify="0"' in page
    d, t = future(minutes=10)
    auth_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="30m"))
    process_due_reminders(str(db_path))
    pending = auth_client.get("/api/notifications/pending").get_json()
    assert len(pending) == 1 and pending[0]["message"].startswith("Еске салу:")
    ack = auth_client.post("/api/notifications/ack", json={"ids": [pending[0]["id"]]}).get_json()
    assert ack["acknowledged"] == 1
    assert auth_client.get("/api/notifications/pending").get_json() == []
    body = auth_client.get("/reminders").get_data(as_text=True)
    assert "Жіберілген хабарландырулар" in body and "оқиғасына" in body


def test_reminders_page_groups(auth_client, db_path):
    d, t = future(days=3)
    auth_client.post("/events/add", data=event_form(title="Алдағы", date=d, time=t, reminder_mode="1h"))
    d, t = future(minutes=20)
    auth_client.post("/events/add", data=event_form(title="Жақында", date=d, time=t, reminder_mode="10m"))
    body = auth_client.get("/reminders").get_data(as_text=True)
    assert "Бүгінгі еске салулар" in body and "Алдағы еске салулар" in body and "Өткен еске салулар" in body
    assert "Алдағы" in body and "Жақында" in body

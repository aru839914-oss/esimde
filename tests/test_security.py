from conftest import event_form, make_app, register

from database import connect


def _two_users(client):
    register(client)
    client.post("/events/add", data=event_form(title="Әлияның құпия оқиғасы"))
    client.post("/logout")
    register(client, name="Бақыт", email="bakyt@mail.kz")
    return client


def test_user_sees_only_own_events(client):
    c = _two_users(client)
    assert "Әлияның құпия оқиғасы" not in c.get("/events").get_data(as_text=True)
    assert "Әлияның құпия оқиғасы" not in c.get("/").get_data(as_text=True)
    feed = c.get("/api/events?start=2000-01-01&end=2100-01-01").get_json()
    assert feed == []
    assert c.get("/api/stats").get_json()["total"] == 0


def test_cannot_access_other_users_event_by_id(client, db_path):
    c = _two_users(client)
    assert c.get("/api/events/1").status_code == 404
    assert c.get("/events/1/edit").status_code == 404
    assert c.post("/events/1/edit", data=event_form(title="Бұзылды")).status_code == 404
    assert c.post("/api/events/1/complete", json={"completed": True}).status_code == 404
    assert c.post("/events/1/delete").status_code == 404
    ev = connect(str(db_path)).execute("SELECT * FROM events WHERE id = 1").fetchone()
    assert ev["title"] == "Әлияның құпия оқиғасы" and ev["is_completed"] == 0


def test_cannot_ack_other_users_notifications(client, db_path):
    from reminder_service import process_due_reminders
    from conftest import future
    register(client)
    d, t = future(minutes=5)
    client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="10m"))
    process_due_reminders(str(db_path))
    client.post("/logout")
    register(client, name="Бақыт", email="bakyt@mail.kz")
    assert client.get("/api/notifications/pending").get_json() == []
    assert client.post("/api/notifications/ack", json={"ids": [1]}).get_json()["acknowledged"] == 0


def test_csrf_protection_enabled(db_path):
    app = make_app(db_path, WTF_CSRF_ENABLED=True)
    c = app.test_client()
    c.post("/register", data={"name": "X", "email": "x@mail.kz", "password": "secret1", "password_confirm": "secret1"})
    assert connect(str(db_path)).execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    resp = c.post("/api/notifications/ack", json={"ids": []})
    assert resp.status_code in (400, 401)


def test_sql_injection_in_search_is_harmless(auth_client, db_path):
    auth_client.post("/events/add", data=event_form(title="Қалыпты оқиға"))
    resp = auth_client.get("/events?q=' OR 1=1 --&sort=date_asc; DROP TABLE events")
    assert resp.status_code == 200
    assert "Ештеңе табылмады" in resp.get_data(as_text=True)
    assert connect(str(db_path)).execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    resp = auth_client.get("/events?q=100%_")
    assert resp.status_code == 200


def test_session_cookie_flags(client):
    resp = register(client)
    cookie = resp.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie

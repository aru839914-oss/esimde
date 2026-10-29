import re

from conftest import event_form, future, make_app, register

from database import connect


def _events(db_path):
    return connect(str(db_path)).execute("SELECT * FROM events ORDER BY id").fetchall()


def test_add_event_success(auth_client):
    resp = auth_client.post("/events/add", data=event_form(), follow_redirects=True)
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "«Математика емтиханы» оқиғасы сәтті қосылды." in body
    assert "Математика емтиханы" in body


def test_event_saved_in_database(auth_client, db_path):
    date, time = future(days=5)
    auth_client.post("/events/add", data=event_form(date=date, time=time))
    rows = _events(db_path)
    assert len(rows) == 1
    ev = rows[0]
    assert (ev["title"], ev["category"], ev["priority"]) == ("Математика емтиханы", "study", "high")
    assert (ev["event_date"], ev["event_time"]) == (date, time)
    assert ev["reminder_enabled"] == 1 and ev["reminder_sent"] == 0 and ev["is_completed"] == 0
    assert ev["user_id"] == 1 and ev["created_at"] and ev["updated_at"]


def test_edit_event(auth_client, db_path):
    auth_client.post("/events/add", data=event_form())
    page = auth_client.get("/events/1/edit").get_data(as_text=True)
    assert 'value="Математика емтиханы"' in page
    date, time = future(days=10)
    resp = auth_client.post("/events/1/edit", data=event_form(title="Физика емтиханы", date=date, time=time,
                                                              category="work", priority="low"))
    assert resp.status_code == 302
    ev = _events(db_path)[0]
    assert (ev["title"], ev["category"], ev["priority"], ev["event_date"]) == ("Физика емтиханы", "work", "low", date)


def test_delete_event(auth_client, db_path):
    auth_client.post("/events/add", data=event_form())
    resp = auth_client.post("/events/1/delete", follow_redirects=True)
    assert "оқиғасы жойылды" in resp.get_data(as_text=True)
    assert _events(db_path) == []
    assert auth_client.get("/api/events/1").status_code == 404
    assert auth_client.get("/events/1/delete").status_code == 405


def test_empty_title_rejected(auth_client, db_path):
    resp = auth_client.post("/events/add", data=event_form(title="   "))
    assert resp.status_code == 400
    assert "Оқиға атауын енгізіңіз." in resp.get_data(as_text=True)
    assert _events(db_path) == []


def test_invalid_date_and_time_rejected(auth_client, db_path):
    resp = auth_client.post("/events/add", data=event_form(date="2026-13-45", time="25:99"))
    body = resp.get_data(as_text=True)
    assert resp.status_code == 400
    assert "Күнді дұрыс енгізіңіз" in body and "Уақытты дұрыс енгізіңіз" in body
    assert _events(db_path) == []


def test_custom_reminder_after_event_rejected(auth_client):
    date, time = future(days=2)
    resp = auth_client.post("/events/add", data=event_form(date=date, time=time, reminder_mode="custom",
                                                           reminder_custom=f"{future(days=3)[0]}T10:00"))
    assert resp.status_code == 400
    assert "Еске салу уақыты оқиға басталғаннан кейін болмауы керек." in resp.get_data(as_text=True)


def test_past_event_shows_warning(auth_client):
    resp = auth_client.post("/events/add", data=event_form(date="2020-01-01", time="10:00"), follow_redirects=True)
    assert "оқиға уақыты өтіп кеткен" in resp.get_data(as_text=True)
    assert "өткен уақытқа жоспарланған" in auth_client.get("/events/1/edit").get_data(as_text=True)


def test_events_sorted_by_date(auth_client):
    for title, days in [("Үшінші", 9), ("Бірінші", 1), ("Екінші", 4)]:
        d, t = future(days=days)
        auth_client.post("/events/add", data=event_form(title=title, date=d, time=t))
    assert _titles(auth_client, "/events?sort=date_asc") == ["Бірінші", "Екінші", "Үшінші"]
    assert _titles(auth_client, "/events?sort=date_desc") == ["Үшінші", "Екінші", "Бірінші"]


def _titles(client, url):
    return re.findall(r'class="event-title" data-event-id="\d+">([^<]+)<', client.get(url).get_data(as_text=True))


def test_search_and_filters(auth_client):
    auth_client.post("/events/add", data=event_form(title="Математика", category="study", priority="high"))
    auth_client.post("/events/add", data=event_form(title="Туған күн кеші", category="birthday", priority="low"))
    assert _titles(auth_client, "/events?q=туған") == ["Туған күн кеші"]
    assert _titles(auth_client, "/events?q=МАТЕМ") == ["Математика"]
    assert _titles(auth_client, "/events?category=study") == ["Математика"]
    assert _titles(auth_client, "/events?priority=low") == ["Туған күн кеші"]


def test_completed_event_counted_in_stats(auth_client):
    auth_client.post("/events/add", data=event_form(title="A"))
    auth_client.post("/events/add", data=event_form(title="B"))
    stats = auth_client.get("/api/stats").get_json()
    assert (stats["total"], stats["completed"], stats["upcoming"]) == (2, 0, 2)
    resp = auth_client.post("/api/events/1/complete", json={"completed": True})
    assert resp.get_json()["event"]["is_completed"] is True
    stats = auth_client.get("/api/stats").get_json()
    assert (stats["total"], stats["completed"], stats["upcoming"], stats["completed_percent"]) == (2, 1, 1, 50)
    assert _titles(auth_client, "/events?status=completed") == ["A"]
    assert _titles(auth_client, "/events?status=active") == ["B"]
    auth_client.post("/api/events/1/complete", json={"completed": False})
    assert auth_client.get("/api/stats").get_json()["completed"] == 0


def test_dashboard_week_and_today_counts(auth_client):
    d, t = future(minutes=5)
    auth_client.post("/events/add", data=event_form(title="Жақын", date=d, time=t))
    d, t = future(days=20)
    auth_client.post("/events/add", data=event_form(title="Алыс", date=d, time=t))
    today = future()[0]
    auth_client.post("/events/add", data=event_form(title="Бүгін өткен", date=today, time="00:00"))
    stats = auth_client.get("/api/stats").get_json()
    assert stats["total"] == 3
    assert stats["week"] == 1
    assert stats["today"] >= 1 and stats["overdue"] >= 1


def test_dashboard_empty_state(auth_client):
    assert "Алғашқы оқиғаңызды қосыңыз" in auth_client.get("/").get_data(as_text=True)


def test_events_persist_after_restart(db_path):
    app1 = make_app(db_path)
    c1 = app1.test_client()
    register(c1)
    c1.post("/events/add", data=event_form(title="Сақталатын оқиға"))

    app2 = make_app(db_path)
    c2 = app2.test_client()
    c2.post("/login", data={"email": "aliya@mail.kz", "password": "secret1"})
    assert "Сақталатын оқиға" in c2.get("/events").get_data(as_text=True)


def test_calendar_feed(auth_client):
    auth_client.post("/events/add", data=event_form(title="Кездесу", date="2026-11-10", time="14:30",
                                                    category="meeting"))
    auth_client.post("/events/add", data=event_form(title="Желтоқсандағы", date="2026-12-20", time="10:00"))
    feed = auth_client.get("/api/events?start=2026-11-01T00:00:00+05:00&end=2026-12-01T00:00:00+05:00").get_json()
    assert len(feed) == 1
    ev = feed[0]
    assert ev["title"] == "Кездесу"
    assert ev["start"] == "2026-11-10T14:30:00"
    assert ev["backgroundColor"] == "#f97316"
    assert ev["extendedProps"]["category_label"] == "Кездесу"
    assert auth_client.get("/calendar").status_code == 200


def test_event_detail_api_and_404(auth_client):
    auth_client.post("/events/add", data=event_form())
    data = auth_client.get("/api/events/1").get_json()
    assert data["title"] == "Математика емтиханы" and data["priority_label"] == "Жоғары"
    resp = auth_client.get("/api/events/999")
    assert resp.status_code == 404 and resp.get_json()["error"]
    assert auth_client.get("/events/999/edit").status_code == 404

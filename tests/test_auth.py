from conftest import login, register

from database import connect


def test_register_success_creates_user_with_hashed_password(client, db_path):
    resp = register(client)
    assert resp.status_code == 302 and resp.headers["Location"] == "/"
    row = connect(str(db_path)).execute("SELECT * FROM users WHERE email = ?", ("aliya@mail.kz",)).fetchone()
    assert row["name"] == "Әлия"
    assert row["password_hash"] != "secret1"
    assert row["password_hash"].startswith(("scrypt:", "pbkdf2:"))
    page = client.get("/").get_data(as_text=True)
    assert "Қош келдіңіз, Әлия!" in page


def test_register_duplicate_email_rejected(client):
    register(client)
    client.post("/logout")
    resp = register(client, email="ALIYA@mail.kz")
    assert resp.status_code == 400
    assert "Бұл электрондық пошта бұрын тіркелген." in resp.get_data(as_text=True)


def test_register_password_mismatch(client):
    resp = register(client, confirm="other12")
    assert resp.status_code == 400
    assert "Құпиясөздер сәйкес келмейді." in resp.get_data(as_text=True)


def test_register_invalid_email_and_empty_fields(client):
    resp = register(client, name="", email="not-an-email")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 400
    assert "Атыңызды енгізіңіз." in body
    assert "Электрондық пошта форматы қате" in body


def test_login_wrong_password(client):
    register(client)
    client.post("/logout")
    resp = login(client, password="wrong-pass")
    assert resp.status_code == 401
    assert "Электрондық пошта немесе құпиясөз қате." in resp.get_data(as_text=True)


def test_login_and_logout(client):
    register(client)
    client.post("/logout")
    assert login(client).status_code == 302
    assert client.get("/events").status_code == 200
    resp = client.post("/logout")
    assert resp.status_code == 302 and resp.headers["Location"] == "/login"
    assert client.get("/events").status_code == 302
    assert client.get("/api/events/1").status_code == 401


def test_anonymous_redirected_to_login(client):
    resp = client.get("/")
    assert resp.status_code == 302 and resp.headers["Location"].startswith("/login")
    for url in ["/calendar", "/events", "/events/add", "/reminders", "/categories", "/settings", "/profile"]:
        assert client.get(url).status_code == 302, url
    api = client.get("/api/events")
    assert api.status_code == 401 and api.is_json


def test_login_next_param_prevents_open_redirect(client):
    register(client)
    client.post("/logout")
    resp = client.post("/login?next=//evil.example.com", data={"email": "aliya@mail.kz", "password": "secret1"})
    assert resp.headers["Location"] == "/"
    client.post("/logout")
    resp = client.post("/login?next=/calendar", data={"email": "aliya@mail.kz", "password": "secret1"})
    assert resp.headers["Location"] == "/calendar"


def test_profile_shows_user_data_and_counts(auth_client):
    from conftest import event_form
    auth_client.post("/events/add", data=event_form())
    body = auth_client.get("/profile").get_data(as_text=True)
    assert "aliya@mail.kz" in body and "Әлия" in body
    assert "Алдағы оқиғалар" in body

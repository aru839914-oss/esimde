from datetime import timedelta

import pytest
from conftest import event_form, future, make_app, register

import push_service
from database import connect
from reminder_service import process_due_reminders
from utils import utc_now

SECRET = "test-secret"
SUB = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "BPkey", "auth": "authkey"}}


class FakeSender:
    public_key = "BFakePublicKey"

    def __init__(self):
        self.sent = []
        self.fail_status = None

    def send(self, subscription, payload, ttl=3600):
        if self.fail_status:
            raise push_service.PushError(self.fail_status, "fake")
        self.sent.append((subscription["endpoint"], payload))


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def push_client(db_path, sender):
    c = make_app(db_path, PUSH_SENDER=sender).test_client()
    register(c)
    return c


def _due_event(client, db_path, minutes=20, mode="30m"):
    d, t = future(minutes=minutes)
    client.post("/events/add", data=event_form(date=d, time=t, reminder_mode=mode))
    process_due_reminders(str(db_path))


def test_subscribe_and_key(push_client, db_path):
    key = push_client.get("/api/push/key").get_json()
    assert key["enabled"] is True and key["public_key"] == "BFakePublicKey" and key["devices"] == 0
    assert push_client.post("/api/push/subscribe", json=SUB).status_code == 200
    assert push_client.get("/api/push/key").get_json()["devices"] == 1
    push_client.post("/api/push/subscribe", json=SUB)
    assert connect(str(db_path)).execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] == 1


def test_invalid_subscription_rejected(push_client):
    assert push_client.post("/api/push/subscribe", json={"endpoint": "http://bad"}).status_code == 400
    assert push_client.post("/api/push/subscribe", json={}).status_code == 400


def test_push_disabled_without_sender(db_path):
    c = make_app(db_path).test_client()
    register(c)
    assert c.get("/api/push/key").get_json()["enabled"] is False
    assert c.post("/api/push/subscribe", json=SUB).status_code == 503


def test_reminder_delivered_by_push_once(push_client, db_path, sender):
    push_client.post("/api/push/subscribe", json=SUB)
    _due_event(push_client, db_path)
    assert push_service.deliver_pending_push(str(db_path), sender, SECRET) == 1
    assert push_service.deliver_pending_push(str(db_path), sender, SECRET) == 0
    endpoint, payload = sender.sent[0]
    assert endpoint == SUB["endpoint"]
    assert payload["title"] == "Esimde" and "Математика емтиханы" in payload["body"]
    assert payload["url"] == "/?event=1" and payload["token"]


def test_old_notifications_not_pushed_after_subscribe(push_client, db_path, sender):
    _due_event(push_client, db_path)
    push_client.post("/api/push/subscribe", json=SUB)
    assert push_service.deliver_pending_push(str(db_path), sender, SECRET) == 0


def test_no_push_when_browser_notifications_disabled(push_client, db_path, sender):
    push_client.post("/api/push/subscribe", json=SUB)
    push_client.post("/settings", data={"timezone": "Asia/Almaty", "date_format": "long", "default_reminder": "30m"})
    _due_event(push_client, db_path)
    assert push_service.deliver_pending_push(str(db_path), sender, SECRET) == 0


def test_expired_subscription_removed_and_retry_on_error(push_client, db_path, sender):
    push_client.post("/api/push/subscribe", json=SUB)
    _due_event(push_client, db_path)
    sender.fail_status = 500
    assert push_service.deliver_pending_push(str(db_path), sender, SECRET) == 0
    sender.fail_status = None
    assert push_service.deliver_pending_push(str(db_path), sender, SECRET) == 1
    sender.fail_status = 410
    push_service.send_to_user(connect(str(db_path)), sender, 1, {"title": "x", "body": "y"})
    assert connect(str(db_path)).execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] == 0


def test_push_action_done_and_snooze(push_client, db_path, sender):
    push_client.post("/api/push/subscribe", json=SUB)
    _due_event(push_client, db_path)
    push_service.deliver_pending_push(str(db_path), sender, SECRET)
    token = sender.sent[0][1]["token"]
    anon = push_client.application.test_client()
    resp = anon.post("/api/push/action", json={"token": token, "action": "snooze10"})
    assert resp.status_code == 200 and "қайта еске саламын" in resp.get_json()["message"]
    resp = anon.post("/api/push/action", json={"token": token, "action": "done"})
    assert resp.get_json()["message"] == "Оқиға орындалды деп белгіленді."
    assert push_client.get("/api/events/1").get_json()["is_completed"] is True
    assert anon.post("/api/push/action", json={"token": token, "action": "done"}).get_json()["message"] \
        == "Бұл оқиға бұрын белгіленген."


def test_push_action_rejects_forged_token(push_client):
    anon = push_client.application.test_client()
    forged = push_service.make_action_token("wrong-secret", 1, 1, "2026-11-10")
    assert anon.post("/api/push/action", json={"token": forged, "action": "done"}).status_code == 403
    assert anon.post("/api/push/action", json={"token": "garbage", "action": "done"}).status_code == 403


def test_push_action_on_recurring_event_advances_once(push_client, db_path, sender):
    push_client.post("/api/push/subscribe", json=SUB)
    d, t = future(minutes=20)
    push_client.post("/events/add", data=event_form(date=d, time=t, reminder_mode="30m", recurrence="daily"))
    process_due_reminders(str(db_path))
    push_service.deliver_pending_push(str(db_path), sender, SECRET)
    token = sender.sent[0][1]["token"]
    anon = push_client.application.test_client()
    anon.post("/api/push/action", json={"token": token, "action": "done"})
    first = push_client.get("/api/events/1").get_json()["event_date"]
    anon.post("/api/push/action", json={"token": token, "action": "done"})
    assert push_client.get("/api/events/1").get_json()["event_date"] == first


def test_unsubscribe_and_test_endpoint(push_client, sender):
    assert push_client.post("/api/push/test").status_code == 400
    push_client.post("/api/push/subscribe", json=SUB)
    assert push_client.post("/api/push/test").status_code == 200
    assert "тексеру" in sender.sent[-1][1]["body"]
    push_client.post("/api/push/unsubscribe", json={"endpoint": SUB["endpoint"]})
    assert push_client.get("/api/push/key").get_json()["devices"] == 0


def test_pwa_routes(client):
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.content_type
    assert b"addEventListener('push'" in sw.data
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200 and manifest.get_json()["short_name"] == "Esimde"
    assert client.get("/offline").status_code == 200
    login = client.get("/login").get_data(as_text=True)
    assert 'rel="manifest"' in login and "apple-touch-icon" in login


def test_vapid_keys_generated_once(tmp_path):
    path1, pub1 = push_service.load_or_create_vapid(str(tmp_path))
    path2, pub2 = push_service.load_or_create_vapid(str(tmp_path))
    assert path1 == path2 and pub1 == pub2 and len(pub1) == 87

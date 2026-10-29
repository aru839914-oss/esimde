from datetime import timedelta

import models
from config import Config
from database import connect, init_db
from utils import local_now, to_utc_str

TZ = "Asia/Almaty"
NAME = "Айгерим"
EMAIL = "demo@mail.kz"
PASSWORD = "Demo12345"


def main():
    init_db(Config.DATABASE)
    db = connect(Config.DATABASE)
    removed = db.execute("DELETE FROM users WHERE email = ?", (EMAIL,)).rowcount
    db.commit()
    user_id = models.create_user(db, NAME, EMAIL, PASSWORD)

    now = local_now(TZ)
    today = now.date()

    def day(n):
        return (today + timedelta(days=n)).isoformat()

    soon_event = (now + timedelta(minutes=30)).replace(second=0, microsecond=0)
    soon_reminder = (now + timedelta(minutes=3)).replace(second=0, microsecond=0)

    events = [
        dict(title="Тіс дәрігеріне бару", description="«Ақ тіс» клиникасы, 3-кабинет",
             category="personal", priority="medium",
             event_date=soon_event.strftime("%Y-%m-%d"), event_time=soon_event.strftime("%H:%M"),
             reminders=["custom"], reminder_custom=soon_reminder.strftime("%Y-%m-%dT%H:%M")),
        dict(title="Ағылшын тілі сабағы", description="Unit 5 үй тапсырмасын тексеру",
             category="study", priority="low", event_date=day(1), event_time="08:30", reminders=["30m"]),
        dict(title="Жобалық топпен кездесу", description="Курстық жобаның жоспарын талқылау",
             category="meeting", priority="medium", event_date=day(1), event_time="14:30", reminders=["30m"]),
        dict(title="Апталық есепті тапсыру", description="Бөлім басшысына жіберу",
             category="work", priority="medium", event_date=day(2), event_time="17:00", reminders=["1h"]),
        dict(title="Математика емтиханы", description="Аудитория 305, калькулятор алу",
             category="study", priority="high", event_date=day(3), event_time="10:00", reminders=["1d", "1h"]),
        dict(title="Анамның туған күні", description="Гүл мен торт алу",
             category="birthday", priority="high", event_date=day(6), event_time="19:00",
             reminders=["1d"], recurrence="yearly"),
        dict(title="Отбасылық мереке кеші", description="Әжемнің үйінде",
             category="holiday", priority="low", event_date=day(8), event_time="18:00", reminders=["1d"]),
        dict(title="Курстық жұмысты тапсыру", description="Түсіндірме жазба + презентация",
             category="study", priority="high", event_date=day(11), event_time="09:00", reminders=["1w", "1d"]),
    ]

    created = {}
    for ev in events:
        data = {"description": "", "reminder_custom": "", "recurrence": "none", **ev}
        data["reminder_mode"] = ",".join(data["reminders"]) or "none"
        created[ev["title"]] = models.create_event(db, user_id, data, TZ)

    models.set_completed(db, user_id, created["Ағылшын тілі сабағы"], True, TZ)
    db.close()

    print(f"Old demo account removed: {'yes' if removed else 'no'}")
    print(f"User: {NAME} / {EMAIL} / {PASSWORD}")
    print(f"Events created: {len(events)} (1 completed)")
    print(f"Reminder «Тіс дәрігеріне бару» at {soon_reminder:%H:%M} (event at {soon_event:%H:%M}), "
          f"UTC {to_utc_str(soon_reminder)}")


if __name__ == "__main__":
    main()

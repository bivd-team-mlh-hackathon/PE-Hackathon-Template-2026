import csv
import os
import random
from datetime import datetime, timedelta

from dotenv import load_dotenv
from peewee import chunked


def _parse_bool(value):
    return str(value).strip().lower() in ("true", "1", "yes")


# ── CSV loaders (used when files exist locally or are uploaded to server) ──────


def _load_users(db, User, filepath):
    with open(filepath, newline="") as f:
        rows = list(csv.DictReader(f))

    data = [
        {
            "id": int(r["id"]),
            "username": r["username"],
            "email": r["email"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]

    with db.atomic():
        for batch in chunked(data, 100):
            User.insert_many(batch).execute()

    max_id = max(r["id"] for r in data)
    db.execute_sql(f"SELECT setval(pg_get_serial_sequence('users', 'id'), {max_id})")
    print(f"  Loaded {len(data)} users")


def _load_urls(db, Url, filepath):
    with open(filepath, newline="") as f:
        rows = list(csv.DictReader(f))

    data = [
        {
            "id": int(r["id"]),
            "user_id": int(r["user_id"]) if r.get("user_id") else None,
            "short_code": r["short_code"],
            "original_url": r["original_url"],
            "title": r.get("title") or None,
            "is_active": _parse_bool(r["is_active"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]

    with db.atomic():
        for batch in chunked(data, 100):
            Url.insert_many(batch).execute()

    max_id = max(r["id"] for r in data)
    db.execute_sql(f"SELECT setval(pg_get_serial_sequence('urls', 'id'), {max_id})")
    print(f"  Loaded {len(data)} URLs")


def _load_events(db, Event, filepath):
    with open(filepath, newline="") as f:
        rows = list(csv.DictReader(f))

    data = [
        {
            "id": int(r["id"]),
            "url_id": int(r["url_id"]),
            "user_id": int(r["user_id"]) if r.get("user_id") else None,
            "event_type": r["event_type"],
            "timestamp": r["timestamp"],
            "details": r.get("details") or None,
        }
        for r in rows
    ]

    with db.atomic():
        for batch in chunked(data, 100):
            Event.insert_many(batch).execute()

    max_id = max(r["id"] for r in data)
    db.execute_sql(f"SELECT setval(pg_get_serial_sequence('events', 'id'), {max_id})")
    print(f"  Loaded {len(data)} events")


# ── Faker generators (fallback when CSVs are not present) ─────────────────────


def _generate_users(db, User, count=100):
    from faker import Faker

    fake = Faker()
    Faker.seed(42)
    now = datetime.utcnow()

    data = [
        {
            "id": i + 1,
            "username": fake.unique.user_name(),
            "email": fake.unique.email(),
            "created_at": (now - timedelta(days=random.randint(0, 365))).isoformat(),
        }
        for i in range(count)
    ]

    with db.atomic():
        for batch in chunked(data, 100):
            User.insert_many(batch).execute()

    db.execute_sql(f"SELECT setval(pg_get_serial_sequence('users', 'id'), {count})")
    print(f"  Generated {len(data)} users (Faker)")
    return data


def _generate_urls(db, Url, user_ids, count=500):
    from faker import Faker

    from app.utils import to_base62

    fake = Faker()
    Faker.seed(42)
    now = datetime.utcnow()

    data = []
    for i in range(count):
        url_id = i + 1
        created = now - timedelta(days=random.randint(0, 365))
        data.append(
            {
                "id": url_id,
                "user_id": random.choice(user_ids) if random.random() > 0.1 else None,
                "short_code": to_base62(url_id),
                "original_url": fake.url(),
                "title": fake.sentence(nb_words=4) if random.random() > 0.3 else None,
                "is_active": random.random() > 0.05,
                "created_at": created.isoformat(),
                "updated_at": created.isoformat(),
            }
        )

    with db.atomic():
        for batch in chunked(data, 100):
            Url.insert_many(batch).execute()

    db.execute_sql(f"SELECT setval(pg_get_serial_sequence('urls', 'id'), {count})")
    print(f"  Generated {len(data)} URLs (Faker)")
    return data


def _generate_events(db, Event, url_ids, user_ids, count=2000):
    EVENT_TYPES = ["click", "create", "delete", "update"]
    now = datetime.utcnow()

    data = [
        {
            "id": i + 1,
            "url_id": random.choice(url_ids),
            "user_id": random.choice(user_ids) if random.random() > 0.2 else None,
            "event_type": random.choice(EVENT_TYPES),
            "timestamp": (
                now
                - timedelta(
                    days=random.randint(0, 365), seconds=random.randint(0, 86400)
                )
            ).isoformat(),
            "details": None,
        }
        for i in range(count)
    ]

    with db.atomic():
        for batch in chunked(data, 100):
            Event.insert_many(batch).execute()

    db.execute_sql(f"SELECT setval(pg_get_serial_sequence('events', 'id'), {count})")
    print(f"  Generated {len(data)} events (Faker)")


# ── Entry point ────────────────────────────────────────────────────────────────


def seed_all():
    load_dotenv()

    from app import create_app

    create_app()

    from app.database import db
    from app.models.event import Event
    from app.models.url import Url
    from app.models.user import User

    db.connect(reuse_if_open=True)

    print("Creating tables...")
    db.create_tables([User, Url, Event], safe=True)

    if User.select().count() > 0:
        print("Database already seeded, skipping.")
        db.close()
        return

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    users_csv = os.path.join(base_dir, "users.csv")
    urls_csv = os.path.join(base_dir, "urls.csv")
    events_csv = os.path.join(base_dir, "events.csv")

    if all(os.path.isfile(p) for p in [users_csv, urls_csv, events_csv]):
        print("CSV files found — seeding from files...")
        print("Seeding users...")
        _load_users(db, User, users_csv)
        print("Seeding URLs...")
        _load_urls(db, Url, urls_csv)
        print("Seeding events...")
        _load_events(db, Event, events_csv)
    else:
        print("CSV files not found — generating seed data with Faker...")
        users = _generate_users(db, User)
        user_ids = [u["id"] for u in users]
        urls = _generate_urls(db, Url, user_ids)
        url_ids = [u["id"] for u in urls]
        _generate_events(db, Event, url_ids, user_ids)

    db.close()
    print("Seeding complete!")


if __name__ == "__main__":
    seed_all()

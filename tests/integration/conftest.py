"""
Integration test fixtures.
Requires a real PostgreSQL instance (provided as a GitHub Actions service container
or locally via: docker run -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16-alpine)
"""

import os

import pytest

# ── Environment must be set BEFORE any app module is imported ────────────────
os.environ.update(
    {
        "DATABASE_HOST": os.environ.get("DATABASE_HOST", "localhost"),
        "DATABASE_NAME": os.environ.get("DATABASE_NAME", "hackathon_db"),
        "DATABASE_USER": os.environ.get("DATABASE_USER", "postgres"),
        "DATABASE_PASSWORD": os.environ.get("DATABASE_PASSWORD", "postgres"),
        "DATABASE_PORT": os.environ.get("DATABASE_PORT", "5432"),
        "DATABASE_READ_HOST": "",  # No replica in CI
        "SECRET_KEY": "ci-test-secret-not-for-production",
        # Point Redis to a non-existent port → triggers SimpleCache fallback
        # so integration tests never require a Redis container
        "REDIS_URL": "redis://localhost:19999/0",
    }
)

from app import create_app  # noqa: E402
from app.cache import cache  # noqa: E402
from app.database import db  # noqa: E402
from app.models.event import Event  # noqa: E402
from app.models.url import Url  # noqa: E402
from app.models.user import User  # noqa: E402


@pytest.fixture(scope="session")
def app():
    flask_app = create_app()
    flask_app.config["TESTING"] = True

    with flask_app.app_context():
        db.connect(reuse_if_open=True)
        db.create_tables([User, Url, Event], safe=True)

    yield flask_app

    with flask_app.app_context():
        db.connect(reuse_if_open=True)
        db.drop_tables([Event, Url, User])


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with app.app_context():
            yield c


@pytest.fixture(autouse=True)
def clean_db(app):
    """Wipe all rows and clear the cache before each test so tests are fully isolated."""
    with app.app_context():
        db.connect(reuse_if_open=True)
        Event.delete().execute()
        Url.delete().execute()
        User.delete().execute()
        cache.clear()
    yield
    with app.app_context():
        db.connect(reuse_if_open=True)
        Event.delete().execute()
        Url.delete().execute()
        User.delete().execute()
        cache.clear()

"""
Integration tests for Flask routes — run against a real PostgreSQL database.
"""


from app.models.event import Event
from app.models.user import User
from datetime import datetime


# ── Health ───────────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_returns_json(self, client):
        r = client.get("/health")
        assert r.content_type == "application/json"

    def test_health_has_checks(self, client):
        body = client.get("/health").get_json()
        assert "checks" in body
        assert "db_primary" in body["checks"]

    def test_health_db_primary_ok(self, client):
        body = client.get("/health").get_json()
        assert body["checks"]["db_primary"] == "ok"


# ── URL API (JSON) ────────────────────────────────────────────────────────────


class TestCreateUrl:
    def _make_user(self, app):
        with app.app_context():
            return User.create(
                username="urlcreator", email="creator@example.com",
                created_at=datetime.utcnow()
            )

    def test_create_returns_201(self, client, app):
        user = self._make_user(app)
        r = client.post("/api/urls", json={"original_url": "https://example.com", "user_id": user.id})
        assert r.status_code == 201

    def test_create_returns_short_code(self, client, app):
        user = self._make_user(app)
        r = client.post("/api/urls", json={"original_url": "https://example.com", "user_id": user.id})
        data = r.get_json()
        assert "short_code" in data
        assert len(data["short_code"]) > 0

    def test_short_code_is_base62_of_id(self, client, app):
        from app.utils import to_base62
        user = self._make_user(app)
        r = client.post("/api/urls", json={"original_url": "https://example.com/base62", "user_id": user.id})
        data = r.get_json()
        assert data["short_code"] == to_base62(data["id"])

    def test_create_with_custom_code(self, client, app):
        user = self._make_user(app)
        r = client.post(
            "/api/urls",
            json={"original_url": "https://example.com", "short_code": "mylink", "user_id": user.id},
        )
        assert r.status_code == 201
        assert r.get_json()["short_code"] == "mylink"

    def test_missing_original_url_returns_400(self, client):
        r = client.post("/api/urls", json={})
        assert r.status_code == 400

    def test_reserved_code_returns_400(self, client, app):
        user = self._make_user(app)
        r = client.post(
            "/api/urls",
            json={"original_url": "https://example.com", "short_code": "urls", "user_id": user.id},
        )
        assert r.status_code == 400
        assert "reserved" in r.get_json()["error"].lower()

    def test_twin_paradox_same_url_creates_new_entry(self, client, app):
        """The Twin's Paradox: same original_url submitted twice gets two distinct short codes."""
        user = self._make_user(app)
        url = "https://example.com/twin-test"
        r1 = client.post("/api/urls", json={"original_url": url, "user_id": user.id})
        r2 = client.post("/api/urls", json={"original_url": url, "user_id": user.id})
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.get_json()["short_code"] != r2.get_json()["short_code"]

    def test_duplicate_short_code_returns_409(self, client, app):
        user = self._make_user(app)
        client.post("/api/urls", json={"original_url": "https://example.com/first", "short_code": "taken", "user_id": user.id})
        r = client.post("/api/urls", json={"original_url": "https://example.com/second", "short_code": "taken", "user_id": user.id})
        assert r.status_code == 409

    def test_create_records_created_event(self, client, app):
        user = self._make_user(app)
        client.post("/api/urls", json={"original_url": "https://example.com/event-test", "user_id": user.id})
        with app.app_context():
            count = Event.select().where(Event.event_type == "created").count()
        assert count == 1

    def test_fractured_vessel_string_body_returns_400(self, client):
        """The Fractured Vessel: raw string body must be rejected."""
        r = client.post(
            "/api/urls",
            data='"just a string"',
            content_type="application/json",
        )
        assert r.status_code == 400

    def test_fractured_vessel_no_content_type_returns_400(self, client):
        """The Fractured Vessel: non-JSON content type body rejected."""
        r = client.post("/api/urls", data="original_url=https://example.com")
        assert r.status_code == 400


class TestRedirect:
    def _create_url(self, client, app, original_url):
        with app.app_context():
            user = User.create(username="redir_user", email="redir@example.com", created_at=datetime.utcnow())
        r = client.post("/api/urls", json={"original_url": original_url, "user_id": user.id})
        return r.get_json()

    def test_redirect_302(self, client, app):
        data = self._create_url(client, app, "https://target.example.com")
        r = client.get(f"/{data['short_code']}", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["Location"] == "https://target.example.com"

    def test_redirect_records_click_event(self, client, app):
        """The Unseen Observer: every redirect must log a click event."""
        data = self._create_url(client, app, "https://click.example.com")
        client.get(f"/{data['short_code']}")
        with app.app_context():
            clicks = Event.select().where(Event.event_type == "click").count()
        assert clicks == 1

    def test_redirect_nonexistent_returns_404(self, client):
        r = client.get("/doesnotexist99")
        assert r.status_code == 404

    def test_slumbering_guide_inactive_no_redirect_no_event(self, client, app):
        """The Slumbering Guide: inactive URL returns 404 and logs NO event."""
        with app.app_context():
            user = User.create(username="sleep_user", email="sleep@example.com", created_at=datetime.utcnow())
        r = client.post("/api/urls", json={"original_url": "https://example.com/inactive", "user_id": user.id})
        url_id = r.get_json()["id"]
        code = r.get_json()["short_code"]

        client.put(f"/api/urls/{url_id}", json={"is_active": False})
        # Clear any cached result so redirect sees updated state
        r = client.get(f"/{code}", follow_redirects=False)
        assert r.status_code == 404

        with app.app_context():
            clicks = Event.select().where(Event.event_type == "click").count()
        assert clicks == 0


class TestUrlCrud:
    def _make_user(self, app):
        with app.app_context():
            return User.create(username="crud_user", email="crud@example.com", created_at=datetime.utcnow())

    def test_list_urls(self, client, app):
        user = self._make_user(app)
        client.post("/api/urls", json={"original_url": "https://a.example.com", "user_id": user.id})
        client.post("/api/urls", json={"original_url": "https://b.example.com", "user_id": user.id})
        r = client.get("/api/urls")
        assert r.status_code == 200
        assert r.get_json()["total"] == 2

    def test_get_url(self, client, app):
        user = self._make_user(app)
        url_id = client.post(
            "/api/urls",
            json={"original_url": "https://get.example.com", "title": "Get Test", "user_id": user.id},
        ).get_json()["id"]
        r = client.get(f"/api/urls/{url_id}")
        assert r.status_code == 200
        assert r.get_json()["title"] == "Get Test"

    def test_get_nonexistent_returns_404(self, client):
        assert client.get("/api/urls/999999").status_code == 404

    def test_update_url(self, client, app):
        user = self._make_user(app)
        url_id = client.post(
            "/api/urls", json={"original_url": "https://update.example.com", "user_id": user.id}
        ).get_json()["id"]
        r = client.put(f"/api/urls/{url_id}", json={"title": "Updated Title"})
        assert r.status_code == 200
        assert r.get_json()["title"] == "Updated Title"

    def test_update_deactivate(self, client, app):
        user = self._make_user(app)
        url_id = client.post(
            "/api/urls", json={"original_url": "https://deactivate.example.com", "user_id": user.id}
        ).get_json()["id"]
        client.put(f"/api/urls/{url_id}", json={"is_active": False})
        r = client.get(f"/api/urls/{url_id}")
        assert r.get_json()["is_active"] is False

    def test_delete_url(self, client, app):
        user = self._make_user(app)
        url_id = client.post(
            "/api/urls", json={"original_url": "https://delete.example.com", "user_id": user.id}
        ).get_json()["id"]
        assert client.delete(f"/api/urls/{url_id}").status_code == 200
        assert client.get(f"/api/urls/{url_id}").status_code == 404

    def test_url_stats_endpoint(self, client, app):
        user = self._make_user(app)
        r = client.post("/api/urls", json={"original_url": "https://stats.example.com", "user_id": user.id})
        url_id = r.get_json()["id"]
        code = r.get_json()["short_code"]
        client.get(f"/{code}")
        client.get(f"/{code}")
        r = client.get(f"/api/urls/{url_id}/stats")
        assert r.status_code == 200
        assert r.get_json()["clicks"] == 2


# ── Stats API ─────────────────────────────────────────────────────────────────


class TestStats:
    def _make_user(self, app):
        with app.app_context():
            return User.create(username="stats_user", email="stats@example.com", created_at=datetime.utcnow())

    def test_stats_structure(self, client):
        r = client.get("/api/stats")
        assert r.status_code == 200
        for key in ("total_urls", "active_urls", "total_users", "total_clicks", "top_urls"):
            assert key in r.get_json(), f"Missing key: {key}"

    def test_stats_counts(self, client, app):
        user = self._make_user(app)
        client.post("/api/urls", json={"original_url": "https://stats1.example.com", "user_id": user.id})
        client.post("/api/urls", json={"original_url": "https://stats2.example.com", "user_id": user.id})
        r = client.get("/api/stats")
        assert r.get_json()["total_urls"] == 2
        assert r.get_json()["active_urls"] == 2


# ── Events API ────────────────────────────────────────────────────────────────


class TestEvents:
    def _make_user(self, app):
        with app.app_context():
            return User.create(username="ev_user", email="ev@example.com", created_at=datetime.utcnow())

    def test_events_returns_200(self, client):
        r = client.get("/api/events")
        assert r.status_code == 200

    def test_events_structure(self, client):
        body = client.get("/api/events").get_json()
        assert "total" in body
        assert "events" in body

    def test_click_event_recorded_and_visible(self, client, app):
        """The Unseen Observer: click events appear in /api/events."""
        user = self._make_user(app)
        r = client.post("/api/urls", json={"original_url": "https://obs.example.com", "user_id": user.id})
        code = r.get_json()["short_code"]
        client.get(f"/{code}")
        body = client.get("/api/events").get_json()
        event_types = [e["event_type"] for e in body["events"]]
        assert "click" in event_types

    def test_filter_by_event_type(self, client, app):
        user = self._make_user(app)
        r = client.post("/api/urls", json={"original_url": "https://filter.example.com", "user_id": user.id})
        code = r.get_json()["short_code"]
        client.get(f"/{code}")
        body = client.get("/api/events?event_type=click").get_json()
        assert all(e["event_type"] == "click" for e in body["events"])
        assert body["total"] >= 1

    def test_filter_by_url_id(self, client, app):
        user = self._make_user(app)
        r = client.post("/api/urls", json={"original_url": "https://urlfilter.example.com", "user_id": user.id})
        data = r.get_json()
        client.get(f"/{data['short_code']}")
        body = client.get(f"/api/events?url_id={data['id']}").get_json()
        assert body["total"] >= 1

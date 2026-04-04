"""
Integration tests for Flask routes — run against a real PostgreSQL database.
"""

import json

from app.models.event import Event


# ── Health ───────────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_returns_json(self, client):
        r = client.get("/health")
        assert r.content_type == "application/json"

    def test_health_has_checks(self, client):
        r = client.get("/health")
        body = json.loads(r.data)
        assert "checks" in body
        assert "db_primary" in body["checks"]

    def test_health_db_primary_ok(self, client):
        body = json.loads(client.get("/health").data)
        assert body["checks"]["db_primary"] == "ok"


# ── URL API (JSON) ────────────────────────────────────────────────────────────


class TestCreateUrl:
    def test_create_returns_201(self, client):
        r = client.post("/api/urls", json={"original_url": "https://example.com"})
        assert r.status_code == 201

    def test_create_returns_short_code(self, client):
        r = client.post("/api/urls", json={"original_url": "https://example.com"})
        data = r.get_json()
        assert "short_code" in data
        assert len(data["short_code"]) > 0

    def test_short_code_is_base62_of_id(self, client):
        """Short code must equal to_base62(url.id) — not a random string."""
        from app.utils import to_base62

        r = client.post(
            "/api/urls", json={"original_url": "https://example.com/base62"}
        )
        data = r.get_json()
        assert data["short_code"] == to_base62(data["id"])

    def test_create_with_custom_code(self, client):
        r = client.post(
            "/api/urls",
            json={
                "original_url": "https://example.com",
                "short_code": "mylink",
            },
        )
        assert r.status_code == 201
        assert r.get_json()["short_code"] == "mylink"

    def test_missing_original_url_returns_400(self, client):
        r = client.post("/api/urls", json={})
        assert r.status_code == 400

    def test_reserved_code_returns_400(self, client):
        r = client.post(
            "/api/urls",
            json={
                "original_url": "https://example.com",
                "short_code": "urls",
            },
        )
        assert r.status_code == 400
        assert "reserved" in r.get_json()["error"].lower()

    def test_duplicate_long_url_returns_existing(self, client):
        """Submitting the same long URL twice must return the existing short URL."""
        url = "https://example.com/duplicate-test"
        r1 = client.post("/api/urls", json={"original_url": url})
        r2 = client.post("/api/urls", json={"original_url": url})
        assert r1.status_code == 201
        assert r2.status_code == 200
        assert r1.get_json()["short_code"] == r2.get_json()["short_code"]

    def test_duplicate_short_code_returns_409(self, client):
        client.post(
            "/api/urls",
            json={
                "original_url": "https://example.com/first",
                "short_code": "taken",
            },
        )
        r = client.post(
            "/api/urls",
            json={
                "original_url": "https://example.com/second",
                "short_code": "taken",
            },
        )
        assert r.status_code == 409

    def test_create_records_created_event(self, client, app):
        client.post(
            "/api/urls", json={"original_url": "https://example.com/event-test"}
        )
        with app.app_context():
            count = Event.select().where(Event.event_type == "created").count()
        assert count == 1


class TestRedirect:
    def test_redirect_302(self, client):
        r = client.post(
            "/api/urls", json={"original_url": "https://target.example.com"}
        )
        code = r.get_json()["short_code"]

        r = client.get(f"/{code}", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["Location"] == "https://target.example.com"

    def test_redirect_records_click_event(self, client, app):
        r = client.post("/api/urls", json={"original_url": "https://click.example.com"})
        code = r.get_json()["short_code"]
        client.get(f"/{code}")

        with app.app_context():
            clicks = Event.select().where(Event.event_type == "click").count()
        assert clicks == 1

    def test_redirect_nonexistent_returns_404(self, client):
        r = client.get("/doesnotexist99")
        assert r.status_code == 404

    def test_inactive_url_returns_404(self, client):
        r = client.post(
            "/api/urls", json={"original_url": "https://example.com/inactive"}
        )
        url_id = r.get_json()["id"]
        code = r.get_json()["short_code"]

        client.put(f"/api/urls/{url_id}", json={"is_active": False})
        r = client.get(f"/{code}", follow_redirects=False)
        assert r.status_code == 404


class TestUrlCrud:
    def test_list_urls(self, client):
        client.post("/api/urls", json={"original_url": "https://a.example.com"})
        client.post("/api/urls", json={"original_url": "https://b.example.com"})
        r = client.get("/api/urls")
        assert r.status_code == 200
        assert r.get_json()["total"] == 2

    def test_get_url(self, client):
        url_id = client.post(
            "/api/urls",
            json={
                "original_url": "https://get.example.com",
                "title": "Get Test",
            },
        ).get_json()["id"]

        r = client.get(f"/api/urls/{url_id}")
        assert r.status_code == 200
        assert r.get_json()["title"] == "Get Test"

    def test_get_nonexistent_returns_404(self, client):
        assert client.get("/api/urls/999999").status_code == 404

    def test_update_url(self, client):
        url_id = client.post(
            "/api/urls",
            json={
                "original_url": "https://update.example.com",
            },
        ).get_json()["id"]

        r = client.put(f"/api/urls/{url_id}", json={"title": "Updated Title"})
        assert r.status_code == 200
        assert r.get_json()["title"] == "Updated Title"

    def test_update_deactivate(self, client):
        url_id = client.post(
            "/api/urls",
            json={
                "original_url": "https://deactivate.example.com",
            },
        ).get_json()["id"]

        client.put(f"/api/urls/{url_id}", json={"is_active": False})
        r = client.get(f"/api/urls/{url_id}")
        assert r.get_json()["is_active"] is False

    def test_delete_url(self, client):
        url_id = client.post(
            "/api/urls",
            json={
                "original_url": "https://delete.example.com",
            },
        ).get_json()["id"]

        assert client.delete(f"/api/urls/{url_id}").status_code == 200
        assert client.get(f"/api/urls/{url_id}").status_code == 404

    def test_url_stats_endpoint(self, client):
        r = client.post("/api/urls", json={"original_url": "https://stats.example.com"})
        url_id = r.get_json()["id"]
        code = r.get_json()["short_code"]

        client.get(f"/{code}")
        client.get(f"/{code}")

        r = client.get(f"/api/urls/{url_id}/stats")
        assert r.status_code == 200
        assert r.get_json()["clicks"] == 2


# ── Stats API ─────────────────────────────────────────────────────────────────


class TestStats:
    def test_stats_structure(self, client):
        r = client.get("/api/stats")
        assert r.status_code == 200
        body = r.get_json()
        for key in (
            "total_urls",
            "active_urls",
            "total_users",
            "total_clicks",
            "top_urls",
        ):
            assert key in body, f"Missing key: {key}"

    def test_stats_counts(self, client):
        client.post("/api/urls", json={"original_url": "https://stats1.example.com"})
        client.post("/api/urls", json={"original_url": "https://stats2.example.com"})
        r = client.get("/api/stats")
        assert r.get_json()["total_urls"] == 2
        assert r.get_json()["active_urls"] == 2


# ── Frontend pages (HTML) ─────────────────────────────────────────────────────


class TestFrontend:
    def test_index_returns_200(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"URLShort" in r.data

    def test_urls_list_page(self, client):
        r = client.get("/urls")
        assert r.status_code == 200

    def test_users_list_page(self, client):
        r = client.get("/users")
        assert r.status_code == 200

    def test_create_url_via_form(self, client):
        r = client.post(
            "/urls/new",
            data={
                "original_url": "https://form.example.com",
                "title": "Form Test",
            },
            follow_redirects=True,
        )
        assert r.status_code == 200
        assert b"Form Test" in r.data or b"form.example.com" in r.data

    def test_duplicate_url_via_form_redirects_to_existing(self, client):
        data = {"original_url": "https://dup.example.com"}
        client.post("/urls/new", data=data)
        r = client.post("/urls/new", data=data, follow_redirects=True)
        assert r.status_code == 200
        assert b"already exists" in r.data

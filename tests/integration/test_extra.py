"""
Additional integration tests for edge cases.
"""

from datetime import datetime

from app.models.user import User


def _make_user(app, username="extra_user", email="extra@example.com"):
    with app.app_context():
        return User.create(username=username, email=email, created_at=datetime.utcnow())


class TestHealthDetailed:
    def test_status_field_present(self, client):
        assert "status" in client.get("/health").get_json()

    def test_status_is_ok_when_db_reachable(self, client):
        assert client.get("/health").get_json()["status"] == "ok"

    def test_checks_dict_present(self, client):
        assert isinstance(client.get("/health").get_json().get("checks"), dict)

    def test_db_primary_check_ok(self, client):
        assert client.get("/health").get_json()["checks"]["db_primary"] == "ok"


class TestUrlListFilters:
    def _create(self, client, app, url, **kwargs):
        user = _make_user(app, f"filter_{url[-5:]}", f"filter_{url[-5:]}@example.com")
        return client.post("/api/urls", json={"original_url": url, "user_id": user.id, **kwargs})

    def test_active_filter_true(self, client, app):
        r1 = self._create(client, app, "https://active.example.com")
        r2 = self._create(client, app, "https://inactive.example.com")
        client.put(f"/api/urls/{r2.get_json()['id']}", json={"is_active": False})
        r = client.get("/api/urls?active=true")
        assert r.get_json()["total"] == 1

    def test_pagination_per_page(self, client, app):
        user = _make_user(app)
        for i in range(5):
            client.post("/api/urls", json={"original_url": f"https://paginate{i}.example.com", "user_id": user.id})
        body = client.get("/api/urls?page=1&per_page=3").get_json()
        assert len(body["urls"]) == 3
        assert body["total"] == 5

    def test_per_page_capped_at_100(self, client):
        assert client.get("/api/urls?per_page=999").get_json()["per_page"] == 100


class TestUrlCrudEdgeCases:
    def test_update_nonexistent_returns_404(self, client):
        assert client.put("/api/urls/999999", json={"title": "x"}).status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        assert client.delete("/api/urls/999999").status_code == 404

    def test_url_stats_nonexistent_returns_404(self, client):
        assert client.get("/api/urls/999999/stats").status_code == 404

    def test_create_invalid_custom_code_too_long(self, client):
        r = client.post("/api/urls", json={"original_url": "https://example.com", "short_code": "a" * 21})
        assert r.status_code == 400

    def test_url_stats_zero_clicks(self, client, app):
        user = _make_user(app)
        url_id = client.post(
            "/api/urls", json={"original_url": "https://noclicks.example.com", "user_id": user.id}
        ).get_json()["id"]
        r = client.get(f"/api/urls/{url_id}/stats")
        assert r.get_json()["clicks"] == 0
        assert r.get_json()["total_events"] == 1  # the 'created' event


class TestStatsDetailed:
    def _make_user(self, app, suffix=""):
        with app.app_context():
            return User.create(
                username=f"st_user{suffix}", email=f"st{suffix}@example.com",
                created_at=datetime.utcnow()
            )

    def test_total_events_counted(self, client, app):
        user = self._make_user(app)
        r = client.post("/api/urls", json={"original_url": "https://ev.example.com", "user_id": user.id})
        client.get(f"/{r.get_json()['short_code']}")
        assert client.get("/api/stats").get_json()["total_events"] >= 2

    def test_total_clicks_matches_redirects(self, client, app):
        user = self._make_user(app, "2")
        r = client.post("/api/urls", json={"original_url": "https://clk.example.com", "user_id": user.id})
        code = r.get_json()["short_code"]
        client.get(f"/{code}")
        client.get(f"/{code}")
        assert client.get("/api/stats").get_json()["total_clicks"] == 2

    def test_top_urls_in_stats(self, client, app):
        user = self._make_user(app, "3")
        r = client.post("/api/urls", json={"original_url": "https://top.example.com", "user_id": user.id})
        code = r.get_json()["short_code"]
        for _ in range(3):
            client.get(f"/{code}")
        body = client.get("/api/stats").get_json()
        assert len(body["top_urls"]) == 1
        assert body["top_urls"][0]["clicks"] == 3

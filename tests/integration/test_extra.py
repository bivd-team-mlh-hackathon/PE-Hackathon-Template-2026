"""
Additional integration tests to push coverage past 60%.
Covers edge cases in URL CRUD, active filters, pagination, and frontend routes.
"""

from datetime import datetime

from app.models.user import User


# ── Health endpoint ──────────────────────────────────────────────────────────


def create_dummy_user():
    user = User.get_or_none(User.username == "dummy")
    if not user:
        user = User.create(
            username="dummy",
            email="dummy@example.com",
            created_at=datetime.utcnow(),
        )
    return user.id


class TestHealthDetailed:
    def test_status_field_present(self, client):
        body = client.get("/health").get_json()
        assert "status" in body

    def test_status_is_ok_when_db_reachable(self, client):
        body = client.get("/health").get_json()
        assert body["status"] == "ok"

    def test_checks_dict_present(self, client):
        body = client.get("/health").get_json()
        assert isinstance(body.get("checks"), dict)

    def test_db_primary_check_ok(self, client):
        body = client.get("/health").get_json()
        assert body["checks"]["db_primary"] == "ok"


# ── URL list filters and pagination ──────────────────────────────────────────


class TestUrlListFilters:
    def _create(self, client, url, **kwargs):
        return client.post(
            "/urls",
            json={"original_url": url, "user_id": create_dummy_user(), **kwargs},
        )

    def test_active_filter_true(self, client):
        self._create(client, "https://active.example.com")
        r1 = self._create(client, "https://inactive.example.com")
        client.put(f"/urls/{r1.get_json()['id']}", json={"is_active": False})

        r = client.get("/urls?active=true")
        assert r.get_json()["total"] == 1

    def test_pagination_per_page(self, client):
        for i in range(5):
            self._create(client, f"https://paginate{i}.example.com")
        body = client.get("/urls?page=1&per_page=3").get_json()
        assert len(body["urls"]) == 3
        assert body["per_page"] == 3
        assert body["total"] == 5

    def test_per_page_capped_at_100(self, client):
        body = client.get("/urls?per_page=999").get_json()
        assert body["per_page"] == 100

    def test_second_page(self, client):
        for i in range(5):
            self._create(client, f"https://page2test{i}.example.com")
        body = client.get("/urls?page=2&per_page=3").get_json()
        assert len(body["urls"]) == 2


# ── URL CRUD edge cases ───────────────────────────────────────────────────────


class TestUrlCrudEdgeCases:
    def test_update_nonexistent_returns_404(self, client):
        r = client.put("/urls/999999", json={"title": "x"})
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        assert client.delete("/urls/999999").status_code == 404

    def test_url_stats_nonexistent_returns_404(self, client):
        assert client.get("/urls/999999/stats").status_code == 404

    def test_update_original_url(self, client):
        url_id = client.post(
            "/urls",
            json={
                "original_url": "https://before.example.com",
                "user_id": create_dummy_user(),
            },
        ).get_json()["id"]
        r = client.put(
            f"/urls/{url_id}", json={"original_url": "https://after.example.com"}
        )
        assert r.get_json()["original_url"] == "https://after.example.com"

    def test_create_invalid_custom_code_too_long(self, client):
        r = client.post(
            "/urls",
            json={
                "original_url": "https://example.com",
                "short_code": "a" * 21,
                "user_id": create_dummy_user(),
            },
        )
        assert r.status_code == 400

    def test_create_invalid_custom_code_special_chars(self, client):
        r = client.post(
            "/urls",
            json={
                "original_url": "https://example.com",
                "short_code": "bad code!",
                "user_id": create_dummy_user(),
            },
        )
        assert r.status_code == 400

    def test_create_with_user_id(self, client, app):
        with app.app_context():
            user = User.create(
                username="urlowner",
                email="o@example.com",
                created_at=datetime.utcnow(),
            )
        r = client.post(
            "/urls",
            json={
                "original_url": "https://owned.example.com",
                "user_id": user.id,
            },
        )
        assert r.status_code == 201
        assert r.get_json()["user_id"] == user.id

    def test_create_with_title(self, client):
        r = client.post(
            "/urls",
            json={
                "original_url": "https://titled.example.com",
                "title": "My Title",
                "user_id": create_dummy_user(),
            },
        )
        assert r.get_json()["title"] == "My Title"

    def test_url_stats_zero_clicks(self, client):
        url_id = client.post(
            "/urls",
            json={
                "original_url": "https://noclicks.example.com",
                "user_id": create_dummy_user(),
            },
        ).get_json()["id"]
        r = client.get(f"/urls/{url_id}/stats")
        assert r.get_json()["clicks"] == 0
        assert r.get_json()["total_events"] == 1  # the 'created' event


# ── Stats ─────────────────────────────────────────────────────────────────────


class TestStatsDetailed:
    def test_total_events_counted(self, client):
        r = client.post(
            "/urls",
            json={
                "original_url": "https://ev.example.com",
                "user_id": create_dummy_user(),
            },
        )
        code = r.get_json()["short_code"]
        client.get(f"/{code}")
        body = client.get("/stats").get_json()
        assert body["total_events"] >= 2  # created + click

    def test_total_clicks_matches_redirects(self, client):
        r = client.post(
            "/urls",
            json={
                "original_url": "https://clk.example.com",
                "user_id": create_dummy_user(),
            },
        )
        code = r.get_json()["short_code"]
        client.get(f"/{code}")
        client.get(f"/{code}")
        body = client.get("/stats").get_json()
        assert body["total_clicks"] == 2

    def test_top_urls_in_stats(self, client):
        r = client.post(
            "/urls",
            json={
                "original_url": "https://top.example.com",
                "user_id": create_dummy_user(),
            },
        )
        code = r.get_json()["short_code"]
        for _ in range(3):
            client.get(f"/{code}")
        body = client.get("/stats").get_json()
        assert len(body["top_urls"]) == 1
        assert body["top_urls"][0]["clicks"] == 3

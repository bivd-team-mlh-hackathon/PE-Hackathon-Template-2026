"""
Integration tests for user routes — /api/users and frontend /users pages.
"""

from datetime import datetime

from app.models.user import User


def _make_user(app, username="testuser", email="test@example.com"):
    with app.app_context():
        return User.create(username=username, email=email, created_at=datetime.utcnow())


# ── User API ──────────────────────────────────────────────────────────────────


class TestListUsers:
    def test_empty_returns_200(self, client):
        r = client.get("/api/users")
        assert r.status_code == 200

    def test_empty_total_is_zero(self, client):
        assert client.get("/api/users").get_json()["total"] == 0

    def test_returns_created_user(self, client, app):
        _make_user(app)
        r = client.get("/api/users")
        body = r.get_json()
        assert body["total"] == 1
        assert body["users"][0]["username"] == "testuser"

    def test_response_has_pagination_fields(self, client):
        body = client.get("/api/users?page=2&per_page=5").get_json()
        assert body["page"] == 2
        assert body["per_page"] == 5

    def test_per_page_capped_at_100(self, client):
        body = client.get("/api/users?per_page=999").get_json()
        assert body["per_page"] == 100

    def test_multiple_users(self, client, app):
        _make_user(app, "alice", "alice@example.com")
        _make_user(app, "bob", "bob@example.com")
        assert client.get("/api/users").get_json()["total"] == 2


class TestGetUser:
    def test_returns_200(self, client, app):
        user = _make_user(app)
        r = client.get(f"/api/users/{user.id}")
        assert r.status_code == 200

    def test_returns_correct_fields(self, client, app):
        user = _make_user(app)
        body = client.get(f"/api/users/{user.id}").get_json()
        assert body["username"] == "testuser"
        assert body["email"] == "test@example.com"
        assert "created_at" in body
        assert "urls" in body

    def test_urls_list_initially_empty(self, client, app):
        user = _make_user(app)
        body = client.get(f"/api/users/{user.id}").get_json()
        assert body["urls"] == []

    def test_includes_associated_urls(self, client, app):
        user = _make_user(app)
        client.post(
            "/api/urls",
            json={
                "original_url": "https://user-url.example.com",
                "user_id": user.id,
            },
        )
        body = client.get(f"/api/users/{user.id}").get_json()
        assert len(body["urls"]) == 1
        assert body["urls"][0]["original_url"] == "https://user-url.example.com"

    def test_nonexistent_returns_404(self, client):
        assert client.get("/api/users/999999").status_code == 404


# ── Frontend user pages ────────────────────────────────────────────────────────


class TestUserFrontend:
    def test_users_list_page_ok(self, client):
        assert client.get("/users").status_code == 200

    def test_users_list_shows_user(self, client, app):
        _make_user(app, "visibleuser", "v@example.com")
        r = client.get("/users")
        assert b"visibleuser" in r.data

    def test_user_detail_page_ok(self, client, app):
        user = _make_user(app)
        r = client.get(f"/users/{user.id}")
        assert r.status_code == 200

    def test_user_detail_redirects_on_missing(self, client):
        r = client.get("/users/999999", follow_redirects=True)
        assert r.status_code == 200

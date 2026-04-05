"""
Integration tests for user routes.
"""

import io
from datetime import datetime

from app.models.user import User


def _make_user(app, username="testuser", email="test@example.com"):
    with app.app_context():
        return User.create(username=username, email=email, created_at=datetime.utcnow())


def _csv_file(content):
    """Return (BytesIO, filename) tuple for Flask test client multipart upload."""
    return (io.BytesIO(content.encode("utf-8")), "users.csv")


class TestListUsers:
    def test_empty_returns_200(self, client):
        assert client.get("/api/users").status_code == 200

    def test_empty_total_is_zero(self, client):
        assert client.get("/api/users").get_json()["total"] == 0

    def test_returns_created_user(self, client, app):
        _make_user(app)
        body = client.get("/api/users").get_json()
        assert body["total"] == 1
        assert body["users"][0]["username"] == "testuser"

    def test_response_has_pagination_fields(self, client):
        body = client.get("/api/users?page=2&per_page=5").get_json()
        assert body["page"] == 2
        assert body["per_page"] == 5

    def test_per_page_capped_at_100(self, client):
        assert client.get("/api/users?per_page=999").get_json()["per_page"] == 100

    def test_multiple_users(self, client, app):
        _make_user(app, "alice", "alice@example.com")
        _make_user(app, "bob", "bob@example.com")
        assert client.get("/api/users").get_json()["total"] == 2


class TestGetUser:
    def test_returns_200(self, client, app):
        user = _make_user(app)
        assert client.get(f"/api/users/{user.id}").status_code == 200

    def test_returns_correct_fields(self, client, app):
        user = _make_user(app)
        body = client.get(f"/api/users/{user.id}").get_json()
        assert body["username"] == "testuser"
        assert body["email"] == "test@example.com"
        assert "created_at" in body
        assert "urls" in body

    def test_urls_list_initially_empty(self, client, app):
        user = _make_user(app)
        assert client.get(f"/api/users/{user.id}").get_json()["urls"] == []

    def test_includes_associated_urls(self, client, app):
        user = _make_user(app)
        client.post("/api/urls", json={"original_url": "https://user-url.example.com", "user_id": user.id})
        body = client.get(f"/api/users/{user.id}").get_json()
        assert len(body["urls"]) == 1
        assert body["urls"][0]["original_url"] == "https://user-url.example.com"

    def test_nonexistent_returns_404(self, client):
        assert client.get("/api/users/999999").status_code == 404


class TestCreateUser:
    def test_create_returns_201(self, client):
        r = client.post("/api/users", json={"username": "newuser", "email": "new@example.com"})
        assert r.status_code == 201

    def test_create_returns_user_fields(self, client):
        r = client.post("/api/users", json={"username": "fields_user", "email": "fields@example.com"})
        body = r.get_json()
        assert body["username"] == "fields_user"
        assert body["email"] == "fields@example.com"
        assert "id" in body

    def test_unwitting_stranger_integer_username_rejected(self, client):
        """The Unwitting Stranger: integer username must be rejected."""
        r = client.post("/api/users", json={"username": 12345, "email": "int@example.com"})
        assert r.status_code == 400

    def test_unwitting_stranger_missing_email_rejected(self, client):
        r = client.post("/api/users", json={"username": "noemail"})
        assert r.status_code == 400

    def test_unwitting_stranger_invalid_email_rejected(self, client):
        r = client.post("/api/users", json={"username": "bademail", "email": "notanemail"})
        assert r.status_code == 400

    def test_duplicate_username_returns_409(self, client):
        client.post("/api/users", json={"username": "dup", "email": "dup1@example.com"})
        r = client.post("/api/users", json={"username": "dup", "email": "dup2@example.com"})
        assert r.status_code == 409

    def test_fractured_vessel_string_body_rejected(self, client):
        r = client.post("/api/users", data='"just a string"', content_type="application/json")
        assert r.status_code == 400

    def test_empty_body_rejected(self, client):
        r = client.post("/api/users", json={})
        assert r.status_code == 400


class TestBulkCreateUsers:
    def test_bulk_import_csv(self, client):
        csv_data = "username,email\nbulkuser1,bulk1@example.com\nbulkuser2,bulk2@example.com\n"
        r = client.post(
            "/api/users/bulk",
            data={"file": _csv_file(csv_data)},
            content_type="multipart/form-data",
        )
        assert r.status_code == 201
        assert r.get_json()["count"] == 2

    def test_bulk_returns_imported_users(self, client):
        csv_data = "username,email\nret_user1,ret1@example.com\n"
        r = client.post(
            "/api/users/bulk",
            data={"file": _csv_file(csv_data)},
            content_type="multipart/form-data",
        )
        body = r.get_json()
        assert "imported" in body
        assert len(body["imported"]) == 1

    def test_bulk_no_file_returns_400(self, client):
        r = client.post("/api/users/bulk", data={}, content_type="multipart/form-data")
        assert r.status_code == 400

    def test_bulk_skips_duplicates(self, client, app):
        _make_user(app, "existing_bulk", "existing_bulk@example.com")
        csv_data = "username,email\nexisting_bulk,existing_bulk@example.com\nnewbulk,newbulk@example.com\n"
        r = client.post(
            "/api/users/bulk",
            data={"file": _csv_file(csv_data)},
            content_type="multipart/form-data",
        )
        assert r.get_json()["count"] == 1
